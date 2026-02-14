# TreeHackNow — LLM-Generated Robot URDF

Generate robot URDF files from natural language using an LLM, validate with urdfpy, and simulate in PyBullet.

## Setup

```bash
pip install -r requirements.txt
```

> **Note:** PyBullet may require building from source on some systems. If simulation fails, generation and validation still work. On macOS ARM, you may need `brew install cmake` first.

Set your OpenAI API key:
```bash
export OPENAI_API_KEY="your-key-here"
```

## Usage

```bash
# Generate a robot (simple)
python -m src.generate "A box with 4 wheels"

# Simulate a URDF
python -m src.simulate output/robot.urdf

# Full agent loop (validate + simulate + retry on failure)
python -m src.agent "A 4-legged dog robot"
```

## Plan

See [PLAN.md](PLAN.md) for the full implementation roadmap.
