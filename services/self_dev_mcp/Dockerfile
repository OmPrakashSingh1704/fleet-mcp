FROM python:3.11-slim
WORKDIR /app

# git is required by services.self_dev_mcp.git_ops (clone/branch/commit/push
# against the repo remote) and services.self_dev_mcp.workspace.
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services /app/services
COPY fleet_manifest.yaml /app/fleet_manifest.yaml
ENV PYTHONPATH=/app

# Non-root user. Unlike the deploy watcher, this service is never given
# docker.sock or deploy credentials (see docker-compose.yml's comments on
# the self-dev-mcp service) -- it has no use for either, and this Dockerfile
# must never reference the docker socket in any way.
#
# create_workspace() (services/self_dev_mcp/workspace.py) uses
# tempfile.mkdtemp(), which honors TMPDIR; point it at a directory this
# user owns outright instead of relying on the base image's /tmp
# permissions.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 1000 selfdev \
    && mkdir -p /app/tmp \
    && chown -R selfdev:selfdev /app
ENV TMPDIR=/app/tmp
USER selfdev

EXPOSE 8080

CMD ["python", "-m", "services.self_dev_mcp.server", "--transport", "http"]
