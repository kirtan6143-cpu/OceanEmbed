# OceanEmbed-NIO · Team DeepSindhu

A local research prototype for retrospective subsurface temperature reconstruction. Built from the supplied OceanEmbed-NIO project guide and five interface references.

**V8 visual update:** Run `python start.py --setup`, then use `python start.py`. Read [V8 changes and limits](docs/V8_CHANGES.md).

**V6 performance update (historical):** read [changes and next steps](docs/V6_CHANGES.md).
Current verification is in `docs/V6_VERIFICATION.json`; the v5 report is historical.
Upgrading from v4? First read [v5 migration](docs/V5_CHANGES.md).

**Start with [START_HERE.md](START_HERE.md).** All code batches are included. Do not run every Python file separately: many are imported modules. Run the numbered commands and check the stated outputs.

The package includes a five-view React dashboard, FastAPI server, synthetic fixture, explicit NetCDF preparation, shared CNN + causal TCN, training and inference, climatology/ridge baselines (validation-selected, evaluated on test separately), Argo conversion and matching (three-way adaptation/calibration/test float reservation), a config-driven RAMA mooring adapter, empirical interval audit, thermal diagnostics, exports and a Colab notebook.

This is buildable research software, not a trained or scientifically validated ocean product. No real satellite data, Argo data or pretrained weights are included. Real source mappings must be checked against actual downloaded files at STOP 2. See [release status](docs/RELEASE_STATUS.md) for differences from the full guide.

- [All batches and their files](BATCHES.md)
- [Detailed STOP instructions](docs/STOPS.md)
- [Dataset contract and counts](docs/DATA_CONTRACT.md)
- [Architecture and scientific limits](docs/ARCHITECTURE.md)
- [Data and software sources](docs/SOURCES.md)
- [Colab training notebook](notebooks/03_train_colab.ipynb)

The UI follows the references' navy/cyan style and tab structure. Its charts render data; the supplied screenshots are not used as fake interactive maps. V8 provides a depth-based scientific cutaway plus quantitative cross-section; it is not photorealistic.

Use Python 3.11 or 3.12 and Node 22 for this build. The frontend lockfile fixes the tested JavaScript dependency graph. Python dependency ranges are in pyproject.toml; the delivered verification report records installed versions.
