# Prompt Sequence: Building `policy_claims_summary.md`

This file lists, in order, the prompts to give an LLM so that it produces the test plan [`policy_claims_summary.md`](policy_claims_summary.md). Each step builds on the previous one, so run them in the same conversation and check each result before moving on.

The prompts are written for an LLM coding assistant that can **read files and run commands** in this project (for example Claude Code). If the LLM cannot run code, paste the files listed in Step 0 into the conversation and replace "calculate from the data" with "calculate from the data I pasted".

---

## How to use this file

1. Start a new conversation in the project folder.
2. Send the prompts one at a time, in order. Copy each prompt from its grey box as written.
3. After each prompt, use the **Check** list under it. If something is wrong, ask for a correction before the next step. Fixing it later means every section built on top of it has to be fixed too.
4. Keep every prompt in the same conversation, because later steps refer to earlier sections by number.

### Rules that apply to every step

Steps 1–12 assume the LLM follows these rules. They are also written into Step 0, so the LLM is told them once at the start.

- **Numbers must come from the data, not from memory.** Every count, min, max, percentage and example record is calculated by running a query against the CSV files or the model output.
- **Every claim about a specific record is checked.** For example, "`OWN1014` has one Denied and one Under Review claim" must be confirmed with a query before it is written.
- **Markdown tables must be valid:** a header row, a `|---|` divider row directly under it, the same number of columns in every row, and a blank line before the table. A `|` inside a cell (including inside code such as `a || b`) must be written as `\|`.
- **Plain English:** short sentences; explain insurance and data terms the first time they are used.
- **Do not rewrite sections that are not part of the step.**

---

## Step 0: Set the context

**Prompt:**
```
I am writing a QA test plan for a DuckDB model. Read these files first:
- model/policy_claims_summary.sql   (the model)
- source/policy_owner.csv, source/policy_coverage.csv, source/policy_claims.csv   (the source tables)
- data_catalog/policy_owner.json, data_catalog/policy_coverage.json, data_catalog/policy_claims.json   (column descriptions and domain_values)
- run_sql.py   (how the model is run)

Rules for everything you write in this conversation:
1. Every number, count, value list and record ID must be calculated by running a query against the
   data or the model output. Do not estimate or write from memory.
2. Before you state a fact about a specific record (for example "OWN1014 has a Denied claim"),
   check it with a query.
3. Markdown tables must have a header row, a |---| divider directly under it, the same number of
   columns in every row, and a blank line before them. Escape any | inside a cell as \|.
4. Use plain English and short sentences. Explain insurance and data terms the first time they appear.
5. Only change the section I ask about.

Do not write anything yet. Reply with a short summary of what the model does and its grain.
```

**Check:**
- The summary says the grain is **one row per `owner_id` + `policy_type`**.
- It mentions the filters: denied claims, cancelled policies, credit score below 600, and rows with no claims.

---

## Step 1: Purpose of the model and the source tables

**Prompt:**
```
Create test_plan/policy_claims_summary.md, titled "Test Plan: `policy_claims_summary`".

Start with a small table: model file (link), engine, source tables, data catalog (link), how to run.

Section 1 "Purpose of the model table":
- What business questions the table answers and who uses it.
- "Grain" subsection: what one row represents, with an example.
- "Business rules applied" subsection: a table with columns # (BR1, BR2, ...), Rule,
  Derivation logic (pseudo code), Effect. Cover every filter, join, aggregation, NULL handling,
  divide-by-zero handling, rounding and sort order in the SQL. Write the derivation logic as
  plain FOR EACH / IF / THEN / ELSE pseudo code, not SQL, using <br> for line breaks inside the cell.
- "Output columns" subsection: column, type, description, source column or derivation.
- "Lineage" subsection: a text diagram from the source tables to the output, showing joins and filters.

Section 2 "Source tables": one subsection per source table with
- a summary table: file (link), catalog (link), description, grain, row count, primary key,
  foreign keys, whether it contains personal data;
- a column table: column, type, "Used in model" (which output column or rule uses it, or –), description.
Then a "Relationships" subsection (parent, child, key, cardinality, join type used in the model)
and a "Source data profile" subsection with policy counts by status, claim counts by status,
owners with credit_score < 600, date ranges and the model's row count. End it with
"What this means for testing": any business rule that the current data never exercises.
```

**Check:**
- Business rules BR1–BR10 are there, and the pseudo code matches the SQL.
- The derivation for `claim_count`, `total_claimed` and the others mentions that claims are totalled **per policy before the join**, to avoid double-counting premium.
- Section 2.5 says there are **no Active policies** and **no owners with a credit score below 600**.

---

## Step 2: Domain validation: source categorical columns

**Prompt:**
```
Add section 3 "Domain validation" with a one-line intro, then "3.1 Source" (one line naming the
source tables), then "3.1.1 Categorical columns".

In 3.1.1:
- State the rule: every value must be in the column's list; empty values, unknown values, and values
  with different case or extra spaces fail.
- A table with columns table_name, column_name, data_type, unique_count, unique_values.
  Include only categorical columns, both nominal and ordinal. Exclude IDs, names, dates and
  quantitative numeric columns, even if they have few distinct values (for example deductible
  and liability_coverage). Take the values from the data and confirm they match domain_values
  in the data catalog.
- Notes: any valid business value missing from the data (for example Active), and why
  quantitative columns are excluded.
- "Value definitions" subsection: for each categorical column, a table with Value and Meaning only
  (no purpose column). Where two columns share the same values (state and property_state,
  flood_coverage and earthquake_coverage), use one table and explain the difference between the
  columns in one sentence. For ordinal columns, show the order (for example the claim workflow).
  While writing the definitions, check the data for records that contradict them (for example a Flood
  claim paid on a policy without flood cover) and add any you find as a "Finding in the current data".
- Validation logic as pseudo code, and one example DuckDB check that should return 0 rows.
  Run the example and confirm it returns 0 rows.
```

**Check:**
- There are 10 categorical columns, and `liability_coverage` and `deductible` are **not** in the table.
- The Value definitions tables have only **Value | Meaning** columns.
- The finding about **`CLM90015`** (a Paid Flood claim with `flood_coverage` = N) is reported.

---

## Step 3: Domain validation: source numerical columns

**Prompt:**
```
Add "3.1.2 Numerical (quantitative) columns" under 3.1 Source.

- Rule: every value must be filled in and inside its expected range; the stats are a baseline,
  and a large shift in a new load should be investigated.
- Include only quantitative columns (amounts, limits, scores, years). Exclude codes stored as
  numbers such as zip_code.
- "Distribution stats (baseline from source data)" table: table_name, column_name, data_type, count,
  null_count, zero_count, min, p25, median, mean, p75, max, std_dev. Calculate with DuckDB.
  Explain p25, p75 and std_dev in one sentence under the table.
- "Expected range (validation rules)" table: table_name, column_name, expected range, notes.
  Include rules that depend on another column (for example dwelling_coverage = 0 only for
  HO-4 Renters; approved_amount <= claim_amount and = 0 for Denied or Under Review), and confirm
  with a query that the current data follows them.
- Validation logic as pseudo code (including a warning when stats move far from the baseline) and
  one example DuckDB check. Run it and confirm it returns 0 rows.
```

**Check:**
- There are 9 numeric columns, and `zip_code` is excluded.
- The notes say all 5 zero `dwelling_coverage` values are HO-4 Renters, and all 15 zero `approved_amount` values are Denied or Under Review.

---

## Step 4: Domain validation: target

**Prompt:**
```
Add "3.2 Target" under section 3 with the same structure as 3.1, built from the model output
table policy_claims_summary. Run the model to get the data.

- One intro line saying the example checks assume the output is loaded as a table
  (CREATE TABLE policy_claims_summary AS <model query>).
- 3.2.1 Categorical columns: same table as 3.1.1 plus a "Source domain" column naming the source
  column each value must exist in. Rule: values must be in the list AND in the source domain.
  Notes: explain any source value missing from the target, tracing which filter removed each
  affected owner. Add a "Value definitions" subsection (Value | Meaning) describing what each value
  means in the target table. Validation logic and an example check (run it).
- 3.2.2 Numerical (quantitative) columns: distribution stats and expected range tables for the
  target's quantitative columns. Base the expected ranges on the business rules (for example
  claim_count >= 1 because of the HAVING filter) and include a formula check for the calculated
  rate. Validation logic and an example check (run it).
```

**Check:**
- The notes explain that **`OR` is missing** from `owner_state`: two Oregon owners have only Cancelled policies, and one has only a Denied claim.
- The example checks return 0 rows.

---

## Step 5: Data profiling

**Prompt:**
```
Add section 4 "Data profiling" with "4.1 Source" and "4.2 Target".

For each, one table covering every column: table_name, column_name, data_type, row_count,
non_null_count, null_count, null_pct, zero_count, non_zero_count, zero_pct.
- Zero columns apply only to numeric columns; use – for text and date columns.
- null_pct = null_count / row_count; zero_pct = zero_count / non_null_count.
- Bold any null or zero count above 0.
- Explain how each measure is calculated, with pseudo code.
- Under each table, a "Findings" table: column, finding, expected? Explain every null and zero with
  the business rule that causes it, and confirm the explanation with a query.
```

**Check:**
- Source findings: `closed_date` has 13 nulls (the open claims), `dwelling_coverage` has 5 zeros, and `approved_amount` has 15 zeros.
- Target findings: `total_approved` and `approval_rate_pct` each have 2 zeros (rows with only Under Review claims).

---

## Step 6: Strategy (column importance)

**Prompt:**
```
Add section 5 "Strategy" that ranks the columns of the target table by how important each is
compared with the others.

- 5.1 How importance is scored: score each column 1-3 on Business impact, Transformation risk and
  Dependency (defines the grain, feeds other columns, or decides which rows are kept). Show what
  1, 2 and 3 mean for each factor, and map total scores to Critical / High / Medium / Low.
- 5.2 Column ranking: rank, column, the three scores, total, priority, and why (link to the BR numbers).
- 5.3 Test depth by priority: which tests to run for each priority and what happens if a test fails
  (Critical and High stop the release; Medium and Low are warnings).
- 5.4 Order of testing: grain first, then row selection, money columns, calculated columns, the rest.
```

**Check:**
- `owner_id` and `policy_type` rank as Critical because they define the grain.
- `claim_count` is Critical because it decides which rows are kept.

---

## Step 7: Profiling review questions

**Prompt:**
```
Add section 6 "Profiling review questions": the questions to ask to decide whether a column's
profile makes sense.

- 6.1 to 6.7: question lists for every column, nulls, zeros, numeric columns, categorical columns,
  date columns, and identifier/key columns. About five questions each, each with a short example
  from this data.
- 6.8: a table for the target columns: column, key question, current answer (checked with a query),
  makes sense?
```

**Check:**
- The 6.8 answers match the model output: 11 unique rows, the latest incident is 2026-04-10, and `policy_count` is always 1.

---

## Step 8: QA test scenarios

**Prompt:**
```
Add section 7 "QA test scenarios" using all the information in the document so far
(business rules, grain, joins, output columns, source profile, domain validation and value
definitions, expected ranges, profiling findings, strategy and review questions).

- One subsection per target column, in the priority order from section 5.
- Several scenarios per column where they apply. Do not add a scenario that does not apply.
- Table columns: ID, Scenario, Importance, Why it matters, Rule, Test data, Input and steps,
  Expected result.
  - Importance (High / Medium / Low) is about whether the column's content and format make sense,
    separate from the column priority. Define the three levels in the intro.
  - Why it matters: what would go wrong in the data if the scenario failed.
  - Test data: "Existing: <record IDs>" when the case is in the current data (check with a query),
    or "New: <records to build>" when it is not. New records go in a test copy, never in source/.
  - Expected result: concrete values, calculated from the data.
- Cover at least: reconciliation with the source; each business rule, including boundaries
  (for example credit_score exactly 600); grain and row count; joins (owners without policies,
  policies or claims with unknown keys); each status value from the value definitions; values with
  different case, extra spaces or empty values reaching the model's filters; expected ranges;
  rounding; data types; and any finding from earlier sections that affects a target row.
- End with a summary table (column, priority, scenarios, existing, new, and counts by importance),
  a note on which new-data scenarios can share one test file, and a "Defects and open issues"
  table for any scenario that fails now or needs a business decision.
```

**Check:**
- Every scenario that uses existing data names real record IDs, and its expected result matches the model output.
- The summary counts match the number of rows in the scenario tables.
- The defects table includes **`claim_count` coming out as `HUGEINT`**, the **case-sensitive filters**, and **`CLM90015`**.

---

## Step 9: Final format and consistency check

**Prompt:**
```
Check the whole of test_plan/policy_claims_summary.md and fix any problems:
1. Every table has a header, a |---| divider directly under it with the same number of columns,
   the same number of columns in every row, and a blank line before it. Check this with a script,
   not by reading.
2. Any | inside a table cell is escaped as \| (including inside code).
3. Section numbers and cross-references (for example "see 3.2.1", "BR5") point to the right place.
4. Counts in summary tables match the rows they summarise.
5. Re-run every example DuckDB query in the document and confirm each still returns 0 rows.
Report what you changed.
```

**Check:**
- The script reports **0** table problems.
- All example queries return 0 rows.

---

## Keeping the test plan up to date

When the model or the source data changes, run these prompts in the same conversation as the original build, or start a new one with Step 0:

| Change | Prompt |
|---|---|
| New source data loaded | `Recalculate every number in sections 2.5, 3, 4 and 6.8 from the current data, update the findings, and re-check the "Existing" test data and expected results in section 7. List what changed.` |
| Model SQL changed | `Compare model/policy_claims_summary.sql with the business rules and output columns in section 1. Update section 1, then every section that depends on the changed rule or column, and add or change QA scenarios in section 7 for the change.` |
| New column added to the model | `Add <column> to section 1 (output columns, lineage), 3.2, 4.2, the ranking in section 5, 6.8 and section 7, following the existing format.` |
| Before sharing the document | Run Step 9 again. |
