-- ============================================================
-- Healthcare Provider ROI & Value-Based Care Analytics System
-- SQL Module: Provider Performance Scoring Model
-- ============================================================
-- Requires: SQLite / DuckDB / PostgreSQL compatible syntax
-- Tables: providers, patients, claims, quality_metrics
-- ============================================================


-- ────────────────────────────────────────────
-- 1. BASE CLAIMS SUMMARY PER PROVIDER
-- ────────────────────────────────────────────
CREATE VIEW IF NOT EXISTS vw_provider_claims_summary AS
SELECT
    c.provider_id,
    p.specialty,
    p.region,
    p.network_tier,
    p.accepts_value_based,

    -- Volume
    COUNT(c.claim_id)                                               AS total_claims,
    COUNT(DISTINCT c.patient_id)                                    AS unique_patients,

    -- Cost metrics
    ROUND(AVG(c.allowed_amount), 2)                                 AS avg_allowed,
    ROUND(AVG(c.paid_amount), 2)                                    AS avg_paid,
    ROUND(SUM(c.paid_amount), 2)                                    AS total_paid,
    ROUND(SUM(c.paid_amount) / NULLIF(COUNT(DISTINCT c.patient_id), 0), 2) AS cost_per_member,

    -- Utilization
    ROUND(AVG(c.los_days), 3)                                       AS avg_los,
    ROUND(SUM(c.readmission_30d) * 1.0 / NULLIF(COUNT(*), 0), 4)   AS readmission_rate,
    ROUND(SUM(c.er_visit) * 1.0 / NULLIF(COUNT(*), 0), 4)          AS er_visit_rate,
    ROUND(SUM(c.preventive_visit) * 1.0 / NULLIF(COUNT(*), 0), 4)  AS preventive_rate,

    -- Claim mix
    SUM(CASE WHEN c.claim_type = 'Inpatient'    THEN 1 ELSE 0 END)  AS inpatient_claims,
    SUM(CASE WHEN c.claim_type = 'Outpatient'   THEN 1 ELSE 0 END)  AS outpatient_claims,
    SUM(CASE WHEN c.claim_type = 'Professional' THEN 1 ELSE 0 END)  AS professional_claims

FROM claims c
JOIN providers p ON c.provider_id = p.provider_id
GROUP BY
    c.provider_id, p.specialty, p.region,
    p.network_tier, p.accepts_value_based;


-- ────────────────────────────────────────────
-- 2. SPECIALTY BENCHMARKS  (peer-group norms)
-- ────────────────────────────────────────────
CREATE VIEW IF NOT EXISTS vw_specialty_benchmarks AS
SELECT
    specialty,
    ROUND(AVG(avg_allowed), 2)       AS benchmark_avg_allowed,
    ROUND(AVG(cost_per_member), 2)   AS benchmark_cost_per_member,
    ROUND(AVG(readmission_rate), 4)  AS benchmark_readmission_rate,
    ROUND(AVG(er_visit_rate), 4)     AS benchmark_er_rate,
    ROUND(AVG(preventive_rate), 4)   AS benchmark_preventive_rate,
    ROUND(AVG(avg_los), 3)           AS benchmark_avg_los
FROM vw_provider_claims_summary
GROUP BY specialty;


-- ────────────────────────────────────────────
-- 3. NORMALISED COMPONENT SCORES  (0–100)
-- ────────────────────────────────────────────
CREATE VIEW IF NOT EXISTS vw_provider_score_components AS
WITH ranked AS (
    SELECT
        cs.*,
        qm.hedis_composite_score,
        qm.patient_satisfaction,
        qm.care_coordination_score,
        qm.generic_rx_rate,
        sb.benchmark_avg_allowed,
        sb.benchmark_cost_per_member,
        sb.benchmark_readmission_rate,
        sb.benchmark_er_rate,
        sb.benchmark_preventive_rate,

        -- Cost score: below-benchmark cost → higher score
        ROUND(100.0 * (1 - (cs.avg_allowed / NULLIF(sb.benchmark_avg_allowed, 0))), 2) AS cost_vs_benchmark,

        -- Efficiency ratio (paid / allowed; lower = more efficient)
        ROUND(cs.avg_paid / NULLIF(cs.avg_allowed, 0), 4)                              AS efficiency_ratio,

        -- Utilisation scores (lower readmit & ER = better)
        ROUND((1 - cs.readmission_rate / NULLIF(sb.benchmark_readmission_rate, 0)) * 100, 2) AS readmit_score,
        ROUND((1 - cs.er_visit_rate    / NULLIF(sb.benchmark_er_rate,          0)) * 100, 2) AS er_score,
        ROUND(cs.preventive_rate / NULLIF(sb.benchmark_preventive_rate, 0) * 100, 2)          AS preventive_score

    FROM vw_provider_claims_summary cs
    JOIN quality_metrics qm ON cs.provider_id = qm.provider_id
    JOIN vw_specialty_benchmarks sb ON cs.specialty  = sb.specialty
)
SELECT
    provider_id,
    specialty,
    region,
    network_tier,
    accepts_value_based,
    total_claims,
    unique_patients,
    cost_per_member,
    readmission_rate,
    er_visit_rate,
    preventive_rate,
    hedis_composite_score,
    patient_satisfaction,
    care_coordination_score,

    -- Clamp individual components to [0, 100]
    ROUND(MIN(MAX(cost_vs_benchmark + 50, 0), 100), 1)  AS cost_score,        -- centred at 50
    ROUND(MIN(MAX(readmit_score,            0), 100), 1) AS utilization_score,
    ROUND(MIN(MAX(er_score,                 0), 100), 1) AS er_score,
    ROUND(MIN(MAX(preventive_score,         0), 100), 1) AS preventive_score,
    ROUND(hedis_composite_score * 100, 1)                AS quality_score,
    ROUND(patient_satisfaction   * 100, 1)               AS satisfaction_score,
    ROUND(care_coordination_score * 100, 1)              AS coordination_score

FROM ranked;


-- ────────────────────────────────────────────
-- 4. COMPOSITE PROVIDER PERFORMANCE SCORE
--    Weights reflect value-based care priorities
-- ────────────────────────────────────────────
CREATE VIEW IF NOT EXISTS vw_provider_performance_scores AS
SELECT
    provider_id,
    specialty,
    region,
    network_tier,
    accepts_value_based,
    total_claims,
    unique_patients,
    cost_per_member,
    readmission_rate,
    er_visit_rate,
    cost_score,
    utilization_score,
    quality_score,
    satisfaction_score,
    coordination_score,

    -- Composite: Cost 30% | Quality 25% | Utilisation 20% | Satisfaction 15% | Coordination 10%
    ROUND(
        cost_score        * 0.30
      + quality_score     * 0.25
      + utilization_score * 0.20
      + satisfaction_score * 0.15
      + coordination_score * 0.10,
    1) AS composite_score,

    -- Tier label
    CASE
        WHEN (cost_score * 0.30 + quality_score * 0.25 + utilization_score * 0.20
              + satisfaction_score * 0.15 + coordination_score * 0.10) >= 70 THEN 'High Value'
        WHEN (cost_score * 0.30 + quality_score * 0.25 + utilization_score * 0.20
              + satisfaction_score * 0.15 + coordination_score * 0.10) >= 50 THEN 'Moderate Value'
        ELSE 'Low Value'
    END AS value_tier

FROM vw_provider_score_components;


-- ────────────────────────────────────────────
-- 5. REGIONAL VARIATION ANALYSIS
-- ────────────────────────────────────────────
CREATE VIEW IF NOT EXISTS vw_regional_variation AS
SELECT
    region,
    specialty,
    COUNT(DISTINCT provider_id)     AS provider_count,
    ROUND(AVG(composite_score), 1)  AS avg_composite_score,
    ROUND(AVG(cost_per_member), 2)  AS avg_cost_per_member,
    ROUND(AVG(readmission_rate), 4) AS avg_readmission_rate,
    ROUND(AVG(quality_score), 1)    AS avg_quality_score,
    SUM(CASE WHEN value_tier = 'High Value'     THEN 1 ELSE 0 END) AS high_value_providers,
    SUM(CASE WHEN value_tier = 'Moderate Value' THEN 1 ELSE 0 END) AS moderate_value_providers,
    SUM(CASE WHEN value_tier = 'Low Value'      THEN 1 ELSE 0 END) AS low_value_providers
FROM vw_provider_performance_scores
GROUP BY region, specialty
ORDER BY region, avg_composite_score DESC;


-- ────────────────────────────────────────────
-- 6. KPI DASHBOARD QUERY
-- ────────────────────────────────────────────
CREATE VIEW IF NOT EXISTS vw_kpi_summary AS
SELECT
    'Overall'                                           AS dimension,
    COUNT(DISTINCT provider_id)                         AS total_providers,
    ROUND(AVG(composite_score), 1)                      AS avg_composite_score,
    SUM(CASE WHEN value_tier = 'High Value' THEN 1 ELSE 0 END) * 100.0
        / NULLIF(COUNT(*), 0)                           AS pct_high_value,
    ROUND(AVG(cost_per_member), 2)                      AS avg_cost_per_member,
    ROUND(AVG(readmission_rate), 4)                     AS avg_readmission_rate,
    ROUND(AVG(quality_score), 1)                        AS avg_quality_score,
    SUM(unique_patients)                                AS total_members_attributed
FROM vw_provider_performance_scores;


-- ────────────────────────────────────────────
-- 7. DATA VALIDATION CHECKS
-- ────────────────────────────────────────────
-- Run these assertions before any downstream analysis

-- 7a. Claim amounts must be positive
SELECT 'FAIL: negative allowed_amount' AS check_name, COUNT(*) AS failures
FROM claims WHERE allowed_amount <= 0
UNION ALL
SELECT 'FAIL: paid > allowed', COUNT(*)
FROM claims WHERE paid_amount > allowed_amount
UNION ALL
-- 7b. All claims must link to valid providers
SELECT 'FAIL: orphan provider_id', COUNT(*)
FROM claims c LEFT JOIN providers p ON c.provider_id = p.provider_id
WHERE p.provider_id IS NULL
UNION ALL
-- 7c. All claims must link to valid patients
SELECT 'FAIL: orphan patient_id', COUNT(*)
FROM claims c LEFT JOIN patients pt ON c.patient_id = pt.patient_id
WHERE pt.patient_id IS NULL
UNION ALL
-- 7d. Binary flags must be 0 or 1
SELECT 'FAIL: invalid readmission flag', COUNT(*)
FROM claims WHERE readmission_30d NOT IN (0, 1)
UNION ALL
SELECT 'FAIL: invalid er_visit flag', COUNT(*)
FROM claims WHERE er_visit NOT IN (0, 1)
UNION ALL
-- 7e. Quality metrics coverage
SELECT 'WARN: providers missing quality metrics', COUNT(*)
FROM providers pr LEFT JOIN quality_metrics qm ON pr.provider_id = qm.provider_id
WHERE qm.provider_id IS NULL;
