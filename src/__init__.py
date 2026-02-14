# TreeHackNow — LLM-generated robot URDF

import logging
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root (parent of src/)
load_dotenv(Path(__file__).parent.parent / ".env")

# Configure package-level logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
