# OceanEmbed-NIO — Architecture and Implementation Record

**Project:** OceanEmbed — Satellite Embedding-Based Deep Learning Framework for Reconstruction of Subsurface Ocean Temperature from Surface Satellite Observations
**Problem statement:** SIH26066 (INCOIS, Ministry of Earth Sciences) · Theme: Disaster Management · Category: Software
**Team:** DeepSindhu (Team ID 79), RVCE
**Document date:** 2026-09-27
**Run described:** `run_sha256 = 3cf229d249b090b7c0732cc50d97ec90414e89452a37c5196804b92fb1e0212e`

This records what the system is, how it was built, every defect found and fixed, and what it still cannot do. Sections marked **[needs Amrutha]** describe the training process itself, which was carried out separately and whose hyperparameters are not recoverable from the inference code alone.

---

## 1. What the system does

It reconstructs a three-dimensional field of ocean temperature — 15 standard depths from the surface to 1000 m — using only surface observations that satellites can see. Direct subsurface measurement is sparse: Argo floats, moorings and ship casts give excellent vertical detail at scattered points, but cannot produce a continuous basin-wide picture. Satellites give continuous surface coverage but see only the skin of the ocean.

The premise is that subsurface structure leaves signatures at the surface. Thermocline displacement alters sea surface height; mesoscale eddies show in surface currents and temperature; wind forcing drives mixing that changes the depth of the mixed layer. A model trained on paired surface-and-subsurface data can learn to invert those signatures.

The system reconstructs, retrospectively, one temperature field per day over the Bay of Bengal for 2023-2025, and refuses to produce a value wherever it cannot stand behind one.

---

## 2. Mapping to the problem statement

| PS requirement | Implementation |
|---|---|
| 0.25° × 0.25° spatial resolution | 101 × 89 grid, `LAT = linspace(5.0, 30.0, 101)`, `LON = linspace(78.0, 100.0, 89)` — exactly 0.25° |
| Daily temporal resolution | 1092 consecutive daily fields, 2023-01-05 to 2025-12-31 |
| Standard depths (0, 5, 10, 20, 30, 50, 75, 100, 125, 150, 200, 300, 500, 700, 1000 m) | All 15 present; 1000 m carries a documented limitation (§8) |
| Surface inputs: SST, SSS, SSH/SLA, currents U/V, winds U/V | All seven channels used (§3.1) |
| Satellite embeddings via DL architecture | CNN encoder producing a 96-channel latent representation (§4) |
| Training target: GLORYS reanalysis | GLORYS 35-level temperature (§3.2) |
| Evaluation against independent observations with correlation, RMSE, bias | Independent Argo validation, 27,972 matchups (§9) |
| Proof of concept over Bay of Bengal / Arabian Sea | Bay of Bengal |

**Scope note.** The PS states a target domain of 5-30°N, 45-105°E — the full North Indian Ocean. This implementation covers 78-100°E, the Bay of Bengal, under the Expected Solution clause permitting a proof of concept over Bay of Bengal *or* Arabian Sea. The dashboard retains an Arabian Sea region selector which returns "region unavailable" for this run rather than silently showing an empty map.

---

## 3. Data

### 3.1 Surface inputs — `X.npy`

Shape `(1096, 7, 101, 89)`, float32. Channel order, from `metadata.json`:

| # | Channel | Quantity |
|---|---|---|
| 0 | `sst` | Sea surface temperature |
| 1 | `sla` | Sea level anomaly |
| 2 | `ugos` | Surface geostrophic current, eastward |
| 3 | `vgos` | Surface geostrophic current, northward |
| 4 | `eastward_wind` | Surface wind, eastward |
| 5 | `northward_wind` | Surface wind, northward |
| 6 | `smap_sss` | Sea surface salinity (SMAP) |

The `ugos`/`vgos` naming indicates altimetry-derived geostrophic velocities rather than the OSCAR product the PS suggests. The PS explicitly permits substitution where a recommended product is unavailable at the required resolution.

Land cells carry `NaN` in every channel. Ocean cells have small genuine gaps — per-channel missing rates over ocean run roughly 0.24% to 8%, which is normal satellite coverage.

### 3.2 Target — `Y.npy`

Shape `(1096, 70, 101, 89)`, float32: 35 temperature levels followed by 35 salinity levels. Only `TEMP_SLICE = slice(0, 35)` is used; salinity is not reconstructed, as the dashboard has no slot for it.

The 35 GLORYS levels run from **0.494025 m** to **902.339294 m**. Both ends matter (§7).

**[needs Amrutha]** Whether `Y.npy` holds potential temperature (`thetao`) or in-situ temperature. GLORYS distributes `thetao`, and no conversion is applied anywhere in this pipeline, so it is almost certainly potential temperature. The `temperature_convention` attribute is deliberately left unset rather than asserted incorrectly. At these depths the difference is small — order 0.001 °C near the surface, rising to perhaps 0.1 °C at 1000 m — but it should be labelled correctly.

### 3.3 Static field — `elevation.npy`

Seabed elevation, negated on load (`elevation = -elevation_raw`) so that positive values mean metres of water depth. Used for the wet mask, and as an eighth input channel in V4.

This sign flip is easy to get wrong and caused a false diagnosis during development (§12.4).

### 3.4 Climatology — `monthly_climatology.npy`

Twelve monthly means. When the channel dimension is ≥ 70 the first 35 are taken as temperature. Interpolated to the 15 canonical depths, then to each output date by linear interpolation between month midpoints (day-of-year 15, 45, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349), wrapping across the year boundary.

This becomes the `prior` field, and `anomaly = temperature − prior`.

---

## 4. Model architecture

Two convolutional networks, ensembled. Both share the same structure; V4 adds bathymetry as an input channel.

### 4.1 TemperatureModelV3

```
in_channels=7, hidden=48, feat_channels=96, out_channels=35, kernel_t=5, dropout=0.2
```

**Spatial encoder** — applied independently to each of the 5 days in the input window:

| Layer | Detail |
|---|---|
| Conv2d(7 → 48) | 3×3, padding 1, dilation 1 → ReLU → Dropout2d(0.2) |
| Conv2d(48 → 48) | 3×3, padding 2, **dilation 2** → ReLU → Dropout2d(0.2) |
| Conv2d(48 → 96) | 3×3, padding 4, **dilation 4** → ReLU |

The dilation ladder is the key design choice. Stacking dilations 1, 2, 4 gives a receptive field of **15 × 15 grid cells** while keeping the parameter count small and the output at full resolution — no pooling, no upsampling. At 0.25° and around 15°N that is roughly **400 km × 415 km**, which is the scale of the mesoscale eddies that carry subsurface thermal signal. Each output pixel therefore sees a patch large enough to contain the features that matter.

The 96-channel tensor emerging from this stack **is the satellite embedding** the problem statement asks for: a compact latent representation of surface ocean state, from which the subsurface profile is decoded.

**Temporal convolution:**

```
Conv3d(96 → 96, kernel=(5, 1, 1))
```

The feature sequence is padded with 4 frames **on the leading edge only** (`Fnn.pad(feat, (0,0,0,0,4,0))`), making this strictly causal — the prediction for a given day uses that day and the four before it, never the future. Only the final timestep is retained. This lets the model use short-term history (a wind event two days ago still influences today's mixed layer) without leaking future information.

**Decoder:**

| Layer | Detail |
|---|---|
| Conv2d(96 → 96) | 3×3, padding 1 → ReLU → Dropout2d(0.2) |
| Conv2d(96 → 35) | 3×3, padding 1 |

Output is 35 channels, one per GLORYS depth level: a full vertical profile at every grid cell, produced in a single forward pass.

### 4.2 TemperatureModelV4

Identical except `in_channels=8`. The eighth channel is normalised bathymetry, broadcast across the time window. This gives the network explicit knowledge of water depth, which constrains what profiles are physically possible — a 200 m shelf cell cannot have a 500 m thermocline.

### 4.3 Ensemble

```
prediction = 0.4 × V3 + 0.6 × V4
```

Weighted toward V4 (`ENSEMBLE_WEIGHT_V4 = 0.6`). Combination happens in normalised space, before denormalisation.

### 4.4 Size

Approximately **225,000 parameters** — encoder ~65k, temporal convolution ~46k, decoder ~113k. This is a deliberately small model. It runs inference over 1,092 daily fields in a few minutes on a single Colab GPU, which matters for a system intended to be rerun as new satellite data arrives.

---

## 5. Training

**[needs Amrutha — this section is incomplete]**

What is recoverable from the inference code:

- **Split:** `TRAIN_FRACTION = 0.8`, so the first 876 of 1096 days form the training period, with the remaining 220 held out.
- **Normalisation:** per-channel mean and standard deviation computed over the **training split only**, using `nanmean`/`nanstd` across `(time, lat, lon)`. Standard deviations floored at 1e-6. The same statistics are applied at inference. Target normalisation is per-depth, computed the same way.
- **Bathymetry normalisation:** mean and standard deviation computed over **ocean cells only** (`elevation > 0`), so land does not distort the statistics.
- **Checkpoints:** `best_temp_v3.pt`, `best_temp_v4.pt`, each a dict with a `model` key holding the state dict. The filename prefix "best" implies validation-based checkpoint selection.
- **Window:** 5 days.

Not recoverable and needed for the write-up: optimiser and learning rate schedule, loss function (a masked loss over valid ocean cells is likely, given `masked_loss` exists in `model.py`), number of epochs, batch size, early-stopping criterion, any augmentation, and the validation metric used to select "best".

---

## 6. Inference pipeline

Implemented in the Colab bridge script, which writes a NetCDF conforming to the dashboard's data contract. It deliberately bypasses the repository's own `prepare.py`/`inference.py` path, so that the dashboard runs unmodified against externally trained checkpoints.

1. **Load** `X`, `Y`, `elevation`, `climatology`; negate elevation.
2. **Compute normalisation statistics** from the training split.
3. **Slide a 5-day window** across all 1096 days, producing 1092 outputs (the first four days lack sufficient history).
4. **Normalise** the window; replace non-finite values with 0 (§12.1).
5. **Forward pass** through both models; ensemble 0.4/0.6.
6. **Denormalise** using the per-depth target statistics.
7. **Interpolate** 35 GLORYS levels to 15 canonical depths (§7).
8. **Build the climatology prior** for each output date.
9. **Compute the support mask:**

```python
wet       = (DEPTHS[:, None, None] <= elevation) & (elevation > 0)
day_good  = np.all(np.isfinite(X[start_offset:]), axis=1)
support   = wet & day_good & np.isfinite(prior_15)
temperature = np.where(support, pred_15, np.nan)
```

A cell is supported only if there is water that deep, every input channel was present that day, and a climatology prior exists. Everything else becomes `NaN` — the model's output is discarded rather than shown.

10. **Assemble** the dataset with provenance attributes (§11) and write NetCDF.
11. **Compute** per-depth reference metrics against the GLORYS target.
12. **Verify** the two depth boundaries before the file is trusted.

---

## 7. Depth interpolation and the two boundaries

`interp_depth_lean` maps 35 GLORYS levels onto the 15 canonical depths by linear interpolation. Its boundary policy is the most consequential detail in the pipeline, because the canonical list extends past the source data at **both** ends.

### Shallow end — 0 m

GLORYS's shallowest level is 0.494 m; the canonical list asks for exactly 0 m. The gap is half a metre, physically indistinguishable from the surface in any ocean dataset. The policy:

```python
NEAR_SURFACE_TOLERANCE_M = 1.0

if z < src_depths[0]:
    if src_depths[0] - z <= NEAR_SURFACE_TOLERANCE_M:
        put(out, k, take(field, 0))   # shallowest real level represents the surface
    else:
        put(out, k, np.nan)
```

Recorded in the file as `surface_convention = "copy_shallowest_to_zero"` with `surface_tolerance_m = 1.0`, so any consumer can see how 0 m was produced.

### Deep end — 1000 m

GLORYS's deepest level here is 902.339 m; the canonical list asks for 1000 m. That is a **98 metre** gap through real, structured water. No tolerance is applied:

```python
if z > src_depths[-1]:
    put(out, k, np.nan)
```

1000 m therefore has zero support everywhere, permanently and by design. The dashboard displays a clearly labelled estimate carried from 700 m for visual continuity, but the underlying field stays empty and the reliability gate keeps abstaining. The release verifier actively **fails** any run that contains native 1000 m values.

The asymmetry is the point: half a metre is a labelling question, ninety-eight metres is a fabrication.

---

## 8. Reliability gate

Every displayed field passes through a three-state classifier (`reliability.py`) before reaching the user.

| State | Meaning |
|---|---|
| **Supported** | Inputs present and current, value finite, water deep enough |
| **Caution** | Displayed, but qualified — stale inputs (older than 48 h), partial channel coverage, or within 3 cells of the domain edge |
| **Abstain** | No value shown |

Abstain reasons are specific rather than generic: `unsupported_depth`, `no_value`, `below_seabed`, `dry_cell`. The seabed and dry-cell checks are evaluated last and override the others, so a cell below the seafloor is never reported as merely stale.

Two details that were got wrong and then corrected during development:

- The finite-value check runs on the **actual displayed quantity**, not on surface temperature. A whole-column diagnostic such as TCHP can be unresolvable at a cell whose surface is perfectly valid, and must be abstained on its own merits.
- Reliability is computed on the **full grid before regional cropping**. Computing it after cropping made domain-edge status depend on which region the user had selected in a dropdown, so the same coordinate could read Supported in one view and Caution in another.

---

## 9. Validation

### 9.1 Independent Argo

**Source:** `argo_bob_2023_2025.nc` — 2,837 profiles, Bay of Bengal, 2023-2025, on 19 standard depth levels. The file carries no global attributes; its structure (a `profile` dimension with per-profile lat/lon/time, and the variable name `psal`) indicates individual float profiles from a GDAC-style source rather than a gridded product. **[needs Amrutha]** the exact download source and whether QC filtering was applied.

**Method.** Each profile is matched to the nearest model grid cell and the exact calendar day. A comparison is counted **only where the model's own `support` flag is true**, so the model is never scored on cells it already declines to report. Of 2,837 profiles, 2,449 contributed at least one usable depth; 3 fell outside the reconstruction date range; none fell outside the domain. Total: **27,972 matchups** across 14 depths.

**Results:**

| Depth | n | RMSE (°C) | Bias (°C) | Correlation |
|---|---|---|---|---|
| 0 m | 178 | 0.453 | +0.247 | 0.908 |
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
| 1000 m | 0 | — | — | — |

**How to read this.** Error peaks at 1.74 °C in the 75-100 m band and falls away above and below. That is the thermocline — the depth range where temperature changes fastest with depth — so a small error in *where* the model places the thermocline becomes a large temperature error there. Every subsurface reconstruction has this hump; its appearing in the right place at a sensible magnitude is evidence of learned physics rather than fitted noise.

Correlation below 300 m (0.28, 0.23) looks poor but is not meaningful: deep water temperature barely varies, so there is almost no signal to correlate against. RMSE is the appropriate metric there, and at 0.30-0.35 °C it is among the best in the table.

The 0 m sample is small (178) because Argo floats rarely report at exactly 0 m — profiles typically begin a few metres down. This is a constraint of the observations, not of the model, which has 4,162,704 supported surface cells.

**Independence caveat.** Argo is independent as an *instrument* — no Argo data entered training or bias calibration, and the model learned only from GLORYS. However, the Argo profiles span the same period the model trained over, so this is not a held-out-in-time evaluation. For a retrospective reconstruction, testing whether the system reproduces observed reality over its operating period is the appropriate test, but the distinction should be stated rather than glossed.

### 9.2 Reference metrics

`demo.metrics.json` scores the reconstruction against the GLORYS target it was trained on, per depth, alongside climatology and anomaly baselines. This is **teacher evaluation, not independent validation**, and is labelled as such in the file and flagged as a warning by the release verifier. It measures how well the model reproduces its training target; only §9.1 measures agreement with reality.

---

## 10. Cyclone thermal context

**Storm:** Cyclone Remal, IBTrACS ID `2024145N14087`, 40 track points from 2024-05-23 12:00 UTC to 2024-05-28 06:00 UTC.

**Provenance:** NOAA IBTrACS v04r01 via the ERDDAP `IBTrACS_since1980_1` dataset. Wind and pressure are attributed to IMD/RSMC New Delhi (`wmo_agency = newdelhi`) as relayed through IBTrACS. Peak recorded intensity 60 kt / 978 mb around 2024-05-26 12:00-18:00 UTC. The configuration is marked `reviewed: true` only after the real column layout was inspected.

The `category` column maps to IBTrACS's `nature` field (DS/TS/MX/ET/SS/NR), which is a **storm-type flag, not IMD's intensity-grade scale**. The `category_scheme` field says so explicitly rather than implying an IMD grade.

**Diagnostics** (`science.diagnostics`):

- **D26** — depth of the 26 °C isotherm, by linear interpolation between the bracketing levels where the profile first crosses 26 °C.
- **TCHP** — tropical cyclone heat potential, the heat stored above that isotherm: `1025 × 3990 × ∫(T − 26) dz / 1e7`, in kJ/cm², using seawater density 1025 kg/m³ and specific heat 3990 J/kg/K.
- **MLD-T** — mixed layer depth, where temperature falls 0.2 °C below the 10 m value.

All three require a finite surface value by physical necessity, which is why the 0 m defect (§12.3) reduced cyclone coverage to zero before it was fixed.

**Results:** 24 of 40 track points have thermal context. The 15 without are post-landfall positions over land, where correctly there is no ocean to reconstruct; one point genuinely never reaches a 26 °C crossing. TCHP along track runs 78-125 kJ/cm². Cold-wake analysis at 50 m found a mean change of −0.049 °C across 24 locations with complete before/after windows.

**Interpretation caveat.** The TCHP/D26 curve follows the storm's *track*, mixing spatial and temporal variation — Remal moved from 13.6°N to 25°N, so the mid-track dip largely reflects entering the northern bay's shallower warm layer rather than the storm cooling the water beneath itself. The cold-wake output is the fixed-location before/after comparison. The module prints its own standing disclaimer: this is retrospective ocean thermal context, not an intensity or rapid-intensification forecast.

---

## 11. Provenance and the release gate

Every artifact is cryptographically bound to the exact run it describes.

| Field | Purpose |
|---|---|
| `run_sha256` | SHA-256 of `demo.nc`; every dependent artifact must carry the matching value |
| `model_fingerprint` | SHA-256 of the two checkpoint hashes concatenated |
| `grid_fingerprint` | SHA-256 over the lat/lon/depth/channel coordinates |
| `surface_convention` | How 0 m was produced |
| `surface_tolerance_m` | The shallow-end tolerance actually applied |
| `partition` | Which slice of the record the run covers |

`scripts/verify_demo_artifacts.py` enforces all of it: a real (non-synthetic) run, an accepted surface convention producing supported 0 m data, **no native 1000 m values**, every artifact checksum matching, Argo tagged as held-out with nested metrics and no 1000 m matchups, cold-wake methodology fields present, and exactly 15 canonical depth entries in the metrics.

Current verdict for this run: **PASS**, `scientific_release: true`, with one expected warning that `demo.metrics.json` is teacher evaluation rather than independent validation.

Regenerating `demo.nc` invalidates every dependent artifact. All must be regenerated or the endpoints return HTTP 409 rather than serving results computed over different data.

---

## 12. Defect history

Each of these was found by running the system and checking output against expectation, not by reading code.

### 12.1 NaN bleed through the convolution stack

**Symptom.** The support mask said 3,492 cells were usable at 75 m; only 942 had finite values.

**Cause.** Land cells carry `NaN` in every input channel. `Conv2d` and `Conv3d` sum over their receptive field, so a single land `NaN` within 15 cells of an ocean pixel propagated into that pixel's prediction. With a 15×15 receptive field, coastal water was extensively poisoned.

**Fix.** Replace non-finite values with zero in normalised space — which is the per-channel mean, a neutral fill — immediately before tensor construction, for both models including V4's bathymetry channel.

**Verification.** A controlled single-day A/B test on the frozen checkpoints recovered 942 → 3,614 wet cells. The full rerun gave support and finite counts matching exactly at 3,492.

### 12.2 Channel label mismatch

`CHANNELS` did not match `metadata.json`'s real `input_channels` order. Cosmetic — it labels the `age_hours` coordinate and affects no computation — but corrected.

### 12.3 The 0 m surface layer was empty across the entire dataset

**Symptom.** Cyclone thermal context returned 0 of 40 track points, every one reporting "No valid surface support".

**Cause.** `interp_depth_lean` rejected any target depth outside the source range. GLORYS's shallowest level is 0.494 m and the canonical list asks for 0 m, so **every surface cell on every day** was set to `NaN` — in `temperature`, `prior` and `reference` alike. 0 of 9,815,988 cells had a surface value.

This went unnoticed for the entire project because the dashboard defaults to 100 m. It also silently explained the Argo validation reporting zero matchups at 0 m, which had been misattributed to Argo's sampling rather than the model's own gap.

**Fix.** The shallow-end tolerance in §7, applied at source in the bridge script, requiring a full pipeline rerun since the 35-level predictions are never persisted.

**Verification.** 0 m: 4,162,704 supported and 4,162,704 finite — exactly 3,812 ocean cells on each of 1,092 days. 1000 m unchanged at zero. Every other depth's Argo metrics came back byte-identical, confirming the change touched only the boundary.

### 12.4 A false diagnosis, corrected

An early check of input data quality applied `ocean_mask = elevation > 0` to the **raw** elevation array without the sign flip the pipeline uses, inverting land and ocean. This produced an apparent finding that 99% of ocean cells were permanently missing, briefly suggesting a structural data failure. Corrected: real ocean gap rates are 0.24-8% per channel, which is normal.

Recorded because the lesson generalises — a diagnostic script must apply the same transformations as the pipeline it is diagnosing, or it measures something else entirely.

### 12.5 Frontend crash on the validation scorecard

The Argo artifact was written with flat per-depth metrics (`{depth, rmse, bias, ...}`) while the frontend reads `r.model.rmse`. Every row returned `undefined`, throwing `Cannot read properties of undefined` and taking down the whole React tree — the Validate tab rendered as a blank panel. Fixed by nesting the scores under a `model` key, which the release verifier now enforces.

### 12.6 The 1000 m estimate ignored the selected variable

The display estimate was hardcoded to `ds.temperature.sel(depth=700.0)` regardless of which variable the user had chosen, so selecting "anomaly" at 1000 m returned raw temperature values mislabelled as anomaly. Fixed to `variable(ds, var).sel(depth=700.0)`.

### 12.7 Cyclone surface workaround, added then retired

Before §12.3 was fixed at source, `thermal_context()` substituted the 5 m value when 0 m was missing, flagging each affected point. Once the real fix landed the substitution stopped occurring (`points_with_estimated_surface: 0`) and the workaround was removed. The release verifier now rejects any artifact still carrying its fields.

---

## 13. Known limitations

1. **1000 m has no reconstruction.** The source reanalysis ends at ~902 m. The display shows a labelled estimate carried from 700 m; the data stays empty and the gate enforces it.
2. **5 m has no Argo validation row.** Argo's standard depth grid does not include 5 m, so no comparison is possible. The model reconstructs it normally.
3. **Domain is the Bay of Bengal**, not the full 45-105°E the PS describes. Scoped deliberately under the proof-of-concept clause.
4. **Validation is not held out in time.** Independent instrument, overlapping period (§9.1).
5. **No uncertainty estimates.** `uncertainty_status` is recorded as "unavailable until observational calibration". The conformal machinery exists in the codebase but has not been run.
6. **Salinity is not reconstructed**, though the target tensor contains it.
7. **Training details are not documented** (§5).

---

## 14. File map

| Path | Role |
|---|---|
| `src/oceanembed/api.py` | FastAPI backend; all dashboard endpoints |
| `src/oceanembed/reliability.py` | Three-state gate |
| `src/oceanembed/science.py` | D26, TCHP, MLD-T, scoring |
| `src/oceanembed/cyclone.py` | Best-track loading, thermal context, cold wake |
| `src/oceanembed/provenance.py` | Grid and config fingerprints |
| `src/oceanembed/validation_contract.py` | Matchup payload schema |
| `src/oceanembed/contracts.py` | Cube schema, canonical depths, NetCDF IO |
| `scripts/verify_demo_artifacts.py` | Release gate |
| `scripts/regenerate_v2_artifacts.py` | Artifact regeneration pipeline |
| `configs/cyclone.remal.yaml` | Reviewed IBTrACS column mapping |
| `data/observations/remal_2024_track.csv` | Remal best track |
| `demo/runs/demo.nc` | The reconstruction (~2.7 GB, not in the repo) |
| `demo/runs/argo_validation.json` | Independent Argo results |
| `demo/runs/cyclone_context.json` | Per-track-point D26/TCHP |
| `demo/runs/cold_wake.json` | Before/after temperature change |
| `demo/runs/RELEASE_MANIFEST.json` | Gate verdict and run identity |
| *(external)* Colab bridge script | Produces `demo.nc` from the checkpoints |

The bridge script lives in Colab rather than the repository, which is a real gap: the code that produces the primary data artifact is not version-controlled alongside the code that consumes it. Worth fixing.

---

## 15. Reproducing a run

1. Apply any pipeline change to the Colab bridge script.
2. Run it end to end; confirm the boundary check reports non-zero 0 m support and zero 1000 m support **before** downloading anything.
3. Copy `demo.nc` and `demo.metrics.json` to Drive, download to the project's `demo/runs/`.
4. Rerun the Argo validation against the new file.
5. Rerun `cyclone-context` and `cold-wake`, which stamp their own checksums.
6. Run the release gate with `--manifest` and confirm PASS.
7. Restart the API with `OCEAN_RUN`, `OCEAN_VALIDATION`, `OCEAN_CYCLONE`, `OCEAN_COLD_WAKE` set.

Skipping step 4 or 5 produces HTTP 409 from the affected endpoints — stale artifacts are refused rather than served over the wrong data.
