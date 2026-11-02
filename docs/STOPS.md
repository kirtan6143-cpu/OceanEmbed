# STOP phases: build together

The source ZIP already contains every implemented batch. Each STOP is an action you perform on your computer or in an authenticated browser. Between STOPs, the commands run the supplied code; there is no need to paste dozens of independent files.

## V5 migration

Read V5_CHANGES.md before reusing older data products or checkpoints. Rebuild matchups/calibration and ridge selections; keep raw data and reviewed cubes.

## STOP 1 — local environment and demo

Follow START_HERE.md. Keep API and frontend in separate terminals. Ctrl+C stops either server. The local API reads its run once; restart it after changing a run file or environment variables.

For optional local model checks, install the training extra in the same Python environment:

```bash
python -m pip install -e ".[train,dev]"
python -m pytest -q
python -m oceanembed.cli train configs/smoke.yaml
python -m oceanembed.cli predict data/processed/synthetic.nc artifacts/smoke --partition test --limit 3 --out demo/runs/smoke-model.nc
```

On Windows, replace each python command with .\.venv\Scripts\python.exe if the environment is not activated. The smoke settings run two epochs and only three batches per phase. They verify code execution; they are not meaningful scientific training.

PASS: local demo loads and exports. Send OS/RAM/GPU and any errors before moving on.

## STOP 2 — accounts, sample data and the real cube

Do this in your browser. No credentials belong in the ZIP or chat.

1. Open Copernicus Marine and NASA Earthdata/PO.DAAC. Create/sign in to your own accounts where the provider requires it.
2. Start with the proposed Bay of Bengal box 5–25°N, 80–100°E. Check whether each selected collection actually covers 2021–2024. If not, agree one common period and update all four split ranges together.
3. Select the source families in DATA_CONTRACT.md. Record product ID, collection version, units, observation window, nominal time, availability information, QC policy and download date. Decide satellite-derived versus blended research mode. Do not call blended winds satellite-only.
4. Download a small sample of each product first: one or a few daily NetCDF files, one relevant SSS composite, GLORYS temperature AND salinity with depths through at least 1000 m, and regional bathymetry. Retain original filenames.
5. Put samples in data/raw/sst, sss, altimetry, wind, glorys, bathymetry. Create the folders using VS Code Explorer if they do not exist. Data files belong on disk here; they are not pasted into code.
6. Inventory them:

```bash
python -m oceanembed.cli inventory data/raw --out data/manifests/inventory.json
```

**STOP and send Codex inventory.json plus representative small files or their headers.** The exact adapter configuration depends on those headers. This is the point for source-specific variable, coordinate, QC and age derivation, not guessing that every download already matches the template.

Copy configs/sources.example.yaml to configs/sources.local.yaml. Edit paths, coordinate rename maps, exact units, conversions, QC and age variables against reviewed files. Keep reviewed: false until that is done. The generic adapter expects rectilinear time/lat/lon arrays. Swath products need a separately reviewed regridding step. Native age arrays must be derived honestly from product metadata; do not fill them with zero just to pass.

Once reviewed, obtain the agreed period as regional subsets. Prefer provider-side subsetting. Do not download global files merely to crop them later. Check available disk/RAM and preprocess time chunks if native arrays are too large. This release's prepare command loads its selected native files into RAM.

Set reviewed: true after the mapping is correct, then:

```bash
python -m oceanembed.cli prepare configs/sources.local.yaml --out data/processed/regional.nc
python -m oceanembed.cli validate data/processed/regional.nc
```

Inspect data/processed/regional.sources.json. Plot/check a few surface and deep slices, units, coast support and missingness. Confirm the finite target count and memory footprint using DATA_CONTRACT.md. Training requires full seasonal coverage in its training partition.

PASS: reviewed source notes and a valid regional.nc with actual nonzero coverage in every input, sensible temperatures, appropriate land/depth masking and enough dates in all partitions. Passing the schema alone is insufficient scientific QC.

## Between STOP 2 and STOP 3 — baselines and short training

Use local Python if available or the Colab notebook. Never start a long run until a one-epoch pilot has worked.

```bash
python -m oceanembed.cli baseline-select configs/regional.yaml --out artifacts/ridge-validation
```

This fits ridge coefficients on train and chooses regularization per depth using validation only. It does not use test values for fitting, selection or reporting (the current loader still loads the whole cube into RAM) -- `selection.json` in the output directory contains only validation-derived numbers. Do not run `baseline-evaluate` yet; that command scores the frozen baseline on test and is reserved for the point in the build order where model development is otherwise finished (see the final validation step at STOP 4, alongside the trained model's own held-out evaluation). Running it early exposes test results before later architecture/hyperparameter choices are locked in, which is the same leakage risk the project already guards against for model checkpoint selection.

For a non-temporal CNN comparator, copy regional.yaml to cnn.yaml, change temporal to false and use a different output directory. For a one-epoch pilot, copy the config and use epochs: 1 and max_batches: 3; do not overwrite the full-run configuration or directory.

Use only validation results to choose architecture and settings. Run full-grid validation inference for comparisons, because training validation uses fixed crops.

## STOP 3 — Colab upload and GPU training

1. Open https://colab.research.google.com/.
2. Choose File → Upload notebook and select notebooks/03_train_colab.ipynb.
3. Choose Runtime → Change runtime type → a GPU if available. The notebook checks the actual device; Colab does not guarantee a particular GPU or runtime duration.
4. Upload the master code ZIP when the first code cell requests it.
5. Mount your Google Drive using the notebook's authorization prompt.
6. In the Drive browser, create MyDrive/OceanEmbed/data and upload the reviewed regional.nc. Also save regional.sources.json there for provenance.
7. Set RUN_NAME to a new version such as regional-v1; set the exact prepared-cube path. Run notebook cells in order. The notebook keeps checkpoints in Drive and copies the cube to fast session storage.
8. Inspect the one-batch pilot before full training. Check training loss, validation loss, runtime and GPU memory. Reduce patch or batch size in a new run config if out of memory.

The full training config saves resume.pt each completed epoch, weights.pt when validation improves, transforms.nc, config.json, split_manifest.json, manifest.json and history.json. If disconnected, reconnect, reload the same code/cube/config and resume your own checkpoint using the resume cell. Do not load a resume checkpoint obtained from an untrusted third party.

PASS: selected weights and transforms exist, validation training history is finite, and bundle ZIP downloads. No particular epoch count or error is a success guarantee.

## STOP 4 — bring the model back and evaluate

Extract the notebook's model-bundle ZIP into artifacts/ so the directory is artifacts/bundle-regional-v1. Do not rename or separate its internal files. Your local prepared cube remains data/processed/regional.nc.

```bash
python -m oceanembed.cli predict data/processed/regional.nc artifacts/bundle-regional-v1 --partition validation --out demo/runs/validation.nc
python -m oceanembed.cli predict data/processed/regional.nc artifacts/bundle-regional-v1 --partition calibration --out demo/runs/calibration.nc
python -m oceanembed.cli predict data/processed/regional.nc artifacts/bundle-regional-v1 --partition test --out demo/runs/test.nc
```

Inference loads on CPU by default. Colab filesystem paths stored in the training config do not need to exist locally; the CLI uses your supplied local cube path. The grid must match the training transforms. Changing the region/resolution requires a compatible new model/prior.

Model development is finished at this point, so this is also the right moment -- not before -- to freeze the ridge baseline's test score, using the `artifacts/ridge-validation` directory produced by `baseline-select` earlier:

```bash
python -m oceanembed.cli baseline-evaluate configs/regional.yaml artifacts/ridge-validation --out artifacts/ridge-test
```

This loads the coefficients `baseline-select` already chose and scores them once on test, without refitting. It refuses `--partition validation`, since validation already picked the regularization strength.

In your browser obtain Argo profile NetCDF files for the agreed region and calibration/test dates from the official selection/GDAC service. Put them under data/raw/argo. Preserve product quality flags.

```bash
python -m oceanembed.cli argo "data/raw/argo/**/*.nc" --out data/observations/argo.csv
python -m oceanembed.cli partitions data/observations/argo.csv
python -m oceanembed.cli match demo/runs/calibration.nc data/observations/argo.csv --partition calibration --out artifacts/argo-calibration.json
python -m oceanembed.cli match demo/runs/test.nc data/observations/argo.csv --partition test --out artifacts/argo-test.json
python -m oceanembed.cli calibrate artifacts/argo-calibration.json --out artifacts/calibration.json
python -m oceanembed.cli intervals demo/runs/test.nc artifacts/calibration.json artifacts/argo-test.json --out demo/runs/test-intervals.nc
```

Floats are reserved three ways -- adaptation, calibration, test -- by a deterministic hash (`observations.float_partition`), not folded into just two groups. `partitions` prints the count in each group so you can sanity-check the split before matching. Every `match()`/`calibrate()` output is stamped with a `partition_scheme_version`; `calibrate()` and `intervals` both refuse a matchups file stamped with an old version, so a cached calibration or test JSON from before a scheme change can never be silently mixed with a new one -- re-run `argo`/`match`/`calibrate` from scratch instead of reusing old artifacts/argo-*.json files after upgrading the code.

Insufficient complete profiles must remain an unavailable interval. Inspect unique float IDs, match distances/times, per-depth counts and the coverage report. The code uses disjoint float hash groups and later test dates, but correlated profiles and teacher assimilation still limit independence claims.

RAMA moorings supplement Argo's coarser time sampling at a small, fixed set of Indian Ocean sites -- they never establish spatial coverage and are not used to calibrate uncertainty. The adapter (`rama.py`) mirrors `prepare.py`'s discipline: it will not guess a real RAMA file's variable or QC-flag names, so review actual downloaded headers and set `reviewed: true` in a rama.yaml config before running it, the same as the gridded sources at STOP 2. Copy configs/rama.example.yaml to configs/rama.local.yaml and edit it against real downloaded files before setting reviewed: true.

```bash
python -m oceanembed.cli rama configs/rama.local.yaml --out data/observations/rama.csv
python -m oceanembed.cli rama-match demo/runs/test.nc data/observations/rama.csv --group held_out --out artifacts/rama-held-out.json
```

The RAMA mapping now requires stable station metadata, declared Celsius/Kelvin units and explicit QC. Byte flags decode correctly. Default daily policy rejects subdaily series; after review use daily_reduction: mean to average once per station/day/depth. Exact duplicates are removed and conflicts fail. Development matching requires a validation run; held_out requires a test run. Never relabel sensor depth to a nearby output level.

### Optional: cyclone thermal context (retrospective, Disaster Management track)

Download an official IMD/RSMC best track for one storm, convert to CSV, and keep
the original alongside for provenance. Copy configs/cyclone.example.yaml to
configs/cyclone.local.yaml and review every column mapping against the real file
before setting reviewed: true -- as with the gridded sources and RAMA, this code
will not guess a layout. Mapping max_wind requires declaring the source's wind
averaging period; mapping category requires declaring the category scheme. IMD
grades are preserved verbatim and never converted to Saffir-Simpson.

```bash
python -m oceanembed.cli cyclone-context demo/runs/test.nc configs/cyclone.local.yaml --out artifacts/cyclone-context.json
python -m oceanembed.cli cold-wake demo/runs/test.nc configs/cyclone.local.yaml --depth 50 --days 3 --out artifacts/cold-wake.json
```

Set OCEAN_CYCLONE and OCEAN_COLD_WAKE to those outputs before starting the API.
Both refuse a payload that does not belong to the selected run. The cold-wake
diagnostic requires a complete window on BOTH sides of passage; a location with a
partial window reports no value and a reason rather than a one-sided average.

### Optional: show all three baselines on the Validate screen

After baseline-evaluate (above), set OCEAN_BASELINES to artifacts/ridge-test/metrics.json.
The Validate screen then plots climatology, persistence and ridge together. This is
gridded agreement with the training reference, deliberately kept separate from the
held-out observational scores -- do not describe it as observational skill.

Set OCEAN_RAMA to the output path (alongside OCEAN_VALIDATION for Argo) before restarting the API to see it in the Validate view. Moorings are reserved two ways (development/held_out) by `rama.mooring_group`, not three: check matchups against `held_out` moorings only for anything you intend to report, and use `development` moorings freely while still iterating.

Start the API on the test run first. Windows PowerShell:

```powershell
$env:OCEAN_RUN="demo/runs/test.nc"
$env:OCEAN_VALIDATION="artifacts/argo-test.json"
$env:OCEAN_BASELINES="artifacts/ridge-test/metrics.json"   # optional
$env:OCEAN_CYCLONE="artifacts/cyclone-context.json"        # optional
$env:OCEAN_COLD_WAKE="artifacts/cold-wake.json"            # optional
$env:OCEAN_RAMA="artifacts/rama-held-out.json"
.\.venv\Scripts\python.exe -m uvicorn oceanembed.api:app --host 127.0.0.1 --port 8000
```

macOS/Linux:

```bash
export OCEAN_RUN=demo/runs/test.nc
export OCEAN_VALIDATION=artifacts/argo-test.json
export OCEAN_BASELINES=artifacts/ridge-test/metrics.json   # optional
export OCEAN_CYCLONE=artifacts/cyclone-context.json        # optional
export OCEAN_COLD_WAKE=artifacts/cold-wake.json            # optional
export OCEAN_RAMA=artifacts/rama-held-out.json
python -m uvicorn oceanembed.api:app --host 127.0.0.1 --port 8000
```

OCEAN_RAMA is optional -- omit it and the Validate view's RAMA tab reports no measured results loaded, the same as Argo without OCEAN_VALIDATION. Restart frontend if needed with npm run dev from frontend. Argo and RAMA now show measured matchups where loaded. Reanalysis shows teacher-reference metrics, separately labelled.

For real heat events, prepare and independently review the long-term daily baseline described in DATA_CONTRACT.md. Then:

```bash
python -m oceanembed.cli heat-baseline demo/runs/test.nc data/processed/heat-baseline.nc --out demo/runs/test-events.nc
```

Set OCEAN_RUN to that output and restart the API. Without a baseline the event view deliberately reports unavailable. Appending intervals/baselines creates a new run; its original teacher metrics sidecar is not automatically copied.

PASS: local model inference works, exports reopen, evidence files reflect real held-out observations, and all displayed limitations/source modes are correct. Report measured results and remaining gaps before a competition demo.

## Common recovery

- API 503: run demo or correct OCEAN_RUN; start the server from the repository root.
- Blank profile: click a wet cell; unsupported land/deep inputs intentionally remain missing.
- Region unavailable: the pilot is Bay of Bengal only; use Full domain/Bay of Bengal, not Arabian Sea.
- Port busy: stop the previous API/frontend terminal; keep the documented ports so the proxy matches.
- Module not found: use the selected .venv interpreter and install from the repository root.
- QC/unit/age error: fix the reviewed mapping; do not disable the validation.
- Colab out of RAM: native source preparation is too large; subset before assembling a cube. GPU memory and CPU RAM are different.
- Colab disconnect: use the same RUN_NAME/config and the saved resume.pt.
- Very wide intervals: investigate reference mismatch and support; do not cosmetically shrink bands.



## Local v5 verification gate

After installing Python extras and frontend dependencies, run:

```bash
python -m pip install -e ".[train,dev]"
python scripts/verify_release.py
```

Run npm ci in frontend first. The gate writes docs/LOCAL_VERIFICATION.json. If a check fails, send that file and pause before real-data training. Old resume checkpoints require a new run directory; fresh training will not overwrite an existing checkpoint.
