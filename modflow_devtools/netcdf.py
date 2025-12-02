from dataclasses import dataclass, field
from typing import Any

import jsonschema
import numpy as np
import xarray as xr

from modflow_devtools.netcdf_schema import NetCDFModel, get_dfn, validate

DNODATA = np.float64(3.0e30)  # MF6 DNODATA constant
FILLNA_INT32 = np.int32(-2147483647)  # netcdf-fortran NF90_FILL_INT
FILLNA_INT64 = np.int64(-2147483647)
FILLNA_FLOAT64 = np.float64(9.96920996838687e36)  # netcdf-fortran NF90_FILL_DOUBLE


@dataclass
class NetCDFPackageCfg:
    """
    NetCDF related configuration for a model package.

    parameters
    ----------
    name : str
        package name, e.g. welg_0.
    type : str
        package type, e.g. welg.
    auxiliary : list[str]
        ordered list of auxiliary names.
    params : list[str]
        list of param names.
    """

    name: str
    type: str
    auxiliary: list[str] = field(default_factory=list)
    params: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.name = self.name.lower()
        self.type = self.type.lower()


@dataclass
class NetCDFModelInput:
    """
    MODFLOW 6 NetCDF model input description and utilities.

    parameters
    ----------
    name : str
        model name.
    type : str
        model type, e.g. gwf.
    grid_type : str
        grid type: "structured" or "vertex"
    mesh_type : str
        mesh topology: "layered" or None
    dims : list[int]
        NetCDF dimensions
        structured grid type: [time, z, y, x]
        vertex grid type: [time, z, nmesh_face (ncpl)]
    packages : list[NetCDFPackageCfg]
        package configuration object list.
    """

    name: str
    type: str
    grid_type: str
    mesh_type: str | None = None
    dims: list[int] = field(default_factory=list)
    packages: list[NetCDFPackageCfg] = field(default_factory=list)

    @staticmethod
    def jsonschema() -> jsonschema:
        return NetCDFModel.model_json_schema()

    @property
    def meta(self) -> dict[Any, Any]:
        self._meta: dict[str, Any] = {}
        self._meta["attrs"] = {}
        self._meta["attrs"]["modflow_model"] = f"{self.type}6: {self.name}"
        self._meta["attrs"]["modflow_grid"] = f"{self.grid_type}"
        if self.mesh_type is not None:
            assert len(self.dims) == 3, (
                f"Configured dims should be [NSTP, NLAY, NCPL], found={self.dims}"
            )
            self._meta["attrs"]["mesh"] = self.mesh_type
            nlay = self.dims[1]
        else:
            assert len(self.dims) == 4, (
                f"Configured dims should be [NSTP, NLAY, NROW, NCOL], found={self.dims}"
            )
            nlay = 0
        self._meta["variables"] = []

        for pkg in self.packages:
            dfn = get_dfn(f"{self.type}-{pkg.type}")

            self._check_params(dfn, pkg)

            for param in pkg.params:
                numeric_type = self._np_type(dfn, param)
                shape = self._param_shape(dfn, param)
                layer = 0 if "z" not in shape else nlay

                if layer > 0:
                    for k in range(layer):
                        self._add_param_meta(dfn, pkg, param, shape, numeric_type, k)
                else:
                    self._add_param_meta(dfn, pkg, param, shape, numeric_type)

        validate(self._meta, self.dims[1:])
        return self._meta

    def to_xarray(self) -> xr.Dataset:
        dimmap = {
            "time": 0,
            "z": 1,
            "y": 2,
            "nmesh_face": 2,
            "x": 3,
        }

        meta = self.meta

        ds = xr.Dataset()
        for a in meta["attrs"]:
            ds.attrs[a] = meta["attrs"][a]

        for p in meta["variables"]:
            dtype: np.dtype[np.float64] | np.dtype[np.int64] | np.dtype[np.int32]
            varname = p["varname"]
            if p["numeric_type"] == "f8":
                dtype = np.dtype(np.float64)
            elif p["numeric_type"] == "i8":
                dtype = np.dtype(np.int32)
            dims = [self.dims[dimmap[dim]] for dim in p["shape"]]
            data = np.full(
                dims,
                p["encodings"]["_FillValue"],
                dtype=dtype,
            )
            var_d = {varname: (p["shape"], data)}
            ds = ds.assign(var_d)
            for a in p["attrs"]:
                ds[varname].attrs[a] = p["attrs"][a]
            for e in p["encodings"]:
                ds[varname].encoding[e] = p["encodings"][e]

        return ds

    def __post_init__(self):
        self._netcdf_blocks = ["griddata", "period"]

        self.name = self.name.lower()
        self.type = self.type.lower()
        self.grid_type = self.grid_type.lower()
        if self.mesh_type is not None:
            self.mesh_type = self.mesh_type.lower()
        if self.type[-1] == "6":
            self.type = self.type[:-1]

    def _add_param_meta(
        self,
        dfn,
        pkg,
        param,
        shape,
        numeric_type,
        layer: int | None = None,
    ):
        param = param.lower()
        _fill: np.float64 | np.int32
        if "time" in shape:
            _fill = DNODATA
        else:
            if numeric_type == "f8":
                _fill = FILLNA_FLOAT64
            elif numeric_type == "i8":
                _fill = FILLNA_INT32

        def _add_param(name, iaux=None):
            varname = (
                f"{pkg.name}_{name}"
                if layer is None
                else f"{pkg.name}_{name}_l{layer + 1}"
            )
            mf6_input = (
                f"{self.name}/{pkg.name}/{param}"
                if "multi" in dfn
                else f"{self.name}/{pkg.type}/{param}"
            )
            longname = ""
            for blk in self._netcdf_blocks:
                if blk in dfn and name in dfn[blk]:
                    longname = dfn[blk][name]["longname"]

            d = {
                "param": (f"{self.type}/{pkg.type}/{param}"),
                "attrs": {
                    "modflow_input": mf6_input,
                    "longname": longname,
                },
                "encodings": {"_FillValue": _fill},
                "shape": shape,
                "varname": varname,
                "numeric_type": numeric_type,
            }

            if layer is not None:
                d["attrs"]["layer"] = layer + 1

            if iaux is not None:
                d["attrs"]["modflow_iaux"] = iaux + 1

            self._meta["variables"].append(d)

        if param == "aux":
            for i, auxname in enumerate(pkg.auxiliary):
                _add_param(auxname.lower(), i)
        else:
            _add_param(param)

    def _check_params(self, dfn, pkg):
        if len(pkg.params) > 0:
            return

        def _add_params(blk):
            for p in dfn[blk]:
                if isinstance(dfn[blk][p], dict) and dfn[blk][p]["netcdf"]:
                    pkg.params.append(p)

        for blk in self._netcdf_blocks:
            if blk in dfn:
                _add_params(blk)

    def _np_type(self, dfn, param):
        numeric_type = None

        def _check_type(blk):
            if dfn[blk][param]["type"] == "double precision":
                nt = "f8"
            elif dfn[blk][param]["type"] == "integer":
                nt = "i8"
            return nt

        for blk in self._netcdf_blocks:
            if blk in dfn and param in dfn[blk]:
                numeric_type = _check_type(blk)

        assert numeric_type is not None, f"Invalid {dfn['name']} package param: {param}"
        return numeric_type

    def _param_shape(self, dfn, param):
        shape = None

        def _check_shape(blk):
            s = ["time"] if blk == "period" else []
            if (
                dfn[blk][param]["shape"] == "(nodes)"
                or dfn[blk][param]["shape"] == "(nper, nodes)"
            ):
                if self.mesh_type is None:
                    s = [*s, "z", "y", "x"]
                elif self.mesh_type == "layered":
                    s = [*s, "z", "nmesh_face"]
            elif dfn[blk][param]["shape"] == "(nper, ncol*nrow; ncpl)":
                if self.mesh_type is None:
                    s = [*s, "y", "x"]
                elif self.mesh_type == "layered":
                    s = [*s, "nmesh_face"]
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

        assert shape is not None, f"Invalid {dfn['name']} package param: {param}"
        return shape
