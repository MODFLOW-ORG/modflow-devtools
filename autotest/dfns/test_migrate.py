import io
import json
import tomllib
from pathlib import Path

import pytest
import yaml

from modflow_devtools.dfn.schema import Dfn
from modflow_devtools.dfns import fetch_dfns, migrate
from modflow_devtools.dfns.migrate_to_v2_0_0_dev2 import to_v2_0_0_dev2
from modflow_devtools.dfns.migrate_to_v2_0_0_dev3 import to_v2_0_0_dev3

FORMATS = ["yaml", "toml", "json"]
MF6_OWNER = "MODFLOW-ORG"
MF6_REPO = "modflow6"
MF6_REF = "6.7.0"


def _load(path: Path, fmt: str) -> dict:
    if fmt == "toml":
        with path.open("rb") as f:
            return tomllib.load(f)
    elif fmt == "json":
        with path.open() as f:
            return json.load(f)
    else:
        with path.open() as f:
            return yaml.safe_load(f)


@pytest.fixture(scope="module")
def dfn_dir(module_tmpdir):
    pytest.importorskip("boltons")
    path = module_tmpdir / "dfn"
    path.mkdir()
    fetch_dfns(MF6_OWNER, MF6_REPO, MF6_REF, path, verbose=True)
    return path


@pytest.fixture(scope="module", params=FORMATS)
def dev0(request, dfn_dir, module_tmpdir):
    fmt = request.param
    out = module_tmpdir / f"dev0-{fmt}"
    migrate(dfn_dir, out, schema_version="2.0.0.dev0", fmt=fmt)
    return out, fmt


@pytest.fixture(scope="module", params=FORMATS)
def dev1(request, dfn_dir, module_tmpdir):
    fmt = request.param
    out = module_tmpdir / f"dev1-{fmt}"
    migrate(dfn_dir, out, schema_version="2.0.0.dev1", fmt=fmt)
    return out, fmt


@pytest.fixture(scope="module", params=FORMATS)
def dev2(request, dfn_dir, module_tmpdir):
    fmt = request.param
    out = module_tmpdir / f"dev2-{fmt}"
    migrate(dfn_dir, out, schema_version="2.0.0.dev2", fmt=fmt)
    return out, fmt


@pytest.fixture(scope="module", params=FORMATS)
def dev3(request, dfn_dir, module_tmpdir):
    fmt = request.param
    out = module_tmpdir / f"dev3-{fmt}"
    migrate(dfn_dir, out, schema_version="2.0.0.dev3", fmt=fmt)
    return out, fmt


def test_migrate_v2_0_0_dev0(dev0, snapshot):
    out, fmt = dev0
    files = sorted(out.glob(f"*.{fmt}"))
    assert files
    for p in files:
        data = _load(p, fmt)
        assert data["name"] == p.stem
        assert data["schema_version"] == "2.0.0.dev0"
        assert snapshot(name=p.stem) == p.read_text()


def test_migrate_v2_0_0_dev1(dev1, snapshot):
    out, fmt = dev1
    files = sorted(out.glob(f"*.{fmt}"))
    assert files
    for p in files:
        data = _load(p, fmt)
        assert data["name"] == p.stem
        assert data["schema_version"] == "2.0.0.dev1"
        assert snapshot(name=p.stem) == p.read_text()


def test_migrate_v2_0_0_dev2(dev2, snapshot):
    out, fmt = dev2
    files = sorted(out.glob(f"*.{fmt}"))
    assert files
    for p in files:
        data = _load(p, fmt)
        assert data["name"] == p.stem
        assert data["schema_version"] == "2.0.0.dev2"
        assert snapshot(name=p.stem) == p.read_text()


def test_migrate_v2_0_0_dev3(dev3, snapshot):
    out, fmt = dev3
    files = sorted(out.glob(f"*.{fmt}"))
    assert files
    for p in files:
        data = _load(p, fmt)
        assert data["name"] == p.stem
        assert data["schema_version"] == "2.0.0.dev3"
        assert snapshot(name=p.stem) == p.read_text()


# Minimal synthetic DFN (shaped like gwt-ssm's SOURCES block) exercising the
# write_if_empty tag. No real upstream DFN sets this tag directly yet (it
# isn't derivable from other DFN attributes -- see Block.write_if_empty in
# schema.py), so the general per-field mechanism is covered here against a
# neutral component name rather than via the real-corpus snapshot tests
# above. gwt-ssm/gwe-ssm themselves get write_if_empty from a dedicated
# migration-time fixup (_fix_ssm_sources_write_if_empty) instead, pending
# that DFN tag -- see the tests below that exercise those two names directly.
_SOURCES_DFN = """\
block sources
name sources
type recarray pname srctype auxname
reader urword
optional false
write_if_empty true
longname package list
description

block sources
name pname
in_record true
type string
tagged false
reader urword
longname package name
description pname

block sources
name srctype
in_record true
type string
tagged false
optional false
reader urword
longname source type
description srctype

block sources
name auxname
in_record true
type string
tagged false
optional false
reader urword
longname auxiliary variable name
description auxname
"""


def _load_sources_fields(dfn_text: str = _SOURCES_DFN):
    pytest.importorskip("boltons")
    return Dfn.load_dfn(io.StringIO(dfn_text))


# A neutral name (not gwt-ssm/gwe-ssm) so these general-mechanism tests
# aren't also exercising the SSM-specific fixup below.
_NEUTRAL_NAME = "gwt-tst"


def test_migrate_v2_0_0_dev2_write_if_empty():
    fields, meta = _load_sources_fields()
    component = to_v2_0_0_dev2(_NEUTRAL_NAME, fields, meta)
    assert component.blocks["sources"].write_if_empty is True


def test_migrate_v2_0_0_dev3_write_if_empty():
    fields, meta = _load_sources_fields()
    component = to_v2_0_0_dev3(_NEUTRAL_NAME, fields, meta)
    assert component.blocks["sources"].write_if_empty is True


def test_migrate_write_if_empty_absent_defaults_false():
    dfn_without_tag = _SOURCES_DFN.replace("write_if_empty true\n", "")
    fields, meta = _load_sources_fields(dfn_without_tag)
    component = to_v2_0_0_dev2(_NEUTRAL_NAME, fields, meta)
    assert component.blocks["sources"].write_if_empty is False


@pytest.mark.parametrize("name", ["gwt-ssm", "gwe-ssm"])
def test_migrate_ssm_sources_write_if_empty_without_tag(name):
    """
    gwt-ssm/gwe-ssm get write_if_empty from _fix_ssm_sources_write_if_empty
    regardless of whether the DFN sets the tag -- no real DFN does yet.
    """
    dfn_without_tag = _SOURCES_DFN.replace("write_if_empty true\n", "")
    fields, meta = _load_sources_fields(dfn_without_tag)
    component = to_v2_0_0_dev2(name, fields, meta)
    assert component.blocks["sources"].write_if_empty is True
