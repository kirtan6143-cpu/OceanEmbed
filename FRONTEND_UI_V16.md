# OceanEmbed-NIO — Frontend UI V16

## Scope
This release changes the frontend presentation only. The Python backend, API routes, model logic, scientific calculations, data contracts, and backend dependencies are intentionally unchanged.

## Visual updates
- OceanEmbed brand mark from the supplied logo artwork is used in the application header, footer, hero landing screen, and favicon.
- Larken is the preferred font family (`Larken`, `Larken Regular`) with a safe editorial fallback stack. A licensed Larken webfont file can be dropped into `frontend/public/fonts/` later if an exact bundled webfont is required.
- The hero retains the original colorful `hero-ocean.png` artwork at full strength; only restrained edge/bottom readability gradients remain.
- Richer Abyssal Blue palette: `#03111F → #062A45 → #087EA4 → #5DE7FF`.
- More fluid hover, focus, entrance, and CTA transitions.

## 3D cutaway
- The previous empty/fragile WebGL cutaway was replaced with a more robust WebGL2 implementation.
- Correct column-major camera/projection math is used.
- Real thermal transect geometry is generated from the existing `/api/section` response.
- Existing bathymetry values drive the seafloor wedge; no new endpoint is required.
- Animated wave surface, thermal colour field, depth attenuation, terrain noise, transparent volume wall, A/B labels, and vertical exaggeration remain frontend-only.
- Pointer rotation and wheel zoom use damped interpolation for smoother motion.
- Renderer requests `high-performance` and adapts device-pixel ratio / water mesh quality when an NVIDIA GPU is detected. Balanced quality is used otherwise.

## Backend guarantee
No backend source file was intentionally modified in this release.
