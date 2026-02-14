"""
Phase 3: Intelligent loop — feed simulator errors back to LLM, retry with max_retries.
Phase 4: Chain-of-thought for multi-legged robots.
"""

import os
from pathlib import Path

from openai import OpenAI

from src.generate import generate_robot, extract_urdf_from_response
from src.validate import validate_all
from src.simulate import simulate_urdf

SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system_prompt.txt"
OUTPUT_DIR = Path(__file__).parent.parent / "output"

MAX_RETRIES = 5


def load_system_prompt() -> str:
    with open(SYSTEM_PROMPT_PATH) as f:
        return f.read().strip()


def build_leg_prompt(base_prompt: str, num_legs: int) -> str:
    """
    Phase 4 Day 19: Chain-of-thought for multi-legged robots.
    Instruct LLM to compute angles and (x,y) coords before generating XML.
    """
    angle_step = 360 / num_legs
    angles = ", ".join(str(i * angle_step) for i in range(num_legs))
    return f"""You are generating a {num_legs}-legged robot.

FIRST, calculate the angle for each leg: {angles} degrees.
THEN, for a cylindrical body of radius ~0.3m, compute (x,y) for each leg mount:
  - angle_rad = angle_deg * pi/180
  - x = 0.3 * cos(angle_rad)
  - y = 0.3 * sin(angle_rad)
FINALLY, generate the URDF XML with each leg at its computed (x, y, 0) offset.

User request: {base_prompt}"""


def is_multi_leg_request(prompt: str) -> tuple[bool, int]:
    """Detect if user wants a multi-legged robot."""
    prompt_lower = prompt.lower()
    for n, word in [(4, "four"), (4, "4"), (6, "six"), (6, "6"), (8, "eight")]:
        if str(n) in prompt or word in prompt_lower:
            if "leg" in prompt_lower or "legged" in prompt_lower or "quadruped" in prompt_lower or "hexapod" in prompt_lower:
                return True, n
    return False, 0


def run_agent(prompt: str, save_path: Path | None = None) -> tuple[bool, str, str]:
    """
    Generate → Validate → Simulate. On failure, retry with error feedback (max 5).
    Returns (success, final_urdf, message).
    """
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    system = load_system_prompt()

    multi_leg, num_legs = is_multi_leg_request(prompt)
    current_prompt = build_leg_prompt(prompt, num_legs) if (multi_leg and num_legs > 0) else prompt

    for attempt in range(MAX_RETRIES):
        # Generate
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": current_prompt},
            ],
        )
        raw = response.choices[0].message.content
        urdf = extract_urdf_from_response(raw)

        # Validate
        valid, err = validate_all(urdf)
        if not valid:
            current_prompt = (
                f"The previous robot failed validation: {err}\n\n"
                f"Original request: {prompt}\n\n"
                "Fix the URDF and output ONLY valid XML."
            )
            continue

        # Simulate
        OUTPUT_DIR.mkdir(exist_ok=True)
        test_path = OUTPUT_DIR / "agent_test.urdf"
        test_path.write_text(urdf)
        success, sim_err = simulate_urdf(test_path)

        if success:
            if save_path:
                save_path.write_text(urdf)
            return True, urdf, "OK"
        else:
            current_prompt = (
                f"The previous robot failed simulation: {sim_err}\n\n"
                f"Original request: {prompt}\n\n"
                "Fix the URDF (check link positions, joint limits, effort) and output ONLY valid XML."
            )

    return False, "", f"Failed after {MAX_RETRIES} retries. Human help needed."


def main():
    import sys
    prompt = sys.argv[1] if len(sys.argv) > 1 else "A 4-legged dog robot"
    success, urdf, msg = run_agent(prompt)
    if success:
        out = OUTPUT_DIR / "robot.urdf"
        out.write_text(urdf)
        print(f"Success! Saved to {out}")
    else:
        print(msg)
        sys.exit(1)


if __name__ == "__main__":
    main()
