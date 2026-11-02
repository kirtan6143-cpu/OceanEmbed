# Release status — 0.6.0

This is research-prototype source code with four guided STOP phases. See
V6_CHANGES.md for serving/rendering improvements and V6_VERIFICATION.json for
current evidence. The capability matrix below retains the v5 scientific scope;
its historical testing statements do not imply a v6 full integration run.

| Capability | Implementation / verification |
|---|---|
| Five-tab React UI and local API | Implemented; RAMA chart schema/labels corrected; three chart-adapter tests passed |
| Synthetic engineering fixture | Generator included; no synthetic metric is ocean skill |
| Shared CNN + causal TCN + direct residual head | Implemented; previous releases reported CPU smoke success; v5 full training not executed here |
| Seeded training crops, fixed validation crops | Implemented |
| Safe resume and inference bundles | Implemented; v5 guards data/config/schema and prevents accidental overwrite |
| Ridge baseline | Train/validation selection separated from final-test evaluation; frozen data/config/file checks added |
| Argo | QC conversion and matching, three-way float reservation, schema/split/model provenance |
| Reliability gate (Supported/Caution/Abstain) | Implemented in `reliability.py`; declared thresholds echoed in every payload; served on /field and /profile; drawn on the Explore map encoded by shape as well as colour. Calibration reported separately from state |
| Persistence baseline | Implemented; only defined where a contiguous previous day exists, reports its own per-depth n |
| Ridge baseline visible in UI | Served via /baselines (OCEAN_BASELINES) and plotted on Validate alongside climatology and persistence; kept separate from observational scores |
| Cyclone thermal context | Implemented in `cyclone.py` (reviewed-config best-track gate, D26/TCHP along track, matched-window cold wake). Retrospective only; never an intensity forecast. No real IMD best-track file has been ingested yet |
| RAMA | Strict reviewed mapping, Celsius conversion, decoded QC, stable IDs, duplicate/daily policy, matching/API/UI integration |
| Native NetCDF preparation | Implemented for reviewed rectilinear mappings; official files still need STOP 2 review |
| Empirical intervals | Constant-width fallback; split/model compatibility checks; actual coverage unmeasured |
| Heat events | Retrospective detector and baseline attachment; independently reviewed long-term baseline required |
| 3D | Scientific distance/depth/temperature surface, not the reference's photorealistic cutaway |
| Real satellite basemap | Not bundled |
| Argo adaptation training, learned scale head, attention, WOA prior | Not implemented; explicitly optional roadmap work |
| Out-of-core / global preprocessing | Not implemented; cube/source assembly is RAM-resident |
| Operational replay, deployment, authentication | Outside this local prototype |

Current checks: Python syntax; 15 NumPy-only core/adapter tests with explicit test doubles; three Node chart-contract tests. The full pytest suite and frontend build must be run locally using scripts/verify_release.py. Dependency installation was unavailable here, so earlier 38/38 and build claims are not presented as current evidence.

No browser visual acceptance, real-data performance, calibration coverage, GPU training or Colab execution is claimed. The large full Plotly bundle remains a local-build tradeoff.
