from __future__ import annotations

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
        normalized = relative_path.replace("\\", "/").lstrip("/")
        if normalized in ALWAYS_PROTECTED_PATHS:
            return True
        for service in self._services.values():
            service_prefix = service.path.rstrip("/") + "/"
            if service.protected and normalized.startswith(service_prefix):
                return True
            for protected_path in service.protected_paths:
                if normalized == protected_path.replace("\\", "/"):
                    return True
        return False
