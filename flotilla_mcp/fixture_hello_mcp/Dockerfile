FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir flask==3.0.3
COPY flotilla_mcp/fixture_hello_mcp /app/flotilla_mcp/fixture_hello_mcp
COPY flotilla_mcp/common /app/flotilla_mcp/common
ENV PYTHONPATH=/app
# Run as a non-root user; the source stays root-owned and read-only to it.
RUN useradd --no-create-home --shell /usr/sbin/nologin --uid 1000 app
USER app
CMD ["python", "-m", "flotilla_mcp.fixture_hello_mcp.server"]
