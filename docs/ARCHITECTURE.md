# Implemented architecture and feasibility

## Flow

QC-reviewed surface fields → daily regional cube → training-only normalization and monthly prior → causal surface window → shared CNN → causal TCN → prior-conditioned direct head → 15-depth in-situ temperature → masked run → API/dashboard/export.

Input to the network is [batch, window, 21, height, width]: seven standardized surface variables, seven valid masks and seven normalized ages. Two shared spatial convolutions encode each day. Three left-padded temporal convolutions use dilations 1, 2, 4, giving a 15-frame temporal receptive field. No BatchNorm mixes frames. The decoder receives the latest encoding, 15 prior temperatures and four static fields (latitude, longitude, log bathymetry, wet mask). It predicts 15 residuals; the prior is added back.

The prior is a per-grid-cell, per-depth monthly mean fitted only on training dates. Interpolation uses actual month midpoints, including leap years. Statistics exclude stale inputs; missing targets do not enter the loss. Training uses equal weight per supported depth. Inference uses a three-cell spatial halo, removes the halo and restores unsupported/land/bottom masks.

## What is buildable?

The code path is executable on a CPU for small fixtures and supports a single CUDA GPU with automatic mixed precision. The supplied Colab notebook trains and saves to Drive. CPU inference uses saved weights, transforms and configuration without training again.

A regional pilot is feasible as an engineering project; useful reconstruction skill is an empirical question. Surface fields do not uniquely determine the ocean interior. Training against GLORYS can learn that reference's structure and errors. Argo held out from this neural network may still have been assimilated into GLORYS, so model holdout is not automatically independent of the teacher.

The limiting steps are aligned source coverage, source-specific QC and time windows, memory during preparation, sparse deep observations and honest evaluation. A working dashboard does not resolve those.

## Evaluation sequence

1. Check a synthetic run, loss gradients, temporal causality and tiled/full inference agreement.
2. Freeze chronological train/validation/calibration/test boundaries; keep windows inside partitions and apply the configured embargo.
3. Train the monthly prior, pointwise ridge baseline, a non-temporal CNN (temporal: false), and the CNN+TCN.
4. Select settings using validation only. Training's validation loss uses fixed crops; use full-grid validation inference before selection.
5. Match calibration Argo profiles to calibration runs. Float hash groups reserve a distinct subset for calibration.
6. Freeze the model and interval method, then evaluate later test dates and distinct test floats. Report per-depth support and errors.
7. Treat final-test results as a report, not another tuning signal.

The same float may provide correlated profiles; simple conformal exchangeability does not follow from float separation alone. The current interval is a constant-width simultaneous absolute-error interval over complete 10–1000 m profiles. Coverage is audited, never promised. It is not the guide's optional learned normalized scale head or conditional/local uncertainty model.

## Diagnostics

D26 uses the first contiguous surface-connected 26°C crossing; cold surface gives zero; unbracketed/missing support remains unavailable. TCHP integrates the warm layer using fixed density 1025 kg/m³ and heat capacity 3990 J/(kg K), reporting kJ/cm². MLD-T is a 0.2°C decline from the 10 m reference and is not density-defined MLD.

Events require strictly above-threshold temperature for five or more consecutive daily records with valid baseline. Missing days break runs, and short gaps are not merged. Categories use the maximum anomaly-to-threshold-anomaly ratio. This is a conservative retrospective detector, not a full reference implementation with all gap/edge conventions or a cyclone intensity forecast.

