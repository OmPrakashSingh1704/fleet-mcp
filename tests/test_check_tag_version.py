import importlib.util
import pathlib

import pytest

_spec = importlib.util.spec_from_file_location(
    "check_tag_version", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "check_tag_version.py"
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_matching_tag_passes():
    mod.check("v0.1.0", "0.1.0")


@pytest.mark.parametrize("tag", ["v0.1.1", "0.1.0", "v0.1", "refs/tags/v0.1.0", ""])
def test_mismatch_or_malformed_fails(tag):
    with pytest.raises(SystemExit) as exc:
        mod.check(tag, "0.1.0")
    assert exc.value.code == 1
