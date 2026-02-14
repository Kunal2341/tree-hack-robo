"""
Comprehensive tests for the Robot Scoring System (src/score.py).
"""

import math
import pytest

from src.score import (
    score_stability,
    score_uprightness,
    score_grounding,
    terrain_multiplier,
    compute_score,
    score_label,
    _clamp,
    TERRAIN_MULTIPLIERS,
    MAX_DISPLACEMENT,
    MAX_HEIGHT_DEVIATION,
    IDEAL_HEIGHT,
    WEIGHT_STABILITY,
    WEIGHT_UPRIGHTNESS,
    WEIGHT_GROUNDING,
)


# ---------------------------------------------------------------------------
# _clamp
# ---------------------------------------------------------------------------
class TestClamp:
    def test_within_range(self):
        assert _clamp(50.0) == 50.0

    def test_below_min(self):
        assert _clamp(-10.0) == 0.0

    def test_above_max(self):
        assert _clamp(150.0) == 100.0

    def test_at_boundaries(self):
        assert _clamp(0.0) == 0.0
        assert _clamp(100.0) == 100.0

    def test_custom_bounds(self):
        assert _clamp(5.0, 0.0, 10.0) == 5.0
        assert _clamp(-1.0, 0.0, 10.0) == 0.0
        assert _clamp(15.0, 0.0, 10.0) == 10.0


# ---------------------------------------------------------------------------
# score_stability
# ---------------------------------------------------------------------------
class TestScoreStability:
    def test_zero_displacement(self):
        """No displacement → perfect score of 100."""
        assert score_stability(0.0) == 100.0

    def test_small_displacement(self):
        """Small displacement should give a high score."""
        s = score_stability(0.1)
        assert 90.0 < s <= 100.0

    def test_moderate_displacement(self):
        """Moderate displacement should give a mid-range score."""
        s = score_stability(MAX_DISPLACEMENT / 2)
        assert 10.0 < s < 60.0

    def test_large_displacement(self):
        """Large displacement (at MAX) should give near-zero score."""
        s = score_stability(MAX_DISPLACEMENT)
        assert s < 10.0

    def test_very_large_displacement(self):
        """Way beyond MAX should be essentially zero."""
        s = score_stability(100.0)
        assert s < 1.0

    def test_negative_displacement_treated_as_zero(self):
        """Negative displacement should be clamped to zero."""
        assert score_stability(-5.0) == 100.0

    def test_returns_rounded_float(self):
        """Score should be rounded to 2 decimal places."""
        s = score_stability(1.23456)
        assert s == round(s, 2)

    def test_exponential_decay(self):
        """Score should decrease exponentially — half displacement > half score."""
        s_full = score_stability(0.0)
        s_half = score_stability(MAX_DISPLACEMENT / 2)
        s_max = score_stability(MAX_DISPLACEMENT)
        assert s_full > s_half > s_max


# ---------------------------------------------------------------------------
# score_uprightness
# ---------------------------------------------------------------------------
class TestScoreUprightness:
    def test_perfectly_upright(self):
        """tilt_cos=1 → 100."""
        assert score_uprightness(1.0) == 100.0

    def test_completely_fallen(self):
        """tilt_cos=0 → 0."""
        assert score_uprightness(0.0) == 0.0

    def test_inverted(self):
        """tilt_cos<0 (upside down) → 0."""
        assert score_uprightness(-0.5) == 0.0
        assert score_uprightness(-1.0) == 0.0

    def test_above_one(self):
        """tilt_cos>1 (should not happen but handle gracefully) → 100."""
        assert score_uprightness(1.5) == 100.0

    def test_halfway(self):
        """tilt_cos=0.5 → 50."""
        assert score_uprightness(0.5) == 50.0

    def test_linear_mapping(self):
        """Score should be linearly proportional to tilt_cos."""
        for tilt in [0.0, 0.25, 0.5, 0.75, 1.0]:
            expected = round(tilt * 100.0, 2)
            assert score_uprightness(tilt) == expected


# ---------------------------------------------------------------------------
# score_grounding
# ---------------------------------------------------------------------------
class TestScoreGrounding:
    def test_at_ideal_height(self):
        """At spawn height → 100."""
        assert score_grounding(IDEAL_HEIGHT) == 100.0

    def test_slightly_above(self):
        """Slightly above ideal → high score."""
        s = score_grounding(IDEAL_HEIGHT + 0.1)
        assert 90.0 < s <= 100.0

    def test_slightly_below(self):
        """Slightly below ideal → high score."""
        s = score_grounding(IDEAL_HEIGHT - 0.1)
        assert 90.0 < s <= 100.0

    def test_max_deviation(self):
        """At max deviation → 0."""
        assert score_grounding(IDEAL_HEIGHT + MAX_HEIGHT_DEVIATION) == 0.0
        assert score_grounding(IDEAL_HEIGHT - MAX_HEIGHT_DEVIATION) == 0.0

    def test_beyond_max_deviation(self):
        """Beyond max deviation → 0."""
        assert score_grounding(IDEAL_HEIGHT + MAX_HEIGHT_DEVIATION + 1.0) == 0.0

    def test_custom_spawn_height(self):
        """Custom spawn height should shift the ideal."""
        assert score_grounding(2.0, spawn_height=2.0) == 100.0
        s = score_grounding(2.5, spawn_height=2.0)
        assert 80.0 < s < 100.0

    def test_negative_z(self):
        """Robot fell through floor → penalised based on deviation."""
        s = score_grounding(-2.0)
        # deviation = abs(-2.0 - 1.0) = 3.0, less than MAX_HEIGHT_DEVIATION=5.0
        expected = round(100.0 * (1.0 - 3.0 / MAX_HEIGHT_DEVIATION), 2)
        assert s == expected


# ---------------------------------------------------------------------------
# terrain_multiplier
# ---------------------------------------------------------------------------
class TestTerrainMultiplier:
    def test_flat(self):
        assert terrain_multiplier("flat") == 1.0

    def test_slope(self):
        assert terrain_multiplier("slope") == 1.15

    def test_stairs(self):
        assert terrain_multiplier("stairs") == 1.25

    def test_uneven(self):
        assert terrain_multiplier("uneven") == 1.30

    def test_unknown_terrain(self):
        """Unknown terrain defaults to 1.0."""
        assert terrain_multiplier("lava") == 1.0

    def test_none_terrain(self):
        """None terrain defaults to flat (1.0)."""
        assert terrain_multiplier(None) == 1.0

    def test_case_insensitive(self):
        """Should be case insensitive."""
        assert terrain_multiplier("FLAT") == 1.0
        assert terrain_multiplier("Slope") == 1.15

    def test_all_multipliers_greater_than_or_equal_to_one(self):
        """All terrain multipliers should be >= 1.0."""
        for mode, mult in TERRAIN_MULTIPLIERS.items():
            assert mult >= 1.0, f"{mode} multiplier {mult} < 1.0"


# ---------------------------------------------------------------------------
# compute_score (integration of components)
# ---------------------------------------------------------------------------
class TestComputeScore:
    @pytest.fixture
    def perfect_metrics(self):
        """Metrics for a perfectly stable, upright robot on flat ground."""
        return {
            "displacement": 0.0,
            "tilt_cos": 1.0,
            "final_position": {"x": 0.0, "y": 0.0, "z": IDEAL_HEIGHT},
            "terrain_mode": "flat",
        }

    @pytest.fixture
    def terrible_metrics(self):
        """Metrics for a robot that fell over and flew away."""
        return {
            "displacement": 50.0,
            "tilt_cos": -0.5,
            "final_position": {"x": 30.0, "y": 20.0, "z": -10.0},
            "terrain_mode": "flat",
        }

    def test_perfect_score_flat(self, perfect_metrics):
        result = compute_score(perfect_metrics)
        assert result["final_score"] == 100.0
        assert result["stability_score"] == 100.0
        assert result["uprightness_score"] == 100.0
        assert result["grounding_score"] == 100.0
        assert result["terrain_multiplier"] == 1.0
        assert result["terrain_mode"] == "flat"

    def test_perfect_score_uneven(self, perfect_metrics):
        """Perfect metrics on uneven terrain should get terrain bonus, capped at 100."""
        result = compute_score(perfect_metrics, terrain_mode="uneven")
        assert result["final_score"] == 100.0  # Capped at 100
        assert result["terrain_multiplier"] == 1.30
        assert result["terrain_mode"] == "uneven"

    def test_terrible_score(self, terrible_metrics):
        result = compute_score(terrible_metrics)
        assert result["final_score"] < 5.0
        assert result["stability_score"] < 1.0
        assert result["uprightness_score"] == 0.0
        assert result["grounding_score"] == 0.0

    def test_returns_all_keys(self, perfect_metrics):
        result = compute_score(perfect_metrics)
        expected_keys = {
            "stability_score",
            "uprightness_score",
            "grounding_score",
            "weighted_score",
            "terrain_multiplier",
            "terrain_mode",
            "final_score",
        }
        assert set(result.keys()) == expected_keys

    def test_terrain_override(self, perfect_metrics):
        """terrain_mode parameter overrides metrics['terrain_mode']."""
        result = compute_score(perfect_metrics, terrain_mode="stairs")
        assert result["terrain_mode"] == "stairs"
        assert result["terrain_multiplier"] == 1.25

    def test_missing_terrain_defaults_to_flat(self):
        metrics = {
            "displacement": 0.5,
            "tilt_cos": 0.9,
            "final_position": {"x": 0.0, "y": 0.0, "z": 1.0},
        }
        result = compute_score(metrics)
        assert result["terrain_mode"] == "flat"

    def test_none_metrics_raises(self):
        with pytest.raises(ValueError, match="metrics must be a non-empty dict"):
            compute_score(None)

    def test_empty_metrics_raises(self):
        with pytest.raises(ValueError, match="metrics must be a non-empty dict"):
            compute_score({})

    def test_non_dict_metrics_raises(self):
        with pytest.raises(ValueError):
            compute_score("not a dict")

    def test_missing_fields_use_defaults(self):
        """Missing fields should default to 0.0, not crash."""
        result = compute_score({"displacement": 1.0})
        assert "final_score" in result
        assert result["final_score"] >= 0.0

    def test_score_bounded_zero_to_hundred(self, perfect_metrics, terrible_metrics):
        """Score should always be between 0 and 100."""
        for metrics in [perfect_metrics, terrible_metrics]:
            for terrain in ["flat", "slope", "stairs", "uneven"]:
                result = compute_score(metrics, terrain_mode=terrain)
                assert 0.0 <= result["final_score"] <= 100.0

    def test_harder_terrain_equal_or_higher_score(self):
        """Same metrics on harder terrain should produce equal or higher final score."""
        metrics = {
            "displacement": 0.5,
            "tilt_cos": 0.85,
            "final_position": {"x": 0.0, "y": 0.0, "z": 1.0},
        }
        scores = {}
        for terrain in ["flat", "slope", "stairs", "uneven"]:
            scores[terrain] = compute_score(metrics, terrain_mode=terrain)["final_score"]
        assert scores["flat"] <= scores["slope"]
        assert scores["slope"] <= scores["stairs"]
        assert scores["stairs"] <= scores["uneven"]

    def test_weights_sum_to_one(self):
        """Component weights must sum to 1.0 for correct scoring."""
        total = WEIGHT_STABILITY + WEIGHT_UPRIGHTNESS + WEIGHT_GROUNDING
        assert abs(total - 1.0) < 1e-9

    def test_final_score_rounded_to_one_decimal(self, perfect_metrics):
        result = compute_score(perfect_metrics)
        assert result["final_score"] == round(result["final_score"], 1)

    def test_weighted_score_correct(self):
        """Verify weighted_score is properly calculated from components."""
        metrics = {
            "displacement": 0.0,  # → stability 100
            "tilt_cos": 0.5,      # → uprightness 50
            "final_position": {"x": 0, "y": 0, "z": IDEAL_HEIGHT},  # → grounding 100
        }
        result = compute_score(metrics, terrain_mode="flat")
        expected_weighted = (
            WEIGHT_STABILITY * 100.0
            + WEIGHT_UPRIGHTNESS * 50.0
            + WEIGHT_GROUNDING * 100.0
        )
        assert abs(result["weighted_score"] - round(expected_weighted, 2)) < 0.01


# ---------------------------------------------------------------------------
# score_label
# ---------------------------------------------------------------------------
class TestScoreLabel:
    def test_excellent(self):
        assert score_label(95.0) == "Excellent"
        assert score_label(90.0) == "Excellent"

    def test_great(self):
        assert score_label(89.9) == "Great"
        assert score_label(75.0) == "Great"

    def test_good(self):
        assert score_label(74.9) == "Good"
        assert score_label(60.0) == "Good"

    def test_fair(self):
        assert score_label(59.9) == "Fair"
        assert score_label(40.0) == "Fair"

    def test_poor(self):
        assert score_label(39.9) == "Poor"
        assert score_label(20.0) == "Poor"

    def test_unstable(self):
        assert score_label(19.9) == "Unstable"
        assert score_label(0.0) == "Unstable"

    def test_perfect_100(self):
        assert score_label(100.0) == "Excellent"

    def test_negative(self):
        """Negative scores should still return a label."""
        assert score_label(-10.0) == "Unstable"
