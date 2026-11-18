# Test Plan: `policy_claims_summary`

| Item | Value |
|---|---|
| Model file | [`model/policy_claims_summary.sql`](../model/policy_claims_summary.sql) |
| Engine | DuckDB |
| Source tables | `policy_owner`, `policy_coverage`, `policy_claims` |
| Data catalog | [`data_catalog/`](../data_catalog/) |
| How to run | `.venv/bin/python run_sql.py model/policy_claims_summary.sql` |

---

## 1. Purpose of the model table

`policy_claims_summary` gives a **claims experience view per policy owner and policy type**. It answers:

- How much premium does each owner pay for each type of policy?
- How many claims have they filed, and how much did they claim?
- How much of what they claimed was approved (approval rate)?
- When was their most recent incident?

Typical uses are underwriting and renewal reviews (spotting owners with high claim activity relative to premium), loss analysis by policy type and state, and monitoring the claims approval rate.

### Grain

**One row per `owner_id` + `policy_type`.** An owner with policies of two different types (for example HO-3 and DP-3) appears on two rows. Two policies of the same type for one owner are combined into one row (`policy_count` = 2).

### Business rules applied

| # | Rule | Derivation logic (pseudo code) | Effect |
|---|---|---|---|
| BR1 | Denied claims are excluded | `FOR EACH claim:`<br>`  IF claim.claim_status = 'Denied' THEN skip claim`<br>`  ELSE keep claim` | Denied claims do not count in `claim_count`, `total_claimed`, `total_approved` or `latest_incident_date` |
| BR2 | Claims are totalled per policy **before** joining | `FOR EACH policy_id IN kept claims:`<br>`  claim_count = number of claims`<br>`  total_claimed = sum of claim_amount`<br>`  total_approved = sum of approved_amount`<br>`  latest_incident_date = latest incident_date`<br>`→ one row per policy_id` | Stops a policy's premium being counted once per claim (join fan-out) |
| BR3 | Cancelled policies are excluded | `FOR EACH policy:`<br>`  IF policy.status IN ('Active','Renewed','Expired') THEN keep`<br>`  ELSE skip  -- i.e. 'Cancelled'` | Cancelled policies and their claims are left out |
| BR4 | Owners with a credit score below 600 are excluded | `FOR EACH owner:`<br>`  IF owner.credit_score >= 600 THEN keep`<br>`  ELSE skip owner and all their policies` | Low-score owners are left out |
| BR5 | Only rows with at least one claim are kept | `FOR EACH (owner_id, policy_type) group:`<br>`  IF claim_count > 0 THEN output row`<br>`  ELSE drop row` | Owner + policy type groups with no (non-denied) claims are left out |
| BR6 | Policies with no claims still contribute premium | `FOR EACH kept policy:`<br>`  look up its claim totals (BR2)`<br>`  IF none found THEN keep policy with empty claim totals`<br>`  -- policy is never dropped for having no claims` | Inside a kept group, a claim-free policy still adds to `policy_count` and `total_annual_premium` |
| BR7 | Missing claim values count as 0 | `IF claim_count / total_claimed / total_approved IS empty`<br>`  THEN use 0` | Totals are never NULL |
| BR8 | Approval rate avoids dividing by zero | `IF total_claimed = 0 THEN approval_rate_pct = NULL`<br>`ELSE approval_rate_pct = total_approved / total_claimed * 100` | `approval_rate_pct` is NULL rather than an error when nothing was claimed |
| BR9 | Money and percentage columns are rounded | `total_annual_premium, total_claimed, total_approved = round(value, 2)`<br>`approval_rate_pct = round(value, 1)` | 2 decimals for USD, 1 decimal for % |
| BR10 | Sort order | `SORT output rows BY total_claimed, highest first` | Highest claimed amount first |

### Output columns

| Column | Type | Description | Source / derivation |
|---|---|---|---|
| `owner_id` | VARCHAR | Policy owner identifier | `policy_owner.owner_id` |
| `owner_name` | VARCHAR | Owner's full name | `policy_owner.first_name \|\| ' ' \|\| policy_owner.last_name` |
| `owner_state` | VARCHAR | Owner's mailing-address state | `policy_owner.state` (renamed) |
| `policy_type` | VARCHAR | Policy form (HO-3, HO-5, HO-6, HO-4, DP-3) | `policy_coverage.policy_type` |
| `policy_count` | BIGINT | Number of policies in the group | `COUNT(policy_coverage.policy_id)` |
| `total_annual_premium` | DOUBLE | Total yearly premium for the group (USD) | `ROUND(SUM(policy_coverage.annual_premium), 2)` |
| `claim_count` | INT128 | Number of non-denied claims | `SUM(COUNT(policy_claims.claim_id))` across the group's policies |
| `total_claimed` | DOUBLE | Total amount claimed (USD), denied claims excluded | `ROUND(SUM(policy_claims.claim_amount), 2)` |
| `total_approved` | DOUBLE | Total amount approved (USD), denied claims excluded | `ROUND(SUM(policy_claims.approved_amount), 2)` |
| `latest_incident_date` | DATE | Most recent non-denied incident | `MAX(policy_claims.incident_date)` |
| `approval_rate_pct` | DOUBLE | Approved as a % of claimed | `ROUND(total_approved / total_claimed * 100, 1)` |

### Lineage

```
policy_owner (owner_id)
    │ 1 : many   INNER JOIN on owner_id
    ▼
policy_coverage (policy_id, owner_id)          WHERE status <> Cancelled, credit_score >= 600
    │ 1 : 0..1   LEFT JOIN on policy_id
    ▼
claims_per_policy (policy_id)                   ← policy_claims, WHERE claim_status <> 'Denied', GROUP BY policy_id
    │
    ▼
policy_claims_summary                           GROUP BY owner_id, policy_type  HAVING claim_count > 0
```

---

## 2. Source tables

All sources are CSV files in [`source/`](../source/). The full column definitions, data types and `domain_values` lists are in the data catalog JSON files.

### 2.1 `policy_owner`

| Item | Value |
|---|---|
| File | [`source/policy_owner.csv`](../source/policy_owner.csv) |
| Catalog | [`data_catalog/policy_owner.json`](../data_catalog/policy_owner.json) |
| Description | People who hold one or more housing insurance policies |
| Grain | One row per owner |
| Row count | 20 |
| Primary key | `owner_id` |
| Foreign keys | None |
| Contains personal data | **Yes** (name, date of birth, email, phone, address) |

| Column | Type | Used in model | Description |
|---|---|---|---|
| `owner_id` | VARCHAR | Join key, output | Unique owner identifier (OWN####) |
| `first_name` | VARCHAR | `owner_name` | Given name |
| `last_name` | VARCHAR | `owner_name` | Family name |
| `date_of_birth` | DATE | – | Date of birth |
| `email` | VARCHAR | – | Contact email |
| `phone` | VARCHAR | – | Contact phone (555-###-####) |
| `address` | VARCHAR | – | Mailing street address |
| `city` | VARCHAR | – | Mailing city |
| `state` | VARCHAR | `owner_state` | Mailing state (2-letter code) |
| `zip_code` | VARCHAR | – | 5-digit ZIP code. Catalogued as text; `read_csv_auto` reads it as a number |
| `credit_score` | BIGINT | Filter (BR4) | Credit-based insurance score (300–850) |
| `customer_since` | DATE | – | Date the person became a customer |

### 2.2 `policy_coverage`

| Item | Value |
|---|---|
| File | [`source/policy_coverage.csv`](../source/policy_coverage.csv) |
| Catalog | [`data_catalog/policy_coverage.json`](../data_catalog/policy_coverage.json) |
| Description | Housing insurance policies with coverage limits, deductible, add-ons and premium |
| Grain | One row per policy term (12 months) |
| Row count | 25 (20 owners; 5 owners have 2 policies) |
| Primary key | `policy_id` |
| Foreign keys | `owner_id` → `policy_owner.owner_id` |
| Contains personal data | No (holds the property address, but not the owner's details) |

| Column | Type | Used in model | Description |
|---|---|---|---|
| `policy_id` | VARCHAR | Join key, `policy_count` | Unique policy identifier (POL####) |
| `owner_id` | VARCHAR | Join key | Owner of the policy |
| `policy_type` | VARCHAR | Group by, output | HO-3 Standard, HO-5 Premium, HO-6 Condo, HO-4 Renters, DP-3 Dwelling |
| `property_address` | VARCHAR | – | Insured property street address |
| `property_city` | VARCHAR | – | Insured property city |
| `property_state` | VARCHAR | – | Insured property state |
| `year_built` | BIGINT | – | Year the dwelling was built |
| `construction_type` | VARCHAR | – | Wood Frame, Brick, Masonry, Concrete, Steel Frame |
| `dwelling_coverage` | BIGINT | – | Coverage A limit (USD); 0 for HO-4 Renters |
| `personal_property_coverage` | BIGINT | – | Coverage C limit (USD) |
| `liability_coverage` | BIGINT | – | Coverage E limit (USD) |
| `deductible` | BIGINT | – | Amount the owner pays per claim (USD) |
| `flood_coverage` | VARCHAR | – | Flood add-on (Y/N) |
| `earthquake_coverage` | VARCHAR | – | Earthquake add-on (Y/N) |
| `annual_premium` | DOUBLE | `total_annual_premium` | Yearly premium (USD) |
| `start_date` | DATE | – | Date coverage starts |
| `end_date` | DATE | – | Date coverage ends |
| `status` | VARCHAR | Filter (BR3) | Active, Renewed, Expired, Cancelled |

### 2.3 `policy_claims`

| Item | Value |
|---|---|
| File | [`source/policy_claims.csv`](../source/policy_claims.csv) |
| Catalog | [`data_catalog/policy_claims.json`](../data_catalog/policy_claims.json) |
| Description | Claims filed against housing insurance policies |
| Grain | One row per claim |
| Row count | 35 (across 19 policies) |
| Primary key | `claim_id` |
| Foreign keys | `policy_id` → `policy_coverage.policy_id` |
| Contains personal data | No |

| Column | Type | Used in model | Description |
|---|---|---|---|
| `claim_id` | VARCHAR | `claim_count` | Unique claim identifier (CLM#####) |
| `policy_id` | VARCHAR | Join key | Policy the claim was filed under |
| `claim_type` | VARCHAR | – | Cause of loss: Water Damage, Fire, Theft, Wind/Hail, Liability, Vandalism, Flood, Mold |
| `incident_date` | DATE | `latest_incident_date` | Date the loss happened |
| `reported_date` | DATE | – | Date the claim was reported |
| `claim_amount` | DOUBLE | `total_claimed` | Amount requested (USD) |
| `approved_amount` | DOUBLE | `total_approved` | Amount approved after the deductible (USD); 0 if Denied or Under Review |
| `claim_status` | VARCHAR | Filter (BR1) | Under Review, Approved, Paid, Denied, Closed |
| `adjuster_name` | VARCHAR | – | Adjuster assigned to the claim |
| `closed_date` | DATE (nullable) | – | Date the claim was settled; empty while Under Review or Approved |

### 2.4 Relationships

| Parent | Child | Key | Cardinality | Join type in model |
|---|---|---|---|---|
| `policy_owner` | `policy_coverage` | `owner_id` | 1 : many | INNER |
| `policy_coverage` | `policy_claims` | `policy_id` | 1 : 0..many | LEFT (after totalling per policy) |

### 2.5 Source data profile (as of 2026-11-18)

| Measure | Value |
|---|---|
| Policies by `status` | Cancelled 8, Expired 8, Renewed 9, **Active 0** |
| Claims by `claim_status` | Paid 10, Under Review 9, Closed 6, Denied 6, Approved 4 |
| Owners with `credit_score` < 600 | 0 |
| Policy dates | `start_date` from 2022-01-01, `end_date` up to 2026-05-27 |
| Incident dates | 2022-02-16 to 2026-04-10 |
| Model output | 11 rows |

**What this means for testing:**
- No policy is `Active`, so the `Active` part of BR3 isn't exercised by the current data.
- No owner has a credit score below 600, so BR4 doesn't remove any rows yet.

Add test records that cover both cases (an Active policy, and an owner with a credit score below 600) to confirm these rules work.

---

## 3. Domain validation

Domain validation checks that each column only holds values from its expected domain.

### 3.1 Categorical columns

**Rule:** every value in a categorical column must be one of the column's unique values listed below. A value not on the list, an empty value, or a value with different case or extra spaces (for example `paid` or `Paid `) fails the check.

The lists are the unique values found in the source data, and they match `domain_values` in the [data catalog](../data_catalog/). Only categorical columns are included, both nominal (for example `claim_type`) and ordinal (for example `claim_status`, which follows a workflow order). IDs, names, dates and quantitative numeric columns are not.

| table_name | column_name | data_type | unique_count | unique_values |
|---|---|---|---|---|
| `policy_owner` | `state` | VARCHAR | 7 | `CO`, `FL`, `NC`, `OH`, `OR`, `TN`, `TX` |
| `policy_coverage` | `policy_type` | VARCHAR | 5 | `DP-3 Dwelling`, `HO-3 Standard`, `HO-4 Renters`, `HO-5 Premium`, `HO-6 Condo` |
| `policy_coverage` | `property_state` | VARCHAR | 7 | `CO`, `FL`, `NC`, `OH`, `OR`, `TN`, `TX` |
| `policy_coverage` | `construction_type` | VARCHAR | 5 | `Brick`, `Concrete`, `Masonry`, `Steel Frame`, `Wood Frame` |
| `policy_coverage` | `flood_coverage` | VARCHAR | 2 | `N`, `Y` |
| `policy_coverage` | `earthquake_coverage` | VARCHAR | 2 | `N`, `Y` |
| `policy_coverage` | `status` | VARCHAR | 3 | `Cancelled`, `Expired`, `Renewed` |
| `policy_claims` | `claim_type` | VARCHAR | 8 | `Fire`, `Flood`, `Liability`, `Mold`, `Theft`, `Vandalism`, `Water Damage`, `Wind/Hail` |
| `policy_claims` | `claim_status` | VARCHAR | 5 | `Approved`, `Closed`, `Denied`, `Paid`, `Under Review` |
| `policy_claims` | `adjuster_name` | VARCHAR | 4 | `A. Reyes`, `J. Brooks`, `K. Patel`, `S. Nguyen` |

**Notes:**
- `policy_coverage.status`: `Active` is a valid business value (the model filters on it in BR3), but it does not appear in the current data. Add it to the allowed list for the validation, or an Active policy will be flagged incorrectly.
- `state` and `property_state` list only the states in the sample data. If the data grows, validate against the full list of US state codes instead.
- Quantitative numeric columns (amounts, limits, counts, years, scores) are excluded even when they have few distinct values, for example `liability_coverage` and `deductible`. Validate them with range checks instead.

**Validation logic (pseudo code):**
```
FOR EACH (table_name, column_name, unique_values) IN the table above:
    FOR EACH row IN table_name:
        IF row.column_name IS empty OR row.column_name NOT IN unique_values:
            report FAIL (table_name, column_name, row key, bad value)
    IF no failures: report PASS (table_name, column_name)
```

**Example check (DuckDB):** should return 0 rows.
```sql
SELECT claim_id, claim_status
FROM read_csv_auto('source/policy_claims.csv')
WHERE claim_status IS NULL
   OR claim_status NOT IN ('Approved', 'Closed', 'Denied', 'Paid', 'Under Review');
```

### 3.2 Numerical (quantitative) columns

**Rule:** every value in a numeric column must be filled in and fall inside the column's expected range. The distribution stats below are a baseline from the current data. When new data arrives, a large shift from this baseline (for example the median doubling, or many more zeros) should be investigated even if every value is within range.

Only quantitative columns are included: amounts, limits, scores and years. Identifiers and codes stored as numbers (such as `zip_code`) are not.

#### Distribution stats (baseline from source data)

| table_name | column_name | data_type | count | null_count | zero_count | min | p25 | median | mean | p75 | max | std_dev |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `policy_owner` | `credit_score` | BIGINT | 20 | 0 | 0 | 600 | 683.5 | 725.5 | 720.7 | 774.25 | 813 | 64.2 |
| `policy_coverage` | `year_built` | BIGINT | 25 | 0 | 0 | 1954 | 1965 | 1989 | 1985.6 | 2004 | 2020 | 20.24 |
| `policy_coverage` | `dwelling_coverage` | BIGINT | 25 | 0 | 5 | 0 | 245,000 | 365,000 | 381,200 | 580,000 | 765,000 | 247,117.89 |
| `policy_coverage` | `personal_property_coverage` | BIGINT | 25 | 0 | 0 | 35,000 | 80,000 | 135,000 | 136,800 | 205,000 | 240,000 | 68,112.65 |
| `policy_coverage` | `liability_coverage` | BIGINT | 25 | 0 | 0 | 100,000 | 300,000 | 300,000 | 332,000 | 500,000 | 500,000 | 160,000 |
| `policy_coverage` | `deductible` | BIGINT | 25 | 0 | 0 | 500 | 1,000 | 1,500 | 1,920 | 2,500 | 5,000 | 1,662.58 |
| `policy_coverage` | `annual_premium` | DOUBLE | 25 | 0 | 0 | 199.25 | 1,030.59 | 1,821.25 | 1,803.05 | 2,308.48 | 3,808.81 | 934.31 |
| `policy_claims` | `claim_amount` | DOUBLE | 35 | 0 | 0 | 1,947.49 | 16,971.99 | 33,666.43 | 31,516.94 | 44,573.02 | 59,800.58 | 17,754.55 |
| `policy_claims` | `approved_amount` | DOUBLE | 35 | 0 | 15 | 0 | 0 | 5,451.58 | 12,486.97 | 25,909.42 | 41,594.12 | 14,831.59 |

p25 and p75 are the 25th and 75th percentiles: half of the values fall between them. std_dev is the sample standard deviation. All amounts are in USD.

#### Expected range (validation rules)

| table_name | column_name | Expected range | Notes |
|---|---|---|---|
| `policy_owner` | `credit_score` | 300 – 850 | Standard credit score scale |
| `policy_coverage` | `year_built` | 1800 – current year | A year in the future is invalid |
| `policy_coverage` | `dwelling_coverage` | ≥ 0 | Must be 0 when `policy_type` = HO-4 Renters, and > 0 for every other type. All 5 zeros in the current data are HO-4 Renters |
| `policy_coverage` | `personal_property_coverage` | > 0 | |
| `policy_coverage` | `liability_coverage` | > 0 | |
| `policy_coverage` | `deductible` | > 0 | |
| `policy_coverage` | `annual_premium` | > 0 | |
| `policy_claims` | `claim_amount` | > 0 | A claim must request some amount |
| `policy_claims` | `approved_amount` | 0 – `claim_amount` | Cannot exceed the amount claimed. Must be 0 when `claim_status` is Denied or Under Review. All 15 zeros in the current data are Denied or Under Review |

**Validation logic (pseudo code):**
```
FOR EACH (table_name, column_name, expected_range) IN the table above:
    FOR EACH row IN table_name:
        IF row.column_name IS empty OR row.column_name OUTSIDE expected_range:
            report FAIL (table_name, column_name, row key, bad value)
    IF no failures: report PASS (table_name, column_name)

FOR EACH column: compare new min / median / max / zero_count with the baseline
    IF the change is large: report WARN for review
```

**Example check (DuckDB):** should return 0 rows.
```sql
SELECT claim_id, claim_status, claim_amount, approved_amount
FROM read_csv_auto('source/policy_claims.csv')
WHERE approved_amount IS NULL
   OR approved_amount < 0
   OR approved_amount > claim_amount
   OR (claim_status IN ('Denied', 'Under Review') AND approved_amount <> 0);
```
