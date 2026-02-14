"""
Web UI for TreeHackNow — prompt input, history, 3D preview, iterative refinement.
"""

import os
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agent import run_agent, run_agent_refine
from src.simulate import simulate_urdf, TERRAIN_MODES

app = Flask(__name__, static_folder="static", template_folder="templates")

# In-memory history (id -> {prompt, urdf, refined_from, timestamp})
_history: dict[str, dict] = {}


def _ensure_api_key():
    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY not set. Set it before running the web app.")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/generate", methods=["POST"])
def api_generate():
    _ensure_api_key()
    data = request.get_json() or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    success, urdf, msg = run_agent(prompt)
    if not success:
        return jsonify({"success": False, "error": msg}), 200

    entry_id = str(uuid.uuid4())
    _history[entry_id] = {
        "id": entry_id,
        "prompt": prompt,
        "urdf": urdf,
        "refined_from": None,
        "timestamp": time.time(),
    }
    return jsonify({
        "success": True,
        "id": entry_id,
        "prompt": prompt,
        "urdf": urdf,
    })


@app.route("/api/refine", methods=["POST"])
def api_refine():
    _ensure_api_key()
    data = request.get_json() or {}
    refinement_prompt = (data.get("prompt") or "").strip()
    base_id = data.get("base_id")
    base_urdf = data.get("base_urdf")

    if not refinement_prompt:
        return jsonify({"error": "prompt is required"}), 400

    if base_urdf:
        urdf_to_use = base_urdf
    elif base_id and base_id in _history:
        urdf_to_use = _history[base_id]["urdf"]
    else:
        return jsonify({"error": "base_id or base_urdf is required"}), 400

    success, urdf, msg = run_agent_refine(refinement_prompt, urdf_to_use)
    if not success:
        return jsonify({"success": False, "error": msg}), 200

    entry_id = str(uuid.uuid4())
    _history[entry_id] = {
        "id": entry_id,
        "prompt": refinement_prompt,
        "urdf": urdf,
        "refined_from": base_id,
        "timestamp": time.time(),
    }
    return jsonify({
        "success": True,
        "id": entry_id,
        "prompt": refinement_prompt,
        "urdf": urdf,
        "refined_from": base_id,
    })


@app.route("/api/history", methods=["GET"])
def api_history():
    entries = sorted(
        _history.values(),
        key=lambda e: e["timestamp"],
        reverse=True,
    )
    return jsonify({
        "history": [
            {
                "id": e["id"],
                "prompt": e["prompt"],
                "refined_from": e.get("refined_from"),
                "timestamp": e["timestamp"],
            }
            for e in entries
        ],
    })


@app.route("/api/robot/<robot_id>", methods=["GET"])
def api_robot(robot_id):
    if robot_id not in _history:
        return jsonify({"error": "not found"}), 404
    entry = _history[robot_id]
    return jsonify({
        "id": entry["id"],
        "prompt": entry["prompt"],
        "urdf": entry["urdf"],
        "refined_from": entry.get("refined_from"),
    })


@app.route("/api/robot/<robot_id>", methods=["DELETE"])
def api_robot_delete(robot_id):
    if robot_id not in _history:
        return jsonify({"error": "not found"}), 404
    del _history[robot_id]
    return jsonify({"success": True})


@app.route("/api/simulate", methods=["POST"])
def api_simulate():
    """Run PyBullet simulation with selected terrain mode."""
    data = request.get_json() or {}
    robot_id = data.get("robot_id")
    base_urdf = data.get("urdf")
    terrain_mode = (data.get("terrain_mode") or "flat").lower()

    if terrain_mode not in TERRAIN_MODES:
        terrain_mode = "flat"

    urdf = base_urdf
    if not urdf and robot_id and robot_id in _history:
        urdf = _history[robot_id]["urdf"]

    if not urdf:
        return jsonify({"error": "robot_id or urdf is required"}), 400

    try:
        tmp_path = Path(__file__).parent.parent / "output" / "sim_test.urdf"
        tmp_path.parent.mkdir(exist_ok=True)
        tmp_path.write_text(urdf)
        success, err = simulate_urdf(tmp_path, terrain_mode=terrain_mode)
        return jsonify({
            "success": success,
            "error": err if not success else None,
            "terrain_mode": terrain_mode,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def main():
    port = int(os.environ.get("PORT", 5000))
    print(f"TreeHackNow Web UI: http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)


if __name__ == "__main__":
    main()
