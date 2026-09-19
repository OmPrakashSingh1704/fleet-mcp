FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir flask==3.0.3
COPY services/fixture_hello_mcp /app/services/fixture_hello_mcp
COPY services/common /app/services/common
ENV PYTHONPATH=/app
CMD ["python", "-m", "services.fixture_hello_mcp.server"]
