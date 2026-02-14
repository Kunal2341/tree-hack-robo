"""
Web UI for TreeHackNow — prompt input, history, 3D preview, iterative refinement.
Supports: URDF generation, MJCF/SDF conversion, RAG-enhanced generation, Image-to-URDF.
"""

import json
import os
import time
import uuid
import base64
import tempfile
from pathlib import Path

from flask import Flask, jsonify, render_template, request

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agent import run_agent, run_agent_refine
from src.simulate import simulate_urdf, stress_test_urdf, physics_sanity_check, generate_feedback_suggestions, TERRAIN_MODES
from src.score import compute_score, score_label
from src.convert import urdf_to_mjcf, urdf_to_sdf, generate_mjcf, generate_sdf
from src.vision import image_to_urdf, image_to_urdf_two_stage, analyze_robot_image

app = Flask(__name__, static_folder="static", template_folder="templates")

# Max upload size: 10MB
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

HISTORY_PATH = Path(__file__).parent.parent / "output" / "history.json"
LEADERBOARD_PATH = Path(__file__).parent.parent / "output" / "leaderboard.json"

# In-memory history (id -> {prompt, urdf, refined_from, timestamp})
_history: dict[str, dict] = {}

# In-memory leaderboard (list of score entries)
_leaderboard: list[dict] = []


def _load_history():
    """Load history from disk on startup."""
    global _history
    if HISTORY_PATH.exists():
        try:
            data = json.loads(HISTORY_PATH.read_text())
            _history = {e["id"]: e for e in data}
        except (json.JSONDecodeError, KeyError):
            _history = {}


def _save_history():
    """Persist history to disk."""
    HISTORY_PATH.parent.mkdir(exist_ok=True)
    entries = sorted(_history.values(), key=lambda e: e.get("timestamp", 0))
    HISTORY_PATH.write_text(json.dumps(entries, indent=2))


def _load_leaderboard():
    """Load leaderboard from disk on startup."""
    global _leaderboard
    if LEADERBOARD_PATH.exists():
        try:
            _leaderboard = json.loads(LEADERBOARD_PATH.read_text())
        except (json.JSONDecodeError, KeyError):
            _leaderboard = []


def _save_leaderboard():
    """Persist leaderboard to disk."""
    LEADERBOARD_PATH.parent.mkdir(exist_ok=True)
    LEADERBOARD_PATH.write_text(json.dumps(_leaderboard, indent=2))


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
    _save_history()
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
    _save_history()
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
    _save_history()
    return jsonify({"success": True})


@app.route("/api/health", methods=["GET"])
def api_health():
    """Health check endpoint — useful for monitoring and uptime checks."""
    return jsonify({
        "status": "ok",
        "robot_count": len(_history),
        "pybullet_available": bool(
            __import__("importlib").util.find_spec("pybullet")
        ),
        "version": "1.0.0",
    })


@app.route("/api/simulate", methods=["POST"])
def api_simulate():
    """Run PyBullet simulation with selected terrain mode.

    Now also performs a quick physics sanity check first (explosion,
    fall-over, self-collision) and returns feedback suggestions so the
    user can iterate on the robot interactively.
    """
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

        # ---- Phase 1: quick physics sanity check ----
        sanity_ok, sanity_err, sanity_diag = physics_sanity_check(tmp_path)

        # ---- Phase 2: full simulation ----
        enable_motors = bool(data.get("enable_motors", False))
        record_trajectory = bool(data.get("record_trajectory", False))
        success, err, metrics = simulate_urdf(
            tmp_path,
            terrain_mode=terrain_mode,
            enable_motors=enable_motors,
            record_trajectory=record_trajectory,
        )

        # Compute score if simulation produced metrics
        score_data = None
        if metrics:
            try:
                score_data = compute_score(metrics, terrain_mode=terrain_mode)
                score_data["label"] = score_label(score_data["final_score"])
            except Exception:
                score_data = None

        # ---- Feedback suggestions for interactive tweaking ----
        suggestions = generate_feedback_suggestions(metrics, sanity_diag)

        return jsonify({
            "success": success,
            "error": err if not success else None,
            "terrain_mode": terrain_mode,
            "metrics": metrics,
            "score": score_data,
            "sanity_check": {
                "passed": sanity_ok,
                "error": sanity_err if not sanity_ok else None,
                "diagnostics": sanity_diag,
            },
            "feedback_suggestions": suggestions,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sanity-check", methods=["POST"])
def api_sanity_check():
    """Run only the quick physics sanity check (no full simulation)."""
    data = request.get_json() or {}
    robot_id = data.get("robot_id")
    base_urdf = data.get("urdf")

    urdf = base_urdf
    if not urdf and robot_id and robot_id in _history:
        urdf = _history[robot_id]["urdf"]

    if not urdf:
        return jsonify({"error": "robot_id or urdf is required"}), 400

    try:
        tmp_path = Path(__file__).parent.parent / "output" / "sanity_test.urdf"
        tmp_path.parent.mkdir(exist_ok=True)
        tmp_path.write_text(urdf)
        passed, err, diagnostics = physics_sanity_check(tmp_path)
        return jsonify({
            "passed": passed,
            "error": err if not passed else None,
            "diagnostics": diagnostics,
        })
    except Exception as e:
        return jsonify({"passed": False, "error": str(e)}), 500


@app.route("/api/stress-test", methods=["POST"])
def api_stress_test():
    """Run simulation on ALL terrain modes and return a scorecard."""
    data = request.get_json() or {}
    robot_id = data.get("robot_id")
    base_urdf = data.get("urdf")
    enable_motors = bool(data.get("enable_motors", False))

    urdf = base_urdf
    if not urdf and robot_id and robot_id in _history:
        urdf = _history[robot_id]["urdf"]

    if not urdf:
        return jsonify({"error": "robot_id or urdf is required"}), 400

    try:
        tmp_path = Path(__file__).parent.parent / "output" / "stress_test.urdf"
        tmp_path.parent.mkdir(exist_ok=True)
        tmp_path.write_text(urdf)
        results = stress_test_urdf(tmp_path, enable_motors=enable_motors)

        # Add scores to each result
        scorecard = {}
        for terrain, result in results.items():
            score_data = None
            if result["metrics"]:
                try:
                    score_data = compute_score(result["metrics"], terrain_mode=terrain)
                    score_data["label"] = score_label(score_data["final_score"])
                except Exception:
                    score_data = None
            scorecard[terrain] = {
                "success": result["success"],
                "error": result["error"],
                "score": score_data,
                "metrics": {
                    k: v for k, v in (result["metrics"] or {}).items()
                    if k != "trajectory"
                },
            }

        # Compute average score
        scores = [
            s["score"]["final_score"]
            for s in scorecard.values()
            if s["score"]
        ]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0
        pass_count = sum(1 for s in scorecard.values() if s["success"])

        return jsonify({
            "scorecard": scorecard,
            "summary": {
                "average_score": avg_score,
                "label": score_label(avg_score),
                "terrains_passed": pass_count,
                "terrains_total": len(TERRAIN_MODES),
                "motors_enabled": enable_motors,
            },
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/leaderboard", methods=["GET"])
def api_leaderboard():
    """Get the robot leaderboard, optionally filtered by terrain_mode."""
    terrain_filter = request.args.get("terrain_mode", "").lower()
    entries = _leaderboard
    if terrain_filter and terrain_filter in TERRAIN_MODES:
        entries = [e for e in entries if e.get("terrain_mode") == terrain_filter]
    # Sort by final_score descending
    entries = sorted(entries, key=lambda e: e.get("final_score", 0), reverse=True)
    return jsonify({"leaderboard": entries})


@app.route("/api/leaderboard/submit", methods=["POST"])
def api_leaderboard_submit():
    """
    Submit a robot's simulation score to the leaderboard.
    Expects: robot_id, terrain_mode (runs simulation + scoring server-side).
    """
    data = request.get_json() or {}
    robot_id = data.get("robot_id")
    terrain_mode = (data.get("terrain_mode") or "flat").lower()

    if not robot_id or robot_id not in _history:
        return jsonify({"error": "valid robot_id is required"}), 400

    if terrain_mode not in TERRAIN_MODES:
        terrain_mode = "flat"

    entry = _history[robot_id]
    urdf = entry["urdf"]

    # Run simulation
    try:
        tmp_path = Path(__file__).parent.parent / "output" / "sim_test.urdf"
        tmp_path.parent.mkdir(exist_ok=True)
        tmp_path.write_text(urdf)
        success, err, metrics = simulate_urdf(tmp_path, terrain_mode=terrain_mode)
    except Exception as e:
        return jsonify({"error": f"Simulation failed: {e}"}), 500

    if not success:
        return jsonify({"success": False, "error": err or "Simulation failed"}), 200

    if not metrics:
        return jsonify({"error": "No metrics from simulation"}), 500

    score_data = compute_score(metrics, terrain_mode=terrain_mode)
    score_data["label"] = score_label(score_data["final_score"])

    # Build leaderboard entry
    lb_entry = {
        "id": str(uuid.uuid4()),
        "robot_id": robot_id,
        "prompt": entry["prompt"],
        "terrain_mode": terrain_mode,
        "final_score": score_data["final_score"],
        "label": score_data["label"],
        "stability_score": score_data["stability_score"],
        "uprightness_score": score_data["uprightness_score"],
        "grounding_score": score_data["grounding_score"],
        "timestamp": time.time(),
    }

    # Check for existing entry for same robot+terrain — keep highest score
    existing_idx = None
    for i, existing in enumerate(_leaderboard):
        if existing["robot_id"] == robot_id and existing["terrain_mode"] == terrain_mode:
            existing_idx = i
            break

    if existing_idx is not None:
        if lb_entry["final_score"] > _leaderboard[existing_idx]["final_score"]:
            _leaderboard[existing_idx] = lb_entry
    else:
        _leaderboard.append(lb_entry)

    _save_leaderboard()
    return jsonify({"success": True, "entry": lb_entry, "score": score_data})


# ---------------------------------------------------------------------------
# MJCF / SDF Conversion Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/convert/mjcf", methods=["POST"])
def api_convert_mjcf():
    """Convert a URDF to MuJoCo MJCF format."""
    data = request.get_json() or {}
    robot_id = data.get("robot_id")
    urdf_str = data.get("urdf")

    if not urdf_str and robot_id and robot_id in _history:
        urdf_str = _history[robot_id]["urdf"]

    if not urdf_str:
        return jsonify({"error": "robot_id or urdf is required"}), 400

    try:
        mjcf = urdf_to_mjcf(urdf_str)
        return jsonify({"success": True, "mjcf": mjcf, "format": "mjcf"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/convert/sdf", methods=["POST"])
def api_convert_sdf():
    """Convert a URDF to Gazebo SDF format."""
    data = request.get_json() or {}
    robot_id = data.get("robot_id")
    urdf_str = data.get("urdf")

    if not urdf_str and robot_id and robot_id in _history:
        urdf_str = _history[robot_id]["urdf"]

    if not urdf_str:
        return jsonify({"error": "robot_id or urdf is required"}), 400

    try:
        sdf = urdf_to_sdf(urdf_str)
        return jsonify({"success": True, "sdf": sdf, "format": "sdf"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/generate/mjcf", methods=["POST"])
def api_generate_mjcf():
    """Generate MJCF directly from natural language."""
    _ensure_api_key()
    data = request.get_json() or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    try:
        mjcf = generate_mjcf(prompt)
        return jsonify({"success": True, "mjcf": mjcf, "format": "mjcf", "prompt": prompt})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/generate/sdf", methods=["POST"])
def api_generate_sdf():
    """Generate SDF directly from natural language."""
    _ensure_api_key()
    data = request.get_json() or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    try:
        sdf = generate_sdf(prompt)
        return jsonify({"success": True, "sdf": sdf, "format": "sdf", "prompt": prompt})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Image-to-URDF Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/image-to-urdf", methods=["POST"])
def api_image_to_urdf():
    """
    Generate URDF from an uploaded robot image (sketch, diagram, photo).

    Accepts either:
    - multipart/form-data with 'image' file field
    - JSON with 'image_base64' (base64-encoded image data)
    - JSON with 'image_url' (URL to an image)

    Optional fields: 'additional_prompt', 'mode' ("direct" or "two_stage")
    """
    _ensure_api_key()

    additional_prompt = ""
    mode = "direct"
    image_input = None

    if request.content_type and "multipart/form-data" in request.content_type:
        # File upload
        file = request.files.get("image")
        if not file:
            return jsonify({"error": "image file is required"}), 400

        additional_prompt = request.form.get("additional_prompt", "")
        mode = request.form.get("mode", "direct")

        # Save to temp file
        suffix = os.path.splitext(file.filename)[1] or ".png"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        file.save(tmp.name)
        tmp.close()
        image_input = tmp.name
    else:
        # JSON body
        data = request.get_json() or {}
        additional_prompt = data.get("additional_prompt", "")
        mode = data.get("mode", "direct")

        if data.get("image_base64"):
            image_input = data["image_base64"]
        elif data.get("image_url"):
            image_input = data["image_url"]
        else:
            return jsonify({"error": "image file, image_base64, or image_url is required"}), 400

    try:
        if mode == "two_stage":
            description, urdf = image_to_urdf_two_stage(image_input, additional_prompt)
            result = {
                "success": True,
                "urdf": urdf,
                "description": description,
                "mode": "two_stage",
            }
        else:
            urdf = image_to_urdf(image_input, additional_prompt)
            result = {
                "success": True,
                "urdf": urdf,
                "mode": "direct",
            }

        # Auto-save to history
        entry_id = str(uuid.uuid4())
        prompt_text = f"[Image-to-URDF] {additional_prompt}" if additional_prompt else "[Image-to-URDF]"
        _history[entry_id] = {
            "id": entry_id,
            "prompt": prompt_text,
            "urdf": urdf,
            "refined_from": None,
            "timestamp": time.time(),
            "source": "image",
        }
        _save_history()

        result["id"] = entry_id
        result["prompt"] = prompt_text
        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        # Clean up temp file if we created one
        if image_input and os.path.exists(image_input) and image_input.startswith(tempfile.gettempdir()):
            try:
                os.unlink(image_input)
            except OSError:
                pass


@app.route("/api/analyze-image", methods=["POST"])
def api_analyze_image():
    """
    Analyze a robot image and return a text description (without generating URDF).
    Useful for previewing what the vision model sees before generating.
    """
    _ensure_api_key()

    image_input = None

    if request.content_type and "multipart/form-data" in request.content_type:
        file = request.files.get("image")
        if not file:
            return jsonify({"error": "image file is required"}), 400
        suffix = os.path.splitext(file.filename)[1] or ".png"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        file.save(tmp.name)
        tmp.close()
        image_input = tmp.name
    else:
        data = request.get_json() or {}
        if data.get("image_base64"):
            image_input = data["image_base64"]
        elif data.get("image_url"):
            image_input = data["image_url"]
        else:
            return jsonify({"error": "image file, image_base64, or image_url is required"}), 400

    try:
        description = analyze_robot_image(image_input)
        return jsonify({"success": True, "description": description})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if image_input and os.path.exists(image_input) and image_input.startswith(tempfile.gettempdir()):
            try:
                os.unlink(image_input)
            except OSError:
                pass


def main():
    _load_history()
    _load_leaderboard()

    # Pre-load RAG index on startup
    try:
        from src.rag import get_rag_index
        idx = get_rag_index()
        print(f"  RAG: {len(idx.snippets)} URDF snippets indexed")
    except Exception as e:
        print(f"  RAG: Failed to load index: {e}")

    port = int(os.environ.get("PORT", 5000))
    print(f"TreeHackNow Web UI: http://localhost:{port}")
    print(f"  History: {len(_history)} robots loaded from {HISTORY_PATH}")
    print(f"  Leaderboard: {len(_leaderboard)} entries loaded from {LEADERBOARD_PATH}")
    print(f"  Features: URDF + MJCF + SDF generation, RAG, Image-to-URDF")
    app.run(host="0.0.0.0", port=port, debug=True)


if __name__ == "__main__":
    main()
