#!/bin/sh
set -eu

# The container starts as root so this script can join the "watcher" user to
# whatever group actually owns /var/run/docker.sock on the host, then drop
# privileges before running the real command. This exists because the GID
# that owns docker.sock varies by host and isn't known at image build time
# (on Docker Desktop it's root:root 660 -- see the comment below and in
# flotilla_mcp/deploy_watcher/Dockerfile for why that's still acceptable).

SOCK=/var/run/docker.sock

if [ -S "$SOCK" ]; then
    SOCK_GID=$(stat -c %g "$SOCK")

    if getent group "$SOCK_GID" >/dev/null 2>&1; then
        GROUP_NAME=$(getent group "$SOCK_GID" | cut -d: -f1)
    else
        GROUP_NAME=dockersock
        groupadd -g "$SOCK_GID" "$GROUP_NAME"
    fi

    # On Docker Desktop the socket is owned by GID 0 (the existing "root"
    # group), so this joins watcher to root. That's acceptable specifically
    # because anyone who can reach docker.sock already has root-equivalent
    # power on the host (they can run arbitrary containers with arbitrary
    # host mounts) -- joining the group that owns the socket doesn't grant
    # any authority beyond what having the socket already implies.
    usermod -aG "$GROUP_NAME" watcher
else
    echo "WARNING: $SOCK not found; deploy-watcher will not be able to reach the docker daemon" >&2
fi

exec setpriv --reuid=watcher --regid=watcher --init-groups -- "$@"
