# LLM-Generated Robot URDF Project — Implementation Plan

## Overview
Build a system where an LLM generates robot descriptions (URDF), validates them, simulates in physics, and auto-fixes failures.

---

## Phase 1: The "It's Just Text" Phase (Days 1–4)
**Goal:** Get an LLM to generate a valid URDF text file.

| Day | Milestone | Key Deliverable |
|-----|-----------|-----------------|
| 1 | Setup | Python env, `generate_robot("A box with 4 wheels")` |
| 2 | Markdown Bug Fix | Regex: strip before `<?xml` and after `</robot>` |
| 3 | Ghost Robot Fix | System prompt: require both `<visual>` and `<collision>` per link |

---

## Phase 2: The "Exploding Robot" Phase (Days 5–10)
**Goal:** Load URDF into PyBullet without physics explosions.

| Day | Milestone | Key Deliverable |
|-----|-----------|-----------------|
| 5 | First Simulation | `simulate_robot.py` loads URDF, gravity on |
| 6 | Supernova Fix | Bounding box check: wheels at y > chassis_radius |
| 8 | Floppy Noodle Fix | Min effort threshold: reject if effort < 100 |

---

## Phase 3: The "Intelligent Loop" Phase (Days 11–18)
**Goal:** Agent fixes its own mistakes automatically.

| Day | Milestone | Key Deliverable |
|-----|-----------|-----------------|
| 11 | Error Loop | Feed simulator errors back to LLM for retry |
| 13 | Infinite Loop Fix | `max_retries=5` guard |

---

## Phase 4: The "Spider" Phase (Days 19–25)
**Goal:** Handle multi-legged robots (hexapods/quadrupeds).

| Day | Milestone | Key Deliverable |
|-----|-----------|-----------------|
| 19 | Centipede Fix | Chain-of-thought: angles → (x,y) coords → XML |
| 25 | MVP Complete | "4-legged dog robot" → valid URDF → stable sim → saved |

---

## Project Structure
```
TreeHackNow/
├── requirements.txt
├── PLAN.md
├── README.md
├── src/
│   ├── __init__.py
│   ├── generate.py      # LLM → URDF generation
│   ├── validate.py      # urdfpy validation + custom checks
│   ├── simulate.py      # PyBullet simulation
│   └── agent.py         # Intelligent loop (retry + error feedback)
├── prompts/
│   └── system_prompt.txt
├── output/              # Generated URDFs
└── tests/
```

---

## GitHub Setup
1. Create repo on GitHub (github.com/new)
2. `git remote add origin <url>`
3. Iterative commits per phase/milestone
