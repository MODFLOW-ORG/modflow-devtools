from os import PathLike
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from modflow_devtools.dfn import Dfn

CONTEXT: dict[str, Any] = {}
TOML_DIR: PathLike = Path()


def get_dfn(toml_dir, toml_name):
    path = Path(toml_dir / f"{toml_name}.toml")
    assert path.is_file()
    with path.open(mode="rb") as toml_file:
        return Dfn.load(toml_file, name=toml_name, version=2)


class ParamAttrs(BaseModel):
    modflow_input: str
    modflow_iaux: int | None = None
    layer: int | None = None

    @field_validator("layer", mode="before")
    @classmethod
    def validate_layer(cls, v: Any) -> Any:
        global CONTEXT
        assert "grid_dims" in CONTEXT
        if v > CONTEXT["grid_dims"][0]:
            raise ValueError(f"Param layer attr {v} exceeds grid k")
        return v


class ModelAttrs(BaseModel):
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


class ParamEncodings(BaseModel):
    _FillValue: float


class ModelNetCDFParam(BaseModel):
    param: str = Field(
        # default=None,
    )
    attrs: ParamAttrs
    encodings: ParamEncodings
    shape: list
    varname: str
    numeric_type: str = Field(
        # default=None,
    )

    @field_validator("param", mode="before")
    @classmethod
    def validate_param(cls, v: Any) -> Any:
        global TOML_DIR
        tokens = v.split("/")
        if len(tokens) != 3:
            raise ValueError(f"Invalid param format: {v}")
        model = tokens[0]
        package = tokens[1]
        param = tokens[2]
        dfn = get_dfn(TOML_DIR, f"{model}-{package}")

        blocks = ["griddata", "period"]
        if not any(blk in dfn for blk in blocks):
            raise ValueError(
                f"griddata/period blocks not found in package type {package}"
            )
        if not any(param in dfn[blk] if blk in dfn else False for blk in blocks):
            raise ValueError(f"Param {param} not found in package {package}")

        for b in blocks:
            if b in dfn and param in dfn[b]:
                if "netcdf" not in dfn[b][param] or not dfn[b][param]["netcdf"]:
                    raise ValueError(f"not a netcdf param: {param}")
        return v

    @field_validator("attrs", mode="before")
    @classmethod
    def validate_attrs(cls, v: Any) -> Any:
        global CONTEXT
        v = {k.lower(): v for k, v in v.items()}
        if "mesh" in CONTEXT:
            if "layer" not in v:
                raise ValueError("Expected param layer attribute for mesh")
        return v


class ModelNetCDFSpec(BaseModel):
    attrs: ModelAttrs
    variables: list[ModelNetCDFParam] = Field(default_factory=list)

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


def validate(v, path: str | PathLike, grid_dims: list[int]):
    """
    Validate model NetCDF specification.

    Parameters
    ----------
    path : str | PathLike
        Path to the directory containing TOML dfn specification.
    grid_dims: list
        modeflow 6 discretization dependent model grid dimensions
        if discretization is DIS then grid_dims should be [nlay, nrow, ncol]
        if discretization is DISV then grid_dims should be [nlay, ncpl]
    """
    global TOML_DIR, CONTEXT
    CONTEXT = {}
    CONTEXT["grid_dims"] = grid_dims
    TOML_DIR = Path(path).expanduser().resolve().absolute()
    if not TOML_DIR.is_dir():
        raise NotADirectoryError(f"Path {path} is not a directory.")
    try:
        ModelNetCDFSpec.model_validate(v)
    except ValidationError:
        raise
