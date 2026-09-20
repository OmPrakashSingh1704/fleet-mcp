from __future__ import annotations


def build_image(docker_client, context_path: str, dockerfile: str, tag: str) -> str:
    """Build a Docker image and return its image id.

    ``context_path`` is the build context root. Fleet Dockerfiles (see
    Task 10) copy ``requirements.txt``, ``flotilla_mcp/``, and
    ``fleet_manifest.yaml`` from the repo root, and compose builds them with
    ``context: .`` plus a per-service ``dockerfile: flotilla_mcp/<svc>/Dockerfile``.
    So the build context passed here must be the repo root, not the
    individual service directory, with ``dockerfile`` pointing at the
    service's Dockerfile relative to that context.
    """
    image, _logs = docker_client.images.build(
        path=context_path, dockerfile=dockerfile, tag=tag, rm=True
    )
    return image.id
