# OceanEmbed-NIO — Setup Guide

How to get the dashboard running on your own laptop from the handoff zip.

**Read this first:** `demo.nc` is not a file you open. It is a NetCDF scientific data container (about 2.7 GB) that the application reads. Double-clicking it will do nothing, or your machine will offer to open it in a text editor and show gibberish. That is expected. It only needs to be placed in the correct folder — the dashboard does the rest.

---

## 1. What you need first

- **Python 3.11 or newer.** Check with `python --version` (Windows) or `python3 --version` (macOS/Linux). If it is older than 3.11, install a newer one from python.org.
- **Node.js 18 or newer.** Check with `node --version`. Install from nodejs.org if missing.
- **About 4 GB of free disk space** — 2.7 GB for the data file, the rest for dependencies.

---

## 2. Unzip the project

Extract the handoff zip somewhere sensible, for example your Documents folder. Avoid paths with unusual characters. You should end up with a folder containing `src`, `frontend`, `configs`, `demo`, `scripts` and `tests`.

Everything below is run **from inside that folder**, so open a terminal there first:

- **Windows:** open the folder in File Explorer, click the address bar, type `cmd` and press Enter.
- **macOS:** right-click the folder → Services → New Terminal at Folder.
- **Linux:** right-click → Open in Terminal.

---

## 3. Get the data file

The zip does not contain `demo.nc` — at 2.7 GB it cannot be emailed or sent over chat. Download it separately from the shared Google Drive folder:

```
oceanembed-nio/demo_runs/demo.nc
```

Put it here, inside the project folder:

```
demo/runs/demo.nc
```

The `demo/runs/` folder already exists and already contains four small `.json` files. **Do not delete or replace those** — they belong with this exact data file (see section 7).

### Check you got the right file

Every result in the dashboard is cryptographically tied to one specific version of `demo.nc`. If you have a different or older copy, parts of the dashboard will refuse to load rather than show you results from the wrong data. Verify it:

**Windows:**

```
python -c "import hashlib; h=hashlib.sha256(); f=open(r'demo\runs\demo.nc','rb'); [h.update(c) for c in iter(lambda: f.read(1024*1024), b'')]; f.close(); print(h.hexdigest())"
```

**macOS/Linux:**

```
shasum -a 256 demo/runs/demo.nc
```

It should print:

```
3cf229d249b090b7c0732cc50d97ec90414e89452a37c5196804b92fb1e0212e
```

This takes a minute on a file that size. If it does not match, you have the wrong copy — redownload before continuing.

---

## 4. Set up Python

Create an isolated environment and install the project into it.

**Windows:**

```
python -m venv .venv
```

```
.venv\Scripts\python.exe -m pip install --upgrade pip
```

```
.venv\Scripts\python.exe -m pip install -e .
```

**macOS/Linux:**

```
python3 -m venv .venv
```

```
.venv/bin/python -m pip install --upgrade pip
```

```
.venv/bin/python -m pip install -e .
```

This pulls in numpy, xarray, fastapi, gsw and the rest. It takes a few minutes the first time.

---

## 5. Set up the frontend

```
cd frontend
```

```
npm install
```

```
cd ..
```

Then return to the project root (the `cd ..` above does that).

---

## 6. Run it

You need **two terminal windows** open at the project folder — one for the backend, one for the frontend. Both must stay running while you use the dashboard.

### Terminal 1 — the API

The four environment variables tell the API where to find the validation and cyclone results. They must be set **before** starting the server, in the same window.

**Windows:**

```
set OCEAN_RUN=demo\runs\demo.nc
```

```
set OCEAN_VALIDATION=demo\runs\argo_validation.json
```

```
set OCEAN_CYCLONE=demo\runs\cyclone_context.json
```

```
set OCEAN_COLD_WAKE=demo\runs\cold_wake.json
```

```
.venv\Scripts\python.exe -m uvicorn oceanembed.api:app --host 127.0.0.1 --port 8001
```

**macOS/Linux:**

```
export OCEAN_RUN=demo/runs/demo.nc
```

```
export OCEAN_VALIDATION=demo/runs/argo_validation.json
```

```
export OCEAN_CYCLONE=demo/runs/cyclone_context.json
```

```
export OCEAN_COLD_WAKE=demo/runs/cold_wake.json
```

```
.venv/bin/python -m uvicorn oceanembed.api:app --host 127.0.0.1 --port 8001
```

Wait until it prints `Uvicorn running on http://127.0.0.1:8001`.

Note that these variables only last for that terminal window. If you close it, set them again next time.

### Terminal 2 — the frontend

```
cd frontend
```

```
npm run dev
```

It will print a local address, usually `http://127.0.0.1:5173`. Open that in your browser.

---

## 7. Confirm it actually works

Before assuming everything is fine, run the release gate:

**Windows:**

```
.venv\Scripts\python.exe scripts\verify_demo_artifacts.py demo\runs\demo.nc
```

**macOS/Linux:**

```
.venv/bin/python scripts/verify_demo_artifacts.py demo/runs/demo.nc
```

You want to see `PASS`. One warning about `demo.metrics.json` being teacher/reference evaluation is expected and correct — leave it alone.

Then click through the dashboard:

- **Explore** at 0 m and at 100 m — should show a coloured temperature map.
- **Explore** at 1000 m — deliberately shows an estimate with a banner, not a normal reading. This is intended behaviour, not a bug.
- **Validate** tab, source **Argo** — a per-depth scorecard. The 1000 m row showing no value is correct.
- **Heat events** — Cyclone Remal's track with D26 and TCHP.

---

## 8. If something goes wrong

**"Evaluation does not belong to the selected run" (error 409).** Your `demo.nc` does not match the `.json` files next to it. Either you have an old `demo.nc`, or you replaced the JSON files. Both must come from the same batch. Recheck the checksum in section 3.

**Validate or Heat events shows "No measured results loaded".** The environment variables were not set, or were set in a different window from the one running the server. Stop the server, set them again in that same window, and restart.

**`.venv\Scripts\python.exe` not found (Windows).** The virtual environment was not created. Go back to section 4. On some systems the Python launcher is `py` rather than `python`, so try `py -m venv .venv`.

**Port 8001 already in use.** Another copy of the server is already running. Close the other terminal, or start this one with `--port 8002` and nothing else changes.

**`npm install` fails.** Check `node --version` is 18 or newer. If it is much older, upgrade Node.

**The page loads but the map is empty.** The API is probably not running, or is running on a different port. Check terminal 1 is still alive and shows no errors.

---

## 9. What this thing is

A deep learning system that reconstructs ocean temperature at 15 standard depths from surface satellite observations, over the Bay of Bengal at 0.25° resolution, daily for 2023-2025. It is validated against independent Argo float measurements, and includes retrospective thermal context for Cyclone Remal (May 2024).

Two deliberate limitations you will notice, both documented rather than hidden:

- **1000 m** shows an estimate, not a reconstruction. The source reanalysis only extends to about 902 m, so there is no real data at that depth. The system says so rather than inventing a number.
- **Cells marked Abstain or Caution** are the reliability system working as designed. Where inputs are missing, stale, or the seabed is shallower than the requested depth, it declines to show a value instead of guessing.
