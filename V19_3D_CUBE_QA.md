# OceanEmbed-NIO V19 — 3D Thermal Cube QA

## Scope
Frontend-only change. The existing `/section` API contract is consumed as-is.

## 3D cutaway
- Three visible cube faces: front thermal field, B-end thermal profile, surface thermal face.
- Heat layers only; no procedural rock/seafloor texture is rendered in the cutaway.
- Front layers use backend `z` values and smooth horizontal SVG gradients whose stops are sourced from real adjacent samples.
- Hover exposes backend-derived distance, depth interval, latitude, longitude, bathymetry, grid position, variable and sampling contract.
- Missing/non-finite samples are skipped rather than allowed to collapse the scene.
- Degenerate/empty data receives safe fallbacks so the component does not throw during render.
- Tooltip positioning is clamped to the cutaway viewport.
- Rendering is SVG-based for deterministic browser compatibility and avoids a GPU/WebGL blank-canvas failure mode.

## Backend protection
No files under `src/oceanembed/` were modified for this release. No API endpoint, model, data processing, dataset, or Python dependency was changed.

## QA performed
- TypeScript/TSX parser diagnostics for `frontend/src/Cutaway.tsx`: 0.
- Python syntax compilation for `src/oceanembed`: PASS.
- Backend file comparison against V18 source: no backend source differences.
- Full frontend production build could not be run in the provided environment because its installed `node_modules` is incomplete and registry installation timed out. This is an environment/dependency-cache limitation, not a reported source syntax failure.
