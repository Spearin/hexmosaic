# Agent Cheat Sheet

Fast answers for common automation tasks inside the HexMosaic repo. For deeper procedures, jump to `docs/agent/task-recipes.md` or the development setup guides.

## High-Frequency Commands

| Task | Command |
| --- | --- |
| Run unit/integration tests | `make test` or `pytest test` |
| Run pylint | `make pylint` |
| Run pep8 style check | `make pep8` |
| Rebuild Qt resources | `make compile` |
| Update translation sources | `make transup` |
| Compile translations | `make transcompile` |
| Build Sphinx docs | `make doc` |
| Deploy to local QGIS profile | `make deploy` or `pb_tool deploy` |
| Package plugin zip | `pb_tool package` or `make package VERSION=Version_X.Y.Z` |

Always run commands from the repository root unless noted otherwise.

## Key Paths & Files

| Path | What lives here |
| --- | --- |
| `hexmosaic.py`, `hexmosaic_dockwidget.py` | Core plugin entry points (business logic + UI wiring). |
| `data/hexmosaic.config.json` | Default configuration values consumed at runtime. |
| `profiles/` | Scenario-specific overrides; profile JSON files are loaded based on user selection. |
| `scripts/` | Helper scripts for translations and environment setup (e.g., `run-env-linux.sh`). |
| `styles/` | `.qml` layer styles referenced when generating grids and helper layers. |
| `utils/` | Shared Python helpers (extend here before adding new modules elsewhere). |
| `test/` | Unit/integration tests plus raster/vector fixtures for automated checks. |
| `help/` | Sphinx documentation source (`help/source/`) and build output (`help/build/html`). |
| `docs/` | Developer, agent, and architecture documentation (Markdown). |

## Configuration & Environment

- `metadata.txt` — ensure version, QGIS compatibility, and flags stay current.
- `pb_tool.cfg` — defines which files ship in deploy/package steps. Update when adding modules.
- Environment variables commonly needed in automation:
  - `QGIS_PREFIX_PATH` (root of your QGIS install)
  - `PYTHONPATH` (include the project root and QGIS Python site-packages)
  - `QT_QPA_PLATFORM=offscreen` for headless runs
  - `OPENTOPOGRAPHY_API_KEY` when exercising DEM downloads

## Quick Workflows

- **Refresh translations:** run `make transup`, review `.ts` diffs, then `make transcompile` to regenerate `.qm` files.
- **Rebuild help docs:** `make doc` and capture `help/build/html` as artifacts if needed.
- **Add new profile:** drop a JSON file into `profiles/`, update any selectors in `hexmosaic.py`, and document the change in `docs/howtos/`.
- **Smoke-test packaging:** `pb_tool package`, unzip the artifact into a clean QGIS profile, and launch QGIS to verify plugin metadata.

## Troubleshooting

| Symptom | Fast check |
| --- | --- |
| `ModuleNotFoundError: qgis` | Source `scripts/run-env-linux.sh` or ensure QGIS Python paths are in `PYTHONPATH`. |
| QGIS ignores local changes | If you copied files, rerun `make deploy` and restart QGIS; symlinks auto-refresh. |
| `pyrcc5` missing | Install Qt development tools (e.g., `qttools5-dev-tools`) or use the QGIS-provided shell. |
| Translation scripts fail with permission error | `chmod +x scripts/update-strings.sh scripts/compile-strings.sh`. |
| Tests hang on CI | Ensure `QT_QPA_PLATFORM=offscreen` or wrap commands with `xvfb-run`. |

## Helpful References

- `docs/dev-setup/local.md` — step-by-step workstation bootstrap.
- `docs/dev-setup/cloud.md` — container/CI guidance.
- `docs/tests.md` — overview of available test suites and fixtures.
- `docs/release.md` — full release checklist.
- `docs/agent/task-recipes.md` — playbooks for multi-step agent tasks.

Update this cheat sheet whenever new automation scripts or workflows land so agents always have the latest runbook.
