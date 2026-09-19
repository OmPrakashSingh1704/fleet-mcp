from __future__ import annotations

import posixpath
from dataclasses import dataclass, field

import yaml

ALWAYS_PROTECTED_PATHS = frozenset({
    "fleet_manifest.yaml",
    "services/common/manifest.py",
})


@dataclass
class ServiceConfig:
    name: str
    path: str
    protected: bool = False
    protected_paths: list[str] = field(default_factory=list)
    container: str | None = None
    health_check: str | None = None


class FleetManifest:
    def __init__(self, services: dict[str, ServiceConfig]):
        self._services = services

    @classmethod
    def load(cls, manifest_path: str) -> "FleetManifest":
        with open(manifest_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        services: dict[str, ServiceConfig] = {}
        for name, cfg in (raw.get("services") or {}).items():
            services[name] = ServiceConfig(
                name=name,
                path=cfg["path"],
                protected=cfg.get("protected", False),
                protected_paths=cfg.get("protected_paths", []),
                container=cfg.get("container"),
                health_check=cfg.get("health_check"),
            )
        return cls(services)

    def get(self, name: str) -> ServiceConfig:
        return self._services[name]

    def all_services(self) -> list[ServiceConfig]:
        return list(self._services.values())

    def is_path_protected(self, relative_path: str) -> bool:
        # Canonicalize the query path: backslash -> forward slash, then normalize
        # dot segments and duplicate slashes, then case-fold for case-insensitive comparison
        normalized = posixpath.normpath(
            relative_path.replace("\\", "/").lstrip("/")
        ).casefold()

        # Reject paths that escape the repo root (contain .. after normalization)
        if normalized.startswith("..") or "/.." in normalized:
            return True

        # Check against always-protected paths (normalized)
        always_protected_normalized = frozenset(
            p.casefold() for p in ALWAYS_PROTECTED_PATHS
        )
        if normalized in always_protected_normalized:
            return True

        # Check against service protections
        for service in self._services.values():
            # Normalize the service path
            service_path_normalized = posixpath.normpath(
                service.path.replace("\\", "/").lstrip("/")
            ).casefold()
            service_prefix = service_path_normalized.rstrip("/") + "/"

            if service.protected and normalized.startswith(service_prefix):
                return True

            # Check specific protected paths
            for protected_path in service.protected_paths:
                protected_normalized = posixpath.normpath(
                    protected_path.replace("\\", "/").lstrip("/")
                ).casefold()
                if normalized == protected_normalized:
                    return True

        return False
