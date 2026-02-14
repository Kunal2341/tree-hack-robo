"""
Image-to-URDF: Analyze a robot sketch/diagram/photo using GPT-4o vision
and generate a corresponding URDF description.

Supports:
  - analyze_robot_image(image_path_or_base64) → text description
  - image_to_urdf(image_path_or_base64) → URDF XML string
"""

import base64
import logging
import os
import re
from pathlib import Path

from openai import OpenAI

logger = logging.getLogger(__name__)


VISION_ANALYSIS_PROMPT = """You are an expert robotics engineer. Analyze this image of a robot (it could be a sketch, diagram, CAD drawing, photo, or schematic).

Describe the robot's structure in detail:
1. What type of robot is it? (wheeled, legged, arm, drone, etc.)
2. How many links/segments does it have?
3. What types of joints connect them? (revolute, prismatic, fixed, continuous)
4. What are approximate dimensions and proportions?
5. What is the kinematic chain? (which links connect to which)
6. Any special features? (grippers, sensors, turrets, etc.)

Be precise and technical. Your description will be used to generate a URDF file."""


VISION_TO_URDF_PROMPT = """You are a robot URDF generator with computer vision. You are given an image of a robot (sketch, diagram, photo, or schematic).

Analyze the image and generate a valid URDF XML file that represents the robot shown.

RULES:
1. Output ONLY valid URDF XML. No markdown, no explanations — just the raw XML.
2. Start with <?xml and end with </robot>.
3. For every link, define both <visual> and <collision> blocks with identical geometry.
4. Use appropriate primitive shapes (box, cylinder, sphere) to approximate the robot's geometry.
5. Set realistic joint types, limits, and effort values.
6. Offset child links properly from parents — never place them at (0,0,0) relative to parent.
7. Include proper <inertial> blocks with realistic mass and inertia values.
8. For revolute joints, set effort limits to at least 1000.0 for heavy robots.
9. Try to match the proportions and structure visible in the image as closely as possible."""


def _encode_image(image_path: str | Path) -> tuple[str, str]:
    """
    Read and base64-encode an image file.
    Returns (base64_string, media_type).
    """
    path = Path(image_path)
    suffix = path.suffix.lower()

    media_type_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_type_map.get(suffix, "image/png")

    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")

    return data, media_type


def _build_image_content(image_input: str) -> dict:
    """
    Build the image content block for OpenAI API.

    image_input can be:
    - A file path (string ending in image extension)
    - A base64-encoded string (prefixed with 'data:image/...' or raw base64)
    - A URL (starting with 'http')
    """
    if image_input.startswith("http://") or image_input.startswith("https://"):
        return {"type": "image_url", "image_url": {"url": image_input}}

    if image_input.startswith("data:image/"):
        return {"type": "image_url", "image_url": {"url": image_input}}

    # Try as file path
    path = Path(image_input)
    if path.exists() and path.is_file():
        b64_data, media_type = _encode_image(path)
        data_url = f"data:{media_type};base64,{b64_data}"
        return {"type": "image_url", "image_url": {"url": data_url}}

    # Assume raw base64
    data_url = f"data:image/png;base64,{image_input}"
    return {"type": "image_url", "image_url": {"url": data_url}}


def analyze_robot_image(image_input: str) -> str:
    """
    Analyze a robot image and return a detailed textual description.

    Parameters
    ----------
    image_input : str
        File path, URL, or base64-encoded image data.

    Returns
    -------
    str
        Detailed description of the robot's structure.
    """
    logger.info("Analyzing robot image...")
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    image_content = _build_image_content(image_input)

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_ANALYSIS_PROMPT},
                    image_content,
                ],
            }
        ],
        max_tokens=1000,
    )

    description = response.choices[0].message.content
    logger.info("Image analysis complete (%d chars)", len(description))
    return description


def image_to_urdf(image_input: str, additional_prompt: str = "") -> str:
    """
    Generate URDF XML directly from a robot image.

    Uses GPT-4o vision to analyze the image and generate corresponding URDF.

    Parameters
    ----------
    image_input : str
        File path, URL, or base64-encoded image data.
    additional_prompt : str
        Optional additional instructions (e.g., "make it larger", "add a gripper").

    Returns
    -------
    str
        Valid URDF XML string.
    """
    logger.info("Generating URDF from image...")
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    image_content = _build_image_content(image_input)

    text_prompt = VISION_TO_URDF_PROMPT
    if additional_prompt:
        text_prompt += f"\n\nAdditional instructions: {additional_prompt}"

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text_prompt},
                    image_content,
                ],
            }
        ],
        max_tokens=4000,
    )

    raw = response.choices[0].message.content

    # Extract URDF XML from response
    match = re.search(r"<\?xml[\s\S]*?</robot>", raw, re.IGNORECASE | re.DOTALL)
    if match:
        urdf = match.group(0).strip()
        logger.info("URDF generated from image (%d chars)", len(urdf))
        return urdf

    logger.warning("No URDF XML found in vision response; returning raw")
    return raw.strip()


def image_to_urdf_two_stage(image_input: str, additional_prompt: str = "") -> tuple[str, str]:
    """
    Two-stage image-to-URDF pipeline:
    1. Analyze the image to get a detailed description
    2. Use that description (+ RAG context) to generate URDF

    Returns (description, urdf_xml).
    """
    # Stage 1: Analyze
    description = analyze_robot_image(image_input)

    # Stage 2: Generate URDF from description
    # Import here to avoid circular imports
    from src.rag import build_rag_context

    rag_context = build_rag_context(description, top_k=2)

    combined_prompt = f"""Based on the following robot description (from analyzing an image):

{description}

{rag_context}

{f'Additional instructions: {additional_prompt}' if additional_prompt else ''}

Generate a complete, valid URDF XML file for this robot."""

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    # Load the system prompt
    system_prompt_path = Path(__file__).parent.parent / "prompts" / "system_prompt.txt"
    system_prompt = system_prompt_path.read_text().strip()

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": combined_prompt},
        ],
    )

    raw = response.choices[0].message.content
    match = re.search(r"<\?xml[\s\S]*?</robot>", raw, re.IGNORECASE | re.DOTALL)
    urdf = match.group(0).strip() if match else raw.strip()

    return description, urdf
