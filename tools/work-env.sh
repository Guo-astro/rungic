# Source from an interactive Bash session before local development:
#   source tools/work-env.sh
task_workspace=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export PYTHONPYCACHEPREFIX="$task_workspace/.work/cache/python"
export CARGO_TARGET_DIR="$task_workspace/.work/build/native-target"
mkdir -p "$PYTHONPYCACHEPREFIX" "$CARGO_TARGET_DIR"
# The development Python (PySide6 for tests, tools/dev-setup.sh creates it).
if [ -f "$task_workspace/.work/venv/bin/activate" ]; then
    . "$task_workspace/.work/venv/bin/activate"
else
    echo "work-env: no .work/venv yet; sh tools/dev-setup.sh installs the development Python" >&2
fi
unset task_workspace
