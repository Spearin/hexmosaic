# Contributing

Thank you for helping improve HexMosaic. These guidelines keep contributions predictable for maintainers, downstream users, and automation agents.

## Community Expectations

- Be respectful and collaborative in all project spaces. When unsure, mirror the QGIS community's constructive, inclusive tone.
- Assume positive intent. Flag blockers early and describe what you already tried so others can assist quickly.
- Prefer asynchronous discussion in issues or pull requests so the history is preserved for future contributors.

## Getting Help

- Start with `docs/overview.md` for a high-level walkthrough of the plugin.
- Agent-focused resources live under `docs/agent/` (cheat sheet, task recipes, glossary).
- File GitHub issues for bugs or feature ideas. Include environment details, reproduction steps, and logs or screenshots when relevant.
- Use draft pull requests for early feedback or when you need guidance on implementation direction.

## Toolchain Requirements

| Component | Supported versions | Notes |
| --- | --- | --- |
| Python | 3.10+ (match your QGIS build) | Prefer the interpreter bundled with QGIS to avoid ABI mismatches. |
| QGIS Desktop | 3.22 LTR or newer | Validate on both the current LTR and latest stable when possible. |
| Qt / PyQt | Qt5 / PyQt5 (default in QGIS 3.x) | Keep `supportsQt6` in `metadata.txt` accurate if support changes. |
| pb_tool | >= 3.4 | Automates packaging and deployment; install with `pip install pb_tool`. |
| Optional: Node/npm | Latest LTS | Needed only for docs or tooling that require node-based pipelines. |

Declare any new runtime dependency in `README.md` and mirror the change in `docs/dev-setup/`.

## Local Development Setup

1. Install QGIS 3.22+ for your platform and confirm the bundled Python version.
2. Clone the repository and create a virtual environment (optional but recommended for linting and tooling):
   ```bash
   git clone https://github.com/<org>/hexmosaic.git
   cd hexmosaic
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # macOS / Linux
   source .venv/bin/activate
   python -m pip install --upgrade pip wheel
   pip install -r requirements-dev.txt  # create/update as needed
   ```
3. Link the plugin into your QGIS profile during development:
   - Windows: `%AppData%\QGIS\QGIS3\profiles\default\python\plugins`
   - macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins`
   - Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins`

   Use `make deploy`, `pb_tool deploy`, or create a symlink pointing to your checkout. Restart QGIS to reload the plugin.
4. Build optional assets when they change:
   - Resources: `make compile` regenerates `resources.py` from `resources.qrc`.
   - Translations: `make transcompile` creates `.qm` files; `make transup` updates `.ts` sources.
   - Help site: `make doc` builds the Sphinx HTML docs under `help/build/html`.

Capture recurring setup tips in `docs/dev-setup/local.md` so new contributors and agents benefit from tribal knowledge.

## Cloud / CI Environments

- Review `docs/dev-setup/cloud.md` for recommended base images and QGIS provisioning notes.
- Headless tests rely on the fixtures in `test/`. Mock QGIS APIs with `test/qgis_interface.py` when the real libraries are unavailable.
- Cache heavy downloads (DEM, OSM) between CI runs where possible; document cache keys in the workflow configuration.

## Branching and Workflow

- Work on feature branches named `feature/<short-description>` or `bugfix/<ticket-id>`.
- Keep each branch focused on a single logical change. Split large efforts into reviewable slices.
- Rebase on `master` (or the active release branch) before opening a pull request to minimize merge conflicts.
- Commit messages should explain the why as well as the what. Reference issue numbers when applicable (`Fixes #123`).

## Coding Standards

- Follow PEP 8 with project-specific exceptions defined in `pylintrc` and noted in the Makefile.
- Add docstrings for functions that have non-obvious behavior or interact with QGIS APIs.
- Prefer enhancing utilities in `utils/` instead of creating one-off helpers. When adding helpers, include accompanying tests.
- Keep type hints current where feasible to improve IDE support and agent reasoning.

## Tests and Quality Gates

- Run unit tests before pushing:
  ```bash
  make test
  # or
  python -m pytest test
  ```
  If QGIS modules are missing, source `scripts/run-env-linux.sh <path-to-qgis>` (adapt similar scripts per platform) to populate `PYTHONPATH`.
- Run linting and style checks:
  ```bash
  make pylint
  make pep8
  ```
- Add or update tests alongside code changes. Use fixtures under `test/` or create new ones when necessary.
- Provide screenshots or sample exports for UI or styling changes to aid reviewers.
- Document known testing gaps or follow-up work in `docs/tests.md`.

## Documentation

- Update user-facing guides (`README.md`, `help/`) whenever behavior changes.
- Maintain technical references under `docs/` in lockstep with code updates (architecture, how-tos, agent material).
- Log significant architectural decisions using an ADR in `docs/adr/` (follow sequential numbering `0001`, `0002`, ...).

## Pull Request Checklist

- [ ] Tests and linters pass locally (`make test`, `make pylint`, `make pep8`).
- [ ] New or changed functionality includes documentation updates (user and technical).
- [ ] UI updates include screenshots or screencasts.
- [ ] Release notes impact reviewed (draft entry per `docs/release.md` if needed).
- [ ] PR description links related issues and lists validation steps.

During review:

- Respond to feedback promptly and push follow-up commits rather than rewriting history, unless reviewers agree to a rebase.
- Resolve conversations only when the underlying concern has been addressed.

## Release Coordination

- Follow the detailed checklist in `docs/release.md`.
- Update `metadata.txt` with the new version, changelog, and compatibility flags.
- Build and validate the package:
  ```bash
  pb_tool build
  pb_tool package
  ```
  or
  ```bash
  make package VERSION=Version_<major>.<minor>.<patch>
  ```
- Smoke-test the packaged plugin in a clean QGIS profile.
- Upload using `plugin_upload.py` (see `pb_tool.cfg`) or via the QGIS Plugin Repository web UI.
- Tag the release in git and announce through the agreed communication channels.

## Housekeeping

- Squash commits only when it clarifies history; otherwise keep meaningful commit boundaries.
- Avoid committing generated artifacts unless required (`resources.py`, compiled translations, packaged zips`).
- Keep `.vscode/`, `.editorconfig`, and other tooling configs aligned with the documented workflows.

## Thanks

Every improvement helps players build better Flashpoint Campaigns maps. If any step in this guide is unclear, open an issue or discussion thread early; maintainers are happy to help refine the workflow for you and future contributors.
