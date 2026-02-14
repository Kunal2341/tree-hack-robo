"""
Format converters: URDF → MJCF (MuJoCo) and URDF → SDF (Gazebo).

Supports:
  - urdf_to_mjcf(urdf_str) → MJCF XML string
  - urdf_to_sdf(urdf_str) → SDF XML string
  - Also: direct LLM generation of MJCF / SDF from natural language
"""

import logging
import math
import os
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom
from pathlib import Path

from openai import OpenAI

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: pretty-print XML
# ---------------------------------------------------------------------------
def _pretty_xml(root: ET.Element) -> str:
    """Return a nicely indented XML string from an ElementTree Element."""
    rough = ET.tostring(root, encoding="unicode")
    parsed = minidom.parseString(rough)
    lines = parsed.toprettyxml(indent="  ").split("\n")
    # Remove the XML declaration minidom adds (we'll add our own)
    return "\n".join(line for line in lines if not line.startswith("<?xml"))


def _parse_urdf(urdf_str: str) -> ET.Element:
    """Parse URDF XML string, stripping any leading junk."""
    # Strip anything before <?xml
    match = re.search(r"<\?xml[\s\S]*", urdf_str)
    clean = match.group(0) if match else urdf_str
    return ET.fromstring(clean)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def _convert_geometry(geom_el: ET.Element, parent_tag: str = "geometry") -> ET.Element:
    """Convert a URDF <geometry> element to MJCF-style geom attributes dict."""
    new_geom = ET.Element("geom")

    for child in geom_el:
        tag = child.tag.lower()
        if tag == "box":
            size = child.get("size", "0.1 0.1 0.1")
            # URDF box size is full extents; MJCF uses half-extents
            halfs = " ".join(str(float(v) / 2) for v in size.split())
            new_geom.set("type", "box")
            new_geom.set("size", halfs)
        elif tag == "cylinder":
            r = child.get("radius", "0.05")
            l = child.get("length", "0.1")
            new_geom.set("type", "cylinder")
            # MJCF cylinder size = "radius half-length"
            new_geom.set("size", f"{r} {float(l) / 2}")
        elif tag == "sphere":
            r = child.get("radius", "0.05")
            new_geom.set("type", "sphere")
            new_geom.set("size", r)
        elif tag == "mesh":
            filename = child.get("filename", "")
            new_geom.set("type", "mesh")
            new_geom.set("mesh", filename)

    return new_geom


def _origin_to_pos_euler(origin_el) -> tuple[str, str]:
    """Extract pos and euler from a URDF <origin> element."""
    if origin_el is None:
        return "0 0 0", "0 0 0"
    xyz = origin_el.get("xyz", "0 0 0")
    rpy = origin_el.get("rpy", "0 0 0")
    return xyz, rpy


# ---------------------------------------------------------------------------
# URDF → MJCF
# ---------------------------------------------------------------------------
def urdf_to_mjcf(urdf_str: str) -> str:
    """
    Convert a URDF XML string to a MuJoCo MJCF XML string.

    This performs a structural conversion:
    - URDF links → MJCF bodies with geoms and inertials
    - URDF joints → MJCF joint elements inside child bodies
    - Visual/collision geometries → MJCF geoms
    - Mass/inertia properties preserved
    """
    urdf_root = _parse_urdf(urdf_str)
    robot_name = urdf_root.get("name", "robot")

    # Build lookup tables
    links = {}
    for link_el in urdf_root.findall("link"):
        links[link_el.get("name")] = link_el

    joints = []
    parent_child_map = {}  # child_name → (joint_el, parent_name)
    children_of = {}       # parent_name → [child_names]

    for joint_el in urdf_root.findall("joint"):
        joints.append(joint_el)
        parent_name = joint_el.find("parent").get("link")
        child_name = joint_el.find("child").get("link")
        parent_child_map[child_name] = (joint_el, parent_name)
        children_of.setdefault(parent_name, []).append(child_name)

    # Find root link (not a child of any joint)
    all_children = set(parent_child_map.keys())
    root_links = [name for name in links if name not in all_children]
    root_link_name = root_links[0] if root_links else list(links.keys())[0]

    # Build MJCF
    mujoco = ET.Element("mujoco", model=robot_name)

    # Compiler settings
    compiler = ET.SubElement(mujoco, "compiler", angle="radian", coordinate="local")

    # Option
    option = ET.SubElement(mujoco, "option", gravity="0 0 -9.81", timestep="0.002")

    # Worldbody
    worldbody = ET.SubElement(mujoco, "worldbody")

    # Ground plane
    ET.SubElement(worldbody, "geom", type="plane", size="5 5 0.1",
                  rgba="0.8 0.8 0.8 1", name="floor")
    ET.SubElement(worldbody, "light", diffuse="0.8 0.8 0.8",
                  pos="0 0 3", dir="0 0 -1")

    # Actuator section (filled as we create joints)
    actuator = ET.SubElement(mujoco, "actuator")

    def _build_body(link_name: str, parent_el: ET.Element):
        """Recursively build MJCF body tree."""
        link_el = links.get(link_name)
        if link_el is None:
            return

        body = ET.SubElement(parent_el, "body", name=link_name)

        # Set position from joint origin if this link has a parent joint
        if link_name in parent_child_map:
            joint_el, _ = parent_child_map[link_name]
            origin = joint_el.find("origin")
            pos, euler = _origin_to_pos_euler(origin)
            body.set("pos", pos)
            if euler != "0 0 0":
                body.set("euler", euler)

            # Add joint
            joint_type = joint_el.get("type", "revolute")
            joint_name = joint_el.get("name", f"joint_{link_name}")

            if joint_type in ("revolute", "continuous"):
                jnt = ET.SubElement(body, "joint", name=joint_name, type="hinge")
                axis_el = joint_el.find("axis")
                if axis_el is not None:
                    jnt.set("axis", axis_el.get("xyz", "0 0 1"))
                limit_el = joint_el.find("limit")
                if limit_el is not None and joint_type == "revolute":
                    lower = limit_el.get("lower", "-3.14")
                    upper = limit_el.get("upper", "3.14")
                    jnt.set("range", f"{lower} {upper}")
                # Add motor actuator
                motor = ET.SubElement(actuator, "motor", joint=joint_name,
                                      name=f"motor_{joint_name}")
                if limit_el is not None:
                    effort = limit_el.get("effort", "100")
                    motor.set("ctrllimited", "true")
                    motor.set("ctrlrange", f"-{effort} {effort}")

            elif joint_type == "prismatic":
                jnt = ET.SubElement(body, "joint", name=joint_name, type="slide")
                axis_el = joint_el.find("axis")
                if axis_el is not None:
                    jnt.set("axis", axis_el.get("xyz", "0 0 1"))
                limit_el = joint_el.find("limit")
                if limit_el is not None:
                    lower = limit_el.get("lower", "0")
                    upper = limit_el.get("upper", "1")
                    jnt.set("range", f"{lower} {upper}")
                motor = ET.SubElement(actuator, "motor", joint=joint_name,
                                      name=f"motor_{joint_name}")
            # fixed joints → no joint element (just body nesting)

        # Inertial
        inertial_el = link_el.find("inertial")
        if inertial_el is not None:
            mass_el = inertial_el.find("mass")
            if mass_el is not None:
                inertial = ET.SubElement(body, "inertial",
                                         mass=mass_el.get("value", "1.0"),
                                         pos="0 0 0")

        # Visual geometries → geoms
        for visual in link_el.findall("visual"):
            geom_el = visual.find("geometry")
            if geom_el is not None:
                geom = _convert_geometry(geom_el)
                geom.set("name", f"{link_name}_visual")
                # Origin offset
                origin = visual.find("origin")
                if origin is not None:
                    pos, _ = _origin_to_pos_euler(origin)
                    geom.set("pos", pos)
                # Material color
                mat = visual.find("material")
                if mat is not None:
                    color = mat.find("color")
                    if color is not None:
                        geom.set("rgba", color.get("rgba", "0.5 0.5 0.5 1"))
                body.append(geom)

        # Collision geometries → contype/conaffinity geoms
        for collision in link_el.findall("collision"):
            geom_el = collision.find("geometry")
            if geom_el is not None:
                geom = _convert_geometry(geom_el)
                geom.set("name", f"{link_name}_collision")
                geom.set("contype", "1")
                geom.set("conaffinity", "1")
                origin = collision.find("origin")
                if origin is not None:
                    pos, _ = _origin_to_pos_euler(origin)
                    geom.set("pos", pos)
                body.append(geom)

        # Recurse into children
        for child_name in children_of.get(link_name, []):
            _build_body(child_name, body)

    # Build from root
    _build_body(root_link_name, worldbody)

    return '<?xml version="1.0" encoding="utf-8"?>\n' + _pretty_xml(mujoco)


# ---------------------------------------------------------------------------
# URDF → SDF
# ---------------------------------------------------------------------------
def urdf_to_sdf(urdf_str: str) -> str:
    """
    Convert a URDF XML string to an SDF (Simulation Description Format) XML string.

    SDF is used by Gazebo. This performs a structural conversion:
    - Wraps in <sdf><model>
    - URDF links → SDF <link> with <visual>, <collision>, <inertial>
    - URDF joints → SDF <joint> with <parent>, <child>, <axis>
    """
    urdf_root = _parse_urdf(urdf_str)
    robot_name = urdf_root.get("name", "robot")

    sdf = ET.Element("sdf", version="1.7")
    model = ET.SubElement(sdf, "model", name=robot_name)

    # Static flag
    ET.SubElement(model, "static").text = "false"

    # Convert links
    for link_el in urdf_root.findall("link"):
        link_name = link_el.get("name")
        sdf_link = ET.SubElement(model, "link", name=link_name)

        # Inertial
        inertial_el = link_el.find("inertial")
        if inertial_el is not None:
            sdf_inertial = ET.SubElement(sdf_link, "inertial")

            mass_el = inertial_el.find("mass")
            if mass_el is not None:
                ET.SubElement(sdf_inertial, "mass").text = mass_el.get("value", "1.0")

            inertia_el = inertial_el.find("inertia")
            if inertia_el is not None:
                sdf_inertia = ET.SubElement(sdf_inertial, "inertia")
                for attr in ["ixx", "ixy", "ixz", "iyy", "iyz", "izz"]:
                    ET.SubElement(sdf_inertia, attr).text = inertia_el.get(attr, "0.001")

            origin = inertial_el.find("origin")
            if origin is not None:
                pose = ET.SubElement(sdf_inertial, "pose")
                xyz = origin.get("xyz", "0 0 0")
                rpy = origin.get("rpy", "0 0 0")
                pose.text = f"{xyz} {rpy}"

        # Visual
        for i, visual in enumerate(link_el.findall("visual")):
            sdf_vis = ET.SubElement(sdf_link, "visual", name=f"{link_name}_visual_{i}")

            origin = visual.find("origin")
            if origin is not None:
                pose = ET.SubElement(sdf_vis, "pose")
                xyz = origin.get("xyz", "0 0 0")
                rpy = origin.get("rpy", "0 0 0")
                pose.text = f"{xyz} {rpy}"

            geom_el = visual.find("geometry")
            if geom_el is not None:
                sdf_geom = ET.SubElement(sdf_vis, "geometry")
                _convert_geom_to_sdf(geom_el, sdf_geom)

            mat = visual.find("material")
            if mat is not None:
                sdf_mat = ET.SubElement(sdf_vis, "material")
                color = mat.find("color")
                if color is not None:
                    rgba = color.get("rgba", "0.5 0.5 0.5 1")
                    parts = rgba.split()
                    ET.SubElement(sdf_mat, "ambient").text = rgba
                    ET.SubElement(sdf_mat, "diffuse").text = rgba

        # Collision
        for i, collision in enumerate(link_el.findall("collision")):
            sdf_col = ET.SubElement(sdf_link, "collision", name=f"{link_name}_collision_{i}")

            origin = collision.find("origin")
            if origin is not None:
                pose = ET.SubElement(sdf_col, "pose")
                xyz = origin.get("xyz", "0 0 0")
                rpy = origin.get("rpy", "0 0 0")
                pose.text = f"{xyz} {rpy}"

            geom_el = collision.find("geometry")
            if geom_el is not None:
                sdf_geom = ET.SubElement(sdf_col, "geometry")
                _convert_geom_to_sdf(geom_el, sdf_geom)

    # Convert joints
    for joint_el in urdf_root.findall("joint"):
        joint_name = joint_el.get("name")
        joint_type = joint_el.get("type", "revolute")

        # Map URDF joint types to SDF
        sdf_type_map = {
            "revolute": "revolute",
            "continuous": "revolute",
            "prismatic": "prismatic",
            "fixed": "fixed",
            "floating": "ball",
            "planar": "prismatic",
        }
        sdf_type = sdf_type_map.get(joint_type, "revolute")

        sdf_joint = ET.SubElement(model, "joint", name=joint_name, type=sdf_type)

        parent_el = joint_el.find("parent")
        child_el = joint_el.find("child")
        ET.SubElement(sdf_joint, "parent").text = parent_el.get("link")
        ET.SubElement(sdf_joint, "child").text = child_el.get("link")

        # Pose from origin
        origin = joint_el.find("origin")
        if origin is not None:
            pose = ET.SubElement(sdf_joint, "pose")
            xyz = origin.get("xyz", "0 0 0")
            rpy = origin.get("rpy", "0 0 0")
            pose.text = f"{xyz} {rpy}"

        # Axis
        if sdf_type != "fixed":
            axis_el = joint_el.find("axis")
            sdf_axis = ET.SubElement(sdf_joint, "axis")
            xyz_val = "0 0 1"
            if axis_el is not None:
                xyz_val = axis_el.get("xyz", "0 0 1")
            ET.SubElement(sdf_axis, "xyz").text = xyz_val

            # Limits
            limit_el = joint_el.find("limit")
            if limit_el is not None:
                sdf_limit = ET.SubElement(sdf_axis, "limit")
                if joint_type != "continuous":
                    ET.SubElement(sdf_limit, "lower").text = limit_el.get("lower", "-3.14")
                    ET.SubElement(sdf_limit, "upper").text = limit_el.get("upper", "3.14")
                effort = limit_el.get("effort", "100")
                velocity = limit_el.get("velocity", "1.0")
                ET.SubElement(sdf_limit, "effort").text = effort
                ET.SubElement(sdf_limit, "velocity").text = velocity

    return '<?xml version="1.0" encoding="utf-8"?>\n' + _pretty_xml(sdf)


def _convert_geom_to_sdf(urdf_geom: ET.Element, sdf_geom: ET.Element):
    """Convert URDF geometry children to SDF geometry children."""
    for child in urdf_geom:
        tag = child.tag.lower()
        if tag == "box":
            box = ET.SubElement(sdf_geom, "box")
            ET.SubElement(box, "size").text = child.get("size", "0.1 0.1 0.1")
        elif tag == "cylinder":
            cyl = ET.SubElement(sdf_geom, "cylinder")
            ET.SubElement(cyl, "radius").text = child.get("radius", "0.05")
            ET.SubElement(cyl, "length").text = child.get("length", "0.1")
        elif tag == "sphere":
            sph = ET.SubElement(sdf_geom, "sphere")
            ET.SubElement(sph, "radius").text = child.get("radius", "0.05")
        elif tag == "mesh":
            mesh = ET.SubElement(sdf_geom, "mesh")
            ET.SubElement(mesh, "uri").text = child.get("filename", "")
            scale = child.get("scale")
            if scale:
                ET.SubElement(mesh, "scale").text = scale


# ---------------------------------------------------------------------------
# Direct LLM generation of MJCF / SDF
# ---------------------------------------------------------------------------

MJCF_SYSTEM_PROMPT = """You are a robot MJCF (MuJoCo XML) generator. Given a natural language description, output valid MuJoCo MJCF XML.

RULES:
1. Output ONLY valid MJCF XML. No markdown, no explanations — just the raw XML.
2. Start with <?xml and end with </mujoco>.
3. Include <worldbody> with ground plane, lights, and the robot bodies.
4. Each body must have <geom> elements for visual and collision.
5. Use <joint> elements inside bodies for articulation.
6. Include an <actuator> section with motors for each joint.
7. Set reasonable inertial properties and joint limits."""

SDF_SYSTEM_PROMPT = """You are a robot SDF (Simulation Description Format) generator for Gazebo. Given a natural language description, output valid SDF XML.

RULES:
1. Output ONLY valid SDF XML. No markdown, no explanations — just the raw XML.
2. Start with <?xml and the <sdf version="1.7"> tag.
3. Wrap the robot in a <model> element.
4. Each <link> must have <visual>, <collision>, and <inertial> blocks.
5. Use <joint> elements with proper <parent>, <child>, and <axis>.
6. Set reasonable mass, inertia, effort limits, and joint ranges."""


def generate_mjcf(prompt: str) -> str:
    """Generate MJCF directly from natural language using LLM."""
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": MJCF_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    raw = response.choices[0].message.content
    # Extract XML
    match = re.search(r"<\?xml[\s\S]*?</mujoco>", raw, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(0).strip()
    return raw.strip()


def generate_sdf(prompt: str) -> str:
    """Generate SDF directly from natural language using LLM."""
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SDF_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    raw = response.choices[0].message.content
    match = re.search(r"<\?xml[\s\S]*?</sdf>", raw, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(0).strip()
    return raw.strip()
