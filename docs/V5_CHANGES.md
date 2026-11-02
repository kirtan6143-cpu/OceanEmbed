# V5 changes and migration

Version: 0.5.0. This supersedes the v4 source package. It fixes known software defects; it does not establish measured ocean-model skill or optimal architecture.

## Fixed

- RAMA and Argo share numeric observed/predicted/depth fields and an explicit observation schema. The UI uses the selected source's label and displays mooring provenance.
- Byte, Unicode, integer and integer-valued float QC flags normalize consistently.
- RAMA temperature units must exist and be supported; Kelvin converts to Celsius.
- Station IDs must be stable metadata, never filenames. Inconsistent station coordinates fail.
- Explicit time-coordinate mapping; extra instrument dimensions must be selected beforehand.
- Duplicate observations are deduplicated before daily aggregation. Conflicting duplicates fail. Subdaily averaging requires explicit mean policy and preserves sample counts.
- All declared temperature/QC variables must exist. Omitting QC requires a written product-specific review.
- Held-out RAMA matches test runs; development matches validation runs. Same-day matching is the default.
- APIs reject legacy observation schemas, missing checksums and real-observation results attached to synthetic runs.
- Argo split fingerprints include actual shares. Calibration/test intervals require identical split and model fingerprints.
- Inference fingerprints weights, transforms and configuration together.
- Frozen ridge evaluation verifies configuration, cube and saved-file checksums; it cannot silently substitute different inputs or refit coefficients.
- Resume validates checkpoint schema, data hash and configuration before modifying output files. Fresh training refuses to overwrite an existing checkpoint directory.
- Stale verification claims were replaced with evidence from this release.

## Migration

1. Extract into a NEW folder; do not mix v4 and v5 source files.
2. Keep raw downloads and reviewed prepared cubes. Check RAMA source units/IDs/QC against the stricter example.
3. Regenerate RAMA CSV and all Argo/RAMA matchup JSON files.
4. Regenerate predictions with v5 to attach model fingerprints, then regenerate interval calibration/attachments. Old constant-width interval files cannot be reused as newly verified artifacts.
5. Re-select ridge baselines before evaluating: old selection files lack the new frozen-data checks.
6. Use a new versioned directory for training. Pre-v5 resume checkpoints lack the current checkpoint schema and are intentionally rejected. Old inference weights may still be loaded in a complete compatible bundle; that is not a claim of new scientific validation.
7. Continue through the same four STOP phases.

## Scope that remains experimental

No real source collection was downloaded or reviewed here. No real-data training, Argo/RAMA benchmark, GPU run or Colab execution was performed. Argo adaptation training, learned heteroscedastic scale heads, attention, WOA priors, operational ingestion and a photorealistic ocean cutaway remain roadmap items. Current intervals are the documented empirical constant-width fallback.

Full dependency-backed pytest and React production build could not run in this environment because dependencies were unavailable and installation failed. NumPy-only checks exercise scientific routines and actual RAMA function bodies using explicit in-memory NetCDF doubles. They do not replace real NetCDF integration tests. Run scripts/verify_release.py locally after installing requirements before relying on the full application.

