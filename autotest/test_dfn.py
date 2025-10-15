from dataclasses import asdict
from pathlib import Path

import pytest
from packaging.version import Version

from modflow_devtools.dfn import Dfn, _load_common, load, load_flat
from modflow_devtools.dfn.fetch import fetch_dfns
from modflow_devtools.dfn.schema.v1 import FieldV1
from modflow_devtools.dfn.schema.v2 import FieldV2
from modflow_devtools.dfn2toml import convert
from modflow_devtools.markers import requires_pkg

PROJ_ROOT = Path(__file__).parents[1]
DFN_DIR = PROJ_ROOT / "autotest" / "temp" / "dfn"
TOML_DIR = DFN_DIR / "toml"
SPEC_DIRS = {1: DFN_DIR, 2: TOML_DIR}
MF6_OWNER = "MODFLOW-ORG"
MF6_REPO = "modflow6"
MF6_REF = "develop"
EMPTY_DFNS = {"exg-gwfgwe", "exg-gwfgwt", "exg-gwfprt", "sln-ems"}


def pytest_generate_tests(metafunc):
    if "dfn_name" in metafunc.fixturenames:
        if not any(DFN_DIR.glob("*.dfn")):
            fetch_dfns(MF6_OWNER, MF6_REPO, MF6_REF, DFN_DIR, verbose=True)
        dfn_names = [
            dfn.stem for dfn in DFN_DIR.glob("*.dfn") if dfn.stem not in ["common", "flopy"]
        ]
        metafunc.parametrize("dfn_name", dfn_names, ids=dfn_names)

    if "toml_name" in metafunc.fixturenames:
        # Only convert if TOML files don't exist yet (avoid repeated conversions)
        dfn_paths = [p for p in DFN_DIR.glob("*.dfn") if p.stem not in ["common", "flopy"]]
        if not TOML_DIR.exists() or not all(
            (TOML_DIR / f"{dfn.stem}.toml").is_file() for dfn in dfn_paths
        ):
            convert(DFN_DIR, TOML_DIR)
        # Verify all expected TOML files were created
        assert all((TOML_DIR / f"{dfn.stem}.toml").is_file() for dfn in dfn_paths)
        toml_names = [toml.stem for toml in TOML_DIR.glob("*.toml")]
        metafunc.parametrize("toml_name", toml_names, ids=toml_names)


@requires_pkg("boltons")
def test_load_v1(dfn_name):
    with (
        (DFN_DIR / "common.dfn").open() as common_file,
        (DFN_DIR / f"{dfn_name}.dfn").open() as dfn_file,
    ):
        common = _load_common(common_file)
        dfn = load(dfn_file, name=dfn_name, format="dfn", common=common)
        assert any(dfn.fields) == (dfn.name not in EMPTY_DFNS)


@requires_pkg("boltons")
def test_load_v2(toml_name):
    with (TOML_DIR / f"{toml_name}.toml").open(mode="rb") as toml_file:
        dfn = load(toml_file, name=toml_name, format="toml")
        assert any(dfn.fields) == (dfn.name not in EMPTY_DFNS)


@requires_pkg("boltons")
@pytest.mark.parametrize("schema_version", list(SPEC_DIRS.keys()))
def test_load_all(schema_version):
    dfns = load_flat(path=SPEC_DIRS[schema_version])
    for dfn in dfns.values():
        assert any(dfn.fields) == (dfn.name not in EMPTY_DFNS)


@requires_pkg("boltons", "tomli")
def test_convert(function_tmpdir):
    import tomli

    convert(DFN_DIR, function_tmpdir)

    assert (function_tmpdir / "sim-nam.toml").exists()
    assert (function_tmpdir / "gwf-nam.toml").exists()

    with (function_tmpdir / "sim-nam.toml").open("rb") as f:
        sim_data = tomli.load(f)
    assert sim_data["name"] == "sim-nam"
    assert sim_data["schema_version"] == "2"
    assert "parent" not in sim_data

    with (function_tmpdir / "gwf-nam.toml").open("rb") as f:
        gwf_data = tomli.load(f)
    assert gwf_data["name"] == "gwf-nam"
    assert gwf_data["parent"] == "sim-nam"
    assert gwf_data["schema_version"] == "2"

    dfns = load_flat(function_tmpdir)
    roots = []
    for dfn in dfns.values():
        if dfn.parent:
            assert dfn.parent in dfns
        else:
            roots.append(dfn.name)
    assert len(roots) == 1
    root = dfns[roots[0]]
    assert root.name == "sim-nam"

    models = root.children or {}
    for mdl in models:
        assert models[mdl].name == mdl
        assert models[mdl].parent == "sim-nam"

    if gwf := models.get("gwf-nam", None):
        pkgs = gwf.children or {}
        pkgs = {
            k: v
            for k, v in pkgs.items()
            if k.startswith("gwf-") and isinstance(v, dict)
        }
        assert len(pkgs) > 0
        if dis := pkgs.get("gwf-dis", None):
            assert dis.name == "gwf-dis"
            assert dis.parent == "gwf"
            assert "options" in (dis.blocks or {})
            assert "dimensions" in (dis.blocks or {})


def test_dfn_from_dict_ignores_extra_keys():
    d = {
        "schema_version": Version("2"),
        "name": "test-dfn",
        "extra_key": "should be allowed",
        "another_extra": 123,
    }
    dfn = Dfn.from_dict(d)
    assert dfn.name == "test-dfn"
    assert dfn.schema_version == Version("2")


def test_dfn_from_dict_strict_mode():
    d = {
        "schema_version": Version("2"),
        "name": "test-dfn",
        "extra_key": "should cause error",
    }
    with pytest.raises(ValueError, match="Unrecognized keys in DFN data"):
        Dfn.from_dict(d, strict=True)


def test_dfn_from_dict_strict_mode_nested():
    d = {
        "schema_version": Version("2"),
        "name": "test-dfn",
        "blocks": {
            "options": {
                "test_field": {
                    "name": "test_field",
                    "type": "keyword",
                    "extra_key": "should cause error",
                },
            },
        },
    }
    with pytest.raises(ValueError, match="Unrecognized keys in field data"):
        Dfn.from_dict(d, strict=True)


def test_dfn_from_dict_roundtrip():
    original = Dfn(
        schema_version=Version("2"),
        name="gwf-nam",
        parent="sim-nam",
        advanced=False,
        multi=True,
        blocks={"options": {}},
    )
    d = asdict(original)
    reconstructed = Dfn.from_dict(d)
    assert reconstructed.name == original.name
    assert reconstructed.schema_version == original.schema_version
    assert reconstructed.parent == original.parent
    assert reconstructed.advanced == original.advanced
    assert reconstructed.multi == original.multi
    assert reconstructed.blocks == original.blocks


def test_fieldv1_from_dict_ignores_extra_keys():
    d = {
        "name": "test_field",
        "type": "keyword",
        "extra_key": "should be allowed",
        "another_extra": 123,
    }
    field = FieldV1.from_dict(d)
    assert field.name == "test_field"
    assert field.type == "keyword"


def test_fieldv1_from_dict_strict_mode():
    d = {
        "name": "test_field",
        "type": "keyword",
        "extra_key": "should cause error",
    }
    with pytest.raises(ValueError, match="Unrecognized keys in field data"):
        FieldV1.from_dict(d, strict=True)


def test_fieldv1_from_dict_roundtrip():
    original = FieldV1(
        name="maxbound",
        type="integer",
        block="dimensions",
        description="maximum number of cells",
        tagged=True,
    )
    d = asdict(original)
    reconstructed = FieldV1.from_dict(d)
    assert reconstructed.name == original.name
    assert reconstructed.type == original.type
    assert reconstructed.block == original.block
    assert reconstructed.description == original.description
    assert reconstructed.tagged == original.tagged


def test_fieldv2_from_dict_ignores_extra_keys():
    d = {
        "name": "test_field",
        "type": "keyword",
        "extra_key": "should be allowed",
        "another_extra": 123,
    }
    field = FieldV2.from_dict(d)
    assert field.name == "test_field"
    assert field.type == "keyword"


def test_fieldv2_from_dict_strict_mode():
    d = {
        "name": "test_field",
        "type": "keyword",
        "extra_key": "should cause error",
    }
    with pytest.raises(ValueError, match="Unrecognized keys in field data"):
        FieldV2.from_dict(d, strict=True)


def test_fieldv2_from_dict_roundtrip():
    original = FieldV2(
        name="nper",
        type="integer",
        block="dimensions",
        description="number of stress periods",
        optional=False,
    )
    d = asdict(original)
    reconstructed = FieldV2.from_dict(d)
    assert reconstructed.name == original.name
    assert reconstructed.type == original.type
    assert reconstructed.block == original.block
    assert reconstructed.description == original.description
    assert reconstructed.optional == original.optional


def test_dfn_from_dict_with_v1_field_dicts():
    d = {
        "schema_version": Version("1"),
        "name": "test-dfn",
        "blocks": {
            "options": {
                "save_flows": {
                    "name": "save_flows",
                    "type": "keyword",
                    "tagged": True,
                    "in_record": False,
                },
            },
        },
    }
    dfn = Dfn.from_dict(d)
    assert dfn.schema_version == Version("1")
    assert dfn.name == "test-dfn"
    assert dfn.blocks is not None
    assert "options" in dfn.blocks
    assert "save_flows" in dfn.blocks["options"]

    field = dfn.blocks["options"]["save_flows"]
    assert isinstance(field, FieldV1)
    assert field.name == "save_flows"
    assert field.type == "keyword"
    assert field.tagged is True
    assert field.in_record is False


def test_dfn_from_dict_with_v2_field_dicts():
    d = {
        "schema_version": Version("2"),
        "name": "test-dfn",
        "blocks": {
            "dimensions": {
                "nper": {
                    "name": "nper",
                    "type": "integer",
                    "optional": False,
                },
            },
        },
    }
    dfn = Dfn.from_dict(d)
    assert dfn.schema_version == Version("2")
    assert dfn.name == "test-dfn"
    assert dfn.blocks is not None
    assert "dimensions" in dfn.blocks
    assert "nper" in dfn.blocks["dimensions"]

    field = dfn.blocks["dimensions"]["nper"]
    assert isinstance(field, FieldV2)
    assert field.name == "nper"
    assert field.type == "integer"
    assert field.optional is False


def test_dfn_from_dict_defaults_to_v2_fields():
    d = {
        "name": "test-dfn",
        "blocks": {
            "options": {
                "some_field": {
                    "name": "some_field",
                    "type": "keyword",
                },
            },
        },
    }
    dfn = Dfn.from_dict(d)
    assert dfn.blocks is not None
    field = dfn.blocks["options"]["some_field"]
    assert isinstance(field, FieldV2)
    assert dfn.schema_version == Version("2")


def test_dfn_from_dict_with_already_deserialized_fields():
    field = FieldV2(name="test", type="keyword")
    d = {
        "schema_version": Version("2"),
        "name": "test-dfn",
        "blocks": {
            "options": {
                "test": field,
            },
        },
    }
    dfn = Dfn.from_dict(d)
    assert dfn.blocks is not None
    assert dfn.blocks["options"]["test"] is field
