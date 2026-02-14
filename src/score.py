"""
Robot Scoring System — compute composite scores from simulation metrics.

Score components (all normalized to 0–100):
  - Stability  : how little the robot displaced (low displacement = high score)
  - Uprightness: how upright the robot remained (tilt_cos near 1 = high score)
  - Grounding  : how close to ground level the robot ended up (penalise flying/falling)
  - Terrain bonus: harder terrains earn a multiplier

Final score = weighted_average(components) * terrain_multiplier, capped at 100.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# Terrain difficulty multipliers
# ---------------------------------------------------------------------------
TERRAIN_MULTIPLIERS: dict[str, float] = {
    "flat": 1.0,
    "slope": 1.15,
    "stairs": 1.25,
    "uneven": 1.30,
}

# ---------------------------------------------------------------------------
# Component weights (must sum to 1.0)
# ---------------------------------------------------------------------------
WEIGHT_STABILITY = 0.40
WEIGHT_UPRIGHTNESS = 0.35
WEIGHT_GROUNDING = 0.25

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
# Displacement beyond which stability score is 0
MAX_DISPLACEMENT = 10.0  # metres
# Height beyond which grounding penalty kicks in fully
MAX_HEIGHT_DEVIATION = 5.0  # metres from spawn-height (~1m)
IDEAL_HEIGHT = 1.0  # approximate spawn height on flat terrain


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def score_stability(displacement: float) -> float:
    """
    Score 0–100 based on displacement from start.
    0 displacement → 100, MAX_DISPLACEMENT or more → 0.
    Uses an exponential decay for smooth falloff.
    """
    if displacement < 0:
        displacement = 0.0
    raw = 100.0 * math.exp(-3.0 * displacement / MAX_DISPLACEMENT)
    return round(_clamp(raw), 2)


def score_uprightness(tilt_cos: float) -> float:
    """
    Score 0–100 based on tilt_cos (cosine of angle from vertical).
    tilt_cos=1 (perfectly upright) → 100
    tilt_cos<=0 (lying flat or inverted) → 0
    Linear mapping between 0 and 1.
    """
    normalised = max(0.0, min(1.0, tilt_cos))
    return round(normalised * 100.0, 2)


def score_grounding(final_z: float, spawn_height: float = IDEAL_HEIGHT) -> float:
    """
    Score 0–100 based on how close to the expected height the robot ended.
    Small deviations are OK; large ones (fell through floor or launched skyward) penalised.
    """
    deviation = abs(final_z - spawn_height)
    if deviation > MAX_HEIGHT_DEVIATION:
        return 0.0
    raw = 100.0 * (1.0 - deviation / MAX_HEIGHT_DEVIATION)
    return round(_clamp(raw), 2)


def terrain_multiplier(terrain_mode: str) -> float:
    """Return the multiplier for the given terrain mode."""
    return TERRAIN_MULTIPLIERS.get((terrain_mode or "flat").lower(), 1.0)


def compute_score(metrics: dict, terrain_mode: str | None = None) -> dict:
    """
    Compute a composite robot score from simulation metrics.

    Parameters
    ----------
    metrics : dict
        Must contain keys: displacement, tilt_cos, final_position (with 'z').
        Typically the dict returned by simulate_urdf().
    terrain_mode : str | None
        Override terrain; defaults to metrics["terrain_mode"] if present.

    Returns
    -------
    dict with keys:
        stability_score, uprightness_score, grounding_score,
        weighted_score (before terrain), terrain_multiplier,
        terrain_mode, final_score (0–100, rounded to 1 decimal).
    """
    if not metrics or not isinstance(metrics, dict):
        raise ValueError("metrics must be a non-empty dict")

    displacement = metrics.get("displacement", 0.0)
    tilt_cos = metrics.get("tilt_cos", 0.0)
    final_pos = metrics.get("final_position", {})
    final_z = final_pos.get("z", 0.0) if isinstance(final_pos, dict) else 0.0

    t_mode = terrain_mode or metrics.get("terrain_mode", "flat")
    t_mult = terrain_multiplier(t_mode)

    s_stability = score_stability(displacement)
    s_upright = score_uprightness(tilt_cos)
    s_ground = score_grounding(final_z)

    weighted = (
        WEIGHT_STABILITY * s_stability
        + WEIGHT_UPRIGHTNESS * s_upright
        + WEIGHT_GROUNDING * s_ground
    )

    final = _clamp(weighted * t_mult, 0.0, 100.0)

    return {
        "stability_score": s_stability,
        "uprightness_score": s_upright,
        "grounding_score": s_ground,
        "weighted_score": round(weighted, 2),
        "terrain_multiplier": t_mult,
        "terrain_mode": t_mode,
        "final_score": round(final, 1),
    }


def score_label(final_score: float) -> str:
    """Human-friendly label for a score."""
    if final_score >= 90:
        return "Excellent"
    if final_score >= 75:
        return "Great"
    if final_score >= 60:
        return "Good"
    if final_score >= 40:
        return "Fair"
    if final_score >= 20:
        return "Poor"
    return "Unstable"
