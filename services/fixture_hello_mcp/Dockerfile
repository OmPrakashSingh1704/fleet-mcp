FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir flask==3.0.3
COPY services/fixture_hello_mcp /app/services/fixture_hello_mcp
COPY services/common /app/services/common
ENV PYTHONPATH=/app
# Run as a non-root user; the source stays root-owned and read-only to it.
RUN useradd --no-create-home --shell /usr/sbin/nologin --uid 1000 app
USER app
CMD ["python", "-m", "services.fixture_hello_mcp.server"]
