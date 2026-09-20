from __future__ import annotations

import shutil
import tempfile

from flotilla_mcp.self_dev_mcp.git_ops import clone


def create_workspace(remote_url: str) -> str:
    workspace_dir = tempfile.mkdtemp(prefix="selfdev-")
    try:
        clone(remote_url, workspace_dir)
    except BaseException:
        shutil.rmtree(workspace_dir, ignore_errors=True)
        raise
    return workspace_dir


def destroy_workspace(workspace_dir: str) -> None:
    shutil.rmtree(workspace_dir, ignore_errors=True)
