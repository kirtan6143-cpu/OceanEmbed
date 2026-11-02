# OceanEmbed-NIO — Abyssal Blue + GPU 3D Frontend Upgrade

## Backend contract

**UNCHANGED.** No Python files, FastAPI routes, model code, scientific calculations, data preparation, API paths, or backend dependencies were modified.

## Frontend changes

- Replaced the SVG/pseudo-3D cutaway renderer with a direct WebGL2 GPU renderer.
- The renderer consumes the existing `section` object returned by the existing `/api/section` request.
- Added interactive orbit rotation, inertial camera movement, zoom, animated ocean surface, thermal field shading, procedural rock shading, seafloor extrusion, depth labels, A/B labels, and vertical exaggeration control.
- Applied the shared Abyssal Blue palette across the application and landing page:
  - `#03111F`
  - `#062A45`
  - `#087EA4`
  - `#5DE7FF`
- No new runtime packages are required for the 3D renderer; it uses browser WebGL2 directly.

## Run

Use the project's existing `start.py` workflow. The backend remains the same.
