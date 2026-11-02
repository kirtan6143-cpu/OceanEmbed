# Start here — V8

**Recommended:** run `python start.py --setup` once, then `python start.py`. Open http://127.0.0.1:5173. See [V8 changes](docs/V8_CHANGES.md) for the new demo, controls and verification limitations.

The manual v6 instructions below still work with the original engineering fixture; the new launcher uses the geographic visual demo by default.

# Start here: STOP 1 — v6

**v6 performance update:** Read `docs/V6_CHANGES.md`. Existing v5 model artifacts
remain compatible; this update changes the API and dashboard. Use a fresh folder
and reinstall the project before starting. The stop phases below still apply.

Upgrading from v4? Extract into a fresh folder and read docs/V5_CHANGES.md. Keep raw data and reviewed cubes; regenerate predictions/matchups/calibration and use new training directories.

You can use VS Code for all local code, terminals, the API and dashboard. Use Colab later for GPU training. The trained weights, transforms and configuration return to the same local project as a bundle. No editor migration is necessary.

## 1. Install and open

Install Python 3.12 from https://www.python.org/downloads/, Node.js 22 from https://nodejs.org/en/download and VS Code from https://code.visualstudio.com/. On Windows select Python's PATH option. Install Microsoft's Python extension in VS Code.

Extract the master ZIP. In VS Code choose **File → Open Folder → oceanembed-nio**. Open **Terminal → New Terminal**. The terminal must be in the folder containing pyproject.toml.

Use a local writable folder, not inside the unextracted ZIP. You do not need a GPU to view the demo. Allow roughly 3–5 GB free space for development tools; real datasets require more.

## 2. Create the Python environment

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m oceanembed.cli doctor
.\.venv\Scripts\python.exe -m oceanembed.cli demo
.\.venv\Scripts\python.exe -m uvicorn oceanembed.api:app --host 127.0.0.1 --port 8000
```

These commands use the environment directly; PowerShell activation policy changes are unnecessary. In VS Code run **Python: Select Interpreter** and select .venv.

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m oceanembed.cli doctor
python -m oceanembed.cli demo
python -m uvicorn oceanembed.api:app --host 127.0.0.1 --port 8000
```

Keep this API terminal running. Open http://127.0.0.1:8000/health — it should show status ok. API documentation is at http://127.0.0.1:8000/docs.

## 3. Start the dashboard in a second terminal

```bash
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173. It should show **DEMO · Synthetic data**. Click the map to change the profile; change depth/date; inspect Sections; view the synthetic warm event near the middle of the timeline; open Validate → Reanalysis for labelled synthetic reference scores; download CSV, PNG and NetCDF.

Argo validation should be empty. That is the correct result before observational data are loaded.

## STOP 1 pass condition

Both terminals run without errors, the map changes with depth/date, a profile appears at a wet grid cell, and a CSV downloads. Tell Codex your OS, RAM, GPU if any, and whether these checks passed. If a command fails, send the exact command and terminal error; do not reinstall everything.

**Pause here in our joint build.** All later code is already in the ZIP. Continue to docs/STOPS.md only after this environment works.
