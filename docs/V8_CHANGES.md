# V8 — Reference-led visual rebuild

## Run

First run, from this extracted folder (Python 3.12 and Node 22 installed):

    python start.py --setup

Later:

    python start.py

Open http://127.0.0.1:5173. Ctrl+C stops both services. On Windows `py -3.12 start.py --setup` also works. The launcher checks ports, waits for API health and respects an existing `OCEAN_RUN`. Setup installs dependencies; it does not download scientific observations or train a model.

## Changes

- Reference-led navy/cyan visual system, readable headings and controls, fuller desktop layouts, responsive CSS, keyboard focus and high-contrast/text-size controls.
- Locally bundled Natural Earth 1:110m geography. Canvas-rendered scientific field cells sit beneath geographic land polygons. No online tile server or screenshot-as-map dependency. Profile selection, zoom, coordinates, regional labels and reliability markers remain interactive.
- New explicitly synthetic geographic demo. It includes spatially varying temperature, illustrative coastal bathymetry, freshness differences and a local warm pulse. None is observational evidence. Original engineering fixture and scientific pipeline unchanged.
- Sections includes click-to-place A/B endpoints, coordinate input, distance/depth heatmap, seafloor fill, a surface-connected 26°C crossing, and a depth-based cutaway. The cutaway is an SVG scientific illustration, not a photorealistic ocean simulation. The quantitative cross-section remains visible below it.
- Existing cyclone context and cold-wake diagnostics preserved. Available track points are also drawn on the Heat events map. No invented historical track is included.
- Plotly v3 axis-title format corrected. The lazy-loaded Cartesian distribution replaces the full plotting distribution, reducing its uncompressed chunk from ~4.84 MB to ~1.33 MB. The initial application JS is ~276 KB before gzip. Vite still warns about the separate plotting chunk exceeding 500 KB; it is not loaded as part of the shell bundle.
- Validate uses explicit evidence states when no evaluation is loaded. Existing measured evaluation and baseline charts remain data driven. Missing observations are never replaced with demo scatter points or attractive made-up accuracy numbers.
- About/Data sources/Accessibility information, SVG favicon, institutional problem context and an explicit research-only footer.
- One-command launcher and GitHub Actions workflow for Python tests, frontend tests and production build.

## Scientific and visual limitations

- No real Argo/RAMA/satellite archive or trained GPU checkpoint was supplied. This release contains no real model accuracy claim and did not execute a real regional GPU training run. The existing training notebook and adapters remain included.
- Three baseline scores and model performance are intentionally separated when their references/sample sets differ. They must not be combined into an unqualified ranking.
- Geography is public-domain Natural Earth cartography, not an official Indian boundary dataset and not suitable for navigation or territorial determinations. The visual land overlay does not change backend scientific masks.
- Text controls and high contrast do not establish WCAG/GIGW certification. This is a student prototype, not an official MoES/INCOIS portal or endorsed product.
- Raster cells use the native regular grid without inventing fine-resolution structure. The map supports selecting profiles; PNG downloads remain backend scientific field plots, not screenshots of the entire interface.
- A browser-based visual audit could not be completed in this environment: the approved browser blocked localhost and local Chrome could not start due to an OS socket restriction. No claim of screenshot/pixel-match verification is made. Check the five screens on your machine before the presentation.

## Verification performed

- Fresh editable Python install and CPU PyTorch install; 106/106 existing Python tests passed (two dependency deprecation warnings).
- Frontend: 3/3 contract tests; TypeScript and production build passed.
- The launcher started FastAPI and Vite successfully; API health responded.
- New demo generated successfully. New endpoint smoke checks are recorded in V8_VERIFICATION.json.
- The CI workflow is provided but has not been run on GitHub here.

## Geographic attribution

Natural Earth, 1:110m Admin 0 countries (public domain).
Source: https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_admin_0_countries.geojson
The bundled GeoJSON keeps polygons intersecting the regional context window and country names; it does not include web tile imagery.
