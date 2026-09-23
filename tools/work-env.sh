# Source from an interactive Bash session before local development:
#   source tools/work-env.sh
task_workspace=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export PYTHONPYCACHEPREFIX="$task_workspace/.work/cache/python"
export CARGO_TARGET_DIR="$task_workspace/.work/build/native-target"
mkdir -p "$PYTHONPYCACHEPREFIX" "$CARGO_TARGET_DIR"
unset task_workspace
