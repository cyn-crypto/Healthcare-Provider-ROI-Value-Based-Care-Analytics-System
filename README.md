![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python&logoColor=white)
![SQL](https://img.shields.io/badge/SQL-SQLite%20%2F%20DuckDB-lightgrey?logo=sqlite)
![Tableau](https://img.shields.io/badge/Tableau-Dashboard%20Specs-E97627?logo=tableau&logoColor=white)
![Status](https://img.shields.io/badge/Status-Complete-brightgreen)
![License](https://img.shields.io/badge/License-MIT-blue)
[![Live Demo](https://img.shields.io/badge/Live%20Demo-View%20Dashboard-22d3a0?style=flat&logo=github)](https://cyn-crypto.github.io/Healthcare-Provider-ROI-Value-Based-Care-Analytics-System/healthcare_vbc_dashboard.html)
# Healthcare Provider ROI & Value-Based Care Analytics System

A full analytics pipeline for evaluating provider performance, modeling financial ROI from patient steering, and tracking value-based care KPIs.

---
## Project Overview
This project builds the analytics infrastructure for a value-based care steering program. Using 50,000 synthetic claims across 80 providers, it scores every provider on a composite index of cost efficiency, clinical quality, and utilization, then models the financial return from steering patients toward higher-value providers. Four steering scenarios are simulated — from 10% to 50% of eligible members — quantifying net savings, readmission reductions, and ER visit avoidance. Product analytics KPIs track steering effectiveness, provider engagement, and cost-per-member savings over time. Five Tableau dashboards surface the results for operational, strategic, and executive audiences. All analytical outputs pass a nine-point data validation and QA suite before export.

## Project structure

```
healthcare_roi/
├── python/
│   ├── generate_data.py      # Synthetic claims & provider data (50K claims, 80 providers)
│   └── roi_model.py          # Provider scoring + ROI simulation + KPI tracker + QA
├── sql/
│   └── provider_scoring.sql  # Views: claims summary, benchmarks, composite scores, KPIs
├── dashboard/
│   └── tableau_specs.md      # 5-dashboard Tableau specification
├── data/                     # Generated outputs (created on first run)
│   ├── providers.csv
│   ├── patients.csv
│   ├── claims.csv
│   ├── quality_metrics.csv
│   ├── provider_scores.csv
│   ├── roi_scenarios.csv
│   ├── regional_variation.csv
│   ├── kpi_summary.json
│   └── data_validation.csv
└── README.md
```

---

## Quick start

```bash
pip install pandas numpy

# 1. Generate synthetic data
python python/generate_data.py

# 2. Run full analytics pipeline
python python/roi_model.py
```

---

## Components

### 1. Synthetic data generation (`generate_data.py`)
Produces four CSVs that simulate a realistic claims environment:

- **providers.csv** — 80 providers across 6 specialties, 5 regions, 3 network tiers
- **patients.csv** — 5,000 members with risk scores, chronic conditions, plan types
- **claims.csv** — 50,000 claims with allowed/paid amounts, LOS, readmission flags, ER flags
- **quality_metrics.csv** — HEDIS composite, patient satisfaction, care coordination, generic Rx rate

### 2. SQL scoring model (`provider_scoring.sql`)
Seven views that build up the composite score in layers:

| View | Purpose |
|------|---------|
| `vw_provider_claims_summary` | Aggregated cost, utilization, claim mix per provider |
| `vw_specialty_benchmarks` | Peer-group averages for normalisation |
| `vw_provider_score_components` | Normalised 0–100 scores for each dimension |
| `vw_provider_performance_scores` | Weighted composite + value tier assignment |
| `vw_regional_variation` | Cross-tab by region × specialty |
| `vw_kpi_summary` | Single-row network KPI snapshot |
| (inline) | 7 data validation assertions |

**Score weights:**

| Dimension | Weight |
|-----------|--------|
| Cost efficiency | 30% |
| Clinical quality (HEDIS) | 25% |
| Utilisation (readmissions) | 20% |
| Patient satisfaction | 15% |
| Care coordination | 10% |

### 3. Python ROI model (`roi_model.py`)

**`ProviderROIModel`** runs four steering scenarios:

| Scenario | Steering rate | Net savings | ROI |
|----------|--------------|-------------|-----|
| Conservative | 10% | ~$1.5M | 2,505% |
| Base case | 20% | ~$4.6M | 3,846% |
| Aggressive | 35% | ~$9.6M | 4,638% |
| Maximum | 50% | ~$16.8M | 5,669% |

**Savings components:**
- Direct cost reduction from switching to lower-cost providers
- Avoided readmission costs ($12,500 per avoided admission)
- Avoided ER visits ($2,200 per avoided visit)

**Program costs:**
- $45 admin cost per member steered
- $75 member incentive per member steered

### 4. KPI tracker
Tracks six product analytics KPIs across four categories:

- **Steering effectiveness** — members steerable, projected ROI, net savings
- **Provider engagement** — high-value %, VBC acceptance rate, avg composite score
- **Cost per member** — current CPM, projected CPM savings, utilisation avoided
- **Quality** — HEDIS score, readmission rate, ER rate, preventive visit rate

### 5. Data validation (9 QA checks)
All checks pass on synthetic data. Checks cover:

- No negative allowed amounts
- Paid amount never exceeds allowed amount
- No orphaned provider or patient foreign keys
- Binary flags (readmission, ER) are valid 0/1
- Quality metrics coverage for all providers
- No null claim IDs or negative LOS

### 6. Tableau dashboards (5 dashboards)
Specified in `dashboard/tableau_specs.md`:

1. **Provider Rankings & Scorecard** — ranked bar, score components, region map
2. **Cost-Quality Trade-Off** — quadrant scatter with quadrant labels and CPM box plots
3. **Regional Variation** — filled US map, heatmap by region × specialty
4. **ROI & Steering Scenarios** — waterfall, ROI trend, interactive steering slider
5. **VBC KPI Tracker** — BAN cards, trend lines, mobile layout

---

## Tech stack

| Layer | Tool |
|-------|------|
| Data generation | Python (pandas, numpy) |
| Storage | SQLite / CSV |
| Analytical views | SQL (SQLite-compatible) |
| ROI modeling | Python (pandas) |
| Visualisation | Tableau (spec) / Chart.js (prototype) |
| QA | SQL assertions + Python checks |
