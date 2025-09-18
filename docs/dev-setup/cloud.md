# Cloud Development Setup

Use this reference when configuring CI pipelines, remote workspaces, or disposable environments for HexMosaic. Tailor the steps to your platform, but keep the expectations here aligned so automation can rely on a predictable environment.

## Recommended Base Images

| Scenario | Base image suggestion | Notes |
| --- | --- | --- |
| GitHub Actions / Codespaces | `mcr.microsoft.com/devcontainers/python:3.11` + QGIS layer | Install QGIS from the official repositories or the `qgis.org` nightly apt source. |
| Linux CI (generic) | `qgis/qgis:release-3_34` Docker image | Includes QGIS Desktop, Python, and `qgis` bindings. Add build tooling and pb_tool. |
| Headless testing | `ubuntu:22.04` + QGIS repo | Lightweight, lets you control exactly which QGIS packages are installed. |

Keep Dockerfiles under version control (e.g., `.devcontainer/Dockerfile` or `.ci/Dockerfile`) so updates are reviewable.

## Installing QGIS and Dependencies

### Debian/Ubuntu example

```bash
apt-get update
apt-get install -y gnupg software-properties-common
wget -qO - https://qgis.org/downloads/qgis-2023.gpg.key | gpg --dearmor > /usr/share/keyrings/qgis-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/qgis-archive-keyring.gpg] https://qgis.org/ubuntu $(lsb_release -sc) main" > /etc/apt/sources.list.d/qgis.list
apt-get update
apt-get install -y qgis python3-qgis qgis-plugin-grass qtbase5-dev-tools build-essential python3-pip
pip3 install --upgrade pip wheel
pip3 install pb_tool pytest pylint
```

### Fedora example

```bash
dnf install -y qgis qgis-python qt5-qtbase-devel make python3-pip
echo 'export QGIS_PREFIX_PATH=/usr' >> /etc/profile.d/qgis.sh
pip3 install --upgrade pip wheel
pip3 install pb_tool pytest pylint
```

If QGIS packages are unavailable for your distribution, use the official Docker images as the base and layer on top of them.

## Environment Variables

Set the following before running Python commands that touch QGIS APIs:

```bash
export QGIS_PREFIX_PATH="/usr"                 # Adjust to the root of the QGIS install
export PYTHONPATH="/usr/share/qgis/python:${PYTHONPATH}"
export QT_QPA_PLATFORM=offscreen               # Prevent Qt from requiring a display
```

For GUI-less CI jobs, wrap commands with `xvfb-run` if any tests instantiate QWidget subclasses:

```bash
xvfb-run -s "-screen 0 1024x768x24" make test
```

## Checking Out the Repository

```bash
git clone https://github.com/<org>/hexmosaic.git
cd hexmosaic
pip3 install -r requirements-ci.txt  # optional helper list if maintained
```

If you rely on submodules (none currently), add `git submodule update --init --recursive`.

## Running Tasks in CI

Typical pipeline steps:

1. **Lint:** `make pylint` and `make pep8`
2. **Tests:** `make test` or `pytest test`
3. **Docs (optional):** `make doc`
4. **Package (optional):** `pb_tool package` or `make package VERSION=...`

Capture JUnit or coverage reports by passing the appropriate flags to pytest (e.g., `pytest --junitxml=reports/junit.xml`). Store artifacts such as `help/build/html` or plugin zips if needed downstream.

## Data and Dependency Caching

- Cache the pip directory (`~/.cache/pip`) between runs to avoid reinstalling dev dependencies.
- Cache the QGIS APT packages when using custom images. For GitHub Actions, rely on prebuilt container images to minimize install time.
- Large sample datasets can be cached by storing the `data/` directory or generating them on the fly in a setup step.

## Secrets and API Keys

- Elevation downloads use the OpenTopography API key. In CI, inject it as an environment secret (e.g., `OPENTOPOGRAPHY_API_KEY`) and ensure workflows redact it from logs.
- Store secrets in the platform’s secret manager (GitHub Secrets, Azure Key Vault, etc.) and reference them in workflow YAML files.

## Headless Plugin Packaging

```bash
pb_tool build
pb_tool package
ls -lh hexmosaic.zip
```

Archive the resulting zip as a CI artifact, or upload it to a staging location for manual testing. Always run smoke tests on at least one GUI-enabled environment before releasing to production.

## Troubleshooting

| Issue | Mitigation |
| --- | --- |
| `ImportError: libqgis_core.so` | Ensure `LD_LIBRARY_PATH` includes the QGIS library directory (often identical to `QGIS_PREFIX_PATH/lib`). |
| Qt errors about display | Set `QT_QPA_PLATFORM=offscreen` or run under `xvfb-run`. |
| Missing translation tools (`lrelease`) | Install `qttools5-dev-tools` (Debian/Ubuntu) or `qt5-qttools` (Fedora). |
| Slow builds due to repeated package installs | Bake dependencies into a custom container image and pin versions in the Dockerfile. |
| API keys exposed in logs | Mask secrets via platform tooling and avoid `set -x` when echoing environment variables. |

Keep this guide updated when CI workflows evolve so automation agents and maintainers share a single source of truth.
