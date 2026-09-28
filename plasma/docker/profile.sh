# The Docker CLI talks to the user's rootless daemon (docs/85); for shells outside the session.
if [ -n "${XDG_RUNTIME_DIR:-}" ] && [ -z "${DOCKER_HOST:-}" ]; then
    export DOCKER_HOST="unix://$XDG_RUNTIME_DIR/docker.sock"
fi
