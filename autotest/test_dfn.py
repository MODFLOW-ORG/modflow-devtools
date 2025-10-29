from dataclasses import asdict
from pathlib import Path

import pytest
from packaging.version import Version

from modflow_devtools.dfn import Dfn, _load_common, load, load_flat
from modflow_devtools.dfn.fetch import fetch_dfns
from modflow_devtools.dfn.schema.v1 import FieldV1
from modflow_devtools.dfn.schema.v2 import FieldV2
from modflow_devtools.dfn2toml import convert, is_valid
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
            dfn.stem
            for dfn in DFN_DIR.glob("*.dfn")
            if dfn.stem not in ["common", "flopy"]
        ]
        metafunc.parametrize("dfn_name", dfn_names, ids=dfn_names)

    if "toml_name" in metafunc.fixturenames:
        convert(DFN_DIR, TOML_DIR)
        expected_toml_paths = [
            dfn for dfn in DFN_DIR.glob("*.dfn") if "common" not in dfn.stem
        ]
        assert all(toml_path.exists() for toml_path in expected_toml_paths)
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


@requires_pkg("boltons")
def test_validate_directory():
    """Test validation on a directory of DFN files."""
    assert is_valid(DFN_DIR)


@requires_pkg("boltons")
def test_validate_single_file(dfn_name):
    """Test validation on a single DFN file."""
    if dfn_name == "common":
        pytest.skip("common.dfn is handled separately")
    assert is_valid(DFN_DIR / f"{dfn_name}.dfn")


@requires_pkg("boltons")
def test_validate_common_file():
    """Test validation on common.dfn."""
    assert is_valid(DFN_DIR / "common.dfn")


@requires_pkg("boltons")
def test_validate_invalid_file(function_tmpdir):
    """Test validation on an invalid DFN file."""
    invalid_dfn = function_tmpdir / "invalid.dfn"
    invalid_dfn.write_text("invalid content")
    assert not is_valid(invalid_dfn)


@requires_pkg("boltons")
def test_validate_nonexistent_file(function_tmpdir):
    """Test validation on a nonexistent file."""
    nonexistent = function_tmpdir / "nonexistent.dfn"
    assert not is_valid(nonexistent)


def test_fieldv1_to_fieldv2_conversion():
    """Test that FieldV1 instances are properly converted to FieldV2."""
    from modflow_devtools.dfn import map

    dfn_v1 = Dfn(
        schema_version=Version("1"),
        name="test-dfn",
        blocks={
            "options": {
                "save_flows": FieldV1(
                    name="save_flows",
                    type="keyword",
                    block="options",
                    description="save calculated flows",
                    tagged=True,
                    in_record=False,
                    reader="urword",
                ),
                "some_float": FieldV1(
                    name="some_float",
                    type="double precision",
                    block="options",
                    description="a floating point value",
                ),
            }
        },
    )

    dfn_v2 = map(dfn_v1, schema_version="2")
    assert dfn_v2.schema_version == Version("2")
    assert dfn_v2.blocks is not None
    assert "options" in dfn_v2.blocks
    assert "save_flows" in dfn_v2.blocks["options"]

    save_flows = dfn_v2.blocks["options"]["save_flows"]
    assert isinstance(save_flows, FieldV2)
    assert save_flows.name == "save_flows"
    assert save_flows.type == "keyword"
    assert save_flows.block == "options"
    assert save_flows.description == "save calculated flows"
    assert not hasattr(save_flows, "tagged")
    assert not hasattr(save_flows, "in_record")
    assert not hasattr(save_flows, "reader")

    some_float = dfn_v2.blocks["options"]["some_float"]
    assert isinstance(some_float, FieldV2)
    assert some_float.name == "some_float"
    assert some_float.type == "double"
    assert some_float.block == "options"
    assert some_float.description == "a floating point value"


def test_fieldv1_to_fieldv2_conversion_with_children():
    """Test that FieldV1 with nested children are properly converted to FieldV2."""
    from modflow_devtools.dfn import map

    # Create nested fields for a record
    child_field_v1 = FieldV1(
        name="cellid",
        type="integer",
        block="period",
        description="cell identifier",
        in_record=True,
        tagged=False,
    )

    parent_field_v1 = FieldV1(
        name="stress_period_data",
        type="recarray cellid",
        block="period",
        description="stress period data",
        in_record=False,
    )

    dfn_v1 = Dfn(
        schema_version=Version("1"),
        name="test-dfn",
        blocks={
            "period": {
                "stress_period_data": parent_field_v1,
                "cellid": child_field_v1,
            }
        },
    )

    # Convert to v2
    dfn_v2 = map(dfn_v1, schema_version="2")

    # Check that all fields are FieldV2 instances
    assert dfn_v2.blocks is not None
    for block_name, block_fields in dfn_v2.blocks.items():
        for field_name, field in block_fields.items():
            assert isinstance(field, FieldV2)
            # Check nested children too
            if field.children:
                for child_name, child_field in field.children.items():
                    assert isinstance(child_field, FieldV2)
