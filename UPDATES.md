# Updates

Log of changes, progress, and notable updates.

---

## 2026-02-14

### Initial setup
- Project scaffold: `requirements.txt`, `PLAN.md`, `README.md`
- Output dir and `src` package

### Phase 1 — LLM → URDF
- System prompt with visual+collision requirement (Day 3)
- `validate.py`: urdfpy parse, bounding box check, effort limits
- `generate.py`: `generate_robot()`, regex XML extraction (Day 1+2)

### Phase 2 — Simulation
- `simulate.py`: PyBullet simulation (Day 5)
- Validation: link position check (Day 6), min effort 100 (Day 8)

### Phase 3–4 — Agent loop
- `agent.py`: error feedback loop, `max_retries=5`, multi-leg chain-of-thought

### Docs & tooling
- `GITHUB_SETUP.md` — repo creation and push
- `environment.yml` — conda env
- `CONTRIBUTING.md` — commit guidelines

---

*Add new entries above this line.*
