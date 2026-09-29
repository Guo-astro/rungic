#!/bin/sh
# Development environment: a Python virtual environment in .work/venv with the dependencies in
# tools/dev-requirements.txt (PySide6 for testing QML, pytest). It sees the system's packages too
# (PyGObject and the like come from the distribution). tools/work-env.sh activates it.
#   sh tools/dev-setup.sh           create or update it
# pip honours http_proxy/https_proxy: set them on hosts that need a proxy (AGENTS.md, 网络).
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
venv=$root/.work/venv
[ -x "$venv/bin/python" ] || python3 -m venv --system-site-packages "$venv"
"$venv/bin/python" -m pip install --quiet --upgrade pip
"$venv/bin/python" -m pip install --quiet -r "$root/tools/dev-requirements.txt"
"$venv/bin/python" -c 'import PySide6; print("PySide6", PySide6.__version__, "in", __import__("sys").prefix)'
