"""
Healthcare Provider ROI & Value-Based Care Analytics System
Data Generation Module - Creates synthetic claims and provider data
"""

import pandas as pd
import numpy as np
import random
import os
from datetime import datetime, timedelta

np.random.seed(42)
random.seed(42)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
N_PROVIDERS   = 80
N_PATIENTS    = 5_000
N_CLAIMS      = 50_000
START_DATE    = datetime(2022, 1, 1)
END_DATE      = datetime(2024, 12, 31)

SPECIALTIES   = ["Primary Care", "Cardiology", "Orthopedics",
                  "Oncology", "Neurology", "General Surgery"]
REGIONS       = ["Northeast", "Southeast", "Midwest", "Southwest", "West"]
PLAN_TYPES    = ["HMO", "PPO", "EPO", "HDHP"]
DIAGNOSIS_CODES = [
    "I10","I25","E11","J44","M54","N18","F32","Z23",
    "K21","M17","I50","J18","E78","Z00","R07","M79"
]
PROCEDURE_CODES = [
    "99213","99214","99215","93000","71046","80053",
    "27447","43239","70553","93306","99232","36415"
]

# ─────────────────────────────────────────────
# 1. PROVIDERS
# ─────────────────────────────────────────────
def generate_providers():
    rows = []
    for i in range(1, N_PROVIDERS + 1):
        spec  = random.choice(SPECIALTIES)
        tier  = np.random.choice([1, 2, 3], p=[0.25, 0.50, 0.25])          # 1 = highest value
        base_cost_mult = {1: 0.80, 2: 1.00, 3: 1.30}[tier]
        quality_base   = {1: 0.88, 2: 0.76, 3: 0.62}[tier]

        rows.append({
            "provider_id":          f"PROV{i:04d}",
            "provider_name":        f"Provider_{i:04d}",
            "specialty":            spec,
            "region":               random.choice(REGIONS),
            "network_tier":         tier,
            "years_in_network":     np.random.randint(1, 20),
            "accepts_value_based":  np.random.choice([True, False], p=[0.65, 0.35]),
            "hospital_affiliation": f"Hospital_{np.random.randint(1, 15):02d}",
            "base_cost_multiplier": round(base_cost_mult + np.random.normal(0, 0.08), 3),
            "quality_score_base":   round(np.clip(quality_base + np.random.normal(0, 0.06), 0.40, 0.99), 3),
        })
    return pd.DataFrame(rows)

# ─────────────────────────────────────────────
# 2. PATIENTS
# ─────────────────────────────────────────────
def generate_patients():
    rows = []
    for i in range(1, N_PATIENTS + 1):
        age       = np.random.randint(18, 85)
        plan_type = random.choice(PLAN_TYPES)
        chronic   = np.random.randint(0, 5)
        rows.append({
            "patient_id":           f"PAT{i:06d}",
            "age":                  age,
            "gender":               np.random.choice(["M", "F", "Other"], p=[0.49, 0.49, 0.02]),
            "region":               random.choice(REGIONS),
            "plan_type":            plan_type,
            "chronic_conditions":   chronic,
            "risk_score":           round(np.clip(0.1 + chronic * 0.15 + np.random.normal(0, 0.1), 0.1, 1.5), 3),
            "annual_premium":       round(np.random.uniform(3_000, 18_000), 2),
            "primary_provider_id":  f"PROV{np.random.randint(1, N_PROVIDERS + 1):04d}",
        })
    return pd.DataFrame(rows)

# ─────────────────────────────────────────────
# 3. CLAIMS
# ─────────────────────────────────────────────
def generate_claims(providers_df, patients_df):
    prov_map = providers_df.set_index("provider_id")[
        ["base_cost_multiplier", "network_tier", "specialty"]
    ].to_dict("index")

    rows = []
    for i in range(1, N_CLAIMS + 1):
        pat     = patients_df.sample(1).iloc[0]
        prov_id = f"PROV{np.random.randint(1, N_PROVIDERS + 1):04d}"
        prov    = prov_map.get(prov_id, {"base_cost_multiplier": 1.0, "network_tier": 2, "specialty": "Primary Care"})

        svc_date = START_DATE + timedelta(days=np.random.randint(0, (END_DATE - START_DATE).days))
        base     = np.random.lognormal(mean=7.5, sigma=1.0)   # ~$1,800 median
        allowed  = round(base * prov["base_cost_multiplier"] * (1 + pat["risk_score"] * 0.3), 2)
        paid     = round(allowed * np.random.uniform(0.70, 0.95), 2)

        rows.append({
            "claim_id":             f"CLM{i:07d}",
            "patient_id":           pat["patient_id"],
            "provider_id":          prov_id,
            "service_date":         svc_date.strftime("%Y-%m-%d"),
            "claim_type":           np.random.choice(["Inpatient","Outpatient","Professional","Pharmacy"],
                                                     p=[0.10, 0.30, 0.50, 0.10]),
            "diagnosis_code":       random.choice(DIAGNOSIS_CODES),
            "procedure_code":       random.choice(PROCEDURE_CODES),
            "allowed_amount":       allowed,
            "paid_amount":          paid,
            "member_cost_share":    round(allowed - paid, 2),
            "los_days":             np.random.choice([0, 1, 2, 3, 4, 5, 7],
                                                     p=[0.55, 0.20, 0.12, 0.06, 0.04, 0.02, 0.01]),
            "readmission_30d":      np.random.choice([0, 1], p=[0.88, 0.12]),
            "er_visit":             np.random.choice([0, 1], p=[0.82, 0.18]),
            "preventive_visit":     np.random.choice([0, 1], p=[0.65, 0.35]),
            "network_tier":         prov["network_tier"],
        })
    return pd.DataFrame(rows)

# ─────────────────────────────────────────────
# 4. QUALITY METRICS
# ─────────────────────────────────────────────
def generate_quality_metrics(providers_df, claims_df):
    rows = []
    for _, prov in providers_df.iterrows():
        pc = claims_df[claims_df["provider_id"] == prov["provider_id"]]
        n  = len(pc)
        if n == 0:
            continue
        qb = prov["quality_score_base"]
        rows.append({
            "provider_id":              prov["provider_id"],
            "total_claims":             n,
            "readmission_rate":         round(pc["readmission_30d"].mean(), 4),
            "er_visit_rate":            round(pc["er_visit"].mean(), 4),
            "preventive_care_rate":     round(pc["preventive_visit"].mean(), 4),
            "avg_allowed_amount":       round(pc["allowed_amount"].mean(), 2),
            "avg_paid_amount":          round(pc["paid_amount"].mean(), 2),
            "total_paid_amount":        round(pc["paid_amount"].sum(), 2),
            "avg_los_days":             round(pc["los_days"].mean(), 3),
            "hedis_composite_score":    round(np.clip(qb + np.random.normal(0, 0.04), 0.35, 0.99), 3),
            "patient_satisfaction":     round(np.clip(qb * 0.95 + np.random.normal(0, 0.05), 0.35, 1.0), 3),
            "care_coordination_score":  round(np.clip(qb * 1.05 + np.random.normal(0, 0.04), 0.35, 1.0), 3),
            "generic_rx_rate":          round(np.random.uniform(0.55, 0.95), 3),
        })
    return pd.DataFrame(rows)

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    out = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(out, exist_ok=True)

    print("Generating providers...")
    providers = generate_providers()
    providers.to_csv(f"{out}/providers.csv", index=False)
    print(f"  → {len(providers)} providers saved")

    print("Generating patients...")
    patients = generate_patients()
    patients.to_csv(f"{out}/patients.csv", index=False)
    print(f"  → {len(patients)} patients saved")

    print("Generating claims...")
    claims = generate_claims(providers, patients)
    claims.to_csv(f"{out}/claims.csv", index=False)
    print(f"  → {len(claims)} claims saved")

    print("Generating quality metrics...")
    quality = generate_quality_metrics(providers, claims)
    quality.to_csv(f"{out}/quality_metrics.csv", index=False)
    print(f"  → {len(quality)} quality records saved")

    print("\n✓ All synthetic data generated successfully.")
    return providers, patients, claims, quality

if __name__ == "__main__":
    main()
