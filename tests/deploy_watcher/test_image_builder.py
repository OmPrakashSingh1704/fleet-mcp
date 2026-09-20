from unittest.mock import MagicMock

from flotilla_mcp.deploy_watcher.image_builder import build_image


def test_build_image_delegates_to_docker_client_and_returns_image_id():
    docker_client = MagicMock()
    mock_image = MagicMock(id="sha256:abc123")
    docker_client.images.build.return_value = (mock_image, iter([]))

    image_id = build_image(
        docker_client,
        context_path=".",
        dockerfile="flotilla_mcp/fixture_hello_mcp/Dockerfile",
        tag="fixture-hello-mcp:abc123",
    )

    assert image_id == "sha256:abc123"
    docker_client.images.build.assert_called_once_with(
        path=".",
        dockerfile="flotilla_mcp/fixture_hello_mcp/Dockerfile",
        tag="fixture-hello-mcp:abc123",
        rm=True,
    )
