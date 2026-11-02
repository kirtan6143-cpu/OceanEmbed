"""Three-state reliability gate: Supported / Caution / Abstain.

This is deliberately separate from the prediction and from the uncertainty
interval, per the specification's rule that these are three distinct outputs.
A reliability state says whether the estimate rests on adequate support --
it is NOT a danger level, NOT a confidence score, and it never changes a
scientific severity class (a marine-heatwave category is computed from
temperature, not from how trustworthy that temperature is).

Rules are explicit, declared up front, and evaluated in fixed precedence so
the same inputs always produce the same state:

  ABSTAIN   structural absence of support. No estimate should be believed:
            non-finite value, dry/land cell, depth below the seabed, or the
            declared valid-depth support mask says this level is unsupported.
            Returns the state plus a machine-readable reason code.

  CAUTION   an estimate exists but a declared precondition for trusting it is
            not met: stale surface inputs (age beyond max_age_hours), partial
            channel coverage, or the point sits within edge_cells of the
            domain boundary where the CNN receptive field is truncated.

  SUPPORTED all checks pass. Note this still does not promise calibrated
            coverage unless the run actually carries calibrated intervals --
            calibration_applies is reported separately for exactly that
            reason, so the UI can distinguish "supported" from "supported
            AND covered by a calibrated interval".

Thresholds are declared here rather than inferred at request time, and are
echoed in every payload so a reader can see what produced a state.
"""

import numpy as np

from .contracts import DEPTHS

SUPPORTED = "Supported"
CAUTION = "Caution"
ABSTAIN = "Abstain"

# Declared thresholds. Changing these changes published states, so they are
# versioned: bump when a rule's meaning changes so cached payloads are not
# silently mixed with new ones.
GATE_VERSION = 1
DEFAULT_MAX_AGE_HOURS = 48.0
DEFAULT_EDGE_CELLS = 3  # matches the inference halo / CNN receptive-field radius

REASONS = {
    "no_value": "No finite estimate at this cell and depth",
    "dry_cell": "Land or dry cell",
    "below_seabed": "Depth is below the seabed here",
    "unsupported_depth": "Declared valid-depth support does not reach this level",
    "stale_inputs": "Surface inputs older than the declared freshness limit",
    "partial_inputs": "One or more surface channels missing for this cell",
    "domain_edge": "Within the truncated-receptive-field margin at the domain edge",
    "ok": "Input coverage, freshness and depth support all within declared limits",
}


def thresholds(max_age_hours=DEFAULT_MAX_AGE_HOURS, edge_cells=DEFAULT_EDGE_CELLS):
    """The declared rule set, echoed into payloads so states are auditable."""
    return {
        "gate_version": GATE_VERSION,
        "max_age_hours": float(max_age_hours),
        "edge_cells": int(edge_cells),
        "states": [SUPPORTED, CAUTION, ABSTAIN],
        "note": (
            "Reliability describes support for the estimate, not danger level "
            "and not calibrated coverage. Calibration is reported separately."
        ),
    }


def _edge_mask(shape, edge_cells):
    """True where a cell lies within edge_cells of the array boundary."""
    ny, nx = shape
    mask = np.zeros(shape, bool)
    if edge_cells <= 0:
        return mask
    k = min(edge_cells, ny, nx)
    mask[:k, :] = True
    mask[-k:, :] = True
    mask[:, :k] = True
    mask[:, -k:] = True
    return mask


def field_states(
    values,
    bathymetry=None,
    depth=None,
    age_hours=None,
    support=None,
    max_age_hours=DEFAULT_MAX_AGE_HOURS,
    edge_cells=DEFAULT_EDGE_CELLS,
):
    """Per-cell states for one 2D slice at one depth.

    values       [lat, lon] estimate at this depth.
    bathymetry   [lat, lon] positive-down seabed depth in metres, or None.
    depth        the scalar depth of this slice, in metres.
    age_hours    [channel, lat, lon] source age, or None if the run omits it.
    support      [lat, lon] declared valid-depth support (truthy = supported).

    Returns an integer code array (0 Supported, 1 Caution, 2 Abstain) plus a
    parallel reason-code array, both JSON-friendly via codes()/reasons().
    """
    if max_age_hours <= 0:
        raise ValueError("max_age_hours must be positive")
    if edge_cells < 0:
        raise ValueError("edge_cells must be non-negative")
    v = np.asarray(values, float)
    if v.ndim != 2:
        raise ValueError("field_states expects a single [lat, lon] slice")
    if support is not None and np.asarray(support).shape != v.shape:
        raise ValueError("support must have the same [lat, lon] shape as values")
    if bathymetry is not None and np.asarray(bathymetry).shape != v.shape:
        raise ValueError("bathymetry must have the same [lat, lon] shape as values")
    if age_hours is not None:
        a_shape = np.asarray(age_hours).shape
        if a_shape != v.shape and (len(a_shape) != 3 or a_shape[1:] != v.shape):
            raise ValueError(
                "age_hours must be [lat, lon] or [channel, lat, lon] matching values"
            )
    state = np.zeros(v.shape, dtype=np.int8)  # default Supported
    reason = np.full(v.shape, "ok", dtype=object)

    # --- Caution layer first, so Abstain can overwrite it (fixed precedence).
    if age_hours is not None:
        a = np.asarray(age_hours, float)
        if a.ndim == 3:
            # Any channel missing entirely -> partial inputs.
            missing = ~np.isfinite(a)
            partial = missing.any(axis=0)
            # A cell where every channel is missing is all-NaN; nanmax would
            # warn and return NaN there. That cell is already flagged partial,
            # so compute the max only over cells that have at least one finite
            # channel and leave the rest as NaN without the warning.
            usable = (~missing).any(axis=0)
            oldest = np.full(a.shape[1:], np.nan, float)
            if usable.any():
                filled = np.where(missing, -np.inf, a)
                oldest[usable] = np.max(filled, axis=0)[usable]
        else:
            partial = ~np.isfinite(a)
            oldest = a
        stale = np.isfinite(oldest) & (oldest > float(max_age_hours))
        state[stale] = 1
        reason[stale] = "stale_inputs"
        state[partial] = 1
        reason[partial] = "partial_inputs"

    edge = _edge_mask(v.shape, edge_cells)
    fresh_enough = state == 0
    state[edge & fresh_enough] = 1
    reason[edge & fresh_enough] = "domain_edge"

    # --- Abstain layer: structural absence of support overrides everything.
    if support is not None:
        unsupported = ~np.asarray(support).astype(bool)
        state[unsupported] = 2
        reason[unsupported] = "unsupported_depth"

    # A missing value is only reported as "no_value" when nothing more
    # specific explains it. Structural reasons are assigned after, so a cell
    # below the seabed reads "below_seabed" (which says why there is no value)
    # rather than the less informative "no_value".
    missing_value = ~np.isfinite(v)
    state[missing_value] = 2
    reason[missing_value] = "no_value"

    if bathymetry is not None and depth is not None:
        b = np.asarray(bathymetry, float)
        below = np.isfinite(b) & (b > 0) & (float(depth) > b)
        state[below] = 2
        reason[below] = "below_seabed"
        dry = ~np.isfinite(b) | (b <= 0)
        state[dry] = 2
        reason[dry] = "dry_cell"
    return state, reason


def codes():
    """Integer code -> state name, for compact transport."""
    return {0: SUPPORTED, 1: CAUTION, 2: ABSTAIN}


def summarize(state):
    """Counts and wet-domain fractions, for a headline readout."""
    s = np.asarray(state)
    total = int(s.size)
    counts = {
        SUPPORTED: int((s == 0).sum()),
        CAUTION: int((s == 1).sum()),
        ABSTAIN: int((s == 2).sum()),
    }
    evaluated = counts[SUPPORTED] + counts[CAUTION]
    return {
        "counts": counts,
        "total_cells": total,
        "evaluated_cells": evaluated,
        "supported_fraction_of_evaluated": (
            counts[SUPPORTED] / evaluated if evaluated else None
        ),
    }


def profile_state(
    temperature,
    depths=None,
    bathymetry=None,
    age_hours=None,
    support=None,
    max_age_hours=DEFAULT_MAX_AGE_HOURS,
    calibrated=False,
    at_domain_edge=False,
    lower=None,
    upper=None,
):
    """One state per depth for a single profile, plus an overall summary.

    The overall state is the worst state across depths that carry an estimate,
    so a profile whose deep levels abstain is not advertised as Supported.

    at_domain_edge  whether this profile's [lat, lon] cell falls within
                    edge_cells of the domain boundary (see _edge_mask).
                    Previously this function had no domain-edge concept at
                    all, while field_states did -- so the same physical
                    cell/depth could report Supported from the profile
                    endpoint and Caution/domain_edge from the map endpoint
                    for the identical point (audit finding B07). Reproduced
                    directly before fixing: calling both functions on the
                    same edge cell returned different states.
    """
    if max_age_hours <= 0:
        raise ValueError("max_age_hours must be positive")
    t = np.asarray(temperature, float)
    z = np.asarray(DEPTHS if depths is None else depths, float)
    if t.shape != z.shape:
        raise ValueError("temperature and depths must align")
    if support is not None and np.asarray(support).reshape(-1).shape != z.shape:
        raise ValueError("support must have one entry per depth")
    if age_hours is not None and np.asarray(age_hours).ndim not in (0, 1):
        raise ValueError("age_hours must be a scalar or one entry per channel")

    per_depth = []
    oldest = None
    partial = False
    if age_hours is not None:
        a = np.asarray(age_hours, float)
        finite = np.isfinite(a)
        partial = bool((~finite).any())
        oldest = float(np.max(a[finite])) if finite.any() else None

    # Bathymetry status resolved once, matching field_states' rule exactly:
    # unknown (non-finite) bathymetry is dry_cell, same as bathymetry<=0 --
    # NOT "skip the check", which is what this did before. Reproduced
    # directly: a finite temperature with bathymetry=NaN previously passed
    # through as Supported here while field_states would Abstain the same
    # cell as dry_cell (audit finding B08).
    bathy_known = bathymetry is not None
    bathy_val = float(bathymetry) if bathy_known else None
    bathy_dry = (not bathy_known) or (not np.isfinite(bathy_val)) or (bathy_val <= 0)

    for i, zi in enumerate(z):
        code, why = 0, "ok"
        if oldest is not None and oldest > float(max_age_hours):
            code, why = 1, "stale_inputs"
        if partial:
            code, why = 1, "partial_inputs"
        if at_domain_edge and code == 0:
            code, why = 1, "domain_edge"
        if support is not None and not bool(np.asarray(support).reshape(-1)[i]):
            code, why = 2, "unsupported_depth"
        # As in field_states: assign "no_value" first, then let a structural
        # reason override it, so the reported reason explains the absence.
        if not np.isfinite(t[i]):
            code, why = 2, "no_value"
        if bathy_known:
            if bathy_dry:
                code, why = 2, "dry_cell"
            elif zi > bathy_val:
                code, why = 2, "below_seabed"
        per_depth.append(
            {
                "depth": float(zi),
                "state": codes()[code],
                "reason_code": why,
                "reason": REASONS[why],
            }
        )

    # The overall state is the worst state among depths that actually carry an
    # estimate. Abstained depths are excluded deliberately: a profile in 400 m
    # water has no 500/700/1000 m values by physical necessity, and marking the
    # whole profile Abstain for that reason would make every shelf profile look
    # broken. The count of reporting depths is published alongside so partial
    # vertical coverage stays visible rather than hidden behind one word.
    live = [d for d in per_depth if d["state"] != ABSTAIN]
    if not live:
        overall = ABSTAIN
    elif any(d["state"] == CAUTION for d in live):
        overall = CAUTION
    else:
        overall = SUPPORTED
    # Reproduced directly (this session): the previous check was
    # `bool(calibrated) and overall != ABSTAIN`, where `calibrated` was a
    # dataset-level boolean set by the caller from `"lower" in ds and
    # "upper" in ds` -- true if the VARIABLES exist anywhere in the run,
    # regardless of whether THIS profile's actual bound values are finite
    # at any depth. A profile whose `lower`/`upper` are both all-NaN (e.g.
    # entirely outside the calibrated depth range, or from a run segment
    # calibration wasn't fitted on) still reported calibration_applies=true.
    # Fixed to check the real values: calibration only applies at depths
    # where BOTH bounds are finite, and the flag is true only if at least
    # one such depth exists. `calibrated_depths` is reported alongside so a
    # partially-calibrated profile is visible rather than collapsed to one
    # boolean the way `depths_reporting` already does for reliability.
    if lower is not None and upper is not None:
        lower_arr = np.asarray(lower).reshape(-1)
        upper_arr = np.asarray(upper).reshape(-1)
        finite_bounds = np.isfinite(lower_arr) & np.isfinite(upper_arr)
        calibrated_depths = int(finite_bounds.sum())
    else:
        # No bound arrays supplied at all: fall back to the caller's
        # coarser boolean rather than assuming zero, so existing callers
        # that haven't been updated to pass lower/upper yet don't regress
        # to "never calibrated".
        calibrated_depths = len(per_depth) if calibrated else 0
    return {
        "overall": overall,
        "depths_reporting": len(live),
        "depths_total": len(per_depth),
        "per_depth": per_depth,
        "oldest_input_hours": oldest,
        # Deliberately separate from the state: a Supported point without a
        # calibrated run still has no validated coverage guarantee.
        "calibration_applies": calibrated_depths > 0 and overall != ABSTAIN,
        "calibrated_depths": calibrated_depths,
        "thresholds": thresholds(max_age_hours=max_age_hours),
    }
