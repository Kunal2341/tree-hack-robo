"""
Phase 3: Intelligent loop — feed simulator errors back to LLM, retry with max_retries.
Phase 4: Chain-of-thought for multi-legged robots.
Feature: Iterative refinement — modify existing URDF with follow-up prompts.
"""

import logging
import os
from pathlib import Path

from openai import OpenAI

logger = logging.getLogger(__name__)

from src.generate import extract_urdf_from_response
from src.validate import validate_all
from src.simulate import simulate_urdf, physics_sanity_check

SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system_prompt.txt"
REFINE_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "refine_prompt.txt"
OUTPUT_DIR = Path(__file__).parent.parent / "output"

MAX_RETRIES = 5


def load_system_prompt() -> str:
    with open(SYSTEM_PROMPT_PATH) as f:
        return f.read().strip()


def load_refine_prompt() -> str:
    with open(REFINE_PROMPT_PATH) as f:
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


def run_agent(
    prompt: str,
    save_path: Path | None = None,
    terrain_mode: str = "flat",
) -> tuple[bool, str, str]:
    """
    Generate → Validate → Simulate. On failure, retry with error feedback (max 5).
    terrain_mode: "flat", "uneven", "stairs", or "slope" to test robustness.
    Returns (success, final_urdf, message).
    """
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    system = load_system_prompt()

    multi_leg, num_legs = is_multi_leg_request(prompt)
    current_prompt = build_leg_prompt(prompt, num_legs) if (multi_leg and num_legs > 0) else prompt

    for attempt in range(MAX_RETRIES):
        logger.info("Agent attempt %d/%d for prompt: %s", attempt + 1, MAX_RETRIES, prompt[:60])

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
            logger.warning("Validation failed (attempt %d): %s", attempt + 1, err)
            current_prompt = (
                f"The previous robot failed validation: {err}\n\n"
                f"Original request: {prompt}\n\n"
                "Fix the URDF and output ONLY valid XML."
            )
            continue

        # Write URDF for physics checks
        OUTPUT_DIR.mkdir(exist_ok=True)
        test_path = OUTPUT_DIR / "agent_test.urdf"
        test_path.write_text(urdf)

        # Quick physics sanity check (explosion, fall-over, self-collisions)
        sanity_ok, sanity_err, _sanity_diag = physics_sanity_check(test_path)
        if not sanity_ok:
            logger.warning("Sanity check failed (attempt %d): %s", attempt + 1, sanity_err)
            current_prompt = (
                f"The robot failed a physics sanity check: {sanity_err}\n\n"
                f"Original request: {prompt}\n\n"
                "Fix the URDF to prevent self-collisions, explosions, or immediate collapse. "
                "Ensure links are properly spaced and joint limits are reasonable. Output ONLY valid XML."
            )
            continue

        # Full simulation
        success, sim_err, _metrics = simulate_urdf(test_path, terrain_mode=terrain_mode)

        if success:
            logger.info("Agent succeeded on attempt %d", attempt + 1)
            if save_path:
                save_path.write_text(urdf)
            return True, urdf, "OK"
        else:
            logger.warning("Simulation failed (attempt %d): %s", attempt + 1, sim_err)
            current_prompt = (
                f"The previous robot failed simulation: {sim_err}\n\n"
                f"Original request: {prompt}\n\n"
                "Fix the URDF (check link positions, joint limits, effort) and output ONLY valid XML."
            )

    logger.error("Agent exhausted all %d retries for: %s", MAX_RETRIES, prompt[:60])
    return False, "", f"Failed after {MAX_RETRIES} retries. Human help needed."


def run_agent_refine(
    refinement_prompt: str,
    base_urdf: str,
    save_path: Path | None = None,
    terrain_mode: str = "flat",
) -> tuple[bool, str, str]:
    """
    Iterative refinement: modify an existing URDF based on a follow-up prompt.
    E.g. "make it heavier", "add another wheel", "shorter legs".
    terrain_mode: "flat", "uneven", "stairs", or "slope" to test robustness.
    Returns (success, final_urdf, message).
    """
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    system = load_refine_prompt()

    user_content = f"""Current URDF:

```xml
{base_urdf}
```

Modification request: {refinement_prompt}

Output the complete modified URDF."""

    current_prompt = user_content

    for attempt in range(MAX_RETRIES):
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": current_prompt},
            ],
        )
        raw = response.choices[0].message.content
        urdf = extract_urdf_from_response(raw)

        valid, err = validate_all(urdf)
        if not valid:
            current_prompt = (
                f"The modified robot failed validation: {err}\n\n"
                f"Original modification request: {refinement_prompt}\n\n"
                "Here was the URDF you tried to output:\n\n"
                f"```xml\n{urdf[:2000]}...\n```\n\n"
                "Fix the URDF and output ONLY valid XML."
            )
            continue

        OUTPUT_DIR.mkdir(exist_ok=True)
        test_path = OUTPUT_DIR / "agent_test.urdf"
        test_path.write_text(urdf)

        # Quick physics sanity check
        sanity_ok, sanity_err, _sanity_diag = physics_sanity_check(test_path)
        if not sanity_ok:
            current_prompt = (
                f"The modified robot failed a physics sanity check: {sanity_err}\n\n"
                f"Original modification request: {refinement_prompt}\n\n"
                "Fix the URDF to prevent self-collisions, explosions, or immediate collapse. "
                "Output ONLY valid XML."
            )
            continue

        success, sim_err, _metrics = simulate_urdf(test_path, terrain_mode=terrain_mode)

        if success:
            if save_path:
                save_path.write_text(urdf)
            return True, urdf, "OK"
        else:
            current_prompt = (
                f"The modified robot failed simulation: {sim_err}\n\n"
                f"Original modification request: {refinement_prompt}\n\n"
                "Fix the URDF (check link positions, joint limits, effort) and output ONLY valid XML."
            )

    return False, "", f"Failed after {MAX_RETRIES} retries. Human help needed."


def main():
    import sys
    prompt = sys.argv[1] if len(sys.argv) > 1 else "A 4-legged dog robot"
    terrain = "flat"
    for i, arg in enumerate(sys.argv):
        if arg in ("--terrain", "-t") and i + 1 < len(sys.argv):
            terrain = sys.argv[i + 1].lower()
            break
    success, urdf, msg = run_agent(prompt, terrain_mode=terrain)
    if success:
        out = OUTPUT_DIR / "robot.urdf"
        out.write_text(urdf)
        print(f"Success! Saved to {out}")
    else:
        print(msg)
        sys.exit(1)


if __name__ == "__main__":
    main()
