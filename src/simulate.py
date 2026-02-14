"""
Phase 2: PyBullet simulation.
Usage: python -m src.simulate output/robot.urdf [--terrain flat|uneven|stairs|slope]
"""

import os
import random
import sys
from pathlib import Path

try:
    import pybullet as p
    import pybullet_data
    PYBULLET_AVAILABLE = True
except ImportError:
    PYBULLET_AVAILABLE = False

# Headless by default for CI/automation
GUI = os.environ.get("PYBULLET_GUI", "0") == "1"
SIM_DURATION = 5.0  # seconds

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
    import math
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


def simulate_urdf(urdf_path: Path, terrain_mode: str = "flat") -> tuple[bool, str]:
    """
    Load URDF in PyBullet, run simulation for SIM_DURATION seconds.
    terrain_mode: "flat", "uneven", "stairs", or "slope" to test robustness.
    Returns (success, error_msg).
    """
    if not PYBULLET_AVAILABLE:
        return False, "pybullet not installed. Run: pip install pybullet"
    if not urdf_path.exists():
        return False, f"File not found: {urdf_path}"

    if GUI:
        physics_client = p.connect(p.GUI)
    else:
        physics_client = p.connect(p.DIRECT)

    try:
        p.setGravity(0, 0, -9.81)
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.setRealTimeSimulation(0)
        p.setTimeStep(1.0 / 240.0)

        spawn_height = _load_terrain(physics_client, terrain_mode)
        robot_id = p.loadURDF(str(urdf_path), [0, 0, spawn_height], useFixedBase=False)

        # Run simulation
        steps = int(SIM_DURATION * 240)
        for _ in range(steps):
            p.stepSimulation()

        # Check if robot exploded (parts too far from origin)
        pos, _ = p.getBasePositionAndOrientation(robot_id)
        x, y, z = pos
        dist = (x**2 + y**2 + z**2) ** 0.5
        if dist > 50:
            return False, f"Robot exploded: base moved {dist:.1f}m from origin"

        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        p.disconnect()


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "output/robot.urdf"
    terrain = "flat"
    for i, arg in enumerate(sys.argv):
        if arg in ("--terrain", "-t") and i + 1 < len(sys.argv):
            terrain = sys.argv[i + 1].lower()
            break
    urdf_path = Path(path)
    success, err = simulate_urdf(urdf_path, terrain_mode=terrain)
    if success:
        print(f"Simulation OK: robot stable on {terrain} terrain.")
    else:
        print(f"Simulation failed: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
