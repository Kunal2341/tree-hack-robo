"""
Phase 1: LLM → URDF generation.
Usage: python -m src.generate "A box with 4 wheels"
"""

import os
import re
from pathlib import Path

from openai import OpenAI

from src.validate import validate_urdf_parse

SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system_prompt.txt"
OUTPUT_DIR = Path(__file__).parent.parent / "output"


def load_system_prompt() -> str:
    with open(SYSTEM_PROMPT_PATH) as f:
        return f.read().strip()


def extract_urdf_from_response(text: str) -> str:
    """
    Day 2 Fix: Strip conversational text and markdown.
    Extract only the XML between <?xml and </robot>.
    """
    # Find <?xml ... </robot>
    match = re.search(r"<\?xml[\s\S]*?</robot>", text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(0).strip()
    return text.strip()


def generate_robot(prompt: str, output_path: Path | None = None) -> str:
    """
    Generate URDF from natural language using OpenAI.
    Returns the raw URDF string.
    """
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    system = load_system_prompt()

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    raw = response.choices[0].message.content
    urdf = extract_urdf_from_response(raw)
    return urdf


def validate_urdf(urdf_str: str) -> tuple[bool, str]:
    """Validate URDF. Returns (valid, error_msg)."""
    return validate_urdf_parse(urdf_str)


def main():
    import sys
    prompt = sys.argv[1] if len(sys.argv) > 1 else "A box with 4 wheels"
    urdf = generate_robot(prompt)
    valid, err = validate_urdf(urdf)
    if valid:
        OUTPUT_DIR.mkdir(exist_ok=True)
        out = OUTPUT_DIR / "robot.urdf"
        out.write_text(urdf)
        print(f"Saved to {out}")
    else:
        print(f"Validation failed: {err}")
        print("Raw URDF:\n", urdf[:500])


if __name__ == "__main__":
    main()
