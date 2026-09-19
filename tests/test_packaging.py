import pathlib
import subprocess
import sys
import zipfile

import pytest

import fleetmcp

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_version_is_semver():
    parts = fleetmcp.__version__.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)


@pytest.fixture(scope="module")
def wheel(tmp_path_factory):
    out = tmp_path_factory.mktemp("dist")
    try:
        subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(out), str(ROOT)],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        pytest.fail(f"wheel build failed:\n{e.stdout}\n{e.stderr}")
    (whl,) = out.glob("fleetmcp-*.whl")
    return whl


def test_wheel_contents(wheel):
    names = zipfile.ZipFile(wheel).namelist()
    assert "fleetmcp/common/manifest.py" in names
    assert "fleetmcp/self_dev_mcp/server.py" in names
    assert "fleetmcp/deploy_watcher/cli.py" in names
    assert not any("fixture_hello_mcp" in n for n in names)
    assert not any(n.endswith("Dockerfile") or n.endswith("entrypoint.sh") for n in names)
    assert not any(n.startswith("tests/") for n in names)


def test_wheel_metadata(wheel):
    zf = zipfile.ZipFile(wheel)
    meta = next(n for n in zf.namelist() if n.endswith(".dist-info/METADATA"))
    text = zf.read(meta).decode()
    assert "Name: fleetmcp" in text
    assert f"Version: {fleetmcp.__version__}" in text
    assert "Provides-Extra: watcher" in text
    ep = zf.read(next(n for n in zf.namelist() if n.endswith("entry_points.txt"))).decode()
    for line in ("fleetmcp = fleetmcp.self_dev_mcp.server:main",
                 "fleetmcp-self-dev = fleetmcp.self_dev_mcp.server:main",
                 "fleetmcp-watcher = fleetmcp.deploy_watcher.cli:main"):
        assert line in ep
