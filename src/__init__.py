# TreeHackNow — LLM-generated robot URDF

from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root (parent of src/)
load_dotenv(Path(__file__).parent.parent / ".env")
