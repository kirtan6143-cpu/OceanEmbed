# v7: the four feature gaps the honest review identified

v6 was a serving/performance release. It did not touch the feature gaps the
external review flagged. v7 closes all four of them in code, with tests.

It does NOT close the gap the review called the most important one: there is
still no real-data validation number, because STOP 2 has never run. See
"What this release still does not do" below.

## 1. Three-state reliability gate (was: missing entirely)

New `reliability.py`. Every grid cell and every profile depth now reports
`Supported` / `Caution` / `Abstain`, with a machine-readable reason code.

Rules are declared, not inferred at request time, and are echoed into every
payload so a state is auditable:

- **Abstain** - structural absence of support: no finite value, land/dry cell,
  depth below the seabed, or the declared valid-depth support mask does not
  reach this level.
- **Caution** - an estimate exists but a declared precondition is unmet: inputs
  older than `max_age_hours` (default 48), any missing surface channel, or the
  cell sits within `edge_cells` (default 3, matching the inference halo) of the
  domain boundary where the receptive field is truncated.
- **Supported** - all checks pass.

Design decisions worth knowing:

- Precedence is fixed: Abstain always overrides Caution. A stale *and* dry cell
  reads Abstain.
- The reported reason explains the absence. A cell below the seabed reads
  `below_seabed`, not the less informative `no_value`.
- A profile's overall state is the worst state among depths that actually
  report. A profile in 400 m water stays `Supported` for the 12 levels it has,
  with `depths_reporting: 12 / 15` published alongside - marking every shelf
  profile `Abstain` would make the gate useless.
- `calibration_applies` is reported **separately** from the state. A Supported
  point on an uncalibrated run does not claim coverage.
- Reliability is never a danger level and never changes a scientific severity
  class. A marine-heatwave category is computed from temperature, not from how
  trustworthy that temperature is.

Served on `/field` (per-cell array + summary + thresholds) and `/profile`
(per-depth + overall). Drawn on the Explore map as an overlay, encoded by
**shape as well as colour** so the three states stay distinguishable without
colour discrimination.

## 2. Naive persistence baseline (was: missing entirely)

Added to `baseline.py`. Persistence for day *t* is the observed field from day
*t-1* at the same cell and depth.

It is only defined where a contiguous previous day exists. Where the time axis
has a gap, persistence yields **no estimate** rather than silently carrying a
stale value across the gap - so it is scored on its own matched subset and
reports its own `n`. Comparing a persistence RMSE computed on fewer points
against a model RMSE computed on all points is not like-for-like, so the
per-baseline counts are published rather than assumed equal.

## 3. Ridge baseline reaches the UI (was: computed but never displayed)

New `/baselines` endpoint serves `baseline-evaluate` output via
`OCEAN_BASELINES`, and the Validate screen now plots climatology, persistence
and ridge together.

It is served **separately from `/validation`** on purpose: these are gridded
agreement scores against the training reference, not held-out observational
skill. Merging them into the observation scorecard would blur exactly the
distinction the evaluation design exists to preserve. The endpoint refuses a
`selection.json` (validation-only scores) with a 409.

## 4. Cyclone thermal context (was: missing entirely)

New `cyclone.py` plus `cyclone-context` and `cold-wake` CLI commands and two
endpoints.

- **Best-track ingestion** is config-driven behind a `reviewed: true` gate, the
  same discipline `prepare.py` and `rama.py` use. It does not guess an IMD/RSMC
  layout. Mapping `max_wind` requires declaring the source's wind averaging
  period; mapping `category` requires declaring the category scheme. IMD grades
  are preserved verbatim and never remapped onto Saffir-Simpson.
- **Thermal context** reports reconstructed D26 and TCHP at each in-domain
  track point. Points outside the domain or outside the run's dates are
  returned *with a reason* rather than dropped, so a sparse overlay looks
  sparse instead of looking complete.
- **Cold wake** averages matched windows either side of passage at the same
  cells. Both windows must be complete - a partial window yields no value and a
  stated reason, because averaging different numbers of days on each side would
  manufacture a difference that is an artefact of the window.
- Every payload carries its limits: this describes a past storm's ocean state.
  It is not an intensity or rapid-intensification forecast, and a negative
  change does not by itself establish that the storm caused it.

## Verification actually performed for this release

- Full suite: **97 tests passing** (was 87), including 16 new reliability
  tests, 14 new cyclone tests, and 10 new API-feature tests.
- Frontend `tsc --noEmit && vite build` passes; shell chunk is 260 kB with
  Plotly lazy-loaded separately (v6's code-splitting confirmed working).
- Live end-to-end run: demo run -> `cyclone-context` -> `cold-wake` -> all
  endpoints served through the real app. Verified the cold-wake diagnostic
  recovers an injected -2.0 C cooling exactly in a controlled fixture.

Two bugs were found and fixed in this release's own new code during testing: a
reason-precedence bug where `no_value` masked the more informative
`below_seabed`, and an all-NaN warning when every channel was missing at a cell.

## What this release still does not do

Unchanged from v6, and still the most important thing on the list:

- **No real ocean data.** STOP 2 has never run. Every number the app can show
  is from synthetic or CPU-smoke-test data.
- **No GPU training.** The model has never trained to convergence on anything.
- **No measured scientific skill.** If asked "what is your RMSE on real Argo
  data", the honest answer is still: none yet.
- Adaptation training stage, learned uncertainty scaling, attention and WOA
  prior remain optional roadmap items.

The new reliability gate and cyclone screens make the demo *complete*. They do
not make it *validated*. Those are different claims and only the first is
earned.

## Adversarial hardening pass (post-release)

After shipping the four features above, they were attacked directly rather
than just read: oversized/negative `edge_cells`, negative `max_age_hours`,
mismatched array shapes for `support`/`bathymetry`/`age_hours`, an empty
track CSV, out-of-range lat/lon, `days <= 0` for the cold-wake window, and
the cyclone CLI commands run through the actual argparse entry point rather
than only called as functions.

Two real robustness gaps were found and fixed:

- `field_states()`/`profile_state()` silently accepted negative
  `max_age_hours`/`edge_cells` and mismatched-shape `support`/`bathymetry`/
  `age_hours` arrays instead of raising. A malformed caller would previously
  get either silently-wrong behaviour (negative thresholds) or a raw
  `IndexError` (mismatched support length) instead of a clear `ValueError`.
  Both now raise explicitly, consistent with the validation discipline the
  rest of the project already applies.

Everything else attacked (lon 270 normalization, empty-file rejection,
out-of-range coordinates, non-positive cold-wake windows, duplicate track
points, boundary case depth == bathymetry) already behaved correctly.

9 new regression tests added for the two fixes and the CLI-wiring gap
(`test_cli_cyclone.py`). Suite: **106 tests passing** (was 97).
