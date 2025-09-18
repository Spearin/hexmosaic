# Local Development Setup

This guide walks through preparing a workstation to hack on HexMosaic. The instructions assume familiarity with QGIS plugins and basic Python tooling.

## Prerequisites

- **Operating system:** Windows 10/11, macOS 12+, or a recent Linux distribution (Ubuntu 22.04 LTS tested).
- **QGIS Desktop:** Install QGIS 3.22 LTR or newer from https://qgis.org. The plugin targets the current LTR plus the latest stable release.
- **Python:** Use the interpreter that ships with your QGIS install. Mixing system Python versions can cause ABI errors with the QGIS bindings.
- **Build tools:**
  - `pip`, `virtualenv` (Python standard tooling)
  - `pb_tool` (`pip install pb_tool`) for packaging/deployment
  - Optional: `make` (ships with Xcode Command Line Tools on macOS; install `build-essential` on Linux; use MSYS2/WSL or `nmake` alternatives on Windows if Make is unavailable)

## Repository Checkout

```bash
git clone https://github.com/<org>/hexmosaic.git
cd hexmosaic
```

If you plan to contribute back, fork the repository first and clone your fork.

## Python Environment

Creating a virtual environment is optional but keeps lint/test dependencies isolated from QGIS system packages.

```bash
# Use the QGIS Python executable (replace path with your installation)
"C:\Program Files\QGIS 3.34\apps\Python39\python.exe" -m venv .venv

# Activate the environment
.venv\Scripts\activate        # Windows PowerShell
source .venv/bin/activate      # macOS / Linux

# Upgrade tooling and install dev helpers
pip install --upgrade pip wheel
pip install pb_tool pytest pylint
```

If you need additional dependencies, document them in `docs/dev-setup/local.md` and `README.md` so other contributors stay in sync.

To run scripts that require QGIS modules outside the QGIS shell, set the environment variables exported by `scripts/run-env-linux.sh` (adapt the paths for your platform) before invoking Python.

## Linking the Plugin into QGIS

QGIS loads plugins from a profile-specific directory. Point QGIS at your working copy using one of the methods below.

| Platform | Plugin directory |
| --- | --- |
| Windows | `%AppData%\QGIS\QGIS3\profiles\default\python\plugins` |
| macOS | `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins` |
| Linux | `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins` |

Options:

1. **Symlink:** Create a symbolic link from the plugin directory to your checkout.
2. **Deploy via Make:** `make deploy` copies the plugin into your profile (requires `make`).
3. **Deploy via pb_tool:** `pb_tool deploy` mirrors the contents specified in `pb_tool.cfg`.

After deploying, start QGIS (or refresh from the Plugin Manager) to load the latest code.

## Common Development Commands

```bash
make compile         # Regenerate resources.py from resources.qrc
make transup         # Update .ts translation sources (passes LOCALES)
make transcompile    # Compile .ts files into .qm files
make doc             # Build Sphinx docs into help/build/html
make test            # Run the nose/pytest-based regression suite
make pylint          # Run pylint with project configuration
make pep8            # Run pep8 style checker with local exclusions
```

The Makefile uses the `scripts/update-strings.sh` and `scripts/compile-strings.sh` helpers for translation management. Ensure those scripts are executable (`chmod +x scripts/*.sh`) when working on Unix-like systems.

## Running Tests

- Ensure `PYTHONPATH` includes the project root and QGIS Python libs. On Linux/macOS the `scripts/run-env-linux.sh` script will export the correct paths when sourced.
- From the project root run `make test` or `python -m pytest test`. Tests rely on fixtures in the `test/` directory, including raster samples.
- For headless UI tests on macOS/Linux, start QGIS once to allow it to create the required profile directories.

## Updating Documentation and Assets

- User documentation lives in `help/source/` (Sphinx). Build HTML output with `make doc`.
- Agent, architecture, and developer documentation lives under `docs/`. Update the relevant markdown files alongside code changes.
- Styles reside in `styles/`; keep naming consistent (`hex_tiles.qml`, etc.) so UI automations can pick them up.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `ModuleNotFoundError: No module named 'qgis'` when running tests | Activate the QGIS Python environment or source `scripts/run-env-linux.sh` to populate `PYTHONPATH` and `QGIS_PREFIX_PATH`. |
| Plugin fails to load in QGIS with "missing metadata" | Ensure `metadata.txt` is present in the deployed folder. Re-run `make deploy` or `pb_tool deploy`. |
| Changes not reflected in QGIS | If you copied files instead of symlinking, redeploy the plugin, then restart QGIS (Plugin Manager caching can delay reloads). |
| Translation scripts exit with permission denied | Run `chmod +x scripts/update-strings.sh scripts/compile-strings.sh` and retry. |
| `pyrcc5` not found during `make compile` | Install Qt development tools. On Windows, ensure the QGIS OSGeo4W shell is in PATH; on macOS/Linux install `qt5-base` / `qt5-default`. |

Document any additional recurring issues you encounter here to keep the setup guide current.
