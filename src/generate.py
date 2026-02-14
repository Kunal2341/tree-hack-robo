"""
Phase 1: LLM → URDF generation with RAG-enhanced context.
Usage: python -m src.generate "A box with 4 wheels"
"""

import logging
import os
import re
from pathlib import Path

from openai import OpenAI

from src.validate import validate_urdf_parse

logger = logging.getLogger(__name__)

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
        logger.debug("Extracted URDF XML (%d chars) from LLM response", len(match.group(0)))
        return match.group(0).strip()
    logger.warning("No <?xml ... </robot> block found in LLM response; returning raw text")
    return text.strip()


def generate_robot(prompt: str, output_path: Path | None = None, use_rag: bool = True) -> str:
    """
    Generate URDF from natural language using OpenAI.
    When use_rag=True, retrieves relevant URDF snippets to augment the prompt.
    Returns the raw URDF string.
    """
    logger.info("Generating URDF for prompt: %s", prompt[:80])
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    system = load_system_prompt()

    # RAG: retrieve relevant snippets and augment the prompt
    augmented_prompt = prompt
    if use_rag:
        try:
            from src.rag import build_rag_context
            rag_context = build_rag_context(prompt, top_k=2)
            if rag_context:
                augmented_prompt = f"{rag_context}\n\nUser request: {prompt}"
                logger.info("RAG: Augmented prompt with retrieved snippets")
        except Exception as e:
            logger.warning("RAG retrieval failed (continuing without): %s", e)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": augmented_prompt},
        ],
    )
    raw = response.choices[0].message.content
    urdf = extract_urdf_from_response(raw)
    logger.info("URDF generated successfully (%d chars)", len(urdf))
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
