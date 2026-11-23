#!/usr/bin/env python3
"""Convert a Markdown file to PDF.

The Markdown is rendered to a styled HTML page (GitHub-like look, A4
landscape) and printed to PDF with headless Google Chrome / Chromium (driven over the
DevTools protocol). Linux/macOS.
Only the Python standard library is required.

Usage:
    python md_to_pdf.py test_plan/policy_claims_summary.md
    python md_to_pdf.py input.md -o output.pdf [--portrait] [--keep-html]

Supported Markdown: ATX headings, paragraphs, bold/italic, inline code,
links, fenced code blocks, GFM pipe tables (with inline <br>), images, ordered and
unordered lists (nested by indentation), block quotes and horizontal rules.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

# --------------------------------------------------------------------------
# Inline formatting
# --------------------------------------------------------------------------

_ALLOWED_TAGS = re.compile(r"<(/?)(br|b|i|em|strong|code|sub|sup|kbd)\s*/?>", re.I)


def render_inline(text: str) -> str:
    """Render inline Markdown (code spans, links, emphasis) to HTML."""
    placeholders: list[str] = []

    def stash(fragment: str) -> str:
        placeholders.append(fragment)
        return f"\x00{len(placeholders) - 1}\x00"

    # Code spans first so their content is not touched by other rules.
    text = re.sub(
        r"(`+)(.+?)\1",
        lambda m: stash(f"<code>{html.escape(m.group(2).strip())}</code>"),
        text,
    )
    # Keep a small set of safe inline HTML tags (e.g. <br> inside tables).
    text = _ALLOWED_TAGS.sub(lambda m: stash(f"<{m.group(1)}{m.group(2).lower()}>"), text)

    text = html.escape(text, quote=False)

    # Links [label](url)
    def link(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        return f'<a href="{html.escape(url, quote=True)}">{label}</a>'

    # Images ![alt](src) before links, so the link rule does not consume them.
    def image(m: re.Match) -> str:
        alt, src = m.group(1), m.group(2)
        return stash(f'<img src="{html.escape(src, quote=True)}" alt="{alt}" '
                     'style="max-width:100%; height:auto; display:block; margin:8px auto;">')

    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", image, text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)
    # Bold, italic
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<em>\1</em>", text)

    # Restore placeholders (may be nested inside link labels etc.).
    while "\x00" in text:
        text = re.sub(r"\x00(\d+)\x00", lambda m: placeholders[int(m.group(1))], text)
    return text


# --------------------------------------------------------------------------
# Block parsing
# --------------------------------------------------------------------------

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_HR = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([\w+-]*)\s*$")
_LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")


def slugify(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"\s+", "-", text)


def split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    # Split on pipes that are not escaped and not inside code spans.
    cells, buf, in_code = [], [], False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line) and line[i + 1] == "|":
            buf.append("|")
            i += 2
            continue
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code:
            cells.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    cells.append("".join(buf).strip())
    return cells


def render_table(lines: list[str]) -> str:
    header = split_row(lines[0])
    aligns = []
    for spec in split_row(lines[1]):
        left, right = spec.startswith(":"), spec.endswith(":")
        aligns.append("center" if left and right else "right" if right else "left" if left else "")

    def cell(tag: str, content: str, idx: int) -> str:
        align = aligns[idx] if idx < len(aligns) else ""
        style = f' style="text-align:{align}"' if align else ""
        return f"<{tag}{style}>{render_inline(content)}</{tag}>"

    out = ["<table>", "<thead><tr>"]
    out += [cell("th", c, i) for i, c in enumerate(header)]
    out.append("</tr></thead><tbody>")
    for row in lines[2:]:
        cells = split_row(row)
        cells += [""] * (len(header) - len(cells))
        out.append("<tr>" + "".join(cell("td", c, i) for i, c in enumerate(cells[: len(header)])) + "</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def render_list(lines: list[str]) -> str:
    """Render a (possibly nested) list from raw lines."""
    out: list[str] = []
    stack: list[tuple[int, str]] = []  # (indent, tag)
    item_open = False

    for line in lines:
        m = _LIST_ITEM.match(line)
        if not m:
            # Continuation of the previous item.
            if out and line.strip():
                out[-1] += " " + render_inline(line.strip())
            continue
        indent = len(m.group(1).expandtabs(4))
        tag = "ol" if m.group(2)[0].isdigit() else "ul"
        while stack and indent < stack[-1][0]:
            out.append(f"</li></{stack.pop()[1]}>")
        if not stack or indent > stack[-1][0]:
            start = ""
            if tag == "ol":
                num = int(re.match(r"\d+", m.group(2)).group())
                start = f' start="{num}"' if num != 1 else ""
            out.append(f"<{tag}{start}>")
            stack.append((indent, tag))
        elif item_open:
            out.append("</li>")
        out.append(f"<li>{render_inline(m.group(3))}")
        item_open = True

    while stack:
        out.append(f"</li></{stack.pop()[1]}>")
    return "\n".join(out)


def markdown_to_html(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    para: list[str] = []
    i = 0

    def flush_para() -> None:
        if para:
            out.append(f"<p>{render_inline(' '.join(s.strip() for s in para))}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]

        # Fenced code block
        fm = _FENCE.match(line)
        if fm:
            flush_para()
            fence = fm.group(2)
            lang = fm.group(3)
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(fence):
                code.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            cls = f' class="language-{lang}"' if lang else ""
            out.append(f"<pre><code{cls}>{html.escape(chr(10).join(code))}</code></pre>")
            continue

        if not line.strip():
            flush_para()
            i += 1
            continue

        hm = _HEADING.match(line)
        if hm:
            flush_para()
            level = len(hm.group(1))
            content = render_inline(hm.group(2))
            out.append(f'<h{level} id="{slugify(content)}">{content}</h{level}>')
            i += 1
            continue

        if _HR.match(line):
            flush_para()
            out.append("<hr>")
            i += 1
            continue

        # Table: header row followed by a separator row
        if "|" in line and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]) and "-" in lines[i + 1]:
            flush_para()
            block = [line, lines[i + 1]]
            i += 2
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                block.append(lines[i])
                i += 1
            out.append(render_table(block))
            continue

        # Block quote
        if line.lstrip().startswith(">"):
            flush_para()
            quote: list[str] = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append(f"<blockquote>{markdown_to_html(chr(10).join(quote))}</blockquote>")
            continue

        # List (may interrupt a paragraph, as in GitHub-flavoured Markdown)
        if _LIST_ITEM.match(line):
            flush_para()
            block = []
            while i < len(lines):
                cur = lines[i]
                if not cur.strip():
                    # A blank line ends the list unless the next line continues it.
                    nxt = lines[i + 1] if i + 1 < len(lines) else ""
                    if _LIST_ITEM.match(nxt) or (nxt.startswith("  ") and nxt.strip()):
                        i += 1
                        continue
                    break
                if (
                    block
                    and not _LIST_ITEM.match(cur)
                    and not cur.startswith((" ", "\t"))
                    and (_HEADING.match(cur) or _FENCE.match(cur) or "|" in cur)
                ):
                    break
                block.append(cur)
                i += 1
            out.append(render_list(block))
            continue

        para.append(line)
        i += 1

    flush_para()
    return "\n".join(out)


# --------------------------------------------------------------------------
# HTML page + PDF printing
# --------------------------------------------------------------------------

CSS = """
@page { size: A4 %(orientation)s; margin: 12mm 12mm 12mm 12mm; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
  font-family: "DejaVu Sans", "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: 8.4pt; line-height: 1.5; color: #1a1a1a; background: #fff; margin: 0;
}
h1, h2, h3, h4, h5, h6 {
  font-weight: bold; line-height: 1.25; margin: 1.4em 0 0.6em;
  break-after: avoid; page-break-after: avoid;
}
h1, h2, h3 { color: #2b4c7e; }
h1 { font-size: 17.9pt; margin-top: 0.4em; padding-bottom: 0.3em; border-bottom: 2px solid #2b4c7e; }
h2 { font-size: 13.9pt; padding-bottom: 0.25em; border-bottom: 1px solid #c8d3e6; }
h3 { font-size: 11.4pt; }
h4 { font-size: 9.9pt; }
h5, h6 { font-size: 8.9pt; }
p { margin: 0 0 0.8em; }
a { color: inherit; text-decoration: none; }
strong { font-weight: bold; }
hr { border: 0; border-top: 1px solid #c8d3e6; margin: 1.5em 0; }
ul, ol { margin: 0 0 0.8em; padding-left: 2.2em; }
li { margin: 0.15em 0; }
li > ul, li > ol { margin-bottom: 0; }
code {
  font-family: "Noto Sans Mono", "DejaVu Sans Mono", Consolas, monospace;
  font-size: 7.8pt; background: #eef1f6; border-radius: 3px; padding: 0.05em 0.3em;
}
pre {
  background: #f3f6fb; border-radius: 4px; padding: 8px 10px; margin: 0 0 0.9em;
  white-space: pre-wrap; word-break: break-word;
}
pre code { background: none; padding: 0; border-radius: 0; line-height: 1.45; }
table { border-collapse: collapse; width: 100%%; margin: 0 0 1em; }
thead { display: table-header-group; }
th, td {
  border: 1px solid #b7c3d6; padding: 3px 6px; text-align: left; vertical-align: top;
  overflow-wrap: break-word;
}
th { background: #2b4c7e; color: #ffffff; font-weight: bold; }
th code { background: rgba(255,255,255,0.15); color: #ffffff; }
tbody tr:nth-child(even) { background: #f3f6fb; }
blockquote { margin: 0 0 0.9em; padding: 0 1em; color: #4a4a4a; border-left: 3px solid #c8d3e6; }
"""

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
{body}
</body>
</html>
"""


def build_html(md_text: str, landscape: bool = True) -> str:
    body = markdown_to_html(md_text)
    m = re.search(r"^#\s+(.+)$", md_text, re.M)
    title = re.sub(r"[`*]", "", m.group(1)).strip() if m else "Document"
    css = CSS % {"orientation": "landscape" if landscape else "portrait"}
    return HTML_TEMPLATE.format(title=html.escape(title), css=css, body=body)


def find_chrome() -> str:
    env = os.environ.get("CHROME_PATH")
    if env:
        return env
    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "chrome",
        "msedge",
    ):
        path = shutil.which(name)
        if path:
            return path
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if os.path.exists(mac):
        return mac
    sys.exit("error: Chrome/Chromium not found. Install it or set CHROME_PATH.")


class _DevTools:
    """Minimal Chrome DevTools Protocol client over --remote-debugging-pipe.

    Chrome reads NUL-terminated JSON messages from fd 3 and writes replies
    to fd 4. Driving Chrome this way is more reliable than the
    ``--print-to-pdf`` command-line switch, which can hang in some
    environments (e.g. WSL).
    """

    def __init__(self, chrome: str, profile: str) -> None:
        to_chrome_r, to_chrome_w = os.pipe()
        from_chrome_r, from_chrome_w = os.pipe()

        def wire_fds() -> None:  # runs in the child before exec
            os.dup2(to_chrome_r, 3)
            os.dup2(from_chrome_w, 4)
            os.set_inheritable(3, True)
            os.set_inheritable(4, True)

        self.proc = subprocess.Popen(
            [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
                "--remote-debugging-pipe",
                f"--user-data-dir={profile}",
                "about:blank",
            ],
            close_fds=False,
            preexec_fn=wire_fds,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.close(to_chrome_r)
        os.close(from_chrome_w)
        self._out = os.fdopen(to_chrome_w, "wb", buffering=0)
        self._in = os.fdopen(from_chrome_r, "rb", buffering=0)
        self._buf = b""
        self._next_id = 0

    def send(self, method: str, params: dict | None = None, session: str | None = None) -> int:
        self._next_id += 1
        msg = {"id": self._next_id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        self._out.write(json.dumps(msg).encode() + b"\0")
        return self._next_id

    def wait_for(self, msg_id: int | None = None, event: str | None = None) -> dict:
        while True:
            while b"\0" not in self._buf:
                chunk = self._in.read(1 << 16)
                if not chunk:
                    raise RuntimeError("Chrome closed the DevTools pipe unexpectedly")
                self._buf += chunk
            raw, self._buf = self._buf.split(b"\0", 1)
            msg = json.loads(raw)
            if msg_id is not None and msg.get("id") == msg_id:
                if "error" in msg:
                    raise RuntimeError(f"DevTools error: {msg['error']}")
                return msg.get("result", {})
            if event is not None and msg.get("method") == event:
                return msg

    def call(self, method: str, params: dict | None = None, session: str | None = None) -> dict:
        return self.wait_for(self.send(method, params, session))

    def close(self) -> None:
        try:
            self.send("Browser.close")
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()
        finally:
            self._out.close()
            self._in.close()


def html_to_pdf(html_path: Path, pdf_path: Path, timeout: int = 120) -> None:
    """Print an HTML file to PDF with headless Chrome (A4 size comes from CSS @page)."""
    chrome = find_chrome()

    def on_timeout(*_):
        raise TimeoutError(f"Chrome did not finish within {timeout}s")

    with tempfile.TemporaryDirectory() as profile:
        devtools = _DevTools(chrome, profile)
        old_handler = signal.signal(signal.SIGALRM, on_timeout)
        signal.alarm(timeout)
        try:
            target = devtools.call("Target.createTarget", {"url": "about:blank"})["targetId"]
            session = devtools.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
            devtools.call("Page.enable", session=session)
            devtools.send("Page.navigate", {"url": html_path.resolve().as_uri()}, session=session)
            devtools.wait_for(event="Page.loadEventFired")
            result = devtools.call(
                "Page.printToPDF",
                {
                    "printBackground": True,
                    "preferCSSPageSize": True,
                    "displayHeaderFooter": False,
                    "generateDocumentOutline": True,
                },
                session=session,
            )
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
            devtools.close()

    pdf_path.write_bytes(base64.b64decode(result["data"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a Markdown file to PDF via headless Chrome.")
    parser.add_argument("input", type=Path, help="Markdown file to convert")
    parser.add_argument("-o", "--output", type=Path, help="PDF path (default: input with .pdf extension)")
    parser.add_argument("--portrait", action="store_true", help="Use A4 portrait (default: A4 landscape)")
    parser.add_argument("--keep-html", action="store_true", help="Also write the intermediate .html next to the PDF")
    args = parser.parse_args()

    if not args.input.is_file():
        sys.exit(f"error: {args.input} not found")
    output = args.output or args.input.with_suffix(".pdf")

    page = build_html(args.input.read_text(encoding="utf-8"), landscape=not args.portrait)

    # Write the HTML next to the source so relative links/images resolve.
    html_path = args.input.with_name(f".{args.input.stem}.render.html")
    html_path.write_text(page, encoding="utf-8")
    try:
        html_to_pdf(html_path, output)
    finally:
        if args.keep_html:
            html_path.replace(output.with_suffix(".html"))
        else:
            html_path.unlink(missing_ok=True)

    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
