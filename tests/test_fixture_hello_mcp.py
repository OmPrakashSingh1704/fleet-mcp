from fleetmcp.fixture_hello_mcp.server import app


def test_health_endpoint_returns_ok():
    client = app.test_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_index_endpoint_returns_service_name():
    client = app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert response.get_json() == {"service": "fixture-hello-mcp"}
