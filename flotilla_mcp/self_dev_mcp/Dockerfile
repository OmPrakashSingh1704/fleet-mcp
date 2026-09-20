FROM python:3.11-slim
WORKDIR /app

# git is required by flotilla_mcp.self_dev_mcp.git_ops (clone/branch/commit/push
# against the repo remote) and flotilla_mcp.self_dev_mcp.workspace.
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY flotilla_mcp /app/flotilla_mcp
COPY fleet_manifest.yaml /app/fleet_manifest.yaml
ENV PYTHONPATH=/app

# Non-root user. Unlike the deploy watcher, this service is never given
# docker.sock or deploy credentials (see docker-compose.yml's comments on
# the self-dev-mcp service) -- it has no use for either, and this Dockerfile
# must never reference the docker socket in any way.
#
# The app source (/app/flotilla_mcp, fleet_manifest.yaml, requirements.txt)
# stays owned by root and read-only to selfdev, so code running as selfdev
# -- including agent-written tests executed by run_tests -- cannot rewrite
# the running server or its manifest code. Only /app/tmp is writable:
# create_workspace() (flotilla_mcp/self_dev_mcp/workspace.py) uses
# tempfile.mkdtemp(), which honors TMPDIR, so workspaces land there.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 1000 selfdev \
    && mkdir -p /app/tmp \
    && chown selfdev:selfdev /app/tmp \
    && chmod 0700 /app/tmp
ENV TMPDIR=/app/tmp
USER selfdev

EXPOSE 8080

CMD ["python", "-m", "flotilla_mcp.self_dev_mcp.server", "--transport", "http"]
