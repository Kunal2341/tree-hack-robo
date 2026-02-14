"""
Tests for leaderboard API endpoints in web/app.py.
Uses Flask test client — no actual LLM or PyBullet needed.
"""

import json
import time
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure project root is on path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from web.app import app, _history, _leaderboard, _save_history, _save_leaderboard


@pytest.fixture(autouse=True)
def reset_state():
    """Reset in-memory state before each test."""
    _history.clear()
    _leaderboard.clear()
    yield
    _history.clear()
    _leaderboard.clear()


@pytest.fixture
def client():
    """Flask test client."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def sample_robot():
    """Add a sample robot to history and return its id."""
    robot_id = str(uuid.uuid4())
    _history[robot_id] = {
        "id": robot_id,
        "prompt": "A 4-legged dog robot",
        "urdf": "<robot name='test'><link name='base_link'/></robot>",
        "refined_from": None,
        "timestamp": time.time(),
    }
    return robot_id


@pytest.fixture
def sample_robot_2():
    """Add a second sample robot to history and return its id."""
    robot_id = str(uuid.uuid4())
    _history[robot_id] = {
        "id": robot_id,
        "prompt": "A hexapod insect",
        "urdf": "<robot name='hexapod'><link name='base_link'/></robot>",
        "refined_from": None,
        "timestamp": time.time(),
    }
    return robot_id


# ---------------------------------------------------------------------------
# GET /api/leaderboard
# ---------------------------------------------------------------------------
class TestGetLeaderboard:
    def test_empty_leaderboard(self, client):
        res = client.get("/api/leaderboard")
        assert res.status_code == 200
        data = res.get_json()
        assert data["leaderboard"] == []

    def test_returns_entries_sorted_by_score(self, client):
        _leaderboard.extend([
            {"id": "a", "robot_id": "r1", "prompt": "A", "terrain_mode": "flat",
             "final_score": 50.0, "label": "Fair", "stability_score": 50,
             "uprightness_score": 50, "grounding_score": 50, "timestamp": 1.0},
            {"id": "b", "robot_id": "r2", "prompt": "B", "terrain_mode": "flat",
             "final_score": 90.0, "label": "Excellent", "stability_score": 90,
             "uprightness_score": 90, "grounding_score": 90, "timestamp": 2.0},
            {"id": "c", "robot_id": "r3", "prompt": "C", "terrain_mode": "slope",
             "final_score": 70.0, "label": "Good", "stability_score": 70,
             "uprightness_score": 70, "grounding_score": 70, "timestamp": 3.0},
        ])
        res = client.get("/api/leaderboard")
        data = res.get_json()
        scores = [e["final_score"] for e in data["leaderboard"]]
        assert scores == [90.0, 70.0, 50.0]

    def test_filter_by_terrain(self, client):
        _leaderboard.extend([
            {"id": "a", "robot_id": "r1", "prompt": "A", "terrain_mode": "flat",
             "final_score": 80.0, "label": "Great", "stability_score": 80,
             "uprightness_score": 80, "grounding_score": 80, "timestamp": 1.0},
            {"id": "b", "robot_id": "r2", "prompt": "B", "terrain_mode": "stairs",
             "final_score": 60.0, "label": "Good", "stability_score": 60,
             "uprightness_score": 60, "grounding_score": 60, "timestamp": 2.0},
        ])
        res = client.get("/api/leaderboard?terrain_mode=flat")
        data = res.get_json()
        assert len(data["leaderboard"]) == 1
        assert data["leaderboard"][0]["terrain_mode"] == "flat"

    def test_filter_invalid_terrain_returns_all(self, client):
        _leaderboard.append(
            {"id": "a", "robot_id": "r1", "prompt": "A", "terrain_mode": "flat",
             "final_score": 50.0, "label": "Fair", "stability_score": 50,
             "uprightness_score": 50, "grounding_score": 50, "timestamp": 1.0}
        )
        res = client.get("/api/leaderboard?terrain_mode=lava")
        data = res.get_json()
        assert len(data["leaderboard"]) == 1  # No filter applied for invalid terrain


# ---------------------------------------------------------------------------
# POST /api/leaderboard/submit
# ---------------------------------------------------------------------------
class TestSubmitScore:
    def _mock_simulate_success(self, *args, **kwargs):
        """Mock simulate_urdf returning success with metrics."""
        return True, "", {
            "displacement": 0.3,
            "tilt_cos": 0.95,
            "final_position": {"x": 0.1, "y": 0.05, "z": 1.0},
            "terrain_mode": "flat",
            "distance_from_origin": 1.05,
            "is_upright": True,
            "sim_duration_s": 5.0,
        }

    def _mock_simulate_failure(self, *args, **kwargs):
        """Mock simulate_urdf returning failure."""
        return False, "Robot exploded", None

    @patch("web.app.simulate_urdf")
    @patch("web.app._save_leaderboard")
    def test_submit_success(self, mock_save, mock_sim, client, sample_robot):
        mock_sim.side_effect = self._mock_simulate_success
        res = client.post(
            "/api/leaderboard/submit",
            json={"robot_id": sample_robot, "terrain_mode": "flat"},
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert "entry" in data
        assert "score" in data
        assert data["entry"]["robot_id"] == sample_robot
        assert data["entry"]["terrain_mode"] == "flat"
        assert 0 <= data["entry"]["final_score"] <= 100
        assert len(_leaderboard) == 1

    @patch("web.app.simulate_urdf")
    def test_submit_missing_robot_id(self, mock_sim, client):
        res = client.post(
            "/api/leaderboard/submit",
            json={"terrain_mode": "flat"},
        )
        assert res.status_code == 400
        data = res.get_json()
        assert "error" in data

    @patch("web.app.simulate_urdf")
    def test_submit_invalid_robot_id(self, mock_sim, client):
        res = client.post(
            "/api/leaderboard/submit",
            json={"robot_id": "nonexistent", "terrain_mode": "flat"},
        )
        assert res.status_code == 400

    @patch("web.app.simulate_urdf")
    def test_submit_simulation_failure(self, mock_sim, client, sample_robot):
        mock_sim.side_effect = self._mock_simulate_failure
        res = client.post(
            "/api/leaderboard/submit",
            json={"robot_id": sample_robot, "terrain_mode": "flat"},
        )
        data = res.get_json()
        assert data["success"] is False
        assert len(_leaderboard) == 0

    @patch("web.app.simulate_urdf")
    @patch("web.app._save_leaderboard")
    def test_submit_replaces_lower_score(self, mock_save, mock_sim, client, sample_robot):
        """Submitting a higher score should replace the existing entry."""
        # First submission with lower score
        mock_sim.return_value = (True, "", {
            "displacement": 2.0,
            "tilt_cos": 0.7,
            "final_position": {"x": 0, "y": 0, "z": 1.0},
            "terrain_mode": "flat",
        })
        client.post(
            "/api/leaderboard/submit",
            json={"robot_id": sample_robot, "terrain_mode": "flat"},
        )
        first_score = _leaderboard[0]["final_score"]

        # Second submission with higher score
        mock_sim.return_value = (True, "", {
            "displacement": 0.0,
            "tilt_cos": 1.0,
            "final_position": {"x": 0, "y": 0, "z": 1.0},
            "terrain_mode": "flat",
        })
        client.post(
            "/api/leaderboard/submit",
            json={"robot_id": sample_robot, "terrain_mode": "flat"},
        )
        assert len(_leaderboard) == 1  # Still one entry
        assert _leaderboard[0]["final_score"] > first_score

    @patch("web.app.simulate_urdf")
    @patch("web.app._save_leaderboard")
    def test_submit_keeps_higher_score(self, mock_save, mock_sim, client, sample_robot):
        """Submitting a lower score should NOT replace the existing entry."""
        # First submission with high score
        mock_sim.return_value = (True, "", {
            "displacement": 0.0,
            "tilt_cos": 1.0,
            "final_position": {"x": 0, "y": 0, "z": 1.0},
            "terrain_mode": "flat",
        })
        client.post(
            "/api/leaderboard/submit",
            json={"robot_id": sample_robot, "terrain_mode": "flat"},
        )
        high_score = _leaderboard[0]["final_score"]

        # Second submission with lower score
        mock_sim.return_value = (True, "", {
            "displacement": 5.0,
            "tilt_cos": 0.3,
            "final_position": {"x": 0, "y": 0, "z": 1.0},
            "terrain_mode": "flat",
        })
        client.post(
            "/api/leaderboard/submit",
            json={"robot_id": sample_robot, "terrain_mode": "flat"},
        )
        assert len(_leaderboard) == 1
        assert _leaderboard[0]["final_score"] == high_score

    @patch("web.app.simulate_urdf")
    @patch("web.app._save_leaderboard")
    def test_submit_different_terrains_separate_entries(
        self, mock_save, mock_sim, client, sample_robot
    ):
        """Same robot on different terrains should create separate entries."""
        mock_sim.side_effect = self._mock_simulate_success
        client.post(
            "/api/leaderboard/submit",
            json={"robot_id": sample_robot, "terrain_mode": "flat"},
        )
        client.post(
            "/api/leaderboard/submit",
            json={"robot_id": sample_robot, "terrain_mode": "stairs"},
        )
        assert len(_leaderboard) == 2
        terrains = {e["terrain_mode"] for e in _leaderboard}
        assert terrains == {"flat", "stairs"}

    @patch("web.app.simulate_urdf")
    @patch("web.app._save_leaderboard")
    def test_submit_defaults_to_flat(self, mock_save, mock_sim, client, sample_robot):
        mock_sim.side_effect = self._mock_simulate_success
        res = client.post(
            "/api/leaderboard/submit",
            json={"robot_id": sample_robot},
        )
        data = res.get_json()
        assert data["entry"]["terrain_mode"] == "flat"

    @patch("web.app.simulate_urdf")
    @patch("web.app._save_leaderboard")
    def test_submit_invalid_terrain_defaults_to_flat(
        self, mock_save, mock_sim, client, sample_robot
    ):
        mock_sim.side_effect = self._mock_simulate_success
        res = client.post(
            "/api/leaderboard/submit",
            json={"robot_id": sample_robot, "terrain_mode": "lava"},
        )
        data = res.get_json()
        assert data["entry"]["terrain_mode"] == "flat"

    @patch("web.app.simulate_urdf")
    @patch("web.app._save_leaderboard")
    def test_submit_entry_has_all_fields(self, mock_save, mock_sim, client, sample_robot):
        mock_sim.side_effect = self._mock_simulate_success
        res = client.post(
            "/api/leaderboard/submit",
            json={"robot_id": sample_robot, "terrain_mode": "flat"},
        )
        entry = res.get_json()["entry"]
        required_fields = {
            "id", "robot_id", "prompt", "terrain_mode",
            "final_score", "label", "stability_score",
            "uprightness_score", "grounding_score", "timestamp",
        }
        assert required_fields.issubset(set(entry.keys()))


# ---------------------------------------------------------------------------
# POST /api/simulate (score included in response)
# ---------------------------------------------------------------------------
class TestSimulateWithScore:
    @patch("web.app.simulate_urdf")
    def test_simulate_includes_score(self, mock_sim, client, sample_robot):
        mock_sim.return_value = (True, "", {
            "displacement": 0.5,
            "tilt_cos": 0.9,
            "final_position": {"x": 0.1, "y": 0.05, "z": 1.0},
            "terrain_mode": "flat",
            "distance_from_origin": 1.05,
            "is_upright": True,
            "sim_duration_s": 5.0,
        })
        res = client.post(
            "/api/simulate",
            json={"robot_id": sample_robot, "terrain_mode": "flat"},
        )
        data = res.get_json()
        assert data["success"] is True
        assert "score" in data
        assert data["score"] is not None
        assert "final_score" in data["score"]
        assert "label" in data["score"]
        assert 0 <= data["score"]["final_score"] <= 100

    @patch("web.app.simulate_urdf")
    def test_simulate_no_metrics_no_score(self, mock_sim, client, sample_robot):
        mock_sim.return_value = (False, "Robot exploded", None)
        res = client.post(
            "/api/simulate",
            json={"robot_id": sample_robot, "terrain_mode": "flat"},
        )
        data = res.get_json()
        assert data["score"] is None
