# Tableau Dashboard Specifications
## Healthcare Provider ROI & Value-Based Care Analytics

---

## Dashboard 1 — Provider Rankings & Scorecard

**Data source:** `provider_scores.csv`

### Sheets required:

| Sheet | Chart type | Dimensions | Measures |
|-------|-----------|------------|---------|
| Provider Ranking | Horizontal bar | Provider ID / Name | Composite Score (sorted desc) |
| Score Components | Stacked bar | Provider ID | Cost, Quality, Utilization, Satisfaction, Coordination scores |
| Value Tier Map | Symbol map | Region | Avg Composite Score (color), Provider Count (size) |
| Provider Detail | Text table | Provider ID | All score columns |

### Calculated fields:
```
// Value tier color hex
IF [Value Tier] = "High Value" THEN "#0F6E56"
ELSEIF [Value Tier] = "Moderate Value" THEN "#BA7517"
ELSE "#A32D2D"
END

// Score performance band
IF [Composite Score] >= 70 THEN "Above target"
ELSEIF [Composite Score] >= 55 THEN "Near target"
ELSE "Below target"
END
```

### Filters:
- Specialty (multi-select)
- Region (multi-select)
- Network Tier (1 / 2 / 3)
- Value Tier (High / Moderate / Low)

### Dashboard actions:
- Click provider bar → filter all sheets to that provider
- Click region on map → filter provider ranking to region

---

## Dashboard 2 — Cost-Quality Trade-Off

**Data source:** `provider_scores.csv`

### Sheets required:

| Sheet | Chart type | Dimensions | Measures |
|-------|-----------|------------|---------|
| Cost vs Quality Scatter | Scatter plot | Provider ID | X: Cost Score, Y: Quality Score |
| Reference Lines | Scatter overlay | — | Avg cost score (vertical), Avg quality score (horizontal) |
| Quadrant Labels | Annotation layer | — | High cost/High quality, Low cost/High quality, etc. |
| Cost per Member | Box & whisker | Specialty | Cost Per Member |

### Parameters:
```
// Scatter point size parameter
Name: Bubble Size Metric
Type: String
Values: Total Claims | Unique Patients | Readmission Rate
```

### Calculated fields:
```
// Quadrant assignment
IF [Cost Score] >= AVG([Cost Score]) AND [Quality Score] >= AVG([Quality Score])
    THEN "Star (Steer Here)"
ELSEIF [Cost Score] < AVG([Cost Score]) AND [Quality Score] >= AVG([Quality Score])
    THEN "High Quality / High Cost"
ELSEIF [Cost Score] >= AVG([Cost Score]) AND [Quality Score] < AVG([Quality Score])
    THEN "Efficient / Lower Quality"
ELSE "Avoid"
END
```

---

## Dashboard 3 — Regional Variation

**Data source:** `regional_variation.csv`

### Sheets required:

| Sheet | Chart type | Dimensions | Measures |
|-------|-----------|------------|---------|
| US Region Map | Filled map | Region | Avg Cost per Member (color gradient) |
| Regional Heatmap | Highlight table | Region × Specialty | Avg Composite Score |
| CPM Bar | Bar chart | Region | Avg Cost per Member |
| High Value % | Bar chart | Region | % High Value Providers |

### Color palette:
- Diverging: Red (#A32D2D) → White → Green (#0F6E56)
- Centered on network mean cost per member

---

## Dashboard 4 — ROI & Steering Scenarios

**Data source:** `roi_scenarios.csv`

### Sheets required:

| Sheet | Chart type | Dimensions | Measures |
|-------|-----------|------------|---------|
| Net Savings by Scenario | Bar | Scenario | Net Savings |
| Savings Waterfall | Waterfall | Component | Direct savings, Readmit savings, ER savings, Program cost, Net |
| ROI Trend | Line | Steering Rate % | ROI % |
| Members Steered | Bar | Scenario | Members Steered |

### Parameters:
```
// Interactive ROI slider
Name: Custom Steering Rate
Type: Float
Min: 0.05 | Max: 0.60 | Step: 0.05
Default: 0.20

// Dynamic calculation on parameter change:
[Members Steered Custom] = ROUND([Total Members] * (1 - [High Value Pct]) * [Custom Steering Rate])
[Net Savings Custom] = [Members Steered Custom] * [Avg Savings Per Member]
```

---

## Dashboard 5 — VBC KPI Tracker

**Data source:** `provider_scores.csv` + `kpi_summary.json`

### KPI cards (BANs):
| KPI | Comparison | Target |
|-----|-----------|--------|
| Avg Composite Score | vs prior period | ≥ 65 |
| % High Value Providers | vs prior period | ≥ 25% |
| Avg Readmission Rate | vs benchmark | ≤ 10% |
| Cost per Member Saved (projected) | vs scenario target | ≥ $4,000 |
| % Providers Accepting VBC | vs prior period | ≥ 70% |
| Members Steerable | — | Monitoring |

### Trend sheets:
- Composite Score over time (requires date dimension in scoring runs)
- Readmission rate trend by specialty
- ER visit rate trend by region

---

## Data Connections & Refresh

```
Extract connections (recommended for performance):
  - providers.csv        → Provider Dimension
  - provider_scores.csv  → Provider Scores Fact
  - roi_scenarios.csv    → ROI Scenarios
  - regional_variation.csv → Regional Summary

Relationships:
  provider_scores [provider_id] → providers [provider_id]

Schedule: Refresh daily after pipeline run
```

---

## Publishing Checklist

- [ ] All filters set to "All" as default
- [ ] Tooltips customized (Provider ID, Specialty, Region, Score, Value Tier)
- [ ] Color legends included on all sheets
- [ ] Dashboard title and last-refresh date displayed
- [ ] Mobile layout created for KPI Tracker dashboard
- [ ] Row-level security configured if multi-org deployment
