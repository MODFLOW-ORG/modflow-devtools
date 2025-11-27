from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, ValidationInfo, field_validator

from modflow_devtools.dfn import fetch, load
from modflow_devtools.dfn2toml import convert

# TODO: standard install location, move to modflow_devtools.dfn
SPEC_ROOT = Path(__file__).parents[1] / "specification"
DFN_DIR = SPEC_ROOT / "dfn"
TOML_DIR = SPEC_ROOT / "toml"
MF6_OWNER = "MODFLOW-ORG"
MF6_REPO = "modflow6"
MF6_REF = "develop"
EMPTY_DFNS = {"exg-gwfgwe", "exg-gwfgwt", "exg-gwfprt", "sln-ems"}
CONTEXT: dict[str, Any] = {}


def get_dfn(toml_name):
    if not any(DFN_DIR.glob("*.dfn")):
        fetch.fetch_dfns(MF6_OWNER, MF6_REPO, MF6_REF, DFN_DIR, verbose=True)
        convert(DFN_DIR, TOML_DIR)
    path = Path(TOML_DIR / f"{toml_name}.toml")
    if not path.is_file():
        raise AssertionError(f"Not a valid mf6 component: {toml_name}")
    with path.open(mode="rb") as toml_file:
        return load(toml_file, format="toml", name=toml_name)


class NetCDFParamAttrs(BaseModel):
    modflow_input: str
    modflow_iaux: int | None = None
    layer: int | None = None

    @field_validator("layer", mode="before")
    @classmethod
    def validate_layer(cls, v: Any) -> Any:
        global CONTEXT
        assert "grid_dims" in CONTEXT
        if v > CONTEXT["grid_dims"][0]:
            raise ValueError(f"Param layer attr value {v} exceeds grid k")
        return v


class NetCDFModelAttrs(BaseModel):
    modflow_grid: str
    modflow_model: str
    mesh: str | None = None

    @field_validator("modflow_model", mode="before")
    @classmethod
    def validate_modeflow_model(cls, v: Any) -> Any:
        global CONTEXT
        tokens = v.split(":")
        if len(tokens) != 2:
            raise ValueError(f"Invalid modflow_model attribute: {v}")
        modeltype = tokens[0].lower().strip()
        if modeltype[-1].isdigit():
            modeltype = modeltype[:-1]
        CONTEXT["modeltype"] = modeltype
        CONTEXT["modelname"] = tokens[1].lower().strip()
        return v


class NetCDFParamEncodings(BaseModel):
    _FillValue: float


class NetCDFPackageParam(BaseModel):
    # order of params dictates when data added to info dict
    param: str = Field()
    shape: list[str] = Field(default_factory=list)
    attrs: NetCDFParamAttrs
    encodings: NetCDFParamEncodings
    varname: str
    numeric_type: str = Field()

    @field_validator("param", mode="before")
    @classmethod
    def validate_param(cls, v: Any) -> Any:
        tokens = v.split("/")
        if len(tokens) != 3:
            raise ValueError(f"Invalid param format: {v}")
        model = tokens[0]
        package = tokens[1]
        param = tokens[2]
        dfn = get_dfn(f"{model}-{package}")

        blocks = ["griddata", "period"]
        if not any(blk in dfn.blocks for blk in blocks):
            raise ValueError(
                f"griddata/period blocks not found in package type {package}"
            )
        if not any(
            param in dfn.blocks[blk] if blk in dfn.blocks else False for blk in blocks
        ):
            raise ValueError(f"Param {param} not found in package {package}")

        for b in blocks:
            if b in dfn.blocks and param in dfn.blocks[b]:
                if not dfn.blocks[b][param].netcdf:
                    raise ValueError(f"Not a netcdf param: '{param}'")
        return v

    @field_validator("attrs", mode="before")
    @classmethod
    def validate_attrs(cls, v: Any, info: ValidationInfo) -> Any:
        global CONTEXT
        v = {k.lower(): v for k, v in v.items()}
        param = info.data.get("param")
        shape = info.data.get("shape")
        if "mesh" in CONTEXT:
            if shape is not None and "z" in shape and "layer" not in v:
                raise AssertionError(
                    f"Expected layer attribute for mesh param '{param}'"
                )
        return v


class NetCDFModel(BaseModel):
    attrs: NetCDFModelAttrs
    variables: list[NetCDFPackageParam] = Field(default_factory=list)

    @field_validator("attrs", mode="before")
    @classmethod
    def validate_attrs(cls, v: Any) -> Any:
        global CONTEXT
        v = {k.lower(): v for k, v in v.items()}
        if "mesh" in v.keys():
            CONTEXT["mesh"] = v["mesh"]
        if "modflow_grid" in v.keys():
            CONTEXT["grid"] = v["modflow_grid"]
            assert "grid_dims" in CONTEXT
            if "mesh" in v.keys() and v["mesh"].lower() == "layered":
                if len(CONTEXT["grid_dims"]) != 2:
                    raise ValueError(
                        f"Expected 2 grid dimensions {CONTEXT['grid_dims']}"
                    )
            else:
                if len(CONTEXT["grid_dims"]) != 3:
                    raise ValueError(
                        f"Expected 3 grid dimensions {CONTEXT['grid_dims']}"
                    )
        return v


def validate(v, grid_dims: list[int]):
    """
    Validate model NetCDF specification.

    Parameters
    ----------
    grid_dims: list
        modeflow 6 discretization dependent model grid dimensions
        if discretization is DIS then grid_dims should be [nlay, nrow, ncol]
        if discretization is DISV then grid_dims should be [nlay, ncpl]
    """
    global CONTEXT
    CONTEXT = {}
    CONTEXT["grid_dims"] = grid_dims
    try:
        NetCDFModel.model_validate(v)
    except ValidationError:
        raise
