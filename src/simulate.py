"""
Phase 2: PyBullet simulation.
Usage: python -m src.simulate output/robot.urdf
"""

import os
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


def simulate_urdf(urdf_path: Path) -> tuple[bool, str]:
    """
    Load URDF in PyBullet, run simulation for SIM_DURATION seconds.
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

        robot_id = p.loadURDF(str(urdf_path), [0, 0, 1.0], useFixedBase=False)

        # Run simulation
        steps = int(SIM_DURATION * 240)
        for _ in range(steps):
            p.stepSimulation()

        # Check if robot exploded (parts too far from origin)
        num_joints = p.getNumJoints(robot_id)
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
    urdf_path = Path(path)
    success, err = simulate_urdf(urdf_path)
    if success:
        print("Simulation OK: robot stable.")
    else:
        print(f"Simulation failed: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
