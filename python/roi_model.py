"""
Healthcare Provider ROI & Value-Based Care Analytics System
ROI Model + Patient Steering Simulation
"""

import pandas as pd
import numpy as np
import sqlite3
import os
import warnings
warnings.filterwarnings("ignore")

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
DB_PATH  = os.path.join(DATA_DIR, "healthcare.db")


# ══════════════════════════════════════════════════════
#  DATABASE SETUP  (load CSVs → SQLite, run SQL views)
# ══════════════════════════════════════════════════════
def setup_database():
    """Load CSV files into SQLite and create all analytical views."""
    conn = sqlite3.connect(DB_PATH)
    for table in ["providers", "patients", "claims", "quality_metrics"]:
        path = f"{DATA_DIR}/{table}.csv"
        if os.path.exists(path):
            pd.read_csv(path).to_sql(table, conn, if_exists="replace", index=False)
            print(f"  Loaded {table}")

    sql_path = os.path.join(os.path.dirname(__file__), "..", "sql", "provider_scoring.sql")
    with open(sql_path) as f:
        statements = [s.strip() for s in f.read().split(";") if s.strip()
                      and not s.strip().startswith("--")]
    for stmt in statements:
        try:
            conn.execute(stmt)
        except Exception:
            pass   # some statements are SELECT-based checks; skip gracefully
    conn.commit()
    print("  Database ready:", DB_PATH)
    return conn


# ══════════════════════════════════════════════════════
#  PROVIDER SCORING  (Python replication of SQL model)
# ══════════════════════════════════════════════════════
def build_provider_scores(conn) -> pd.DataFrame:
    """Pull composite scores from the SQL view."""
    try:
        scores = pd.read_sql("SELECT * FROM vw_provider_performance_scores", conn)
    except Exception:
        # Fallback: compute in Python if views aren't available
        scores = compute_scores_python(conn)
    return scores


def compute_scores_python(conn) -> pd.DataFrame:
    """Pure-Python scoring fallback."""
    claims   = pd.read_sql("SELECT * FROM claims", conn)
    providers= pd.read_sql("SELECT * FROM providers", conn)
    quality  = pd.read_sql("SELECT * FROM quality_metrics", conn)

    summary = (
        claims
        .groupby("provider_id")
        .agg(
            total_claims    = ("claim_id",       "count"),
            unique_patients = ("patient_id",     "nunique"),
            avg_allowed     = ("allowed_amount",  "mean"),
            avg_paid        = ("paid_amount",     "mean"),
            total_paid      = ("paid_amount",     "sum"),
            readmission_rate= ("readmission_30d", "mean"),
            er_visit_rate   = ("er_visit",        "mean"),
            preventive_rate = ("preventive_visit","mean"),
        )
        .reset_index()
    )
    summary["cost_per_member"] = summary["total_paid"] / summary["unique_patients"]

    # Specialty benchmarks
    merged = summary.merge(providers[["provider_id","specialty","region","network_tier","accepts_value_based"]], on="provider_id")
    benchmarks = merged.groupby("specialty")[["avg_allowed","cost_per_member","readmission_rate","er_visit_rate"]].mean()
    merged = merged.join(benchmarks, on="specialty", rsuffix="_bench")

    # Normalise
    merged["cost_score"]        = (1 - merged["avg_allowed"] / merged["avg_allowed_bench"].clip(lower=1)) * 100 + 50
    merged["utilization_score"] = (1 - merged["readmission_rate"] / merged["readmission_rate_bench"].clip(lower=0.001)) * 100
    merged["er_score"]          = (1 - merged["er_visit_rate"]    / merged["er_visit_rate_bench"].clip(lower=0.001)) * 100

    merged = merged.merge(quality[["provider_id","hedis_composite_score","patient_satisfaction","care_coordination_score"]], on="provider_id", how="left")
    merged["quality_score"]      = merged["hedis_composite_score"].fillna(0.7) * 100
    merged["satisfaction_score"] = merged["patient_satisfaction"].fillna(0.7)  * 100
    merged["coordination_score"] = merged["care_coordination_score"].fillna(0.7) * 100

    for col in ["cost_score","utilization_score","er_score","quality_score","satisfaction_score","coordination_score"]:
        merged[col] = merged[col].clip(0, 100).round(1)

    merged["composite_score"] = (
        merged["cost_score"]         * 0.30
      + merged["quality_score"]      * 0.25
      + merged["utilization_score"]  * 0.20
      + merged["satisfaction_score"] * 0.15
      + merged["coordination_score"] * 0.10
    ).round(1)

    merged["value_tier"] = pd.cut(
        merged["composite_score"],
        bins=[0, 50, 70, 100],
        labels=["Low Value", "Moderate Value", "High Value"]
    )
    return merged


# ══════════════════════════════════════════════════════
#  ROI MODEL
# ══════════════════════════════════════════════════════
class ProviderROIModel:
    """
    Estimates financial ROI from steering patients toward high-value providers.
    """

    STEERING_COST_PER_MEMBER = 45    # $ program admin cost per member steered
    INCENTIVE_PER_MEMBER     = 75    # $ incentive for member to switch (cost-share reduction)
    READMIT_COST             = 12_500
    ER_VISIT_COST            = 2_200

    def __init__(self, scores_df: pd.DataFrame, claims_df: pd.DataFrame):
        self.scores  = scores_df
        self.claims  = claims_df
        self._enrich_tiers()

    def _enrich_tiers(self):
        tier_map = self.scores.set_index("provider_id")["value_tier"].to_dict()
        self.claims["value_tier"] = self.claims["provider_id"].map(tier_map)

    # ── Baseline metrics ──────────────────────────────
    def baseline_metrics(self) -> dict:
        c = self.claims
        return {
            "total_members":         c["patient_id"].nunique(),
            "total_spend":           round(c["paid_amount"].sum(), 2),
            "avg_cost_per_member":   round(c["paid_amount"].sum() / c["patient_id"].nunique(), 2),
            "avg_readmission_rate":  round(c["readmission_30d"].mean(), 4),
            "avg_er_rate":           round(c["er_visit"].mean(), 4),
            "high_value_pct":        round((c["value_tier"] == "High Value").mean(), 4),
        }

    # ── Steering scenario ─────────────────────────────
    def simulate_steering(
        self,
        steering_rate: float = 0.20,
        cost_reduction_pct: float = 0.15,
        readmit_reduction_pct: float = 0.25,
        er_reduction_pct: float = 0.20,
        scenario_name: str = "Base Steering",
    ) -> dict:
        """
        steering_rate         : fraction of low/moderate-value patients switched
        cost_reduction_pct    : expected cost reduction when moved to high-value provider
        readmit_reduction_pct : expected readmission rate improvement
        er_reduction_pct      : expected ER visit rate improvement
        """
        base = self.baseline_metrics()
        n_members = base["total_members"]
        n_steerable = int(
            n_members
            * (1 - base["high_value_pct"])   # currently NOT on high-value providers
            * steering_rate
        )

        # Financial savings
        steered_spend   = base["avg_cost_per_member"] * n_steerable
        direct_savings  = steered_spend * cost_reduction_pct

        readmit_avoided = (
            n_steerable
            * base["avg_readmission_rate"]
            * readmit_reduction_pct
        )
        readmit_savings = readmit_avoided * self.READMIT_COST

        er_avoided      = (
            n_steerable
            * base["avg_er_rate"]
            * er_reduction_pct
        )
        er_savings      = er_avoided * self.ER_VISIT_COST

        gross_savings   = direct_savings + readmit_savings + er_savings
        program_cost    = n_steerable * (self.STEERING_COST_PER_MEMBER + self.INCENTIVE_PER_MEMBER)
        net_savings     = gross_savings - program_cost
        roi_pct         = (net_savings / program_cost * 100) if program_cost > 0 else 0

        return {
            "scenario":               scenario_name,
            "steering_rate":          steering_rate,
            "members_steered":        n_steerable,
            "direct_cost_savings":    round(direct_savings,  2),
            "readmit_savings":        round(readmit_savings, 2),
            "er_savings":             round(er_savings,      2),
            "gross_savings":          round(gross_savings,   2),
            "program_cost":           round(program_cost,    2),
            "net_savings":            round(net_savings,     2),
            "roi_pct":                round(roi_pct,         1),
            "readmissions_avoided":   round(readmit_avoided, 0),
            "er_visits_avoided":      round(er_avoided,      0),
            "cost_per_member_saved":  round(net_savings / n_steerable, 2) if n_steerable else 0,
        }

    def run_all_scenarios(self) -> pd.DataFrame:
        """Run multiple steering scenarios for comparison."""
        scenarios = [
            dict(steering_rate=0.10, cost_reduction_pct=0.10, readmit_reduction_pct=0.15, er_reduction_pct=0.12, scenario_name="Conservative (10% Steering)"),
            dict(steering_rate=0.20, cost_reduction_pct=0.15, readmit_reduction_pct=0.25, er_reduction_pct=0.20, scenario_name="Base Case (20% Steering)"),
            dict(steering_rate=0.35, cost_reduction_pct=0.18, readmit_reduction_pct=0.30, er_reduction_pct=0.25, scenario_name="Aggressive (35% Steering)"),
            dict(steering_rate=0.50, cost_reduction_pct=0.22, readmit_reduction_pct=0.35, er_reduction_pct=0.30, scenario_name="Maximum (50% Steering)"),
        ]
        return pd.DataFrame([self.simulate_steering(**s) for s in scenarios])


# ══════════════════════════════════════════════════════
#  KPI TRACKER
# ══════════════════════════════════════════════════════
def compute_kpis(scores: pd.DataFrame, claims: pd.DataFrame, roi_results: pd.DataFrame) -> dict:
    """Track all product analytics KPIs."""
    base_scenario = roi_results[roi_results["scenario"].str.contains("Base")].iloc[0]

    return {
        # Steering effectiveness
        "steering_effectiveness": {
            "members_steerable":      int(claims["patient_id"].nunique() * (1 - (scores["value_tier"] == "High Value").mean())),
            "projected_members_steered": int(base_scenario["members_steered"]),
            "roi_pct":                float(base_scenario["roi_pct"]),
            "net_savings_usd":        float(base_scenario["net_savings"]),
        },
        # Provider engagement
        "provider_engagement": {
            "total_providers":        len(scores),
            "high_value_providers":   int((scores["value_tier"] == "High Value").sum()),
            "pct_accepting_vbc":      round(scores["accepts_value_based"].mean() * 100, 1) if scores["accepts_value_based"].dtype == bool else round((scores["accepts_value_based"] == True).mean() * 100, 1),
            "avg_composite_score":    round(scores["composite_score"].mean(), 1),
        },
        # Cost per member
        "cost_per_member": {
            "current_avg_cpm":        round(claims.groupby("patient_id")["paid_amount"].sum().mean(), 2),
            "projected_savings_cpm":  float(base_scenario["cost_per_member_saved"]),
            "readmissions_avoided":   int(base_scenario["readmissions_avoided"]),
            "er_visits_avoided":      int(base_scenario["er_visits_avoided"]),
        },
        # Quality
        "quality_metrics": {
            "avg_hedis_score":        round(scores["quality_score"].mean(), 1) if "quality_score" in scores else None,
            "avg_readmission_rate":   round(claims["readmission_30d"].mean(), 4),
            "avg_er_rate":            round(claims["er_visit"].mean(), 4),
            "preventive_visit_rate":  round(claims["preventive_visit"].mean(), 4),
        }
    }


# ══════════════════════════════════════════════════════
#  VALIDATION  (QA checks)
# ══════════════════════════════════════════════════════
def run_data_validation(conn) -> pd.DataFrame:
    checks = []

    def chk(name, query, expected_zero=True):
        try:
            result = pd.read_sql(query, conn)
            n = result.iloc[0, 0] if len(result) > 0 else 0
            status = "PASS" if (n == 0) == expected_zero else "FAIL"
            checks.append({"check": name, "count": n, "status": status})
        except Exception as e:
            checks.append({"check": name, "count": -1, "status": f"ERROR: {e}"})

    chk("No negative allowed amounts",   "SELECT COUNT(*) FROM claims WHERE allowed_amount <= 0")
    chk("No paid > allowed",             "SELECT COUNT(*) FROM claims WHERE paid_amount > allowed_amount * 1.01")
    chk("No orphan provider IDs",        "SELECT COUNT(*) FROM claims c LEFT JOIN providers p ON c.provider_id=p.provider_id WHERE p.provider_id IS NULL")
    chk("No orphan patient IDs",         "SELECT COUNT(*) FROM claims c LEFT JOIN patients pt ON c.patient_id=pt.patient_id WHERE pt.patient_id IS NULL")
    chk("Valid readmission flags",       "SELECT COUNT(*) FROM claims WHERE readmission_30d NOT IN (0,1)")
    chk("Valid ER visit flags",          "SELECT COUNT(*) FROM claims WHERE er_visit NOT IN (0,1)")
    chk("Quality metrics coverage",      "SELECT COUNT(*) FROM providers pr LEFT JOIN quality_metrics qm ON pr.provider_id=qm.provider_id WHERE qm.provider_id IS NULL")
    chk("No null claim IDs",             "SELECT COUNT(*) FROM claims WHERE claim_id IS NULL")
    chk("Positive LOS days",             "SELECT COUNT(*) FROM claims WHERE los_days < 0")

    return pd.DataFrame(checks)


# ══════════════════════════════════════════════════════
#  EXPORT  – all analytics outputs to CSV
# ══════════════════════════════════════════════════════
def export_analytics(scores, roi_results, kpis, validation, conn):
    out = DATA_DIR

    scores.to_csv(f"{out}/provider_scores.csv", index=False)
    roi_results.to_csv(f"{out}/roi_scenarios.csv", index=False)
    validation.to_csv(f"{out}/data_validation.csv", index=False)

    import json
    with open(f"{out}/kpi_summary.json", "w") as f:
        json.dump(kpis, f, indent=2, default=str)

    # Regional summary
    try:
        regional = pd.read_sql("SELECT * FROM vw_regional_variation", conn)
        regional.to_csv(f"{out}/regional_variation.csv", index=False)
    except Exception:
        pass

    print(f"\n✓ All analytics exported to {out}/")


# ══════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("  Healthcare Provider ROI Analytics")
    print("=" * 60)

    # Ensure data exists
    if not os.path.exists(f"{DATA_DIR}/claims.csv"):
        print("Generating synthetic data first...")
        import sys; sys.path.insert(0, os.path.dirname(__file__))
        from generate_data import main as gen
        gen()

    # Setup DB
    print("\n[1/5] Setting up database...")
    conn = setup_database()

    # Build scores
    print("\n[2/5] Building provider performance scores...")
    scores = build_provider_scores(conn)
    print(f"  Scored {len(scores)} providers")
    vt = scores["value_tier"].value_counts()
    for tier, n in vt.items():
        print(f"    {tier}: {n}")

    # ROI model
    print("\n[3/5] Running ROI & steering simulations...")
    claims = pd.read_sql("SELECT * FROM claims", conn)
    roi_model = ProviderROIModel(scores, claims)
    roi_results = roi_model.run_all_scenarios()

    print("\n  Steering Scenario Results:")
    print(f"  {'Scenario':<35} {'Steered':>8} {'Net Savings':>14} {'ROI %':>8}")
    print("  " + "-" * 70)
    for _, row in roi_results.iterrows():
        print(f"  {row['scenario']:<35} {int(row['members_steered']):>8,} "
              f"${row['net_savings']:>13,.0f} {row['roi_pct']:>7.1f}%")

    # KPIs
    print("\n[4/5] Computing KPIs...")
    kpis = compute_kpis(scores, claims, roi_results)
    eng = kpis["provider_engagement"]
    cpm = kpis["cost_per_member"]
    print(f"  High-value providers:   {eng['high_value_providers']} / {eng['total_providers']}")
    print(f"  Avg composite score:    {eng['avg_composite_score']}")
    print(f"  Projected CPM savings:  ${cpm['projected_savings_cpm']:,.2f} / member")
    print(f"  Readmissions avoided:   {cpm['readmissions_avoided']:,}")
    print(f"  ER visits avoided:      {cpm['er_visits_avoided']:,}")

    # Validation
    print("\n[5/5] Running data validation...")
    validation = run_data_validation(conn)
    passes = (validation["status"] == "PASS").sum()
    fails  = (validation["status"] == "FAIL").sum()
    print(f"  QA checks: {passes} PASS, {fails} FAIL")
    if fails:
        print("  FAILURES:")
        print(validation[validation["status"] == "FAIL"].to_string(index=False))

    # Export
    export_analytics(scores, roi_results, kpis, validation, conn)
    conn.close()
    print("\n✓ Analysis complete.")
    return scores, roi_results, kpis, validation


if __name__ == "__main__":
    main()
