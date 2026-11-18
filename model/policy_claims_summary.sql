-- =============================================================================
-- policy_claims_summary.sql
-- Sample DuckDB query joining all 3 source tables:
--   source/policy_owner.csv     (owner)
--   source/policy_coverage.csv  (policy)  -> owner_id
--   source/policy_claims.csv    (claims)  -> policy_id
--
-- Demonstrates: JOIN, WHERE, GROUP BY, HAVING, aggregation, column aliasing.
-- Run from the project root:
--   .venv/bin/python -c "import duckdb; print(duckdb.sql(open('model/policy_claims_summary.sql').read()))"
-- =============================================================================

WITH
owner AS (
    SELECT * FROM read_csv_auto('source/policy_owner.csv')
),
policy AS (
    SELECT * FROM read_csv_auto('source/policy_coverage.csv')
),
claims AS (
    SELECT * FROM read_csv_auto('source/policy_claims.csv')
),

-- Step 1: aggregate claims to one row per policy.
-- Doing this before the join avoids fan-out (a policy with 3 claims would
-- otherwise repeat its premium 3 times in the final SUM).
claims_per_policy AS (
    SELECT
        policy_id,
        COUNT(*)              AS claim_count,
        SUM(claim_amount)     AS total_claimed,
        SUM(approved_amount)  AS total_approved,
        MAX(incident_date)    AS latest_incident_date
    FROM claims
    WHERE claim_status <> 'Denied'          -- ignore denied claims
    GROUP BY policy_id
)

-- Step 2: join owner -> policy -> claim summary, then aggregate per owner & policy type.
SELECT
    o.owner_id                                   AS owner_id,
    o.first_name || ' ' || o.last_name           AS owner_name,
    o.state                                      AS owner_state,
    p.policy_type                                AS policy_type,
    COUNT(p.policy_id)                           AS policy_count,
    ROUND(SUM(p.annual_premium), 2)              AS total_annual_premium,
    SUM(COALESCE(c.claim_count, 0))              AS claim_count,
    ROUND(SUM(COALESCE(c.total_claimed, 0)), 2)  AS total_claimed,
    ROUND(SUM(COALESCE(c.total_approved, 0)), 2) AS total_approved,
    MAX(c.latest_incident_date)                  AS latest_incident_date,
    ROUND(
        SUM(COALESCE(c.total_approved, 0))
        / NULLIF(SUM(c.total_claimed), 0) * 100, 1
    )                                            AS approval_rate_pct
FROM owner AS o
INNER JOIN policy AS p
    ON p.owner_id = o.owner_id
LEFT JOIN claims_per_policy AS c                    -- keep policies with no claims
    ON c.policy_id = p.policy_id
WHERE p.status IN ('Active', 'Renewed', 'Expired')  -- exclude cancelled policies
  AND o.credit_score >= 600
GROUP BY
    o.owner_id,
    o.first_name,
    o.last_name,
    o.state,
    p.policy_type
HAVING SUM(COALESCE(c.claim_count, 0)) > 0          -- only groups with at least one claim
ORDER BY total_claimed DESC;
