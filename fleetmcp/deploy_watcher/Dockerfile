FROM python:3.11-slim
WORKDIR /app

# git is required by fleetmcp.deploy_watcher.checkout.sync_checkout, which
# shells out to `git` to keep a local checkout of the fleet repo current at
# the latest merged sha. groupadd/usermod/getent/stat/setpriv (used by
# entrypoint.sh below) all ship in this base image already -- no extra
# packages needed for those.
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY fleetmcp /app/fleetmcp
COPY fleet_manifest.yaml /app/fleet_manifest.yaml
ENV PYTHONPATH=/app

# --- Non-root user, dropped to at runtime, not at build time ---------------
# The watcher is handed /var/run/docker.sock (see docker-compose.yml) so it
# can build and run fleet service containers. That socket is a bind mount
# from the host, so whichever *group* actually owns it (e.g. root:root 660
# on Docker Desktop, or group "docker" with a host-specific GID on many
# Linux hosts) is only known at container start, not at image build time --
# a build-time ARG can't match every host. So the "watcher" user is created
# here but privileges are dropped in entrypoint.sh instead of via USER: the
# container starts as root, entrypoint.sh joins watcher to whatever group
# owns docker.sock right now, then execs the real command as watcher via
# setpriv.
#
# That non-root user is defense-in-depth for the watcher's *other* code
# paths (checkout, image builds, file I/O under /data), not a sandbox
# around the socket itself. Anyone who can talk to /var/run/docker.sock can
# run arbitrary containers with arbitrary host mounts -- that access is
# root-equivalent on the host regardless of which uid inside this container
# holds it (see entrypoint.sh's comment on the Docker Desktop / GID 0 case).
RUN useradd --create-home --shell /usr/sbin/nologin --uid 1000 watcher \
    && mkdir -p /data \
    && chown -R watcher:watcher /app /data

COPY fleetmcp/deploy_watcher/entrypoint.sh /app/fleetmcp/deploy_watcher/entrypoint.sh
RUN chmod +x /app/fleetmcp/deploy_watcher/entrypoint.sh

ENTRYPOINT ["/app/fleetmcp/deploy_watcher/entrypoint.sh"]
CMD ["python", "-m", "fleetmcp.deploy_watcher.main"]
