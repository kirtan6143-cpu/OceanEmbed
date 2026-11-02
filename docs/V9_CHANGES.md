# V9 — closed two gaps between what was claimed and what v8 actually shipped

This project's own prior session (visible in the person's screenshots) said it
would (1) block the flat, fabricated 0.54 RMSE from displaying, and (2) make
TCHP/D26/MLD-T selectable on Explore. Both were checked against the actual
delivered v8 code rather than taken on the session's word, because it visibly
ran out of usage mid-response in the screenshots. Neither claim held up:

## 1. The flat-0.54-at-all-depths bug was still live

`demo_run()`'s synthetic fixture applies the same global sinusoidal offset to
every depth/lat/lon, so its "model" RMSE is identical (0.538 -> rounds to
0.54) at all 15 depths -- confirmed by direct computation, not by reading
code. `/validation?source=Reanalysis` still rendered that flat line on a real
chart; a text note underneath it ("Computed synthetic illustration...") was
the only thing that had actually been added. A judge glancing at the chart,
not the caption, would still see what looks like 15 independent measurements.

**Fixed at the API, not just the UI**: `/validation` now returns empty
`metrics` for every source (not only Argo/RAMA as before) whenever the
underlying run's `source_mode` is `synthetic`. The frontend's existing
`metrics.length > 0` guard then makes the chart disappear entirely instead of
rendering fabricated numbers with a caption. The same guard was added to
`/baselines` for the identical risk on the ridge/climatology/persistence
comparison. 3 new regression tests, including one confirming real runs are
NOT accidentally blocked by the fix.

## 2. TCHP/D26/MLD-T were never actually wired in

Checked both layers directly: `api.py`'s `variable()` only ever accepted
`temperature`/`anomaly`, and the frontend's Variable dropdown only ever
offered those same two options. Nothing about TCHP/D26/MLD-T selection
existed in either file, despite the claim.

**Implemented properly, including the one subtlety the prior session had
correctly identified but not built**: TCHP/D26/MLD-T describe the whole warm
water column, not one depth level, so they must return the *same* value
regardless of the depth slider. Verified this directly: querying at depth=20
and depth=500 returns byte-identical TCHP fields.

- New `science.field_diagnostics()`: loops the existing per-profile
  `diagnostics()` over a full `[depth, lat, lon]` grid.
- `/field` now accepts `var=tchp|d26|mld_t`, marks the response
  `depth_independent: true`, and computes reliability from the surface cell
  (diagnostics() itself requires valid surface support before reporting
  anything, so that's the right basis -- not whichever depth the slider
  happened to be on).
- `OceanMap.tsx`'s colour system was generalized from a temperature/anomaly
  boolean to a `mode` string with its own domain and unit per variable (TCHP
  0-150 kJ/cm², D26 0-250 m, MLD-T 0-150 m) -- reusing the temperature palette
  for these would have made the map nearly one flat colour, since none of
  them sit in a 0-32°C range.
- Explore's Depth selector disables itself with an explicit note when a
  whole-column diagnostic is selected, rather than silently ignoring the
  slider.

3 new tests for `field_diagnostics()`, plus the endpoint verified live
end-to-end through the running app.

## Verification actually performed for this release

- Full backend suite: **112/112 passing** (was 106).
- Frontend: `tsc --noEmit && vite build` passes (1586 modules).
- Frontend contract tests: 3/3 passing.
- Live end-to-end: built a real demo run, confirmed `/validation` on the
  synthetic run now returns `metrics: []` instead of the flat line, and
  confirmed all three new field variables return correct units and the
  depth-invariance property.

## What this release does not do

Unchanged from v8, and still the actual gap between this project and a
validated result:

- No real ocean data, no GPU training, no measured Argo/RAMA RMSE.
- No browser-based visual audit was possible in this sandbox either (same
  environment restriction v8 hit). Check the five screens on a real machine
  before presenting.

## Visual pass toward the reference mockups (post-release)

The person shared polished reference mockups and asked for a pixel-match.
Two elements in those mockups were declined rather than built, because they
conflict with decisions this project already made deliberately:

- **A photo-satellite basemap.** v8's rewrite specifically removed an online
  tile-server dependency after the v5 review flagged it as a live-demo
  failure mode (blank grey map if the venue network drops). Reintroducing
  satellite tiles would undo that fix; bundling real satellite imagery
  instead means a large, license-uncertain asset unrelated to this
  project's own data.
- **Photorealistic 3D rock-textured seafloor.** `Cutaway.tsx` deliberately
  renders a plain schematic seafloor ("no invented bathymetry, terrain
  texture" per its own comment) because texture at that fidelity isn't
  backed by this project's actual bathymetry data. The written spec this
  project is built against also explicitly says "not a decorative 3D
  globe" -- a photoreal terrain box leans toward exactly that.

What WAS built, safely, from the same mockups:

- **`Locator.tsx`**: a small, non-interactive locator inset for the Sections
  screen, showing the transect line against the basin using the same
  offline Natural Earth data `OceanMap` already bundles -- no new asset, no
  network call. Extracted a shared `useCoastline()` hook out of `OceanMap`
  so both components read the same cached fetch instead of duplicating it.
- A "Transect A-B" facts readout (From/To/Length), matching the mockup's
  info-card content, added directly into the transect panel.

Verified: frontend `tsc --noEmit && vite build` passes (1587 modules);
backend suite unaffected (112/112, untouched by this frontend-only change).

## The "premium but offline-safe" middle path

Rather than choosing between "flat and safe" and "photo-realistic but
network-dependent," built the middle path discussed: richer visuals with
zero network dependency and zero fabricated data precision.

- **Procedural water texture**, entirely offline: a soft depth vignette
  (CSS radial gradients) plus a subtle grain generated by an inlined SVG
  `feTurbulence` filter (a data URI -- no image file, no request, no
  licensing question, ~200 bytes of code). Applied to the page background,
  and as a low-opacity "sheen" layered on top of (never replacing) the real
  data-coloured raster in both `OceanMap` and `Cutaway` -- the actual
  temperature/TCHP/D26 colours underneath are untouched; the sheen is purely
  a soft-light blend for visual depth.
- **Interaction polish**: nav links, buttons, and toggle switches now have
  real hover/press feedback (colour shift, subtle lift, glow on active
  toggles) instead of instant state changes.
- **Panel depth**: richer shadow/gradient on cards, with a hover border
  highlight.

Verified this cost nothing in bundle size or dependencies: CSS grew ~1.3KB
(19.80KB -> 21.10KB gzip), JS essentially unchanged (279.02KB -> 279.91KB) --
this is all inline SVG/CSS, no new packages, no new network calls. Frontend
build passes; backend suite unaffected (112/112, untouched by this
frontend-only change).

## Final pass: the data-mode badge and telemetry freshness (closes a gap open since v5's review)

The spec's header requirement -- a "Research-blended vs. Strict satellite"
data-mode badge plus a telemetry-freshness readout -- was flagged as missing
across multiple review rounds and never actually built until now.

- `/runs` now reports `freshness: {oldest_input_hours, as_of_date}`, computed
  from the run's own real `age_hours` data at its own latest date -- this is
  a retrospective research run, not a live feed, so freshness is relative to
  the date being displayed, not wall-clock time. `None` when a run has no
  age data at all, handled gracefully rather than assumed present.
- The header badge now shows the actual mode (`Strict satellite` /
  `Research-blended` / `DEMO - Synthetic data`, matching the real
  `source_mode` values `prepare.py` already enforces: `satellite_observation`
  / `research_blended` / `synthetic` -- not invented labels) plus the
  freshness line beneath it.

Verified live end-to-end against a real generated run before touching the
frontend: confirmed `source_mode` and a real `oldest_input_hours` value (not
a placeholder) come back correctly. 1 new regression test
(`test_runs_reports_freshness_from_real_age_data`).

Final verification for this release: **113/113 backend tests passing**
(was 112), frontend `tsc --noEmit && vite build` passes (1587 modules,
280KB shell / 1.33MB lazy Plotly chunk, unchanged from the prior pass).

This closes every item from the original v5 review's "Highest priority" and
"Medium priority" lists except the one that was never a code problem: a real
accuracy number from real data. That one remains open, same as it has been
every version of this project.
