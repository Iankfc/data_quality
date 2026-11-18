# LLM prompts log

Every prompt typed in this project session, in order, copied exactly as typed (typos included).
The **Result** column notes what each prompt produced.

For a cleaned-up, reusable version of the test-plan prompts, see [prompt_sequence.md](prompt_sequence.md).

## 1. Source data and model

| # | Prompt | Result |
|---|---|---|
| 1 | in the source folder create 3 csv file that will serve as a source data. create 3 sample csv data about housing insurance. one table is about the policy coverage, another for the policy owner, another for the policy claims | `source/policy_owner.csv`, `source/policy_coverage.csv`, `source/policy_claims.csv` |
| 2 | install duckdb in the .venv and create a sql script in the model folder for a sample script on how to join all 3 source table with group by, where, aggregation, renaming of columns | DuckDB installed; `model/policy_claims_summary.sql` |

## 2. Tooling

| # | Prompt | Result |
|---|---|---|
| 3 | how to run duckdb sql file in vscode | Explanation of the options |
| 4 | yes | `.vscode/tasks.json` (Ctrl+Shift+B runs the open SQL file) |
| 5 | write a python script that runs the .sql file as duck db | `run_sql.py` |
| 6 | change the python script so i can use python debuger. declare the file in the \_\_name\_\_ | `run_sql.py` default files in `__main__`; `.vscode/launch.json` |

## 3. Data catalog

| # | Prompt | Result |
|---|---|---|
| 7 | in the data_catalog folder create a json file for each source to detail the column name and the description or purpose of each columns | `data_catalog/*.json` |
| 8 | change allowed_values with domain_value | Key renamed (later changed by hand to `domain_values`) |

## 4. Test plan: purpose, sources, validation, profiling

| # | Prompt | Result |
|---|---|---|
| 9 | in the test_plan folder create a markdown file detailing the purpose of the model table, the details about the source tables | `test_plan/policy_claims_summary.md`, sections 1 and 2 |
| 10 | replace Where in SQL with deriviation logic like a sudo code that demonstrate the rule | Business rules table uses pseudo code |
| 11 | in the test plan, add a section that shows the domain validation which contains a table with column_name column, list of unique values per column. apply only for categorical column | Section 3, domain validation |
| 12 | remove columns from the domain validation sections that are quantitative numerical but kept the categorical oridinal | Numeric quantitative columns removed |
| 13 | under domain validation put categorical columns under categorical section | Categorical subsection |
| 14 | under domain validation add a section for numerical quantitative columns, create a table containing a column_name column, a column for min, max, other distribution stats or stats that best describe the data | Numerical subsection with distribution stats |
| 15 | add a data profiling section that shows a table with the column_name column, column about null count, non-null count, null percentage, zero count, non-zero, zero percentage | Section 4, data profiling |
| 16 | update the section in data profiling and domain validation to put source over the source table | Clarified by the next prompt |
| 17 | under domain validation put in source | "Source" subsections (3.1, 4.1) |
| 18 | then create the same tables in data profiling and domain validation  using the model table and call it as target | "Target" subsections (3.2, 4.2) |

## 5. Test plan: strategy, questions, test scenarios

| # | Prompt | Result |
|---|---|---|
| 19 | add a section for strategy detailing how important each column in the target table is relative to other columns in the target table | Section 5, strategy and column ranking |
| 20 | add a section with the list of questions that are important to ask to determin whether the data profile in a certain column make sense or not | Section 6, profiling review questions |
| 21 | what is the difference between doing data QA vs data quality checks | Explanation only (no file change) |
| 22 | create a section and create qa test scenarios for each column. use all information in the markdown file. create multiple test scenarios per column as they are applicable. do not create a qa test case if not applicable | Section 7, QA test scenarios |
| 23 | add a column for test case importance, explain the importance of each test case as it relates on making sure that the data format or content make sense or not | Importance and "Why it matters" columns |
| 24 | in the domain validation for both source and target, add a section that provides a description of what each unique value means and their purpose] | Value definitions tables |
| 25 | continue | Resumed the interrupted value definitions work |
| 26 | remove purpose just leave meaning | Value definitions reduced to Value \| Meaning |
| 27 | update the list of testcase base all information in the markdown file | Test scenarios expanded to 84 |

## 6. Formatting and outputs

| # | Prompt | Result |
|---|---|---|
| 28 | fix table format issue | Escaped `\|` inside table cells |
| 29 | fix missing tables with missing \|---\|---\|---\|---\| | Separator rows restored in 10 tables |
| 30 | create a separate markdown file which will contain the sequence of instruction on how to prompt an llm to produce the policy_clains_summary.md. | `test_plan/prompt_sequence.md` |
| 31 | convert policy_claims_summary.md as pdf | `test_plan/policy_claims_summary.pdf` |
| 32 | create a separate sheet for llm prompt, list down all the prompt I typed in | This file |
