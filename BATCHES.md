# All code batches

One master ZIP contains all batches so imports and dependency versions stay consistent. The stages are execution checkpoints, not separate incompatible projects.

| Batch | Main files | Run / output |
|---|---|---|
| 01 · Environment and contracts | pyproject.toml, src/oceanembed/contracts.py, demo.py, cli.py | doctor; demo → synthetic cube and run |
| 02 · Interface and local API | frontend/src/App.tsx, styles.css, src/oceanembed/api.py | uvicorn + npm run dev → five views |
| STOP 1 | START_HERE.md | Install locally and verify the demo |
| 03 · Dataset inventory and preparation | prepare.py, configs/sources.example.yaml | inventory; prepare; validate → regional.nc + source manifest |
| STOP 2 | docs/STOPS.md, docs/DATA_CONTRACT.md | Download samples, review QC/ages/units, then assemble the cube |
| 04 · Model and training inputs | model.py, dataset.py, baseline.py | 21-channel windows, 15-depth prior, CNN/TCN and ridge |
| 05 · Training | training.py, configs/smoke.yaml, configs/regional.yaml | train → selected weights, resume checkpoint, history |
| STOP 3 | notebooks/03_train_colab.ipynb | Upload code and prepared cube; choose runtime; start/resume training |
| 06 · Inference and validation | inference.py, observations.py, rama.py | predict; argo; rama; match; rama-match → runs and measured matchup metrics |
| 07 · Science and export | science.py, products.py, api.py | intervals; heat-baseline; CSV/NetCDF/PNG |
| STOP 4 | docs/STOPS.md | Download bundle, run final validation locally, point API at real run |
| 08 · Verification | tests/, docs/VERIFICATION.json | pytest; npm run build |

All Python module paths in the table are under src/oceanembed unless otherwise stated. You edit files in VS Code, but execute CLI commands from the repository root.

## Folder structure

```text
oceanembed-nio/
  START_HERE.md
  README.md
  BATCHES.md
  pyproject.toml
  configs/
    smoke.yaml
    regional.yaml
    sources.example.yaml
  src/oceanembed/
    contracts.py
    demo.py
    prepare.py
    dataset.py
    model.py
    training.py
    baseline.py
    inference.py
    observations.py
    rama.py
    validation_contract.py
    rama.py
    science.py
    products.py
    api.py
    cli.py
  frontend/
    package.json
    package-lock.json
    vite.config.ts
    index.html
    src/
      main.tsx
      App.tsx
      styles.css
  notebooks/
    03_train_colab.ipynb
  docs/
    STOPS.md
    DATA_CONTRACT.md
    ARCHITECTURE.md
    RELEASE_STATUS.md
    SOURCES.md
    VERIFICATION.json
  scripts/
    check_core.py
    verify_release.py
  tests/
  data/                  # generated/downloaded, not in source ZIP
    raw/
    processed/
    observations/
    manifests/
  artifacts/             # generated model checkpoints and bundles
  demo/runs/             # generated display-ready runs
```

