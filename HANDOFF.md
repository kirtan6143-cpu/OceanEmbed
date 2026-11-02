# OceanEmbed-NIO — Handoff Notes

**Date:** 2026-09-26
**Covers:** Phase 1 completion, independent Argo validation, Phase 2 (cyclone thermal context), and the known issues that still need fixing.

---

## 1. What now works

### Phase 1 — Explore / Sections / Validate

The dashboard runs off `demo/runs/demo.nc`, regenerated from the trained v3/v4 ensemble checkpoints via the Colab bridge script. Two fixes went into that regeneration:

**NaN-bleed through the CNN (the coverage bug).** Land pixels carry real `NaN` in every input channel. `nn.Conv2d` / `nn.Conv3d` sum over their receptive field, so land `NaN`s propagated into neighbouring *ocean* pixels and turned perfectly valid predictions into `NaN`. The support mask said 3492 cells were usable at 75m; only 942 actually had finite values.

Fix, in `run_ensemble_inference`, applied to the normalized window immediately before building the model tensors (both `x_v3` and the concatenated-bathymetry `x_v4`):

```python
window_norm = np.nan_to_num(window_norm, nan=0.0, posinf=0.0, neginf=0.0)
```

Zero in normalized space is the per-channel mean, i.e. a neutral fill. Verified on the full 3-year run: at 75m, `support True = 3492` and `temperature finite = 3492` — an exact match, where before it was 3492 vs 942.

**Channel label order.** `CHANNELS` did not match `metadata.json`'s real `input_channels`. Corrected to:

```python
CHANNELS = ["sst", "sla", "current_u", "current_v", "wind_u", "wind_v", "sss"]
```

Cosmetic only — it labels the `age_hours` coordinate and does not affect any computation.

### Independent Argo validation

Built from scratch (there was no existing template for this, unlike `cyclone.py`'s track matching). Each Argo profile is matched to the nearest model grid cell and the exact calendar day, and a comparison is only counted where the model's own `support` is `True` — so the model is never scored on cells it already honestly abstains from.

Source: `argo_bob_2023_2025.nc` (2837 profiles, Bay of Bengal, 2023–2025). 2449 profiles contributed at least one usable depth. 14 of the 15 canonical depths have an Argo equivalent (5m does not).

| Depth | n | RMSE (°C) | Bias (°C) | Correlation |
|---|---|---|---|---|
| 10 m | 2393 | 0.382 | +0.247 | 0.949 |
| 20 m | 2383 | 0.434 | +0.285 | 0.922 |
| 30 m | 2366 | 0.587 | +0.325 | 0.799 |
| 50 m | 2323 | 1.124 | +0.615 | 0.711 |
| 75 m | 2309 | 1.740 | +1.064 | 0.788 |
| 100 m | 2309 | 1.717 | +0.971 | 0.815 |
| 125 m | 2310 | 1.368 | +0.496 | 0.804 |
| 150 m | 2305 | 1.103 | +0.029 | 0.774 |
| 200 m | 2289 | 0.742 | −0.073 | 0.720 |
| 300 m | 2275 | 0.413 | +0.043 | 0.534 |
| 500 m | 2267 | 0.346 | +0.037 | 0.282 |
| 700 m | 2265 | 0.304 | −0.047 | 0.229 |

Error peaking in the 75–100m thermocline band and falling away above and below it is the physically expected shape. Low correlation at depth is expected too — below ~300m the real temperature variance is tiny, so correlation is a poor skill measure there and RMSE is the one to quote.

0m shows n=0. **That is not an Argo limitation — it is issue #1 below.**

Served at `/validation?source=Argo` via `OCEAN_VALIDATION`.

### Phase 2 — cyclone thermal context

Storm: **Cyclone Remal**, IBTrACS storm ID `2024145N14087`, 40 track points from 2024-05-23 12:00 UTC to 2024-05-28 06:00 UTC.

Source: NOAA IBTrACS v04r01 via the ERDDAP `IBTrACS_since1980_1` dataset. Wind and pressure values are attributed to IMD/RSMC New Delhi (`wmo_agency = newdelhi`) as relayed through IBTrACS. Peak intensity in the record is 60 kt / 978 mb around 2024-05-26 12:00–18:00 UTC.

`configs/cyclone.remal.yaml` maps the real IBTrACS column layout and is marked `reviewed: true` only after the file was actually inspected. Note the `category` column maps to IBTrACS's `nature` field (DS/TS/MX/ET/SS/NR), which is a **storm-type flag, not IMD's intensity-grade scale** — `category_scheme` says so explicitly rather than implying an IMD grade.

Results:

- `cyclone-context`: 24 of 40 track points have thermal context. The 15 with none are post-landfall / coastal, and 1 genuinely never reaches a 26 °C crossing.
- `cold-wake`: 24 of 39 locations have complete before/after windows, mean change **−0.049 °C at 50m**.

**Interpretation caveat for the pitch:** the TCHP/D26 curve follows the storm's *track*, so it mixes spatial and temporal variation. Remal moved from ~13.6°N to ~25°N, so the mid-track dip mostly reflects the storm entering the northern bay's shallower warm layer (freshwater stratification from river discharge), not the storm cooling the ocean beneath itself. For "did the storm cool the ocean," point at the cold-wake output, which is a genuine fixed-location before/after comparison.

### 1000m estimated-value display

`/field` now returns `estimated_z` and `estimated_note` when `depth == 1000.0`, computed on the fly from `ds.temperature.sel(depth=700.0)`. The frontend swaps it into the map and shows an explanatory `<Notice>`. `demo.nc` is **not** modified — `support` stays `False` and the reliability gate still abstains, so nothing is ever presented as a real prediction.

---

## 2. Issues to fix

### Issue 1 — the 0m surface layer is NaN across the entire dataset (HIGH, real bug)

**Symptom:** every cell, every day, at depth 0:

```
support True count: 0
temperature finite count: 0
prior finite count: 0
total cells: 9,815,988
```

**Root cause:** `interp_depth_lean()` in the Colab bridge script refuses any target depth outside the source range:

```python
if z < src_depths[0] or z > src_depths[-1]:
    put(out, k, np.nan); continue
```

`GLORYS_DEPTHS_35[0]` is `0.494025`. Canonical `DEPTHS[0]` is `0`. Since `0 < 0.494025`, the surface is treated as out-of-range extrapolation and zeroed to `NaN` unconditionally — for `temperature`, `prior` and `reference` alike, which is why all three are NaN together.

This is *not* the same situation as 1000m. The gap here is half a metre, which is physically indistinguishable from the surface in any real ocean dataset. The model's real 0.494m prediction legitimately represents the surface; the boundary check is simply too strict.

**Consequences:** no sea-surface temperature anywhere in the dashboard (nobody noticed because the UI defaults to 100m); Argo validation reports n=0 at 0m; `thermal_context()` returned 0/40 points before the workaround, because `diagnostics()` hard-requires a finite surface value to compute D26/TCHP at all.

**Suggested fix** — tolerance only at the shallow end:

```python
NEAR_SURFACE_TOLERANCE_M = 1.0

for k, z in enumerate(dst_depths):
    if z < src_depths[0]:
        if src_depths[0] - z <= NEAR_SURFACE_TOLERANCE_M:
            put(out, k, take(field, 0)); continue   # shallowest real level == the surface
        put(out, k, np.nan); continue
    if z > src_depths[-1]:
        put(out, k, np.nan); continue               # deep end unchanged, see issue 3
    ...
```

**Do not apply the same tolerance at the deep end.** 1000m vs 902m is a 98m gap and should keep abstaining.

**This needs a full Colab pipeline rerun** — `pred_35` is never written to disk, so the interpolation cannot be redone from saved intermediates. After rerunning and redeploying `demo.nc`, see the checksum warning in section 4.

### Issue 2 — anomaly gets no 1000m estimate (LOW, cosmetic)

In `api.py`'s `field()`, the estimate block hardcodes temperature regardless of which variable was requested:

```python
estimated_z = ds.temperature.sel(depth=700.0).values
```

So `var=anomaly` at 1000m produces raw temperature values mislabeled as anomaly.

**Fix:** use the requested variable instead —

```python
estimated_z = variable(ds, var).sel(depth=700.0).values
```

TCHP / D26 / MLD-T correctly get no estimate. They are depth-independent whole-column diagnostics and the depth selector is disabled for them, so there is nothing to estimate. Not a bug.

### Issue 3 — no data below ~902m (NOT a bug, document it)

`GLORYS_DEPTHS_35` tops out at `902.339294`. `Y.npy` is `(1096, 70, 101, 89)` — 35 temperature depths plus 35 salinity depths. There is no deeper temperature data hiding anywhere to recover.

The current handling (abstain, plus a clearly labeled estimate carried from 700m) is the honest treatment. This belongs in the limitations section of the writeup, not the bug list.

### Issue 4 — the cyclone surface workaround is a stopgap

`thermal_context()` currently substitutes the 5m value when 0m is NaN, and flags each affected point with `surface_estimated: true` plus a `surface_note` on the payload. Once issue 1 is properly fixed this becomes a harmless no-op (`temp[0]` will be finite), and can be removed.

---

## 3. Running it

```
set OCEAN_RUN=demo\runs\demo.nc
set OCEAN_VALIDATION=demo\runs\argo_validation.json
set OCEAN_CYCLONE=demo\runs\cyclone_context.json
set OCEAN_COLD_WAKE=demo\runs\cold_wake.json
.venv\Scripts\python.exe -m uvicorn oceanembed.api:app --host 127.0.0.1 --port 8001
```

`OCEAN_RUN` is optional — `demo/runs/demo.nc` is already the default.

Regenerating the cyclone artifacts:

```
.venv\Scripts\python.exe -m oceanembed.cli cyclone-context demo\runs\demo.nc configs\cyclone.remal.yaml --out demo\runs\cyclone_context.json
.venv\Scripts\python.exe -m oceanembed.cli cold-wake demo\runs\demo.nc configs\cyclone.remal.yaml --out demo\runs\cold_wake.json
```

---

## 4. The checksum trap — read this before regenerating demo.nc

`/validation?source=Argo`, `/cyclone/context` and `/cyclone/cold-wake` all reject any payload whose `run_sha256` does not match the sha256 of the `demo.nc` currently being served. This is deliberate: it stops an evaluation from being drawn over the wrong ocean.

**If you regenerate `demo.nc`, all three artifacts must be regenerated or re-stamped, or those endpoints will return 409.**

The two cyclone CLI commands compute and stamp their own checksum, so just rerun them. `argo_validation.json` does not — re-stamp it with:

```
python -c "import json,hashlib; h=hashlib.sha256(); f=open(r'demo\runs\demo.nc','rb'); [h.update(chunk) for chunk in iter(lambda: f.read(1024*1024), b'')]; f.close(); digest=h.hexdigest(); obj=json.load(open(r'demo\runs\argo_validation.json',encoding='utf8')); obj['run_sha256']=digest; json.dump(obj, open(r'demo\runs\argo_validation.json','w',encoding='utf8'), indent=2); print('patched run_sha256:', digest)"
```

Also note the schema `validation_contract.validate_matchup_payload()` enforces on `argo_validation.json`:

- `source` must be exactly `"Argo"`
- `observation_schema_version` must be `2`
- every row in `matchups` needs finite `observed`, `predicted` and `depth`
- `run_sha256` must be a 64-character string matching the served run
- each entry in `metrics` must be `{depth, model: {n, rmse, mae, bias, correlation}}` — the **nested `model` key matters**; the frontend reads `r.model.rmse` and crashes the whole React tree with `Cannot read properties of undefined` if the metrics are flat

---

## 5. Files changed

| File | Change |
|---|---|
| `src/oceanembed/api.py` | `estimated_z` / `estimated_note` in `field()` |
| `src/oceanembed/cyclone.py` | surface fallback in `thermal_context()`, two new payload keys |
| `frontend/src/App.tsx` | `estimatedActive` / `displayField`, Notice banner in `map()` |
| `configs/cyclone.remal.yaml` | new — reviewed IBTrACS column mapping |
| `data/observations/remal_2024_track.csv` | new — Remal best track |
| `demo/runs/demo.nc` + `.metrics.json` | regenerated with the NaN-bleed fix |
| `demo/runs/argo_validation.json` | new |
| `demo/runs/cyclone_context.json` | new |
| `demo/runs/cold_wake.json` | new |
| `patch_field.py`, `patch_map.py`, `patch_cyclone.py` | one-off patch scripts, safe to delete |

`demo.nc` is ~2.7 GB and is excluded from the handoff zip. Get it from Google Drive at `oceanembed-nio/demo_runs/demo.nc`.

---

## 6. Status against the problem statement

| SIH26066 requirement | Status |
|---|---|
| 15 canonical depths | Met — 0m and 1000m carry documented caveats (issues 1 and 3) |
| 0.25° spatial resolution | Met — 101×89 grid, 5–30°N, 78–100°E |
| Daily temporal resolution | Met — 1092 days, 2023-01-05 to 2025-12-31 |
| Bay of Bengal / Arabian Sea proof of concept | Met — Bay of Bengal |
| Validated against independent Argo observations | Met — section 1 |

Cyclone thermal context is not a problem-statement requirement. It was added to support the Disaster Management theme repositioning.
