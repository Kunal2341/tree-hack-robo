"""
URDF validation: urdfpy parse + custom checks (bounding box, effort limits).
"""

import re
from pathlib import Path

from urdfpy import URDF


def validate_urdf_parse(urdf_str: str) -> tuple[bool, str]:
    """Parse URDF with urdfpy. Returns (valid, error_msg)."""
    try:
        URDF.from_xml_string(urdf_str)
        return True, ""
    except Exception as e:
        return False, str(e)


def get_chassis_size(urdf_str: str) -> float:
    """
    Estimate chassis bounding box size from base link geometry.
    Returns approximate half-extent (radius) in meters.
    """
    robot = URDF.from_xml_string(urdf_str)
    for link in robot.links:
        colls = link.collisions if hasattr(link, "collisions") else ([link.collision] if link.collision else [])
        for coll in colls:
            if coll is not None and coll.geometry is not None:
                geom = coll.geometry
                if hasattr(geom, "size"):
                    s = geom.size
                    return max(s) / 2.0 if hasattr(s, "__len__") else s / 2.0
                if hasattr(geom, "radius"):
                    return geom.radius
    return 0.5  # default


def check_link_positions(urdf_str: str, min_offset: float = 0.5) -> tuple[bool, str]:
    """
    Day 6 Fix: Ensure child links (wheels, legs) are not at same position as parent.
    Returns (valid, error_msg).
    """
    robot = URDF.from_xml_string(urdf_str)
    chassis_size = get_chassis_size(urdf_str)
    threshold = max(min_offset, chassis_size)

    for joint in robot.joints:
        if joint.parent == joint.child:
            continue
        origin = joint.origin
        if origin is None:
            continue
        x, y, z = origin[0, 3], origin[1, 3], origin[2, 3]
        dist = (x**2 + y**2 + z**2) ** 0.5
        if dist < 0.01:  # effectively (0,0,0)
            return False, (
                f"Link '{joint.child}' is at same position as parent. "
                f"Offset must be > {threshold:.2f}m to avoid self-collision."
            )
    return True, ""


def check_effort_limits(urdf_str: str, min_effort: float = 100.0) -> tuple[bool, str]:
    """
    Day 8 Fix: Reject URDF if joint effort is too weak (floppy noodle).
    """
    effort_pattern = re.compile(r'<limit[^>]*effort\s*=\s*["\']([^"\']+)["\']', re.I)
    for m in effort_pattern.finditer(urdf_str):
        try:
            effort = float(m.group(1))
            if effort < min_effort:
                return False, (
                    f"Joint effort {effort} is too weak. "
                    f"Use at least {min_effort} for heavy robots."
                )
        except ValueError:
            pass
    return True, ""


def validate_all(urdf_str: str) -> tuple[bool, str]:
    """Run all validations. Returns (valid, error_msg)."""
    valid, err = validate_urdf_parse(urdf_str)
    if not valid:
        return False, f"Parse error: {err}"

    valid, err = check_link_positions(urdf_str)
    if not valid:
        return False, err

    valid, err = check_effort_limits(urdf_str)
    if not valid:
        return False, err

    return True, ""
