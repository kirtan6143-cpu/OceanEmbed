# Dataset plan and contract

## How much data?

Use a small engineering fixture first, then a regional pilot. Counts below are design counts, not available observations or independent samples.

| Stage | Dates / grid | Count |
|---|---|---|
| Included generator | 2023-01-01 through 2024-03-05; 16 × 24 synthetic grid | 430 daily frames; 384 cells; 15 target depths |
| Synthetic UI run | Last 45 days of that fixture | 45 daily display frames |
| Candidate regional pilot | 2021-01-01 through 2024-12-31; 5–25°N, 80–100°E, 0.25° inclusive | 1,461 daily frames; 81 × 81 = 6,561 cells |
| Regional channel data | Seven dynamic inputs + seven age arrays | 14 scalar arrays per cell/day |
| Regional target | 15 in-situ temperature levels | 143,784,315 values before wet/support masking |

Exact unmasked target count is 1,461 × 6,561 × 15 = **143,784,315**; use the inventory script below to avoid confusing nominal elements with usable observations.

```python
import xarray as xr
import numpy as np
ds = xr.open_dataset("data/processed/regional.nc")
print(dict(ds.sizes))
print("Nominal target values:", ds.target.size)
print("Finite target values:", int(np.isfinite(ds.target.values).sum()))
print("Cube bytes in memory:", ds.nbytes)
```

The four-year 81 × 81 cube contains about 1.04 GiB of float32 payload for inputs, ages and targets alone. Preparation creates intermediate arrays, so peak RAM can be several times the final size, especially with finer native data. This release loads the cube into memory. Begin with one month of native files to inspect their size, then preprocess time shards or use a smaller domain if RAM is insufficient. Do not request a global archive.

With window 15 and embargo 8, the regional configuration yields 708 training, 159 validation, 162 calibration and 344 test output dates. These overlapping windows are correlated, not independent samples. Each training date uses one deterministic 32 × 32 crop per epoch. Actual valid targets depend on ocean depth, channel coverage and prior support. No arbitrary required Argo count is claimed: report unique floats, profiles, dates and per-depth matched values after QC.

## Source families

1. SST: ODYSSEA satellite-derived option, or OSTIA blended research option.
2. SSS: SMAP JPL L3 CAP eight-day composite. Daily delivery is not an independent daily observation.
3. SLA and current U/V: DUACS. These are mapped geostrophic velocities, not total surface currents.
4. Wind U/V: scatterometer satellite-derived option or blended winds in explicitly labelled research mode.
5. GLORYS temperature **and salinity** as training reference. Convert potential temperature to in-situ temperature.
6. Bathymetry: GEBCO or another documented compatible grid.
7. Argo profiles: separately for adaptation, calibration and evaluation (see observations.float_partition). RAMA (rama.py) supplements Argo's temporal resolution at a small, fixed set of mooring sites; its variable-name mapping is config-driven and untested against real files -- review real downloads before setting reviewed: true, same as the gridded sources.
8. Optional long-term daily temperature baseline for heat events; a short training climatology is not a 30-year event baseline.

This is seven dynamic variables from approximately four surface-product families, not seven independent datasets. Actual product IDs, years, collection versions, QC and availability must be confirmed at STOP 2.

## Canonical cube

NetCDF on increasing, rectilinear coordinates:

| Variable | Dimensions | Convention |
|---|---|---|
| inputs | time, channel, lat, lon | SST °C; SSS practical-salinity numeric scale; SLA m; current and wind m/s |
| age_hours | time, channel, lat, lon | Nonnegative source age/window metadata in hours; missing if input missing |
| target | time, depth, lat, lon | In-situ temperature °C; NaN on land, below bottom and outside source support |
| bathymetry | lat, lon | Positive metres below sea surface; nonpositive land |
| time | time | Unique consecutive daily timestamps, including missing-data days |
| channel | channel | sst, sss, sla, current_u, current_v, wind_u, wind_v |
| depth | depth | 0, 5, 10, 20, 30, 50, 75, 100, 125, 150, 200, 300, 500, 700, 1000 m |

The data preparation function reads explicit variable/coordinate mappings, exact source unit strings, scale/offset, QC flags or reviewed QC explanation, age arrays and spatial tolerances. It performs daily retrospective averaging and bounded nearest-grid reindexing. It does not implement general satellite-swath regridding, guessed variable detection or automatic raw-product age derivation.

A native age variable often does not exist. Derive it using the product's observation/window metadata during STOP 2; keep the derivation and reference time in the source notes. Do not insert fabricated zeros. For centered composites, describe window support and future information honestly; do not claim an as-issued causal replay. The 240-hour rejection limit is a pilot setting to review per product.

Target salinity is used by GSW to obtain Absolute Salinity, Conservative Temperature from potential temperature, and then in-situ temperature at pressure. An explicit copy-shallowest-to-zero option supplies the reference's nominal 0 m level; it is an approximation, not observed SST.

No temporal forward fill and no depth extrapolation beyond source support. Nearest-grid sampling is not conservative regridding. Inspect coastlines and coverage before science use.

## Heat baseline contract

An independently prepared NetCDF must contain event_mean and event_threshold in degC, dimensions (month_day, depth, lat, lon), with month_day strings such as 01-01 through 12-31, including 02-29 if required. Coordinates must exactly match the run. Attributes: baseline_period, source, method, leap_day_policy. The threshold should be a documented seasonal 90th percentile, on the same temperature convention and depth grid. This package attaches and checks the baseline; it does not silently manufacture a 30-year climatology.


V5 RAMA contract: raw temperature variables must declare Celsius/Kelvin units. Stable station IDs are mandatory. Explicit time mapping, QC review and daily-reduction policy are required. Daily CSV columns include units=degC and n_samples. Matchups use numeric observed/predicted/depth fields and observation_schema_version=2. See configs/rama.example.yaml.
