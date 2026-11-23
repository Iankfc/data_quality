add section to check if it make sense that a column can null, zero or negative
column inferring reason why not nullable or zero or negative

https://www.ibm.com/think/insights/data-testing-methods

define what an accurate  data is

https://www.keboola.com/blog/data-quality-checks
Validity	Is each value in the expected format and range?	1. Schema, 4. Accepted values, 5. Range
Completeness	Are required values present?	2. Completeness
Uniqueness	Is each record there once?	3. Uniqueness
Timeliness	Is the data current and for the right period?	6. Freshness and period
Consistency	Do values contradict each other or other tables?	7. Cross-field consistency, 8. Referential integrity
Accuracy	Does the data match reality?	9. Reconciliation and volume

data architect - definitions missing

test plan defines numerical quantitative columns for comparisson

id only 2 columns change all the rest of the colums still has to be checked

Test the source number data type decrease between source and target

Create a test that details what are the steps that need to be done to execute the test scenarios

make sure to add version tag in the output to make sure we can version control the output and revert if needed

connect to wiki for more business context

make sure there is not PII in the output report

Officially let us use the the dbt code the we can create a s2t file vs dbt generated s2t file 
We send BSA with the official definition of the column name and table description