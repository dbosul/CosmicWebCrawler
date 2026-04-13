# CosmicWebCrawler

Agent harness for autonomous astrophysics research. Recreates PhD-level work finding
Lyman-alpha nebulae around high-redshift quasars (FLASHES Survey methodology).

## Running

```bash
# Activate the venv first
source .venv/bin/activate

python run.py --project <name> --stage <sample|archive|reduce|analyze>
python run.py --project cosmos-pilot --stage sample --dry-run

# Run tests
pytest tests/smoke_test_cosmos_pilot.py -v
```

## Project namespace convention

Every run lives in `projects/<name>/`. The SQLite DB is `projects/<name>/<name>.db`.
Never write files outside the project namespace for a given run.

## Key invariants

- All DB reads/writes go through `src/db.py`. No raw sqlite3 anywhere else.
- Skills write to DB themselves — they do not return data for agents to write.
- `query_history` is the dedup layer. Check it before any catalog query.
- Only coordinators spawn sub-agents. Leaf agents (query-agent, literature-agent) never spawn.
- Literature agents take a `citation_depth` budget. They stop when it hits 0.
- `claude-sonnet-4-6` for coordinators. `claude-haiku-4-5` for leaf agents.

## Architecture

```
research-assistant          top-level orchestrator, manages pipeline stages
└── sample-coordinator      persistent context, owns sampling stage
    ├── skills              query-simbad, query-sdss, query-ned, query-vizier,
    │                       check-data-quality, check-field-of-view, sample-bias
    └── spawns              query-agent (parallel batches)
                            literature-agent (parallel, depth-budget controlled)
```

Archive / Reduction (KCWI + PCWI) / Analysis coordinators: stubs, not yet implemented.

## Skill implementations

Python scripts live in `src/`. Skills in `.claude/skills/<name>/SKILL.md` invoke them via:
```bash
python src/<skill_name>.py --project $PROJECT [args]
```

## Adding a new stage or skill

1. Add Python implementation to `src/`.
2. Create `.claude/skills/<name>/SKILL.md` with frontmatter + invocation instructions.
3. If a new coordinator agent is needed, add `.claude/agents/<name>.md`.
4. Update `run.py` STAGE_COORDINATORS if adding a new pipeline stage.

## Smoke test

Namespace: `cosmos-pilot`
Goal: Find 10 UV-luminous z~2-3 QSOs in the COSMOS field (RA~150.1, Dec~2.2, r~0.75 deg)
      with no known extended Lya emission in the literature.
