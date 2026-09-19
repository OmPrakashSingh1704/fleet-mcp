from __future__ import annotations

import posixpath
from dataclasses import dataclass, field

import yaml

# Exact repo-relative files that Self-Dev MCP may never write, regardless of
# what fleet_manifest.yaml says. Mirrored in .github/CODEOWNERS.
ALWAYS_PROTECTED_PATHS = frozenset({
    "fleet_manifest.yaml",
    "services/common/manifest.py",
    "services/__init__.py",
    "requirements.txt",
    "docker-compose.yml",
    "pyproject.toml",
    ".gitattributes",
    ".gitignore",
})

# Repo-relative directories whose entire subtree is always protected
# (the directory itself, and everything under it). Mirrored in
# .github/CODEOWNERS.
ALWAYS_PROTECTED_PREFIXES = frozenset({
    "services/common/",
    ".github/",
})


def canonicalize_path(path: str) -> str:
    """Canonical, case-folded, forward-slash form of a repo-relative path.

    Used for every protected-path comparison, on both the query side and the
    constant side, so the two can never disagree:

    - backslashes become forward slashes, leading slashes are dropped;
    - ``.`` / ``..`` segments and duplicate slashes are collapsed
      (``posixpath.normpath``);
    - each component is cut at the first ``:`` (an NTFS alternate data
      stream -- ``file::$DATA`` writes ``file`` itself on Windows) and loses
      trailing dots and spaces (Windows silently strips those, so
      ``fleet_manifest.yaml.`` would open ``fleet_manifest.yaml``);
    - the result is case-folded (case-insensitive filesystems, and
      ``.GIT`` style evasion).

    Over-matching is the safe direction here: at worst a legitimate but
    oddly named path is refused.
    """
    normalized = posixpath.normpath(path.replace("\\", "/").lstrip("/"))
    parts = []
    for part in normalized.split("/"):
        if part not in (".", ".."):
            part = part.split(":", 1)[0].rstrip(" .")
        parts.append(part)
    return "/".join(parts).casefold()


def _canonical_prefix(prefix: str) -> str:
    return canonicalize_path(prefix).rstrip("/")


# Precomputed canonical forms, so constants and queries share one canonicalization.
_ALWAYS_PROTECTED_PATHS_NORMALIZED = frozenset(canonicalize_path(p) for p in ALWAYS_PROTECTED_PATHS)
_ALWAYS_PROTECTED_PREFIXES_NORMALIZED = frozenset(_canonical_prefix(p) for p in ALWAYS_PROTECTED_PREFIXES)


def _under(normalized: str, directory: str) -> bool:
    """True if ``normalized`` is ``directory`` itself or anything beneath it."""
    return normalized == directory or normalized.startswith(directory + "/")


@dataclass
class ServiceConfig:
    name: str
    path: str
    protected: bool = False
    protected_paths: list[str] = field(default_factory=list)
    container: str | None = None
    # Informational only: the deploy watcher always health-checks
    # http://<service>-<sha>:8080/health (see ARCHITECTURE.md), not this URL.
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
        normalized = canonicalize_path(relative_path)

        # Reject paths that escape the repo root (contain .. after normalization)
        if normalized.startswith("..") or "/.." in normalized:
            return True

        if normalized in _ALWAYS_PROTECTED_PATHS_NORMALIZED:
            return True

        for prefix in _ALWAYS_PROTECTED_PREFIXES_NORMALIZED:
            if _under(normalized, prefix):
                return True

        for service in self._services.values():
            service_dir = _canonical_prefix(service.path)
            if service.protected and _under(normalized, service_dir):
                return True

            for protected_path in service.protected_paths:
                if normalized == canonicalize_path(protected_path):
                    return True

        return False
