from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, ValidationInfo, field_validator

from modflow_devtools.dfn import Dfn, get_dfns
from modflow_devtools.dfn2toml import convert


def get_dfn(toml_name):
    import tempfile

    SYSTEMP = tempfile.gettempdir()
    MF6_DIR = Path(SYSTEMP) / "modflow6"
    DFN_DIR = MF6_DIR / "dfn"
    TOML_DIR = MF6_DIR / "toml"
    MF6_OWNER = "MODFLOW-ORG"
    MF6_REPO = "modflow6"
    MF6_REF = "develop"

    if not any(TOML_DIR.glob("*.toml")):
        get_dfns(MF6_OWNER, MF6_REPO, MF6_REF, DFN_DIR, verbose=True)
        convert(DFN_DIR, TOML_DIR)

    path = Path(TOML_DIR / f"{toml_name}.toml")
    if not path.is_file():
        raise AssertionError(f"Not a valid mf6 component: {toml_name}")
    with path.open(mode="rb") as toml_file:
        return Dfn.load(toml_file, name=toml_name, version=2)


def validate(v, dims: list[int]):
    """
    Validate model NetCDF specification against schema.

    Parameters
    ----------
    dims: list
        modeflow 6 model grid dimensions
        [nlay, nrow, ncol] or [nlay, ncpl]
    """
    try:
        NetCDFModel.model_validate(v, context={"dims": dims})
    except ValidationError:
        raise


class NetCDFModel(BaseModel):
    attrs: "NetCDFModelAttrs"
    variables: list["NetCDFPackageParam"] = Field(default_factory=list)

    @field_validator("attrs", mode="before")
    @classmethod
    def validate_attrs(cls, v: Any) -> Any:
        """
        validate model (dataset) scoped attributes dictionary
        """
        v = {k.lower(): v.lower() if isinstance(v, str) else v for k, v in v.items()}
        return v


class NetCDFModelAttrs(BaseModel):
    # order of params dictates when data added to info dict
    mesh: str | None = Field(default=None)
    modflow_grid: str = Field()
    modflow_model: str = Field()

    @field_validator("mesh", mode="before")
    @classmethod
    def validate_mesh(cls, v: Any, info: ValidationInfo) -> Any:
        if v is not None:
            assert v == "layered"
            info.context["mesh"] = v  # type: ignore
        return v

    @field_validator("modflow_grid", mode="before")
    @classmethod
    def validate_modflow_grid(cls, v: Any, info: ValidationInfo) -> Any:
        mesh = info.data.get("mesh")
        dims = info.context.get("dims")  # type: ignore
        if mesh is None:
            assert v == "structured"
            if len(dims) != 3:
                raise AssertionError(f"Expected 3 grid dimensions: {dims}")
        else:
            if len(dims) != 2:
                raise AssertionError(
                    f"Expected 2 grid dimensions for layered mesh: {dims}"
                )
        info.context["grid"] = v  # type: ignore
        return v

    @field_validator("modflow_model", mode="before")
    @classmethod
    def validate_modflow_model(cls, v: Any, info: ValidationInfo) -> Any:
        tokens = v.split(":")
        if len(tokens) != 2:
            raise ValueError(f"Invalid modflow_model attribute: {v}")
        modeltype = tokens[0].strip()
        if modeltype[-1].isdigit():
            modeltype = modeltype[:-1]
        info.context["modeltype"] = modeltype  # type: ignore
        info.context["modelname"] = tokens[1].strip()  # type: ignore
        return v


class NetCDFPackageParam(BaseModel):
    param: str = Field()
    shape: list[str] = Field(default_factory=list)
    attrs: "NetCDFParamAttrs"
    encodings: "NetCDFParamEncodings"
    varname: str = Field()
    numeric_type: str = Field()

    @field_validator("param", mode="before")
    @classmethod
    def validate_param(cls, v: Any) -> Any:
        """
        validate package parameter
        """
        tokens = v.split("/")
        if len(tokens) != 3:
            raise ValueError(f"Invalid param format: {v}")
        model = tokens[0]
        package = tokens[1]
        param = tokens[2]
        dfn = get_dfn(f"{model}-{package}")

        blocks = ["griddata", "period"]
        if not any(blk in dfn for blk in blocks):
            raise ValueError(
                f"griddata/period blocks not found in package type {package}"
            )
        if not any(param in dfn[blk] if blk in dfn else False for blk in blocks):
            if (
                "stress_period_data" not in dfn["period"]
                or param not in dfn["period"]["stress_period_data"]["item"]["fields"]
            ):
                raise ValueError(f"Param {param} not found in package {package}")

        for b in blocks:
            if b in dfn and param in dfn[b]:
                if not dfn[b][param]["netcdf"]:
                    raise ValueError(f"Not a netcdf param: '{param}'")
        return v

    @field_validator("attrs", mode="before")
    @classmethod
    def validate_attrs(cls, v: Any, info: ValidationInfo) -> Any:
        """
        validate parameter attributes dictionary
        """
        v = {k.lower(): v.lower() if isinstance(v, str) else v for k, v in v.items()}
        param = info.data.get("param")
        shape = info.data.get("shape")
        mesh = info.context.get("mesh")  # type: ignore
        if mesh is not None and "z" in shape and "layer" not in v:  # type: ignore
            raise AssertionError(f"Expected layer attribute for mesh param '{param}'")
        if (
            param is not None
            and param.split("/")[2] == "aux"
            and "modflow_iaux" not in v
        ):
            raise AssertionError(
                f"Expected modflow_iaux attribute for aux param '{param}'"
            )
        return v


class NetCDFParamAttrs(BaseModel):
    modflow_input: str = Field()
    modflow_iaux: int | None = Field(default=None)
    layer: int | None = Field(default=None)

    @field_validator("modflow_input", mode="before")
    @classmethod
    def validate_modflow_input(cls, v: Any, info: ValidationInfo) -> Any:
        modelname = info.context.get("modelname")  # type: ignore
        if v.split("/")[0] != modelname:
            raise ValueError(
                f'modflow_input attribute "{v}" does not '
                f'match dataset modelname "{modelname}")'
            )
        return v

    @field_validator("modflow_iaux", mode="before")
    @classmethod
    def validate_modflow_iaux(cls, v: Any, info: ValidationInfo) -> Any:
        return v

    @field_validator("layer", mode="before")
    @classmethod
    def validate_layer(cls, v: Any, info: ValidationInfo) -> Any:
        dims = info.context.get("dims")  # type: ignore
        if v > dims[0]:
            raise ValueError(f"Param layer attr value {v} exceeds grid k")
        return v


class NetCDFParamEncodings(BaseModel):
    fill: float = Field(alias="_FillValue")

    @field_validator("fill", mode="before")
    @classmethod
    def validate_fill(cls, v: Any, info: ValidationInfo) -> Any:
        return v
