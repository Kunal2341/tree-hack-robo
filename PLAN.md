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

## Phase 5: Web UI Enhancements (Post-MVP)
**Goal:** Improve web UX — export, inspect, manage history.

| Milestone | Deliverable | Files |
|-----------|-------------|-------|
| **5.1 Download URDF** | Add "Download" button to save selected robot as `.urdf` file | `web/templates/index.html`, `web/static/app.js` |
| **5.2 View URDF Source** | Collapsible "View source" section showing raw XML | `web/templates/index.html`, `web/static/app.js`, `web/static/style.css` |
| **5.3 Delete from History** | Trash icon per history item; remove from `_history` | `web/app.py` (add `DELETE /api/robot/<id>`), `web/static/app.js`, `web/templates/index.html` |
| **5.4 Prompt Examples** | Clickable example prompts (e.g. "4-legged dog", "box with wheels") | `web/templates/index.html`, `web/static/app.js` |
| **5.5 History Persistence** | Save `_history` to `output/history.json`; load on startup | `web/app.py` |
| **5.6 Simulation Metrics** | Return distance traveled, final position from `simulate_urdf` | `src/simulate.py`, `web/app.py`, `web/static/app.js` |

### Implementation Order
1. **5.1** — Download (client-only: create Blob + `<a download>`)
2. **5.2** — View source (client-only: collapsible `<pre>` with URDF)
3. **5.3** — Delete (API + client)
4. **5.4** — Examples (client-only: preset buttons)
5. **5.5** — Persistence (server: load/save JSON)
6. **5.6** — Metrics (simulate.py changes + API + UI display)

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
├── web/
│   ├── app.py           # Flask — /api/generate, /api/refine, /api/simulate, /api/robot
│   ├── templates/       # index.html
│   └── static/          # app.js, style.css
├── prompts/
│   └── system_prompt.txt
├── output/              # Generated URDFs, history.json (Phase 5.5)
└── tests/
```

---

## GitHub Setup
1. Create repo on GitHub (github.com/new)
2. `git remote add origin <url>`
3. Iterative commits per phase/milestone
