from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from modflow_devtools.netcdf_schema import ModelNetCDFSpec, get_dfn, validate

# "param": "gwf/welg/q",
# "attrs": {"modflow_input": "<GWF_NAME>/<WELG_NAME>/Q"},
# "encodings": {"_FillValue": 3e30},
# "shape": ["time", "z", "y", "x"],
# "varname": "<welg_name>_q",
# "numeric_type": "f8",

## ?? also need
# "package_name": "welg_0"
# "grid_dims": [10, 2, 2]     #3d structured, 2d vertex, 1d unstructured? =>


@dataclass
class PkgNetCDFConfig:
    """
    NetCDF related configuration for a model package.

    Attributes:
        name (str): package name, e.g. welg_0.
        type (str): package type, e.g. welg.
        params (list[str]): list of param names
            to add to configuration.
    """

    name: str
    type: str
    params: list[str] = field(default_factory=list)


@dataclass
class ModelNetCDFConfig:
    """
    NetCDF related configuration for a model.

    Attributes:
        name (str): model name, e.g. twri.
        type (str): model type, e.g. gwf.
        grid_type (str): grid type, "structured"
            if mf6 DIS and "vertex" if mf6 DISV
        mesh_type (str): mesh topology, "layered"
            if UGRID 2D, else none.
        dims (list[int]): list of netcdf dimensions
            [time, z, y, x] if structured grid type
            [time, z, nmesh_face(ncpl)] if vertex grid type
        params (list[str]): List of PkgNetCDFConfig
            objects to add to configuration.
    """

    name: str
    type: str
    grid_type: str
    mesh_type: str | None = None
    dims: list[int] = field(default_factory=list)
    packages: list[PkgNetCDFConfig] = field(default_factory=list)


class NetCDFInput:
    """
    MODFLOW 6 NetCDF input objects that provide
        metadata dictionaries, modflow 6 input
        json schemas used to validate these dictionaries,
        and xarray objects as basic initialized
        variables that meet modflow 6 input requirements.

    Attributes:
        path (str): path to toml package specification
            directory.
        config (ModelNetCDFConfig): configuration for
            instance.
        params (list[str]): list of param names to add
            to configuration.
    """

    def __init__(
        self,
        path: str | PathLike,
        config: ModelNetCDFConfig,
    ):
        toml_dir = Path(path).expanduser().resolve().absolute()
        if not toml_dir.is_dir():
            raise NotADirectoryError(f"Path {path} is not a directory.")

        self._config = config
        self._netcdf_blocks = ["griddata", "period"]
        self._meta: dict[str, Any] = {}
        self._package: list[dict] = []

        # model attrs
        self._meta["attrs"] = {}
        self._meta["attrs"]["modflow_model"] = (
            f"{config.type.lower()}: {config.name.lower()}"
        )
        self._meta["attrs"]["modflow_grid"] = f"{config.grid_type.lower()}"
        if config.mesh_type is not None:
            self._meta["attrs"]["mesh"] = config.mesh_type
            nlay = config.dims[1]
        else:
            nlay = 0
            # pass
        self._meta["variables"] = []

        for pkg in config.packages:
            dfn = get_dfn(toml_dir, f"{config.type.lower()}-{pkg.type.lower()}")

            self._check_params(dfn, pkg)

            for param in pkg.params:
                numeric_type = self._np_type(dfn, param)
                shape = self._param_shape(dfn, param)

                if nlay > 0:
                    for layer in range(nlay):
                        self._add_param_meta(pkg, param, shape, numeric_type, layer)
                else:
                    self._add_param_meta(pkg, param, shape, numeric_type)
        try:
            validate(self._meta, toml_dir, config.dims[1:])
        except:
            raise

    def to_jsonschema(self):
        return ModelNetCDFSpec.model_json_schema()

    def to_xarray(self):
        ds = xr.Dataset()
        ds.attrs["modflow_grid"] = self._meta["attrs"]["modflow_grid"]
        ds.attrs["modflow_model"] = self._meta["attrs"]["modflow_model"]
        if self._config.mesh_type is not None:
            ds.attrs["mesh"] = self._config.mesh_type.lower()

        for p in self._meta["variables"]:
            varname = p["varname"]
            print(varname)
            if p["numeric_type"] == "f8":
                dtype = np.float64
            elif p["numeric_type"] == "i8":
                dtype = np.int64
            dims = self._config.dims if "time" in p["shape"] else self._config.dims[1:]
            data = np.full(
                dims,
                p["encodings"]["_FillValue"],
                dtype=dtype,
            )
            print(p["shape"])
            var_d = {varname: (p["shape"], data)}
            ds = ds.assign(var_d)
            for a in p["attrs"]:
                ds[varname].attrs[a] = p["attrs"][a]

        return ds

    def to_meta(self):
        return self._meta

    def _add_param_meta(
        self,
        pkg,
        param,
        shape,
        numeric_type,
        layer: int | None = None,
    ):
        varname = f"{pkg.name.lower()}_{param.lower()}"
        if layer is not None:
            varname = f"{varname}_l{layer + 1}"

        d = {
            "param": (
                f"{self._config.type.lower()}/{pkg.type.lower()}/{param.lower()}"
            ),
            "attrs": {
                "modflow_input": (
                    f"{self._config.type.lower()}/{pkg.type.lower()}/{param.lower()}"
                )
            },
            "encodings": {"_FillValue": 3e30},
            "shape": shape,
            "varname": varname,
            "numeric_type": numeric_type,
        }

        if layer is not None:
            d["attrs"]["layer"] = layer + 1

        self._meta["variables"].append(d)

    def _check_params(self, dfn, pkg):
        if len(pkg.params) > 0:
            return

        def _add_params(blk):
            print(dfn[blk])
            for p in dfn[blk]:
                print(p)
                if (
                    isinstance(dfn[blk][p], dict)
                    and "netcdf" in dfn[blk][p]
                    and dfn[blk][p]["netcdf"]
                ):
                    pkg.params.append(p)

        for blk in self._netcdf_blocks:
            if blk in dfn:
                _add_params(blk)

    def _np_type(self, dfn, param):
        numeric_type = None

        def _check_type(blk):
            if "type" not in dfn[blk][param]:
                return
            if dfn[blk][param]["type"] == "double precision":
                nt = "f8"
            elif dfn[blk][param]["type"] == "integer":
                nt = "i8"
            return nt

        for blk in self._netcdf_blocks:
            if blk in dfn and param in dfn[blk]:
                numeric_type = _check_type(blk)

        return numeric_type

    def _param_shape(self, dfn, param):
        shape = None

        def _check_shape(blk):
            if "shape" not in dfn[blk][param]:
                return
            s = ["time"] if blk == "period" else []
            if dfn[blk][param]["shape"] == "(nodes)":
                if self._config.mesh_type is None:
                    s = [*s, "z", "y", "x"]
                elif self._config.mesh_type.lower() == "layered":
                    s = [*s, "z", "nmesh_face"]
            else:
                dfn_shape = dfn[blk][param]["shape"]
                dfn_shape = dfn_shape.replace("(", "")
                dfn_shape = dfn_shape.replace(")", "")
                dfn_shape = dfn_shape.replace(",", "")
                dfn_shape = dfn_shape.split(" ").reverse()
                s = s + dfn_shape
            return s

        for blk in self._netcdf_blocks:
            if blk in dfn and param in dfn[blk]:
                shape = _check_shape(blk)

        return shape
