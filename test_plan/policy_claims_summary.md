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

### 3.1 Source

Checks on the source tables (`policy_owner`, `policy_coverage`, `policy_claims`) in [`source/`](../source/).

#### 3.1.1 Categorical columns

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

##### Value definitions

What each unique value means. A value with no clear meaning here should be questioned before the data is accepted.

**`policy_owner.state` and `policy_coverage.property_state`**

Both columns use the same two-letter US state codes. `state` is the state of the **owner's mailing address**. `property_state` is the state where the **insured home** is.

| Value | Meaning |
|---|---|
| `CO` | Colorado |
| `FL` | Florida |
| `NC` | North Carolina |
| `OH` | Ohio |
| `OR` | Oregon |
| `TN` | Tennessee |
| `TX` | Texas |

**`policy_coverage.policy_type`**

| Value | Meaning |
|---|---|
| `HO-3 Standard` | Most common homeowners policy. Covers the house against all causes of loss unless excluded, and belongings against named causes only (fire, theft, wind and so on) |
| `HO-5 Premium` | Broadest homeowners policy. Covers both the house and belongings against all causes unless excluded |
| `HO-6 Condo` | Condominium unit owner policy. Covers the inside of the unit, improvements and belongings; the building itself is covered by the condo association |
| `HO-4 Renters` | Renters policy. Covers belongings and liability only, no building |
| `DP-3 Dwelling` | Dwelling fire policy for a home the owner does not live in, usually a rental property |

**`policy_coverage.construction_type`**

| Value | Meaning |
|---|---|
| `Wood Frame` | Structure built from a timber frame |
| `Brick` | Brick or brick-veneer walls |
| `Masonry` | Concrete block or stone walls |
| `Concrete` | Poured or precast concrete |
| `Steel Frame` | Structure built on a steel frame |

**`policy_coverage.flood_coverage` and `policy_coverage.earthquake_coverage`**

| Value | Meaning |
|---|---|
| `Y` | Yes: the optional cover is added to the policy |
| `N` | No: the optional cover is not included |

A `Flood` claim on a policy with `flood_coverage` = `N` is not covered and would normally be denied.

**Finding in the current data:** `CLM90015` is a `Flood` claim with status `Paid` on a policy with `flood_coverage` = `N`. Either the claim type is wrong, the cover flag is wrong, or the claim was paid in error. Confirm with the claims team. (`CLM90011`, the other Flood claim without cover, is correctly `Denied`.)

**`policy_coverage.status`**

| Value | Meaning |
|---|---|
| `Active` | Policy is currently in force (today is between `start_date` and `end_date`) |
| `Renewed` | Term has ended and has been replaced by a new term |
| `Expired` | Term has ended and was not renewed |
| `Cancelled` | Policy was ended before its `end_date`, by the owner or the insurer |

**`policy_claims.claim_type`**

| Value | Meaning |
|---|---|
| `Water Damage` | Sudden water escape inside the home (burst pipe, appliance leak) |
| `Fire` | Damage from fire or smoke |
| `Theft` | Belongings stolen, or damage during a break-in |
| `Wind/Hail` | Damage from windstorms, hurricanes or hail |
| `Liability` | Owner is responsible for injury to someone else or damage to their property |
| `Vandalism` | Deliberate damage by someone else |
| `Flood` | Rising surface water entering the home |
| `Mold` | Mold growth, usually after water damage |

**`policy_claims.claim_status`**

The values follow the claim workflow: `Under Review` → `Approved` or `Denied` → `Paid` → `Closed`.

| Value | Meaning |
|---|---|
| `Under Review` | Claim received and being assessed by an adjuster |
| `Approved` | Claim accepted and an amount agreed, but not paid yet |
| `Paid` | Payment has been issued to the owner |
| `Denied` | Claim rejected (not covered, under the deductible, or not valid) |
| `Closed` | Claim file finalised with no further action |

**`policy_claims.adjuster_name`**

| Value | Meaning |
|---|---|
| `A. Reyes` | Claims adjuster (sample name) |
| `J. Brooks` | Claims adjuster (sample name) |
| `K. Patel` | Claims adjuster (sample name) |
| `S. Nguyen` | Claims adjuster (sample name) |

A new name appearing should be checked against the list of current adjusters rather than treated as an error straight away.

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

#### 3.1.2 Numerical (quantitative) columns

**Rule:** every value in a numeric column must be filled in and fall inside the column's expected range. The distribution stats below are a baseline from the current data. When new data arrives, a large shift from this baseline (for example the median doubling, or many more zeros) should be investigated even if every value is within range.

Only quantitative columns are included: amounts, limits, scores and years. Identifiers and codes stored as numbers (such as `zip_code`) are not.

##### Distribution stats (baseline from source data)

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

##### Expected range (validation rules)

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

### 3.2 Target

Checks on the model output table `policy_claims_summary`, produced by [`model/policy_claims_summary.sql`](../model/policy_claims_summary.sql). The example checks assume the output has been loaded as a table, for example by running `CREATE TABLE policy_claims_summary AS <model query>` in a DuckDB database file (`run_sql.py --db`).

#### 3.2.1 Categorical columns

**Rule:** every value must be one of the values listed below, **and** must exist in the matching source column's domain (3.1.1). The model only passes values through, so a target value that is not in the source means the transformation is wrong.

| table_name | column_name | data_type | unique_count | unique_values | Source domain |
|---|---|---|---|---|---|
| `policy_claims_summary` | `owner_state` | VARCHAR | 6 | `CO`, `FL`, `NC`, `OH`, `TN`, `TX` | `policy_owner.state` |
| `policy_claims_summary` | `policy_type` | VARCHAR | 5 | `DP-3 Dwelling`, `HO-3 Standard`, `HO-4 Renters`, `HO-5 Premium`, `HO-6 Condo` | `policy_coverage.policy_type` |

**Notes:**
- `owner_state` has 6 values, while the source `state` has 7. `OR` drops out because none of the 3 Oregon owners passes the filters: two have only Cancelled policies (BR3), and the third has only a Denied claim (BR1). A target domain that is a subset of the source domain is expected; a value outside the source domain is a failure.
- `owner_id` and `owner_name` are identifiers, and `latest_incident_date` is a date, so they are not included.

##### Value definitions

The values mean the same as in the source (see 3.1.1 value definitions). This table explains what each value means **in the target table**.

**`owner_state`** (from `policy_owner.state`)

| Value | Meaning |
|---|---|
| `CO` | Owner's mailing address is in Colorado |
| `FL` | Owner's mailing address is in Florida |
| `NC` | Owner's mailing address is in North Carolina |
| `OH` | Owner's mailing address is in Ohio |
| `TN` | Owner's mailing address is in Tennessee |
| `TX` | Owner's mailing address is in Texas |

`OR` (Oregon) is a valid value but is not in the current output, because no Oregon owner passes the filters (see Notes above).

**`policy_type`** (from `policy_coverage.policy_type`)

| Value | Meaning |
|---|---|
| `HO-3 Standard` | The row covers the owner's standard homeowners policies |
| `HO-5 Premium` | The row covers the owner's premium (broadest) homeowners policies |
| `HO-6 Condo` | The row covers the owner's condo unit policies |
| `HO-4 Renters` | The row covers the owner's renters policies |
| `DP-3 Dwelling` | The row covers the owner's rental (landlord) properties |

**Validation logic (pseudo code):**
```
FOR EACH (column_name, unique_values, source_domain) IN the table above:
    FOR EACH row IN policy_claims_summary:
        IF row.column_name IS empty
           OR row.column_name NOT IN unique_values
           OR row.column_name NOT IN source_domain:
            report FAIL (column_name, owner_id, policy_type, bad value)
    IF no failures: report PASS (column_name)
```

**Example check (DuckDB):** should return 0 rows.
```sql
SELECT t.owner_id, t.policy_type
FROM policy_claims_summary AS t
WHERE t.policy_type IS NULL
   OR t.policy_type NOT IN (SELECT DISTINCT policy_type
                            FROM read_csv_auto('source/policy_coverage.csv'));
```

#### 3.2.2 Numerical (quantitative) columns

**Rule:** every value must be filled in and fall inside the expected range. The distribution stats below are a baseline from the current model output.

##### Distribution stats (baseline from target data)

| table_name | column_name | data_type | count | null_count | zero_count | min | p25 | median | mean | p75 | max | std_dev |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `policy_claims_summary` | `policy_count` | BIGINT | 11 | 0 | 0 | 1 | 1 | 1 | 1 | 1 | 1 | 0 |
| `policy_claims_summary` | `total_annual_premium` | DOUBLE | 11 | 0 | 0 | 199.25 | 993.87 | 1,370.23 | 1,804.33 | 2,573.59 | 3,808.81 | 1,163.09 |
| `policy_claims_summary` | `claim_count` | HUGEINT | 11 | 0 | 0 | 1 | 1 | 2 | 1.55 | 2 | 2 | 0.52 |
| `policy_claims_summary` | `total_claimed` | DOUBLE | 11 | 0 | 0 | 3,772.93 | 14,549.73 | 40,397.32 | 42,847.37 | 60,141.21 | 98,955.95 | 30,930.97 |
| `policy_claims_summary` | `total_approved` | DOUBLE | 11 | 0 | 2 | 0 | 4,049.98 | 27,318.85 | 21,567.93 | 32,271.43 | 53,553.52 | 18,200.92 |
| `policy_claims_summary` | `approval_rate_pct` | DOUBLE | 11 | 0 | 2 | 0 | 32.25 | 69.1 | 52.53 | 71.4 | 88.5 | 32 |

p25 and p75 are the 25th and 75th percentiles. std_dev is the sample standard deviation. All amounts are in USD; `approval_rate_pct` is a percentage.

##### Expected range (validation rules)

| table_name | column_name | Expected range | Notes |
|---|---|---|---|
| `policy_claims_summary` | `policy_count` | ≥ 1 | Every row comes from at least one policy. In the current data it is always 1, so the case where an owner has two policies of the same type is not tested yet |
| `policy_claims_summary` | `total_annual_premium` | > 0 | Must equal the sum of `annual_premium` of the row's policies in the source |
| `policy_claims_summary` | `claim_count` | ≥ 1 | Rows with no non-denied claims are removed (BR5) |
| `policy_claims_summary` | `total_claimed` | > 0 | Follows from `claim_count` ≥ 1 and source `claim_amount` > 0 |
| `policy_claims_summary` | `total_approved` | 0 – `total_claimed` | 0 when every non-denied claim in the row is still Under Review. Both zeros in the current data are this case (`OWN1001` DP-3 Dwelling, `OWN1014` HO-6 Condo) |
| `policy_claims_summary` | `approval_rate_pct` | 0 – 100 | Must equal `total_approved / total_claimed × 100`, rounded to 1 decimal. Never null, because `total_claimed` > 0 |

**Validation logic (pseudo code):**
```
FOR EACH (column_name, expected_range) IN the table above:
    FOR EACH row IN policy_claims_summary:
        IF row.column_name IS empty OR row.column_name OUTSIDE expected_range:
            report FAIL (column_name, owner_id, policy_type, bad value)
    IF no failures: report PASS (column_name)

FOR EACH column: compare new min / median / max / zero_count with the baseline
    IF the change is large: report WARN for review
```

**Example check (DuckDB):** should return 0 rows.
```sql
SELECT owner_id, policy_type, total_claimed, total_approved, approval_rate_pct
FROM policy_claims_summary
WHERE claim_count < 1
   OR total_claimed <= 0
   OR total_approved < 0
   OR total_approved > total_claimed
   OR approval_rate_pct NOT BETWEEN 0 AND 100
   OR approval_rate_pct <> ROUND(total_approved / total_claimed * 100, 1);
```

---

## 4. Data profiling

### 4.1 Source

Null and zero profile of every column in the three source tables, as of 2026-11-18. Use it as the baseline to compare new data loads against.

How each measure is calculated:
- **null_pct** = null_count / row_count × 100. An empty field in the CSV counts as null.
- **zero_count / non_zero_count / zero_pct** apply only to numeric columns (`–` for text and date columns). non_zero_count = non_null_count − zero_count, and zero_pct = zero_count / non_null_count × 100.

| table_name | column_name | data_type | row_count | non_null_count | null_count | null_pct | zero_count | non_zero_count | zero_pct |
|---|---|---|---|---|---|---|---|---|---|
| `policy_owner` | `owner_id` | VARCHAR | 20 | 20 | 0 | 0.0% | – | – | – |
| `policy_owner` | `first_name` | VARCHAR | 20 | 20 | 0 | 0.0% | – | – | – |
| `policy_owner` | `last_name` | VARCHAR | 20 | 20 | 0 | 0.0% | – | – | – |
| `policy_owner` | `date_of_birth` | DATE | 20 | 20 | 0 | 0.0% | – | – | – |
| `policy_owner` | `email` | VARCHAR | 20 | 20 | 0 | 0.0% | – | – | – |
| `policy_owner` | `phone` | VARCHAR | 20 | 20 | 0 | 0.0% | – | – | – |
| `policy_owner` | `address` | VARCHAR | 20 | 20 | 0 | 0.0% | – | – | – |
| `policy_owner` | `city` | VARCHAR | 20 | 20 | 0 | 0.0% | – | – | – |
| `policy_owner` | `state` | VARCHAR | 20 | 20 | 0 | 0.0% | – | – | – |
| `policy_owner` | `zip_code` | VARCHAR | 20 | 20 | 0 | 0.0% | – | – | – |
| `policy_owner` | `credit_score` | BIGINT | 20 | 20 | 0 | 0.0% | 0 | 20 | 0.0% |
| `policy_owner` | `customer_since` | DATE | 20 | 20 | 0 | 0.0% | – | – | – |
| `policy_coverage` | `policy_id` | VARCHAR | 25 | 25 | 0 | 0.0% | – | – | – |
| `policy_coverage` | `owner_id` | VARCHAR | 25 | 25 | 0 | 0.0% | – | – | – |
| `policy_coverage` | `policy_type` | VARCHAR | 25 | 25 | 0 | 0.0% | – | – | – |
| `policy_coverage` | `property_address` | VARCHAR | 25 | 25 | 0 | 0.0% | – | – | – |
| `policy_coverage` | `property_city` | VARCHAR | 25 | 25 | 0 | 0.0% | – | – | – |
| `policy_coverage` | `property_state` | VARCHAR | 25 | 25 | 0 | 0.0% | – | – | – |
| `policy_coverage` | `year_built` | BIGINT | 25 | 25 | 0 | 0.0% | 0 | 25 | 0.0% |
| `policy_coverage` | `construction_type` | VARCHAR | 25 | 25 | 0 | 0.0% | – | – | – |
| `policy_coverage` | `dwelling_coverage` | BIGINT | 25 | 25 | 0 | 0.0% | **5** | 20 | **20.0%** |
| `policy_coverage` | `personal_property_coverage` | BIGINT | 25 | 25 | 0 | 0.0% | 0 | 25 | 0.0% |
| `policy_coverage` | `liability_coverage` | BIGINT | 25 | 25 | 0 | 0.0% | 0 | 25 | 0.0% |
| `policy_coverage` | `deductible` | BIGINT | 25 | 25 | 0 | 0.0% | 0 | 25 | 0.0% |
| `policy_coverage` | `flood_coverage` | VARCHAR | 25 | 25 | 0 | 0.0% | – | – | – |
| `policy_coverage` | `earthquake_coverage` | VARCHAR | 25 | 25 | 0 | 0.0% | – | – | – |
| `policy_coverage` | `annual_premium` | DOUBLE | 25 | 25 | 0 | 0.0% | 0 | 25 | 0.0% |
| `policy_coverage` | `start_date` | DATE | 25 | 25 | 0 | 0.0% | – | – | – |
| `policy_coverage` | `end_date` | DATE | 25 | 25 | 0 | 0.0% | – | – | – |
| `policy_coverage` | `status` | VARCHAR | 25 | 25 | 0 | 0.0% | – | – | – |
| `policy_claims` | `claim_id` | VARCHAR | 35 | 35 | 0 | 0.0% | – | – | – |
| `policy_claims` | `policy_id` | VARCHAR | 35 | 35 | 0 | 0.0% | – | – | – |
| `policy_claims` | `claim_type` | VARCHAR | 35 | 35 | 0 | 0.0% | – | – | – |
| `policy_claims` | `incident_date` | DATE | 35 | 35 | 0 | 0.0% | – | – | – |
| `policy_claims` | `reported_date` | DATE | 35 | 35 | 0 | 0.0% | – | – | – |
| `policy_claims` | `claim_amount` | DOUBLE | 35 | 35 | 0 | 0.0% | 0 | 35 | 0.0% |
| `policy_claims` | `approved_amount` | DOUBLE | 35 | 35 | 0 | 0.0% | **15** | 20 | **42.9%** |
| `policy_claims` | `claim_status` | VARCHAR | 35 | 35 | 0 | 0.0% | – | – | – |
| `policy_claims` | `adjuster_name` | VARCHAR | 35 | 35 | 0 | 0.0% | – | – | – |
| `policy_claims` | `closed_date` | DATE | 35 | 22 | **13** | **37.1%** | – | – | – |

**Findings** (values in bold above):

| Column | Finding | Expected? |
|---|---|---|
| `policy_claims.closed_date` | 13 nulls (37.1%) | Yes. All 13 are open claims (9 Under Review, 4 Approved), which have no closed date yet |
| `policy_coverage.dwelling_coverage` | 5 zeros (20.0%) | Yes. All 5 are HO-4 Renters policies, which have no dwelling cover |
| `policy_claims.approved_amount` | 15 zeros (42.9%) | Yes. All 15 are Denied or Under Review claims |
| All other columns | No nulls, no zeros | Yes |

**Profiling logic (pseudo code):**
```
FOR EACH table, FOR EACH column:
    row_count      = number of rows
    non_null_count = rows where column is filled in
    null_count     = row_count − non_null_count
    null_pct       = null_count / row_count × 100
    IF column is numeric:
        zero_count     = rows where column = 0
        non_zero_count = non_null_count − zero_count
        zero_pct       = zero_count / non_null_count × 100
```

### 4.2 Target

Null and zero profile of every column in the model output table `policy_claims_summary`, as of 2026-11-18. The measures are calculated the same way as in 4.1.

| table_name | column_name | data_type | row_count | non_null_count | null_count | null_pct | zero_count | non_zero_count | zero_pct |
|---|---|---|---|---|---|---|---|---|---|
| `policy_claims_summary` | `owner_id` | VARCHAR | 11 | 11 | 0 | 0.0% | – | – | – |
| `policy_claims_summary` | `owner_name` | VARCHAR | 11 | 11 | 0 | 0.0% | – | – | – |
| `policy_claims_summary` | `owner_state` | VARCHAR | 11 | 11 | 0 | 0.0% | – | – | – |
| `policy_claims_summary` | `policy_type` | VARCHAR | 11 | 11 | 0 | 0.0% | – | – | – |
| `policy_claims_summary` | `policy_count` | BIGINT | 11 | 11 | 0 | 0.0% | 0 | 11 | 0.0% |
| `policy_claims_summary` | `total_annual_premium` | DOUBLE | 11 | 11 | 0 | 0.0% | 0 | 11 | 0.0% |
| `policy_claims_summary` | `claim_count` | HUGEINT | 11 | 11 | 0 | 0.0% | 0 | 11 | 0.0% |
| `policy_claims_summary` | `total_claimed` | DOUBLE | 11 | 11 | 0 | 0.0% | 0 | 11 | 0.0% |
| `policy_claims_summary` | `total_approved` | DOUBLE | 11 | 11 | 0 | 0.0% | **2** | 9 | **18.2%** |
| `policy_claims_summary` | `latest_incident_date` | DATE | 11 | 11 | 0 | 0.0% | – | – | – |
| `policy_claims_summary` | `approval_rate_pct` | DOUBLE | 11 | 11 | 0 | 0.0% | **2** | 9 | **18.2%** |

**Findings** (values in bold above):

| Column | Finding | Expected? |
|---|---|---|
| `total_approved` | 2 zeros (18.2%) | Yes. Both rows have only Under Review claims left after denied claims are removed (BR1), and Under Review claims have `approved_amount` = 0 |
| `approval_rate_pct` | 2 zeros (18.2%) | Yes. Same 2 rows: 0 approved ÷ amount claimed = 0% |
| All other columns | No nulls, no zeros | Yes. `claim_count` ≥ 1 for every row (BR5), so `latest_incident_date` and `approval_rate_pct` are never null |

---

## 5. Strategy

This section ranks the 11 columns of the target table `policy_claims_summary` by how important each is compared with the others. Testing effort, and how strictly a failure is treated, follow the ranking: the most important columns get the deepest testing, and a failure in them stops the release.

### 5.1 How importance is scored

Each column is scored from 1 (low) to 3 (high) on three factors. The three scores are added together, giving a total from 3 to 9.

| Factor | Question | 1 | 2 | 3 |
|---|---|---|---|---|
| **Business impact** | How much harm does a wrong value do to the decisions made from this table? | Display only | Used in analysis | Drives underwriting, renewal or financial decisions |
| **Transformation risk** | How likely is the model to get it wrong? | Copied straight from source | Simple calculation or one rule | Several rules, joins or aggregation that can double-count |
| **Dependency** | How much else in the table depends on it? | Nothing | One other column or rule | Defines the grain, feeds other columns, or decides which rows are kept |

| Total score | Priority |
|---|---|
| 8 – 9 | Critical |
| 6 – 7 | High |
| 4 – 5 | Medium |
| 3 | Low |

### 5.2 Column ranking

| Rank | column_name | Business impact | Transformation risk | Dependency | Score | Priority | Why |
|---|---|---|---|---|---|---|---|
| 1 | `total_claimed` | 3 | 3 | 3 | **9** | Critical | Main measure of claims exposure. Depends on BR1 (denied excluded), BR2 (total per policy before join) and BR7. Feeds `approval_rate_pct` and sets the sort order (BR10) |
| 2 | `owner_id` | 3 | 2 | 3 | **8** | Critical | Half of the grain and the join key to policies. A wrong key duplicates, merges or drops rows, which makes every other column wrong |
| 3 | `policy_type` | 3 | 2 | 3 | **8** | Critical | The other half of the grain. A wrong value moves policies into the wrong group, changing every total on both rows |
| 4 | `total_approved` | 3 | 3 | 2 | **8** | Critical | The amount actually paid or due to be paid. Same rules and double-counting risk as `total_claimed`. Feeds `approval_rate_pct` |
| 5 | `claim_count` | 2 | 3 | 3 | **8** | Critical | Decides which rows appear at all (BR5: at least one claim). Depends on BR1 and BR2. An error adds or removes whole rows |
| 6 | `total_annual_premium` | 3 | 3 | 1 | **7** | High | Revenue side of the claims-to-premium comparison. Most at risk of double-counting: it is only correct because claims are totalled per policy first (BR2). BR6 (claim-free policies still count) also affects it |
| 7 | `approval_rate_pct` | 3 | 3 | 1 | **7** | High | Key indicator for reviews. Calculated from two other columns, with divide-by-zero handling (BR8) and rounding (BR9). Usually correct if ranks 1 and 4 are correct |
| 8 | `latest_incident_date` | 2 | 2 | 1 | **5** | Medium | Shows how recent the activity is. Simple `MAX`, but must ignore denied claims (BR1) |
| 9 | `policy_count` | 1 | 2 | 1 | **4** | Medium | Context for the totals. Simple count, but the case of two policies of the same type for one owner is not in the current data (see 3.2.2) |
| 10 | `owner_state` | 2 | 1 | 1 | **4** | Medium | Used to slice results by state. Copied straight from `policy_owner.state` |
| 11 | `owner_name` | 1 | 1 | 1 | **3** | Low | Display only. Simple concatenation of first and last name. Contains personal data, so check where the table is shared rather than the value itself |

### 5.3 Test depth by priority

| Priority | Columns | Tests to run | If a test fails |
|---|---|---|---|
| **Critical** | `total_claimed`, `owner_id`, `policy_type`, `total_approved`, `claim_count` | Reconcile every row against totals calculated independently from the source tables. Test each business rule that affects the column (BR1, BR2, BR5) with records built for that purpose, including edge cases: a policy with several claims, a policy with only denied claims, and an owner with two policies of the same type. Check the grain is unique (no duplicate `owner_id` + `policy_type`). Domain, range and null checks (sections 3 and 4) | **Stop the release.** Fix before the table is used |
| **High** | `total_annual_premium`, `approval_rate_pct` | Reconcile against the source (premium) or recalculate from other columns (rate). Specific test for double-counting: a policy with 3 claims must add its premium once. Range and null checks | **Stop the release.** Fix before the table is used |
| **Medium** | `latest_incident_date`, `policy_count`, `owner_state` | Range, domain and null checks. Spot-check a sample of rows against the source | Warn. Release can go ahead; fix in the next change |
| **Low** | `owner_name` | Null check and data profiling only | Warn. Fix when convenient |

### 5.4 Order of testing

1. **Grain first:** check `owner_id` + `policy_type` is unique and that the row count matches what is expected. If the grain is wrong, every other test result is meaningless.
2. **Row selection:** check `claim_count`, and with it the filters BR1, BR3, BR4 and BR5, so that the right rows are in the table.
3. **Money columns:** reconcile `total_claimed`, `total_approved` and `total_annual_premium` with the source tables.
4. **Calculated columns:** check `approval_rate_pct` against the money columns.
5. **Everything else:** run domain validation and profiling on the remaining Medium and Low columns.

---

## 6. Profiling review questions

Profiling (section 4) gives the numbers; these questions decide whether the numbers make sense. Work through them for each column, starting with the Critical and High columns from section 5. A question with no clear answer should go to the data or business owner before the column is signed off.

### 6.1 General questions (every column)

1. **Meaning:** What does this column represent in the business, and what values would someone who works with it expect to see?
2. **Source of truth:** Where does the value come from (entered by a person, set by a system, calculated by the model)? Who owns it?
3. **Data type:** Is the data type right for the meaning? For example, is a ZIP code stored as text so leading zeros are kept, and is a date stored as a date rather than text?
4. **Row count:** Does the number of rows match what is expected from the source or the previous load?
5. **Change over time:** Compared with the previous load, did the null count, zero count, distinct count, min, max or median change by more than normal growth would explain?

### 6.2 Nulls (missing values)

1. Is the column **required**? If yes, any null is a defect.
2. If nulls are allowed, **what does a null mean**: not yet known, not applicable, or lost in loading?
3. Do the nulls follow a **business rule**? For example, `closed_date` should be null only for claims that are still open.
4. Are the nulls **concentrated** in one group (one state, one policy type, one load date)? A cluster usually points to a loading problem, not real missing data.
5. Are there **hidden nulls**: empty strings, spaces, `N/A`, `unknown`, `0` or `1900-01-01` used to mean "missing"?

### 6.3 Zeros

1. Is zero a **valid business value** for this column, or is it impossible (for example, a premium of 0)?
2. If zero is valid, **which rule explains it**? For example, `dwelling_coverage` = 0 only for HO-4 Renters, and `approved_amount` = 0 only for Denied or Under Review claims.
3. Do all the zeros **match that rule**? Cross-check the zero rows against the column that explains them.
4. Is zero being used **in place of null** (the value was unknown, so 0 was stored)?
5. Is the zero percentage **reasonable**? For example, if 90% of approved amounts were 0, would that match the claims process?

### 6.4 Numeric (quantitative) columns

1. Are **min and max** inside the possible range (credit score 300–850, a year not in the future, amounts not negative)?
2. Are min and max **believable for the business**, not just possible? For example, is a $5 premium or a $50M claim realistic for this book of business?
3. Are **mean and median** close? A mean much higher than the median means a few large values are pulling it up. Are those values real, or errors such as an extra zero?
4. Are there **outliers** far outside p25–p75? Check those rows one by one.
5. Are the values **suspiciously round or repeated** (for example many values of exactly 1,000), suggesting a default or placeholder?
6. Is the **precision** right: two decimal places for money, whole numbers for counts?
7. Do values agree with **related columns**? For example, `approved_amount` ≤ `claim_amount`, and `approval_rate_pct` = `total_approved / total_claimed × 100`.

### 6.5 Categorical columns

1. Is every value in the **expected list** (section 3)? Are any expected values **missing** (for example, no `Active` policies)?
2. Are there **near-duplicates** that mean the same thing: different case, extra spaces, spelling (`Paid`, `paid`, `PAID `)?
3. Does the **split between values** make sense? For example, would the business expect a third of all policies to be Cancelled?
4. Does any value appear **only once or twice**? Rare values are often typos.
5. Does a **target** column contain only values that exist in its source column?

### 6.6 Date columns

1. Are the dates within a **sensible window**: not in the future when they shouldn't be, and not unreasonably old?
2. Are dates in the **right order** with related dates (`start_date` < `end_date`, `incident_date` ≤ `reported_date` ≤ `closed_date`)?
3. Do dates fall inside related **periods**? For example, a claim's `incident_date` should be between its policy's `start_date` and `end_date`.
4. Are there **default dates** such as `1900-01-01` or `9999-12-31` standing in for missing values?
5. Are there gaps or spikes in the **distribution over time** (for example no claims for a whole month)?

### 6.7 Identifier and key columns

1. Is the key **unique** where it should be (the primary key of a source table, or the grain of the target)?
2. Is the key **never null**?
3. Does every foreign key **find a match** in its parent table (every `policy_id` in claims exists in coverage)?
4. Do the IDs follow the **expected format** (OWN####, POL####, CLM#####)?
5. Is the number of **distinct keys** in the target what the source predicts after the filters are applied?

### 6.8 Target table: questions to ask per column

The questions most important for each target column, with the answer from the current data (as of 2026-11-18).

| column_name | Key question | Current answer | Makes sense? |
|---|---|---|---|
| `owner_id` | Is `owner_id` + `policy_type` unique, and does every `owner_id` exist in `policy_owner`? | 11 rows, 11 unique combinations; all owners found | Yes |
| `owner_name` | Is it always "first last" from the source, with no extra spaces or nulls? | No nulls | Yes. Spot-check format |
| `owner_state` | Are all values in the source `state` list? Why is any source state missing? | 6 of 7 source states; `OR` is missing because of the filters (see 3.2.1) | Yes |
| `policy_type` | Are all values in the source list? Is every type present? | All 5 types present | Yes |
| `policy_count` | Is it ever greater than 1? If not, has the multi-policy case been tested? | Always 1 | Valid, but the multi-policy case is **not tested** |
| `total_annual_premium` | Does it equal the sum of source premiums for the row's policies, counted once each? | Min 199.25, max 3,808.81, no zeros | Yes, if the reconciliation in 5.3 passes |
| `claim_count` | Is it always ≥ 1? Does it match a count of non-denied source claims? | Min 1, max 2 | Yes |
| `total_claimed` | Is it always > 0? Is the largest value (98,955.95) a real total of real claims? | No zeros; largest row is OWN1005 with 2 claims | Yes. Confirm the largest rows against the source |
| `total_approved` | Are the zeros explained? Is it ever more than `total_claimed`? | 2 zeros, both rows with only Under Review claims; never above `total_claimed` | Yes |
| `latest_incident_date` | Is it ever null, or later than today? Does it ignore denied claims? | No nulls; latest is 2026-04-10 | Yes |
| `approval_rate_pct` | Is it always 0–100? Are the 0% rows the same as the zero `total_approved` rows? | 0 – 88.5; the 2 zeros match | Yes |

---

## 7. QA test scenarios

QA test scenarios for each column of the target table `policy_claims_summary`. They check that the model logic is correct (see the business rules BR1–BR10 in section 1), not the quality of incoming data (sections 3 and 4). Columns are listed in the priority order from section 5. A scenario is included only when it applies to the column.

**Test data column:**
- **Existing:** the case is already in the source CSVs. The record named is the one to check.
- **New:** the case is not in the current data (see 2.5 and 6.8). Build the records in a separate test copy of the source files, never in `source/`, then run the model against that copy.

**Pass / fail:** a failed Critical or High scenario stops the release; a failed Medium or Low scenario is a warning (section 5.3).

**Importance column:** how much the scenario matters for deciding whether the column's content and format make sense. This is separate from the column priority in section 5: a Critical column can still have a Low-importance format check.
- **High:** if this fails, the values are wrong or misleading. Totals are off, rows are in the table that should not be (or are missing), or the row contradicts itself. Decisions made from the table would be wrong.
- **Medium:** if this fails, values are wrong only in an edge case or for a small group of rows, or the problem is easy to spot. The content is doubtful but not misleading overall.
- **Low:** if this fails, the meaning of the data is still right, but the format or presentation is off (rounding, spacing, sort order, data type).
- **Why it matters** explains what would go wrong in the data if the scenario failed.

### 7.1 `total_claimed` (Critical)

| ID | Scenario | Importance | Why it matters | Rule | Test data | Input and steps | Expected result |
|---|---|---|---|---|---|---|---|
| TC-01 | Total matches the source for every row | **High** | Main check that the claims exposure figure is true. If it fails, the headline number for every owner is wrong and any underwriting or renewal decision based on it is misleading. | BR1, BR2 | Existing: all 11 rows | Sum `claim_amount` of non-denied claims on non-cancelled policies per `owner_id` + `policy_type`, calculated directly from the source | Equal for every row, to 2 decimals |
| TC-02 | Denied claim amount is left out | **High** | Makes sure the amount shows only claims that can still be paid. Without it, rejected claims inflate exposure; `OWN1014` would look three times riskier than it is. | BR1 | Existing: `OWN1014` HO-6 Condo (`POL5014`: Under Review 12,310.57 + Denied 26,464.59) | Run model | `total_claimed` = 12,310.57, not 38,775.16 |
| TC-03 | Claims from several policies of the same type are added together | **High** | Makes sure the total is complete when an owner has several policies of the same type. A failure silently drops or double-counts claims, and current data has no such owner to reveal it. | BR2 | New: one owner, two HO-3 policies; policy A has claims of 1,000 and 2,000, policy B has a claim of 500 | Run model | One row, `total_claimed` = 3,500.00 |
| TC-04 | Claims on a cancelled policy are left out | **Medium** | Claims on cancelled policies are not current business. Including them overstates exposure, but only for owners with a cancelled and a live policy of the same type. | BR3 | New: one owner, two HO-3 policies; policy A Renewed with a 1,000 claim, policy B Cancelled with a 5,000 claim | Run model | `total_claimed` = 1,000.00 |
| TC-05 | Result is rounded to 2 decimals | **Low** | Format check: money should read as a clean 2-decimal amount. Rounding noise does not change the meaning but looks wrong in reports and breaks exact comparisons. | BR9 | New: two claims of 0.10 and 0.20 on one policy | Run model | `total_claimed` = 0.30 exactly (not 0.30000000000000004) |
| TC-06 | Value is always above 0 | **Medium** | Quick sense check: every row exists because it has claims, so a total of 0 or less means amounts were lost or a row was kept that should not be. | BR5 | Existing: all rows | Check min | Min > 0 (current min 3,772.93) |
| TC-07 | Rows are sorted by `total_claimed`, highest first | **Low** | Presentation: readers expect the largest exposure first. A wrong order does not change any value. | BR10 | Existing: all rows | Compare each row with the next | Every row ≥ the row after it; first row `OWN1005` DP-3 Dwelling (98,955.95) |
| TC-08 | Amounts from every non-denied status are included | **High** | Under Review, Approved, Paid and Closed are all live claims (claim status definitions, 3.1.1). Leaving any of them out understates exposure. | BR1; claim status definitions (3.1.1) | Existing: `OWN1020` DP-3 (`POL5020`: Paid + Approved), `OWN1007` HO-4 (`POL5007`: Under Review + Closed) | Run model; add up both claims of each policy in the source | `OWN1020` DP-3 = 60,481.85 and `OWN1007` HO-4 = 47,231.28, each equal to the sum of its two claims |
| TC-09 | A questionable source claim is passed through unchanged | **Medium** | The model does not check cover flags, so the uncovered Paid Flood claim `CLM90015` (finding in 3.1.1) is included. It is 52,117.60 of the top-ranked row's 98,955.95, so the highest exposure in the table depends on a record that may be wrong. | Source finding (3.1.1 flood cover) | Existing: `OWN1005` DP-3 (`POL5021`, `CLM90015`) | Run model; compare with the source claim | `total_claimed` = 98,955.95 including `CLM90015`. Re-run after the claims team confirms the claim; if it is corrected, this row changes and may lose its first place (TC-07) |

### 7.2 `owner_id` (Critical)

| ID | Scenario | Importance | Why it matters | Rule | Test data | Input and steps | Expected result |
|---|---|---|---|---|---|---|---|
| OID-01 | `owner_id` + `policy_type` is unique | **High** | Protects the grain. A duplicate row doubles every total when the table is summed, and users cannot tell which row is right. | Grain | Existing: all rows | Count rows vs distinct `owner_id` + `policy_type` | Equal (current: 11 = 11) |
| OID-02 | Every `owner_id` exists in `policy_owner` | **High** | A row for an owner who is not in the owner table describes a customer who does not exist, so its content cannot be trusted or traced. | Join | Existing: all rows | Look up each `owner_id` in the source | All found |
| OID-03 | `owner_id` is never null and keeps the source format | **Medium** | Null or badly formatted IDs cannot be matched to other systems. The format check also catches IDs being cut short or read as numbers. | Join | Existing: all rows | Check nulls and format `OWN` + 4 digits | No nulls; all match the format |
| OID-04 | Owner with policies of two types appears on two rows | **High** | Keeps an owner's different policy types apart. Merged rows would mix, for example, renters and dwelling figures into a total that means nothing. | Grain | Existing: `OWN1005` (HO-3 and DP-3, both with claims) | Run model | Two rows for `OWN1005`, one per type |
| OID-05 | Owner whose only policy is Cancelled is left out | **High** | Cancelled business must not appear as current claims experience. `OWN1015` has 4 claims that would wrongly mark them as high-risk. | BR3 | Existing: `OWN1015` (`POL5015` Cancelled, with 4 claims) | Run model | `OWN1015` not in output |
| OID-06 | Owner with a credit score below 600 is left out | **High** | Low-score owners are outside this view. Including them changes which customers the totals describe, and the current data cannot show the filter working. | BR4 | New: owner with `credit_score` = 599, a Renewed policy and a Paid claim | Run model | Owner not in output |
| OID-07 | Owner with a credit score of exactly 600 is kept | **Medium** | Boundary check: using `>` instead of `>=` would silently drop valid owners with a score of exactly 600. | BR4 (boundary) | Existing: `OWN1007` (`credit_score` = 600) | Run model | `OWN1007` in output |
| OID-08 | Owner with a null credit score is left out | **Medium** | Owners with no score are dropped without warning. They may be real customers, so the business needs to confirm this is intended. | BR4 | New: owner with `credit_score` null, Renewed policy, Paid claim | Run model | Owner not in output (a null score fails `>= 600`). Confirm with the business that this is intended |
| OID-09 | Owner with no policies is left out | **Low** | Owners without policies cannot have claims. This mainly confirms the join does not create empty rows. | Join (INNER) | New: owner in `policy_owner` with no rows in `policy_coverage` | Run model | Owner not in output |
| OID-10 | Policy whose `owner_id` is not in `policy_owner` is left out | **Medium** | Confirms the model does not invent rows for unknown customers. It also shows that such claims are silently dropped, which should be reported as a source data problem. | Join (INNER) | New: policy with `owner_id` = `OWN9999` (not in owners) and a Paid claim | Run model | No row for `OWN9999`; no error |
| OID-11 | Number of rows matches the number the source predicts | **High** | The row count is the first sign that the filters and the grain work together (review question 6.7). Too many rows means a filter failed; too few means valid owners were lost. | Grain; BR1, BR3, BR4, BR5 | Existing: all source data | From the source, count distinct `owner_id` + `policy_type` with a non-denied claim on a non-cancelled policy and `credit_score` ≥ 600 | 11 predicted = 11 in output |

### 7.3 `policy_type` (Critical)

| ID | Scenario | Importance | Why it matters | Rule | Test data | Input and steps | Expected result |
|---|---|---|---|---|---|---|---|
| PT-01 | Values are passed through from the source unchanged | **Medium** | Values must match the source exactly. A changed spelling or case splits one type into two groups in every report. | Pass-through | Existing: all rows | Compare each row's `policy_type` with its policies in `policy_coverage` | Exact match, including case and spacing |
| PT-02 | Values are in the source domain | **Medium** | A type outside the source list is not a real product, and reports grouped by type would show a stray category. | Domain (3.2.1) | Existing: all rows | Check against `policy_coverage.policy_type` values | All 5 values valid; none outside the list |
| PT-03 | Two policies of the same type for one owner become one row | **High** | Core grain rule that the current data never tests. Two rows for one owner and type would break the grain and split that owner's totals. | Grain | New: one owner, two HO-3 policies, each with a Paid claim | Run model | One row for that owner + HO-3 |
| PT-04 | A type whose policies are all filtered out produces no row | **High** | Only types with live, non-denied claims should appear. A row for a cancelled or claim-free type shows claims experience that does not exist. | BR3, BR5 | Existing: `OWN1009` DP-3 (Cancelled), `OWN1006` DP-3 (Cancelled), `OWN1020` HO-4 (Renewed, no claims) | Run model | No DP-3 row for `OWN1009` or `OWN1006`; no HO-4 row for `OWN1020`; their other types still appear |
| PT-05 | `policy_type` is never null | **Medium** | A row with no policy type has no meaning in a table grouped by type. | Grain | Existing: all rows | Check nulls | No nulls |
| PT-06 | Same type written with different case or spaces becomes a separate row | **Medium** | The model groups on the exact text. `HO-3 Standard` and `ho-3 standard ` would split one owner's HO-3 policies into two rows and break the grain. Domain validation (3.1.1) must reject the bad value before the model runs. | Grain; domain rule (3.1.1: case and spaces) | New: one owner, two HO-3 policies with claims, one written `HO-3 Standard` and one `ho-3 standard ` | Run the 3.1.1 domain check, then the model | Domain check flags `ho-3 standard `. If the model runs anyway it produces two rows for that owner: raise this as a defect |

### 7.4 `total_approved` (Critical)

| ID | Scenario | Importance | Why it matters | Rule | Test data | Input and steps | Expected result |
|---|---|---|---|---|---|---|---|
| TA-01 | Total matches the source for every row | **High** | Main check that the approved amount is true. This is money paid or owed, so an error misstates losses. | BR1, BR2 | Existing: all 11 rows | Sum `approved_amount` of non-denied claims on non-cancelled policies per group | Equal for every row, to 2 decimals |
| TA-02 | Denied claim is left out even when it has an approved amount | **Medium** | Guards against a source problem the current data does not have. If it happens, the total would include money that was never approved. | BR1 | New: Denied claim with `approved_amount` = 1,000 (a source anomaly) next to a Paid claim with `approved_amount` = 500 | Run model | `total_approved` = 500.00. Current data cannot test this: every Denied claim has `approved_amount` = 0 |
| TA-03 | Group with only Under Review claims gives 0 | **High** | Nothing approved must show as 0, not blank. A blank reads as "unknown" and breaks sums and the approval rate. | BR1, BR7 | Existing: `OWN1001` DP-3 (one Under Review claim) | Run model | `total_approved` = 0.00, not null |
| TA-04 | Approved amounts from several same-type policies are added together | **High** | Makes sure approved amounts are complete when an owner has several policies of the same type. | BR2 | New: one owner, two HO-3 policies with approved amounts 1,000 and 250 | Run model | `total_approved` = 1,250.00 |
| TA-05 | Never more than `total_claimed` | **High** | Approving more than was claimed is impossible. If it appears, the content makes no sense and usually points to double-counting. | Range (3.2.2) | Existing: all rows | Compare the two columns | `total_approved` ≤ `total_claimed` on every row |
| TA-06 | Result is rounded to 2 decimals | **Low** | Format check: amounts read as clean 2-decimal values. | BR9 | Existing: `OWN1003` HO-3 (raw sum 27,663.620000000003) | Run model | 27,663.62 |
| TA-07 | Approved but not yet paid amounts are included | **High** | `Approved` means an amount is agreed but not paid yet (3.1.1). It is money owed, so it must count; leaving it out understates losses. | BR1; claim status definitions (3.1.1) | Existing: `OWN1020` DP-3 (`POL5020`: Paid + Approved) | Run model; add up `approved_amount` of both source claims | `total_approved` = 53,553.52, including the Approved claim |
| TA-08 | A questionable source claim is passed through unchanged | **Medium** | All 27,318.85 approved for `OWN1005` DP-3 comes from `CLM90015`, the Paid Flood claim on a policy without flood cover (3.1.1). If that claim is wrong, this row's approved amount and approval rate are wrong too. | Source finding (3.1.1 flood cover) | Existing: `OWN1005` DP-3 (`CLM90015`) | Run model; compare with the source claim | `total_approved` = 27,318.85, all from `CLM90015`. Re-run after the claims team confirms the claim |

### 7.5 `claim_count` (Critical)

| ID | Scenario | Importance | Why it matters | Rule | Test data | Input and steps | Expected result |
|---|---|---|---|---|---|---|---|
| CC-01 | Count matches the source for every row | **High** | Main check that claim activity is counted correctly. The count decides which rows exist, so an error adds or removes whole rows. | BR1, BR2 | Existing: all 11 rows | Count non-denied claims on non-cancelled policies per group | Equal for every row |
| CC-02 | Denied claims are not counted | **High** | Rejected claims must not count as activity. Counting them makes owners look riskier than they are. | BR1 | Existing: `OWN1014` HO-6 (1 Under Review + 1 Denied) | Run model | `claim_count` = 1 |
| CC-03 | All non-denied statuses are counted | **High** | Every live status (Under Review, Approved, Paid, Closed) must be counted. Missing one hides open or settled exposure. | BR1 | Existing: `OWN1020` DP-3 (`POL5020`: Paid + Approved), `OWN1007` HO-4 (`POL5007`: Under Review + Closed) | Run model | `claim_count` = 2 for both |
| CC-04 | Group where every claim is Denied is left out | **High** | An owner whose only claims were rejected has no claims experience. A row for them would show a claim count of 0, which makes no sense in this table. | BR1, BR5 | Existing: `OWN1013` (`POL5013` Renewed, one Denied claim) | Run model | `OWN1013` not in output |
| CC-05 | Group with no claims at all is left out | **High** | Rows without claims do not belong in a claims experience view. A row with 0 claims means the filter failed. | BR5 | Existing: `OWN1002` (`POL5002` Expired, no claims) | Run model | `OWN1002` not in output |
| CC-06 | Claims from several same-type policies are added together | **High** | Makes sure the count is complete across several policies of the same type. | BR2 | New: one owner, two HO-3 policies with 2 and 1 non-denied claims | Run model | `claim_count` = 3 |
| CC-07 | Claims on a cancelled policy are not counted | **Medium** | Claims on cancelled policies are not current activity. Only affects owners with both a cancelled and a live policy of the same type. | BR3 | New: one owner, two HO-3 policies; Renewed with 1 claim, Cancelled with 2 claims | Run model | `claim_count` = 1 |
| CC-08 | Value is always 1 or more | **Medium** | Quick sense check: a count of 0 means the row should not exist. | BR5 | Existing: all rows | Check min | Min = 1 |
| CC-09 | Column type is a standard whole number | **Medium** | The output column list shows this column as a 128-bit integer (DuckDB `HUGEINT`), the type DuckDB gives when it adds up counts. Many tools (pandas, Parquet readers, BI tools) cannot read 128-bit integers, so the value may fail to load or turn into text. | Output columns | Existing: model output | Check the column type | `BIGINT`. **Currently fails:** the type is `HUGEINT`. Fix by casting in the model, for example `CAST(SUM(...) AS BIGINT)` |
| CC-10 | `Denied` written with different case or spaces is counted | **High** | The model leaves out claims only when the status is exactly `Denied`. `denied` or `Denied ` slips through, so a rejected claim counts as activity and can create a row that should not exist. Domain validation (3.1.1) must reject the value first. | BR1; domain rule (3.1.1: case and spaces) | New: owner whose only claim has `claim_status` = `denied` (lower case) | Run the 3.1.1 domain check, then the model | Domain check flags `denied`. If the model runs anyway the owner appears with `claim_count` = 1: raise this as a defect and make the filter ignore case and spaces |
| CC-11 | Claim with no status is silently left out | **Medium** | An empty status fails `<> 'Denied'` (a null comparison is never true), so the claim disappears without any warning, even if it is a real open claim. | BR1 | New: policy with a Paid claim and a claim with empty `claim_status` | Run model | `claim_count` = 1; the empty-status claim is not counted. Confirm with the business whether such claims should count, and report them as a source data problem |
| CC-12 | Claim whose policy is not in `policy_coverage` is left out | **Medium** | A claim for an unknown policy cannot be linked to an owner, so it is dropped without warning. The model behaves correctly, but the lost claim should be reported as a source data problem. | Join (LEFT, claims to policies) | New: claim with `policy_id` = `POL9999` (not in coverage) | Run model | No row created for the claim; model runs without error; totals of other rows unchanged |

### 7.6 `total_annual_premium` (High)

| ID | Scenario | Importance | Why it matters | Rule | Test data | Input and steps | Expected result |
|---|---|---|---|---|---|---|---|
| TAP-01 | Premium of a policy with several claims is counted once | **High** | Catches the most likely bug in this model: premium repeated once per claim. A doubled premium makes claims look half as costly relative to premium. | BR2 | Existing: `OWN1005` DP-3 (`POL5021`, premium 1,370.23, 2 claims) | Run model | `total_annual_premium` = 1,370.23, not 2,740.46 |
| TAP-02 | Premium is counted once with 3 or more claims | **High** | Same as TAP-01 with 3 or more claims, which catches a fix that only works for 2 claims. The current data has at most 2 claims per policy. | BR2 | New: one policy, premium 1,000, with 3 Paid claims | Run model | `total_annual_premium` = 1,000.00, not 3,000.00 |
| TAP-03 | Same-type policy with no claims still adds its premium | **High** | Premium from a claim-free policy is real income. Leaving it out understates premium and makes the owner look riskier. | BR6 | New: one owner, two HO-3 policies; A (premium 1,000) has a Paid claim, B (premium 800) has no claims | Run model | `total_annual_premium` = 1,800.00 |
| TAP-04 | Same-type policy with only Denied claims still adds its premium | **Medium** | Combines two rules (rejected claims left out, premium kept). Makes sure removing a policy's only claim does not also remove its premium. | BR1, BR6 | New: as TAP-03, but policy B has one Denied claim | Run model | `total_annual_premium` = 1,800.00; B's claim not in `claim_count` |
| TAP-05 | Premium of a cancelled policy is left out | **Medium** | Premium from a cancelled policy is not current income. Including it overstates premium for owners with mixed policies. | BR3 | New: one owner, two HO-3 policies; Renewed (premium 1,000) with a claim, Cancelled (premium 700) | Run model | `total_annual_premium` = 1,000.00 |
| TAP-06 | Result is rounded to 2 decimals | **Low** | Format check: amounts read as clean 2-decimal values. | BR9 | New: two same-type policies with premiums 1,000.10 and 1,000.20 | Run model | 2,000.30 exactly |
| TAP-07 | Total matches the source for every row | **High** | Main check that the premium figure is true for every row. | BR2, BR3 | Existing: all 11 rows | Sum `annual_premium` of non-cancelled policies per group, each policy once | Equal for every row |
| TAP-08 | Value is always above 0 | **Medium** | Every row has at least one policy, and every source premium is above 0 (3.1.2), so a total of 0 or less means premium was lost (expected range, 3.2.2). | Range (3.2.2) | Existing: all rows | Check min | Min > 0 (current min 199.25) |

### 7.7 `approval_rate_pct` (High)

| ID | Scenario | Importance | Why it matters | Rule | Test data | Input and steps | Expected result |
|---|---|---|---|---|---|---|---|
| AR-01 | Rate matches the formula for every row | **High** | The rate must agree with the two totals next to it. If not, the row contradicts itself and readers cannot trust any of it. | BR8, BR9 | Existing: all 11 rows | Recalculate `ROUND(total_approved / total_claimed × 100, 1)` from the unrounded source sums | Equal for every row |
| AR-02 | Nothing approved gives 0% | **Medium** | Lower limit: nothing approved must show 0.0, not blank. | BR8 | Existing: `OWN1001` DP-3, `OWN1014` HO-6 | Run model | `approval_rate_pct` = 0.0 for both |
| AR-03 | Everything approved gives 100% | **Medium** | Upper limit: fully approved must show exactly 100.0. A value above 100 would make no sense. | BR8 | New: one Paid claim with `claim_amount` = `approved_amount` = 2,000 | Run model | `approval_rate_pct` = 100.0. Not in current data (max is 88.5) |
| AR-04 | Nothing claimed gives null, not an error | **Medium** | Makes sure the model does not crash when nothing was claimed, and that the result is blank ("not applicable") rather than a misleading 0. | BR8 | New: one non-denied claim with `claim_amount` = 0 (a source anomaly) | Run model | Model runs without error; `approval_rate_pct` is null |
| AR-05 | Rounded to 1 decimal | **Low** | Format check: rates read with 1 decimal. | BR9 | New: claimed 3,000, approved 1,000 (33.333…%) | Run model | 33.3 |
| AR-06 | Denied claims do not affect the rate | **High** | The rate must use the same claims as `total_claimed`. If rejected claims slip into the calculation, the rate disagrees with the totals shown. | BR1 | Existing: `OWN1014` HO-6 | Run model | Rate uses only the Under Review claim: 0 / 12,310.57 = 0.0, not 0 / 38,775.16 |
| AR-07 | Rate is always between 0 and 100 | **Medium** | A percentage outside 0–100 makes no sense (expected range, 3.2.2). A value above 100 would mean more was approved than claimed, usually a sign of double-counting. | Range (3.2.2) | Existing: all rows | Check min and max | Min 0.0, max 88.5; all within 0–100 |

### 7.8 `latest_incident_date` (Medium)

| ID | Scenario | Importance | Why it matters | Rule | Test data | Input and steps | Expected result |
|---|---|---|---|---|---|---|---|
| LID-01 | Date matches the source for every row | **Medium** | Main check that the date shows the owner's most recent real activity. | BR1, BR2 | Existing: all 11 rows | Latest `incident_date` of non-denied claims on non-cancelled policies per group | Equal for every row |
| LID-02 | A later Denied claim is ignored | **Medium** | A rejected claim must not make activity look more recent than it is. The current data cannot show this rule working. | BR1 | New: Paid claim on 2025-03-01 and Denied claim on 2025-09-01 on the same policy | Run model | 2025-03-01. Current data cannot test this: `OWN1014`'s Denied claim (2026-01-28) is earlier than its Under Review claim (2026-04-10) |
| LID-03 | Latest date is taken across several same-type policies | **Medium** | Makes sure the most recent date is found across several policies of the same type. | BR2 | New: one owner, two HO-3 policies with claims on 2024-05-01 and 2025-02-01 | Run model | 2025-02-01 |
| LID-04 | Never null, never in the future | **Medium** | Sense check: a row with claims must have an incident date, and a date after today is impossible. | BR5 | Existing: all rows | Check nulls and max against the run date | No nulls; max 2026-04-10 ≤ run date |
| LID-05 | Type is DATE | **Low** | Format check: a date stored as text sorts and compares wrongly (for example `2026-4-10` before `2026-04-09`). | Output columns | Existing: model output | Check the column type | DATE |
| LID-06 | Date falls within the row's policy periods | **Medium** | A claim can only happen while the policy is in force (review question 6.6). A date before the earliest `start_date` or after the latest `end_date` of the row's policies means a claim was linked to the wrong policy. | BR2; date rule (6.6) | Existing: all rows | Compare with the earliest `start_date` and latest `end_date` of the row's non-cancelled policies | All 11 rows within the period |

### 7.9 `policy_count` (Medium)

| ID | Scenario | Importance | Why it matters | Rule | Test data | Input and steps | Expected result |
|---|---|---|---|---|---|---|---|
| PC-01 | Count matches the source for every row | **Medium** | Main check that the number of policies behind each row is right. | BR3 | Existing: all 11 rows | Count non-cancelled policies per group | Equal for every row (currently all 1) |
| PC-02 | A policy with several claims is counted once | **High** | If the count goes up with the number of claims, the premium is being double-counted too (see TAP-01). A quick visible symptom of the most likely bug. | BR2 | Existing: `OWN1005` DP-3 (`POL5021`, 2 claims) | Run model | `policy_count` = 1, not 2 |
| PC-03 | Two same-type policies, both with claims | **Medium** | Shows the combining of same-type policies working. The current data never has a count above 1. | Grain | New: one owner, two HO-3 policies, each with a Paid claim | Run model | `policy_count` = 2 |
| PC-04 | Same-type policy with no claims is still counted | **Medium** | A claim-free policy is still a policy. Leaving it out understates the count and the premium. | BR6 | New: as PC-03, but the second policy has no claims | Run model | `policy_count` = 2 |
| PC-05 | Cancelled policy of the same type is not counted | **Medium** | Cancelled policies must not be counted as current business. | BR3 | New: one owner, two HO-3 policies; one Renewed with a claim, one Cancelled | Run model | `policy_count` = 1 |
| PC-06 | An Active policy is counted | **High** | Active policies are the current book of business. A mistake in the status filter would drop them all, and the current data has none to reveal it. | BR3 | New: owner with an Active HO-5 policy and a Paid claim | Run model | Row present, `policy_count` = 1. Not in current data (no Active policies) |
| PC-07 | Value is always 1 or more | **Low** | Quick sense check: every row comes from at least one policy (expected range, 3.2.2). | Range (3.2.2) | Existing: all rows | Check min | Min = 1 |
| PC-08 | Policy status written with different case or spaces is dropped | **High** | The model keeps a policy only when the status is exactly `Active`, `Renewed` or `Expired`. `renewed` or `Renewed ` fails the match, so a valid policy disappears with all its claims and premium. Domain validation (3.1.1) must reject the value first. | BR3; domain rule (3.1.1: case and spaces) | New: owner with one policy, `status` = `renewed` (lower case), and a Paid claim | Run the 3.1.1 domain check, then the model | Domain check flags `renewed`. If the model runs anyway the owner is missing from the output: raise this as a defect and make the filter ignore case and spaces |
| PC-09 | Policy with no status is silently dropped | **Medium** | An empty status never matches the list of kept statuses, so the policy and its claims disappear without warning. | BR3 | New: owner with one policy with empty `status` and a Paid claim | Run model | Owner not in output. Confirm with the business whether this is intended, and report the policy as a source data problem |

### 7.10 `owner_state` (Medium)

| ID | Scenario | Importance | Why it matters | Rule | Test data | Input and steps | Expected result |
|---|---|---|---|---|---|---|---|
| OS-01 | Value comes from the owner's mailing state | **Medium** | A wrong state puts the owner in the wrong group for state-level analysis. | Pass-through | Existing: all rows | Compare with `policy_owner.state` for the same `owner_id` | Exact match on every row |
| OS-02 | Mailing state is used, not the property state | **Medium** | Two state columns exist with different meanings. Using the property state changes what the column describes, and the current data cannot tell them apart. | Pass-through | New: owner with `state` = TX and a policy with `property_state` = FL, with a Paid claim | Run model | `owner_state` = TX. Current data cannot test this: property state always equals mailing state |
| OS-03 | Values are in the source domain | **Low** | A state outside the source list suggests the value was changed or corrupted along the way. | Domain (3.2.1) | Existing: all rows | Check against `policy_owner.state` values | All valid. `OR` is missing because of the filters (3.2.1) |
| OS-04 | Never null | **Low** | A row without a state drops out of any state-level analysis. | Pass-through | Existing: all rows | Check nulls | No nulls |
| OS-05 | A state with no qualifying owners does not appear | **Low** | A state can be valid in the source but missing from the target because of the filters (3.2.1). The test confirms the gap is explained, not caused by lost rows. | BR1, BR3; target domain (3.2.1) | Existing: `OR` owners `OWN1012` and `OWN1015` (Cancelled), `OWN1013` (only a Denied claim) | Run model | `OR` not in output; each of the 3 Oregon owners is excluded by BR3 or BR1 |

### 7.11 `owner_name` (Low)

| ID | Scenario | Importance | Why it matters | Rule | Test data | Input and steps | Expected result |
|---|---|---|---|---|---|---|---|
| ON-01 | Name is first name, one space, last name | **Low** | The name must match the customer record so people can recognise the owner. It does not affect any number. | Output columns | Existing: all rows | Compare with `first_name \|\| ' ' \|\| last_name` from the source | Exact match on every row |
| ON-02 | Missing first or last name | **Low** | A blank name makes the row hard to recognise. The business needs to decide whether the first name alone is acceptable. | Output columns | New: owner with `last_name` empty, Renewed policy, Paid claim | Run model | `owner_name` is null (in DuckDB, joining text with a null gives null). Confirm with the business whether the first name alone should be shown instead |
| ON-03 | No extra spaces | **Low** | Format check: extra spaces look wrong and break exact matching on names. | Output columns | Existing: all rows | Check for leading, trailing or double spaces | None found |

### 7.12 Summary

| Column | Priority | Scenarios | Existing data | New data needed | High importance | Medium importance | Low importance |
|---|---|---|---|---|---|---|---|
| `total_claimed` | Critical | 9 | 6 | 3 | 4 | 3 | 2 |
| `owner_id` | Critical | 11 | 7 | 4 | 6 | 4 | 1 |
| `policy_type` | Critical | 6 | 4 | 2 | 2 | 4 | 0 |
| `total_approved` | Critical | 8 | 6 | 2 | 5 | 2 | 1 |
| `claim_count` | Critical | 12 | 7 | 5 | 7 | 5 | 0 |
| `total_annual_premium` | High | 8 | 3 | 5 | 4 | 3 | 1 |
| `approval_rate_pct` | High | 7 | 4 | 3 | 2 | 4 | 1 |
| `latest_incident_date` | Medium | 6 | 4 | 2 | 0 | 5 | 1 |
| `policy_count` | Medium | 9 | 3 | 6 | 3 | 5 | 1 |
| `owner_state` | Medium | 5 | 4 | 1 | 0 | 2 | 3 |
| `owner_name` | Low | 3 | 2 | 1 | 0 | 0 | 3 |
| **Total** | | **84** | **50** | **34** | **33** | **37** | **14** |

Several new-data scenarios use the same setup: **one owner with two policies of the same type**. TC-03, TC-04, TA-04, CC-06, CC-07, TAP-03 to TAP-06, LID-03 and PC-03 to PC-05 can share one small test file with a few owners built this way. A second small file with **bad source values** (wrong case, extra spaces, empty statuses, unknown IDs) covers PT-06, CC-10 to CC-12, OID-10 and PC-08 to PC-09.

**Defects and open issues found by these scenarios:**

| Scenario | Issue | Action |
|---|---|---|
| CC-09 | `claim_count` is output as a 128-bit integer (`HUGEINT`), which many tools cannot read | **Fails now.** Cast to `BIGINT` in the model |
| CC-10, PC-08, PT-06 | Status and type filters match text exactly, so a value with different case or extra spaces is handled wrongly | Run domain validation (3.1.1) before the model; consider making the filters ignore case and spaces |
| CC-11, PC-09, OID-08 | Empty statuses and credit scores silently remove claims, policies or owners | Business to decide the intended handling |
| TC-09, TA-08 | Top-ranked row (`OWN1005` DP-3) depends on the questionable claim `CLM90015` | Claims team to confirm the claim; re-run the scenarios afterwards |

