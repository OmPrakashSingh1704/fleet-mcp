FROM python:3.11-slim
WORKDIR /app

# git is required by services.deploy_watcher.checkout.sync_checkout, which
# shells out to `git` to keep a local checkout of the fleet repo current at
# the latest merged sha.
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services /app/services
COPY fleet_manifest.yaml /app/fleet_manifest.yaml
ENV PYTHONPATH=/app

# --- Non-root user, with a caveat -----------------------------------------
# The watcher is handed /var/run/docker.sock (see docker-compose.yml) so it
# can build and run fleet service containers. That socket is a bind mount
# from the host, so whether a non-root process here can actually open it
# depends entirely on the host's socket ownership/permissions (typically
# group "docker", GID varies by host) -- not on anything this image
# controls. DOCKER_GID lets that group be matched at build time; the
# default (999) matches the common Debian/Ubuntu docker package default,
# but must be overridden (`docker build --build-arg DOCKER_GID=<gid>`) to
# match the actual host running docker-compose.
#
# More importantly: this non-root user is defense-in-depth for the
# watcher's *other* code paths (checkout, image builds, file I/O under
# /data), not a sandbox around the socket itself. Anyone who can talk to
# /var/run/docker.sock can run arbitrary containers with arbitrary host
# mounts -- that access is root-equivalent on the host regardless of which
# uid inside this container holds it.
ARG DOCKER_GID=999
RUN groupadd -g ${DOCKER_GID} docker \
    && useradd --create-home --shell /usr/sbin/nologin --uid 1000 --gid ${DOCKER_GID} watcher \
    && mkdir -p /data \
    && chown -R watcher:docker /app /data

USER watcher

CMD ["python", "-m", "services.deploy_watcher.main"]
