FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir flask==3.0.3
COPY fleetmcp/fixture_hello_mcp /app/fleetmcp/fixture_hello_mcp
COPY fleetmcp/common /app/fleetmcp/common
ENV PYTHONPATH=/app
# Run as a non-root user; the source stays root-owned and read-only to it.
RUN useradd --no-create-home --shell /usr/sbin/nologin --uid 1000 app
USER app
CMD ["python", "-m", "fleetmcp.fixture_hello_mcp.server"]
