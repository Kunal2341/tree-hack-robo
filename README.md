# TreeHackNow — LLM-Generated Robot URDF

Generate robot URDF files from natural language using an LLM, validate with urdfpy, and simulate in PyBullet.

---

## Architecture & Design

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              TreeHackNow Pipeline                                │
└─────────────────────────────────────────────────────────────────────────────────┘

  User Prompt                    ┌──────────────┐
  "A 4-legged dog"    ──────────►│   generate   │──────────► Raw URDF XML
                                 │   (LLM)      │
                                 └──────┬───────┘
                                        │
                                        ▼
                                 ┌──────────────┐
                                 │   validate   │──────────► Parse + custom checks
                                 │  (urdfpy)    │
                                 └──────┬───────┘
                                        │
                                        ▼
                                 ┌──────────────┐
                                 │   simulate   │──────────► PyBullet physics
                                 │  (PyBullet)  │
                                 └──────┬───────┘
                                        │
                                        ▼
                                 output/robot.urdf
```

### Data Flow

```
Natural Language ──► LLM (GPT-4o-mini) ──► URDF XML ──► Validation ──► Simulation ──► Saved URDF
                         │                      │              │
                         │                      │              └── On failure: error feedback → retry
                         │                      └── On failure: error feedback → retry
                         └── System prompt + optional chain-of-thought (multi-legged)
```

### Component Architecture

| Module | Responsibility | Key Functions |
|--------|----------------|---------------|
| **`src/generate.py`** | LLM-based URDF generation | `generate_robot()`, `extract_urdf_from_response()` |
| **`src/validate.py`** | URDF correctness & physics sanity | `validate_all()`, `validate_urdf_parse()`, `check_link_positions()`, `check_effort_limits()` |
| **`src/simulate.py`** | Physics simulation in PyBullet | `simulate_urdf()` — loads URDF, terrain modes (flat/uneven/stairs/slope), 5s sim |
| **`src/agent.py`** | Orchestrator with retry loop | `run_agent()` — Generate → Validate → Simulate, up to 5 retries with error feedback |

### Design Decisions

1. **Separation of concerns** — Generation, validation, and simulation are independent modules. Each can be run standalone (`python -m src.generate`, `python -m src.simulate`) or composed by the agent.

2. **Error feedback loop** — When validation or simulation fails, the error message is fed back into the LLM prompt so it can fix the URDF. Max 5 retries prevents infinite loops.

3. **Multi-legged chain-of-thought** — For prompts like "4-legged dog" or "hexapod", the agent injects a structured prompt that instructs the LLM to: (a) compute angles for each leg, (b) compute (x,y) mount positions from body radius, (c) then generate XML. This avoids legs overlapping at (0,0,0).

4. **Validation layers**:
   - **Parse** — `urdfpy` ensures valid URDF syntax and structure.
   - **Link positions** — Child links (wheels, legs) must be offset from parent to avoid self-collision.
   - **Effort limits** — Joint effort ≥ 100 to prevent "floppy noodle" robots.

5. **Simulation stability check** — If the robot base moves >50m from origin during the 5s sim, it's considered "exploded" (unstable).

### File Structure

```
TreeHackNow/
├── src/
│   ├── agent.py         # Orchestrator: retry loop + error feedback
│   ├── generate.py      # LLM → URDF (OpenAI API)
│   ├── simulate.py      # PyBullet physics (headless or GUI)
│   └── validate.py      # urdfpy + custom checks
├── web/
│   ├── app.py           # Flask server — /api/generate, /api/refine, /api/simulate
│   ├── templates/       # index.html
│   └── static/          # app.js, style.css — 3D preview (Three.js + urdf-loader)
├── prompts/
│   └── system_prompt.txt   # LLM system instructions
├── output/                  # Generated URDFs (agent_test.urdf, robot.urdf)
├── package.json         # npm run web — start localhost server
├── requirements.txt
└── environment.yml
```

### External Dependencies

| Dependency | Purpose |
|------------|---------|
| **OpenAI** | LLM API for natural language → URDF generation |
| **urdfpy** | Parse and validate URDF XML |
| **PyBullet** | Physics simulation (gravity, collision, stability) |

---

## Setup

**Conda (recommended):**

```bash
conda env create -f environment.yml
conda activate treehacknow
```

**Or pip only:**

```bash
pip install -r requirements.txt
```

> **Note:** PyBullet may require building from source on some systems. If simulation fails, generation and validation still work. On macOS ARM, you may need `brew install cmake` first.

Set your OpenAI API key:
```bash
export OPENAI_API_KEY="your-key-here"
```

## Usage

### Web UI (recommended)

```bash
npm run web
```

Then open **http://localhost:5000** in your browser. You get:
- **Generate** — describe a robot (e.g. "A 4-legged dog"), get URDF + 3D preview
- **Refine** — select a robot, type a change (e.g. "make it heavier"), get updated URDF
- **Simulate** — run PyBullet physics on flat/uneven/stairs/slope terrain

### CLI

```bash
# Generate a robot (simple)
python -m src.generate "A box with 4 wheels"

# Simulate a URDF (with optional terrain mode)
python -m src.simulate output/robot.urdf
python -m src.simulate output/robot.urdf --terrain uneven   # uneven, stairs, slope
# Terrain modes: flat (default), uneven, stairs, slope — test robustness

# Full agent loop (validate + simulate + retry on failure)
python -m src.agent "A 4-legged dog robot"
python -m src.agent "A 4-legged dog" --terrain slope   # optional terrain for sim

# Web UI (same as above)
npm run web
```

## Plan

See [PLAN.md](PLAN.md) for the full implementation roadmap. **Phase 5** covers web UI enhancements: Download URDF, View source, Delete from history, Prompt examples, History persistence, Simulation metrics.
