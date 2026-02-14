"""
Phase 2: PyBullet simulation with motor control and trajectory recording.
Usage: python -m src.simulate output/robot.urdf [--terrain flat|uneven|stairs|slope] [--motors] [--record]
"""

import logging
import math
import os
import random
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import pybullet as p
    import pybullet_data
    PYBULLET_AVAILABLE = True
except ImportError:
    PYBULLET_AVAILABLE = False

# Headless by default for CI/automation
GUI = os.environ.get("PYBULLET_GUI", "0") == "1"
SIM_DURATION = 5.0  # seconds
SANITY_CHECK_DURATION = 0.5  # seconds — quick spawn-and-check
SIM_TIMESTEP = 1.0 / 240.0
RECORD_FPS = 30  # frames per second for trajectory recording

TERRAIN_MODES = ("flat", "uneven", "stairs", "slope")


def _load_terrain_flat(physics_client: int) -> float:
    """Load flat ground plane. Returns robot spawn height."""
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.loadURDF("plane.urdf", [0, 0, 0], useFixedBase=True)
    return 1.0


def _load_terrain_uneven(physics_client: int) -> float:
    """Load uneven terrain (heightfield with random bumps). Returns robot spawn height."""
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    random.seed(42)
    num_rows = 128
    num_cols = 128
    height_scale = 0.08  # Max bump height in meters
    heightfield_data = [0.0] * (num_rows * num_cols)
    for j in range(num_cols):
        for i in range(num_rows):
            idx = i + j * num_rows
            heightfield_data[idx] = random.uniform(0, height_scale)
    terrain_shape = p.createCollisionShape(
        shapeType=p.GEOM_HEIGHTFIELD,
        meshScale=[0.25, 0.25, 1.0],
        heightfieldTextureScaling=(num_rows - 1) / 2,
        heightfieldData=heightfield_data,
        numHeightfieldRows=num_rows,
        numHeightfieldColumns=num_cols,
    )
    terrain = p.createMultiBody(0, terrain_shape)
    p.resetBasePositionAndOrientation(terrain, [0, 0, 0], [0, 0, 0, 1])
    return 1.2  # Spawn slightly higher for uneven ground


def _load_terrain_stairs(physics_client: int) -> float:
    """Load staircase. Returns robot spawn height."""
    step_height = 0.08
    step_depth = 0.25
    step_width = 2.0
    num_steps = 8
    for i in range(num_steps):
        half_extents = [step_width / 2, step_depth / 2, step_height / 2]
        shape = p.createCollisionShape(p.GEOM_BOX, halfExtents=half_extents)
        x = i * step_depth
        z = (i + 0.5) * step_height
        body = p.createMultiBody(0, shape, -1, [x, 0, z], [0, 0, 0, 1])
        p.changeDynamics(body, -1, friction=0.8)
    return 0.6  # Spawn above first step


def _load_terrain_slope(physics_client: int) -> float:
    """Load angled slope (ramp). Returns robot spawn height."""
    slope_angle_deg = 15
    slope_length = 3.0
    slope_width = 2.0
    angle_rad = math.radians(slope_angle_deg)
    half_extents = [slope_length / 2, slope_width / 2, 0.05]
    shape = p.createCollisionShape(p.GEOM_BOX, halfExtents=half_extents)
    orientation = p.getQuaternionFromEuler(-angle_rad, 0, 0)
    x = slope_length / 2 * math.cos(angle_rad)
    z = slope_length / 2 * math.sin(angle_rad) + 0.05
    body = p.createMultiBody(0, shape, -1, [x, 0, z], orientation)
    p.changeDynamics(body, -1, friction=0.8)
    return 1.0  # Spawn at bottom of slope


def _load_terrain(physics_client: int, terrain_mode: str) -> float:
    """Load terrain for the given mode. Returns robot spawn height."""
    mode = (terrain_mode or "flat").lower()
    if mode not in TERRAIN_MODES:
        mode = "flat"
    elif mode == "flat":
        return _load_terrain_flat(physics_client)
    elif mode == "uneven":
        return _load_terrain_uneven(physics_client)
    elif mode == "stairs":
        return _load_terrain_stairs(physics_client)
    elif mode == "slope":
        return _load_terrain_slope(physics_client)
    return _load_terrain_flat(physics_client)


def _check_self_collisions(robot_id: int, num_joints: int) -> list[str]:
    """
    Check for self-collisions between non-adjacent robot links.
    Returns list of collision pair descriptions (e.g. "upper_leg<->lower_leg").
    """
    collisions: list[str] = []
    contact_points = p.getContactPoints(bodyA=robot_id, bodyB=robot_id)
    if not contact_points:
        return collisions

    seen: set[tuple[int, int]] = set()
    for cp in contact_points:
        link_a = cp[3]   # linkIndexA
        link_b = cp[4]   # linkIndexB
        # Skip adjacent links (parent-child joints naturally touch)
        if abs(link_a - link_b) <= 1:
            continue
        pair = (min(link_a, link_b), max(link_a, link_b))
        if pair in seen:
            continue
        seen.add(pair)
        # Resolve human-readable link names
        name_a = "base"
        name_b = "base"
        if link_a >= 0:
            info_a = p.getJointInfo(robot_id, link_a)
            name_a = info_a[12].decode("utf-8")
        if link_b >= 0:
            info_b = p.getJointInfo(robot_id, link_b)
            name_b = info_b[12].decode("utf-8")
        collisions.append(f"{name_a}<->{name_b}")
    return collisions


def physics_sanity_check(urdf_path: Path) -> tuple[bool, str, dict | None]:
    """
    Quick physics sanity check: spawn the robot on flat ground and run for 0.5 s.
    Detects three failure modes:
      1. Explosion — robot flies away (distance > 10 m)
      2. Immediate fall-over — tilt_cos < 0.1 (nearly horizontal/inverted)
      3. Self-collisions — non-adjacent links in contact

    Returns (passed, error_msg, diagnostics_dict_or_None).
    """
    if not PYBULLET_AVAILABLE:
        return False, "pybullet not installed", None
    if not urdf_path.exists():
        return False, f"File not found: {urdf_path}", None

    logger.info("Running physics sanity check on %s", urdf_path.name)
    physics_client = p.connect(p.DIRECT)

    try:
        p.setGravity(0, 0, -9.81)
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.setRealTimeSimulation(0)
        p.setTimeStep(1.0 / 240.0)

        # Flat ground only for sanity check
        p.loadURDF("plane.urdf", [0, 0, 0], useFixedBase=True)

        spawn_height = 1.0
        start_pos = [0, 0, spawn_height]
        robot_id = p.loadURDF(str(urdf_path), start_pos, useFixedBase=False)
        num_joints = p.getNumJoints(robot_id)

        steps = int(SANITY_CHECK_DURATION * 240)
        issues: list[str] = []

        # --- One step to settle contacts, then check initial self-collisions ---
        p.stepSimulation()
        initial_self_collisions = _check_self_collisions(robot_id, num_joints)
        if initial_self_collisions:
            issues.append(
                f"Self-collisions at spawn between: {', '.join(initial_self_collisions)}"
            )

        # --- Run remaining steps, checking for explosion at quarter-intervals ---
        quarter = max(1, steps // 4)
        exploded = False
        for step in range(1, steps):
            p.stepSimulation()
            if step % quarter == 0:
                pos, _ = p.getBasePositionAndOrientation(robot_id)
                dist = (pos[0] ** 2 + pos[1] ** 2 + pos[2] ** 2) ** 0.5
                if dist > 10:
                    issues.append(
                        f"Robot exploded: moved {dist:.1f}m in {step / 240:.2f}s"
                    )
                    exploded = True
                    break

        # --- Final state ---
        pos, orn = p.getBasePositionAndOrientation(robot_id)
        x, y, z = pos
        dist = (x ** 2 + y ** 2 + z ** 2) ** 0.5
        displacement = (
            (x - start_pos[0]) ** 2
            + (y - start_pos[1]) ** 2
            + (z - start_pos[2]) ** 2
        ) ** 0.5

        rot_matrix = p.getMatrixFromQuaternion(orn)
        up_z = rot_matrix[8]

        if not exploded and dist > 10:
            issues.append(f"Robot exploded: moved {dist:.1f}m from origin")

        if up_z < 0.1:
            issues.append(f"Robot fell over immediately (tilt_cos={up_z:.3f})")

        if z < -0.5:
            issues.append(f"Robot fell through the ground (z={z:.3f})")

        # Check self-collisions after settling
        final_self_collisions = _check_self_collisions(robot_id, num_joints)
        if final_self_collisions and not initial_self_collisions:
            issues.append(
                f"Self-collisions developed during settling: {', '.join(final_self_collisions)}"
            )

        diagnostics = {
            "duration_s": SANITY_CHECK_DURATION,
            "final_position": {"x": round(x, 3), "y": round(y, 3), "z": round(z, 3)},
            "displacement": round(displacement, 3),
            "tilt_cos": round(up_z, 3),
            "self_collisions_initial": initial_self_collisions,
            "self_collisions_final": final_self_collisions,
            "issues": issues,
            "num_joints": num_joints,
            "passed": len(issues) == 0,
        }

        if issues:
            msg = "Physics sanity check FAILED: " + "; ".join(issues)
            logger.warning(msg)
            return False, msg, diagnostics

        logger.info("Physics sanity check passed")
        return True, "", diagnostics

    except Exception as e:
        logger.error("Sanity check error: %s", e)
        return False, f"Sanity check error: {e}", None
    finally:
        p.disconnect()


def generate_feedback_suggestions(
    metrics: dict | None,
    diagnostics: dict | None = None,
) -> list[dict]:
    """
    Generate human-readable feedback suggestions based on simulation results.
    Each suggestion is ``{"text": "<display>", "prompt": "<refinement prompt>"}``.
    Used by the UI so the user can one-click iterate on the robot.
    """
    suggestions: list[dict] = []
    if not metrics:
        return suggestions

    displacement = metrics.get("displacement", 0)
    tilt_cos = metrics.get("tilt_cos", 1.0)
    final_z = (metrics.get("final_position") or {}).get("z", 0)

    # --- Physics issues ---
    if displacement > 2.0:
        suggestions.append({
            "text": "Robot is unstable — too much displacement",
            "prompt": "Make the robot more stable by widening the base and lowering the center of gravity",
        })
    if tilt_cos < 0.3:
        suggestions.append({
            "text": "Robot falls over easily",
            "prompt": "Make the robot more balanced — widen the legs/wheels and lower the center of mass",
        })
    elif tilt_cos < 0.7:
        suggestions.append({
            "text": "Robot tilts significantly",
            "prompt": "Improve balance by adjusting leg positions for better weight distribution",
        })
    if final_z < 0.1:
        suggestions.append({
            "text": "Robot is too low to the ground",
            "prompt": "Make the legs longer so the robot sits higher off the ground",
        })
    if final_z > 3.0:
        suggestions.append({
            "text": "Robot launched into the air",
            "prompt": "Reduce joint effort and fix joint limits to prevent the robot from launching itself",
        })

    # --- Diagnostics from sanity check ---
    if diagnostics:
        self_colls = (
            diagnostics.get("self_collisions_initial", [])
            or diagnostics.get("self_collisions_final", [])
        )
        if self_colls:
            suggestions.append({
                "text": "Self-collisions between robot parts",
                "prompt": "Increase spacing between links to eliminate self-collisions; move joints further apart",
            })
        for issue in diagnostics.get("issues", []):
            if "explod" in issue.lower() and not any("unstable" in s["text"].lower() for s in suggestions):
                suggestions.append({
                    "text": "Robot structure is unstable (explodes)",
                    "prompt": "Reduce joint effort values and fix joint limits to prevent the robot from flying apart",
                })

    # --- Generic tweaking suggestions when the robot is already decent ---
    if not suggestions:
        suggestions.extend([
            {"text": "Make the legs shorter", "prompt": "Make the legs shorter"},
            {"text": "Make the legs longer", "prompt": "Make the legs longer"},
            {"text": "Make it heavier and more sturdy", "prompt": "Increase the mass and make the robot sturdier"},
            {"text": "Make it lighter and more agile", "prompt": "Decrease the mass and make the robot lighter"},
            {"text": "Widen the stance", "prompt": "Widen the stance by moving legs further apart"},
        ])

    return suggestions


def _get_movable_joints(robot_id: int) -> list[dict]:
    """
    Discover all non-fixed joints on the robot.
    Returns list of dicts with: index, name, type, lower_limit, upper_limit.
    """
    joints = []
    num_joints = p.getNumJoints(robot_id)
    for i in range(num_joints):
        info = p.getJointInfo(robot_id, i)
        joint_type = info[2]
        # 0=REVOLUTE, 1=PRISMATIC — skip FIXED(4), POINT2POINT(5), GEAR(6)
        if joint_type in (p.JOINT_REVOLUTE, p.JOINT_PRISMATIC):
            joints.append({
                "index": i,
                "name": info[1].decode("utf-8"),
                "type": joint_type,
                "lower": info[8],
                "upper": info[9],
            })
    return joints


def _apply_motor_control(robot_id: int, joints: list[dict], sim_time: float):
    """
    Apply sinusoidal position control to each movable joint.
    Each joint gets a different phase offset to create a walking-like gait.
    """
    if not joints:
        return
    amplitude = 0.5  # radians
    frequency = 1.0  # Hz
    for idx, joint in enumerate(joints):
        # Stagger phase by joint index for gait-like motion
        phase = (2 * math.pi * idx) / max(len(joints), 1)
        target = amplitude * math.sin(2 * math.pi * frequency * sim_time + phase)

        # Clamp to joint limits if defined (lower < upper)
        if joint["lower"] < joint["upper"]:
            midpoint = (joint["lower"] + joint["upper"]) / 2
            half_range = (joint["upper"] - joint["lower"]) / 2
            target = midpoint + min(amplitude, half_range) * math.sin(
                2 * math.pi * frequency * sim_time + phase
            )

        p.setJointMotorControl2(
            robot_id,
            joint["index"],
            p.POSITION_CONTROL,
            targetPosition=target,
            force=150,
            maxVelocity=2.0,
        )


def _record_frame(robot_id: int, joints: list[dict], sim_time: float) -> dict:
    """Capture a single frame of the simulation state."""
    pos, orn = p.getBasePositionAndOrientation(robot_id)
    joint_positions = {}
    for joint in joints:
        state = p.getJointState(robot_id, joint["index"])
        joint_positions[joint["name"]] = round(state[0], 4)
    return {
        "t": round(sim_time, 4),
        "pos": [round(v, 4) for v in pos],
        "orn": [round(v, 4) for v in orn],
        "joints": joint_positions,
    }


def simulate_urdf(
    urdf_path: Path,
    terrain_mode: str = "flat",
    enable_motors: bool = False,
    record_trajectory: bool = False,
) -> tuple[bool, str, dict | None]:
    """
    Load URDF in PyBullet, run simulation for SIM_DURATION seconds.

    Parameters
    ----------
    urdf_path : Path to the URDF file.
    terrain_mode : "flat", "uneven", "stairs", or "slope".
    enable_motors : If True, apply sinusoidal position control to joints.
    record_trajectory : If True, record base pose + joint states at RECORD_FPS.

    Returns (success, error_msg, metrics_dict_or_None).
    metrics includes: distance_from_origin, final_position, is_upright, displacement.
    If record_trajectory is True, metrics also includes "trajectory" key.
    """
    if not PYBULLET_AVAILABLE:
        return False, "pybullet not installed. Run: pip install pybullet", None
    if not urdf_path.exists():
        return False, f"File not found: {urdf_path}", None

    logger.info(
        "Simulating %s on %s terrain (%.1fs, motors=%s, record=%s)",
        urdf_path.name, terrain_mode, SIM_DURATION, enable_motors, record_trajectory,
    )

    if GUI:
        physics_client = p.connect(p.GUI)
    else:
        physics_client = p.connect(p.DIRECT)

    try:
        p.setGravity(0, 0, -9.81)
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.setRealTimeSimulation(0)
        p.setTimeStep(SIM_TIMESTEP)

        spawn_height = _load_terrain(physics_client, terrain_mode)
        start_pos = [0, 0, spawn_height]
        robot_id = p.loadURDF(str(urdf_path), start_pos, useFixedBase=False)

        # Discover joints
        joints = _get_movable_joints(robot_id)
        joint_names = [j["name"] for j in joints]
        logger.info("Found %d movable joints: %s", len(joints), joint_names[:8])

        # Trajectory recording setup
        frames = []
        steps_per_frame = max(1, int(1.0 / (SIM_TIMESTEP * RECORD_FPS)))

        # Run simulation
        total_steps = int(SIM_DURATION / SIM_TIMESTEP)
        for step in range(total_steps):
            sim_time = step * SIM_TIMESTEP

            if enable_motors:
                _apply_motor_control(robot_id, joints, sim_time)

            p.stepSimulation()

            if record_trajectory and (step % steps_per_frame == 0):
                frames.append(_record_frame(robot_id, joints, sim_time))

        # Record final frame
        if record_trajectory:
            frames.append(_record_frame(robot_id, joints, SIM_DURATION))

        # Collect metrics
        pos, orn = p.getBasePositionAndOrientation(robot_id)
        x, y, z = pos

        dist = (x**2 + y**2 + z**2) ** 0.5
        displacement = ((x - start_pos[0])**2 + (y - start_pos[1])**2 + (z - start_pos[2])**2) ** 0.5

        rot_matrix = p.getMatrixFromQuaternion(orn)
        up_z = rot_matrix[8]
        is_upright = up_z > 0.5

        metrics = {
            "final_position": {"x": round(x, 3), "y": round(y, 3), "z": round(z, 3)},
            "distance_from_origin": round(dist, 3),
            "displacement": round(displacement, 3),
            "is_upright": is_upright,
            "tilt_cos": round(up_z, 3),
            "terrain_mode": terrain_mode,
            "sim_duration_s": SIM_DURATION,
            "motors_enabled": enable_motors,
            "num_joints": len(joints),
            "joint_names": joint_names,
        }

        if record_trajectory:
            metrics["trajectory"] = {
                "fps": RECORD_FPS,
                "duration": SIM_DURATION,
                "frame_count": len(frames),
                "joint_names": joint_names,
                "frames": frames,
            }

        if dist > 50:
            logger.warning("Robot exploded: moved %.1fm from origin", dist)
            return False, f"Robot exploded: base moved {dist:.1f}m from origin", metrics

        logger.info("Simulation OK — dist=%.2fm, upright=%s", dist, is_upright)
        return True, "", metrics
    except Exception as e:
        logger.error("Simulation error: %s", e)
        return False, str(e), None
    finally:
        p.disconnect()


def stress_test_urdf(
    urdf_path: Path,
    enable_motors: bool = False,
) -> dict:
    """
    Run simulation on ALL terrain modes. Returns a dict of results per terrain.
    Each result: {success, error, metrics, score (if available)}.
    """
    results = {}
    for terrain in TERRAIN_MODES:
        success, err, metrics = simulate_urdf(
            urdf_path, terrain_mode=terrain, enable_motors=enable_motors,
        )
        results[terrain] = {
            "success": success,
            "error": err if not success else None,
            "metrics": metrics,
        }
    return results


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "output/robot.urdf"
    terrain = "flat"
    motors = False
    record = False
    for i, arg in enumerate(sys.argv):
        if arg in ("--terrain", "-t") and i + 1 < len(sys.argv):
            terrain = sys.argv[i + 1].lower()
        if arg == "--motors":
            motors = True
        if arg == "--record":
            record = True

    urdf_path = Path(path)
    success, err, metrics = simulate_urdf(
        urdf_path, terrain_mode=terrain, enable_motors=motors, record_trajectory=record,
    )
    if success:
        print(f"Simulation OK: robot stable on {terrain} terrain.")
        if metrics:
            pos = metrics["final_position"]
            print(f"  Final position: ({pos['x']}, {pos['y']}, {pos['z']})")
            print(f"  Distance from origin: {metrics['distance_from_origin']}m")
            print(f"  Displacement: {metrics['displacement']}m")
            print(f"  Upright: {'yes' if metrics['is_upright'] else 'no'} (tilt_cos={metrics['tilt_cos']})")
            print(f"  Motors: {'on' if motors else 'off'} | Joints: {metrics.get('num_joints', 0)}")
            if record and "trajectory" in metrics:
                traj = metrics["trajectory"]
                print(f"  Trajectory: {traj['frame_count']} frames at {traj['fps']}fps")
    else:
        print(f"Simulation failed: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
