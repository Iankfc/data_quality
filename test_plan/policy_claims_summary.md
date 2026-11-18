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

| # | Rule | Where in SQL | Effect |
|---|---|---|---|
| BR1 | Denied claims are excluded | `claims_per_policy` CTE: `WHERE claim_status <> 'Denied'` | Denied claims do not count in `claim_count`, `total_claimed`, `total_approved` or `latest_incident_date` |
| BR2 | Claims are totalled per policy **before** joining | `claims_per_policy` CTE: `GROUP BY policy_id` | Stops a policy's premium being counted once per claim (join fan-out) |
| BR3 | Cancelled policies are excluded | `WHERE p.status IN ('Active','Renewed','Expired')` | Cancelled policies and their claims are left out |
| BR4 | Owners with a credit score below 600 are excluded | `WHERE o.credit_score >= 600` | Low-score owners are left out |
| BR5 | Only rows with at least one claim are kept | `HAVING SUM(COALESCE(c.claim_count,0)) > 0` | Owner + policy type groups with no (non-denied) claims are left out |
| BR6 | Policies with no claims still contribute premium | `LEFT JOIN claims_per_policy` | Inside a kept group, a claim-free policy still adds to `policy_count` and `total_annual_premium` |
| BR7 | Missing claim values count as 0 | `COALESCE(..., 0)` | Totals are never NULL |
| BR8 | Approval rate avoids dividing by zero | `NULLIF(SUM(c.total_claimed), 0)` | `approval_rate_pct` is NULL rather than an error when nothing was claimed |
| BR9 | Money and percentage columns are rounded | `ROUND(..., 2)` / `ROUND(..., 1)` | 2 decimals for USD, 1 decimal for % |
| BR10 | Sort order | `ORDER BY total_claimed DESC` | Highest claimed amount first |

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

All sources are CSV files in [`source/`](../source/). The full column definitions, data types and `domain_value` lists are in the data catalog JSON files.

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
