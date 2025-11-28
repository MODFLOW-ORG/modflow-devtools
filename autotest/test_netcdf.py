import sys
from pathlib import Path

import numpy as np
from pydantic import ValidationError

from modflow_devtools.netcdf import (
    DNODATA,
    FILLNA_FLOAT64,
    FILLNA_INT32,
    NetCDFModelInput,
    NetCDFPackageCfg,
)
from modflow_devtools.netcdf_schema import validate


def test_validate_model():
    variables = [
        {
            "param": "gwf/welg/aux",
            "attrs": {"modflow_input": "<GWF_NAME>/<WELG_NAME>/AUX", "modflow_iaux": 1},
            "encodings": {"_FillValue": 3e30},
            "shape": ["time", "z", "y", "x"],
            "varname": "welg_0_aux",
            "numeric_type": "f8",
        },
        {
            "param": "gwf/welg/q",
            "attrs": {"modflow_input": "<GWF_NAME>/<WELG_NAME>/Q"},
            "encodings": {"_FillValue": 3e30},
            "shape": ["time", "z", "y", "x"],
            "varname": "welg_0_q",
            "numeric_type": "f8",
        },
    ]
    nc_meta = {
        "attrs": {
            "modflow_grid": "structured",
            "modflow_model": "gwf6: gwfmodel",
        },
        "variables": variables,
    }

    validate(nc_meta, dims=[1, 1, 1])


def test_validate_model_mesh():
    variables = [
        {
            "param": "gwf/welg/aux",
            "attrs": {
                "modflow_input": "<GWF_NAME>/<WELG_NAME>/AUX",
                "modflow_iaux": 1,
                "layer": 1,
            },
            "encodings": {"_FillValue": 3e30},
            "shape": ["time", "z", "y", "x"],
            "varname": "welg_0_aux",
            "numeric_type": "f8",
        },
        {
            "param": "gwf/welg/q",
            "attrs": {"modflow_input": "<GWF_NAME>/<WELG_NAME>/Q", "layer": 1},
            "encodings": {"_FillValue": 3e30},
            "shape": ["time", "z", "y", "x"],
            "varname": "welg_0_q",
            "numeric_type": "f8",
        },
    ]
    nc_meta = {
        "attrs": {
            "modflow_grid": "structured",
            "modflow_model": "gwf6: gwfmodel",
            "mesh": "layered",
        },
        "variables": variables,
    }

    validate(nc_meta, dims=[1, 1])


def test_fail_invalid_param():
    variables = [
        {
            "param": "gwf/wel/q",
            "attrs": {"modflow_input": "<GWF_NAME>/<WEL_NAME>/Q"},
            "encodings": {"_FillValue": 3e30},
            "shape": ["time", "z", "y", "x"],
            "varname": "wel_0_q",
            "numeric_type": "f8",
        },
    ]
    nc_meta = {
        "attrs": {
            "modflow_grid": "structured",
            "modflow_model": "gwf6: gwfmodel",
        },
        "variables": variables,
    }

    try:
        validate(nc_meta, dims=[1, 1, 1])
    except ValidationError as e:
        assert "Not a netcdf param" in str(e)


def test_fail_invalid_component():
    variables = [
        {
            "param": "gwf/abcg/q",
            "attrs": {"modflow_input": "<GWF_NAME>/<ABCG_NAME>/Q"},
            "encodings": {"_FillValue": 3e30},
            "shape": ["time", "z", "y", "x"],
            "varname": "abcg_0_q",
            "numeric_type": "f8",
        },
    ]
    nc_meta = {
        "attrs": {
            "modflow_grid": "structured",
            "modflow_model": "gwf6: gwfmodel",
        },
        "variables": variables,
    }

    try:
        validate(nc_meta, dims=[1, 1, 1])
    except ValidationError as e:
        assert "Not a valid mf6 component" in str(e)


def test_fail_param_attr_layer():
    variables = [
        {
            "param": "gwf/welg/q",
            "attrs": {"modflow_input": "<GWF_NAME>/<WELG_NAME>/Q"},
            "encodings": {"_FillValue": 3e30},
            "shape": ["time", "z", "y", "x"],
            "varname": "welg_0_q",
            "numeric_type": "f8",
        },
    ]
    nc_meta = {
        "attrs": {
            "modflow_grid": "structured",
            "modflow_model": "gwf6: gwfmodel",
            "mesh": "layered",
        },
        "variables": variables,
    }

    try:
        validate(nc_meta, dims=[1, 1])
    except ValidationError as e:
        assert "Expected layer attribute for mesh param" in str(e)


def test_fail_param_attr_layer_val():
    variables = [
        {
            "param": "gwf/welg/q",
            "attrs": {"modflow_input": "<GWF_NAME>/<WELG_NAME>/Q", "layer": 2},
            "encodings": {"_FillValue": 3e30},
            "shape": ["time", "z", "y", "x"],
            "varname": "welg_0_q",
            "numeric_type": "f8",
        },
    ]
    nc_meta = {
        "attrs": {
            "modflow_grid": "structured",
            "modflow_model": "gwf6: gwfmodel",
            "mesh": "layered",
        },
        "variables": variables,
    }

    try:
        validate(nc_meta, dims=[1, 1])
    except ValidationError as e:
        assert "Param layer attr value 2 exceeds grid k" in str(e)


def test_fail_param_attr_input():
    variables = [
        {
            "param": "gwf/welg/q",
            "attrs": {"layer": 1},
            "encodings": {"_FillValue": 3e30},
            "shape": ["time", "z", "y", "x"],
            "varname": "welg_0_q",
            "numeric_type": "f8",
        },
    ]
    nc_meta = {
        "attrs": {
            "modflow_grid": "structured",
            "modflow_model": "gwf6: gwfmodel",
            "mesh": "layered",
        },
        "variables": variables,
    }

    try:
        validate(nc_meta, dims=[1, 1])
    except ValidationError as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        print(f"Exception Type: {exc_type.__name__}")
        print(f"Exception Value: {exc_value}")
        print(f"Traceback Object: {exc_traceback}")
        assert "modflow_input" in str(e)


def test_xarray_structured_mesh():
    nc_input = NetCDFModelInput(
        name="twri",
        type="gwf",
        grid_type="structured",
        dims=[2, 4, 3, 2],  # ["time", "z", "y", "x"]
    )

    nc_input.packages.append(NetCDFPackageCfg("npf", "npf", params=["k", "k22"]))
    nc_input.packages.append(NetCDFPackageCfg("welg_0", "welg", params=["q"]))

    ds = nc_input.to_xarray()

    assert ds.attrs["modflow_grid"] == "structured"
    assert ds.attrs["modflow_model"] == "gwf6: twri"
    assert "mesh" not in ds.attrs
    assert "npf_k" in ds
    assert "npf_k22" in ds
    assert "welg_0_q" in ds
    assert np.allclose(ds["npf_k"].values, FILLNA_FLOAT64)
    assert np.allclose(ds["npf_k22"].values, FILLNA_FLOAT64)
    assert np.allclose(ds["welg_0_q"].values, DNODATA)
    assert ds["npf_k"].dims == ("z", "y", "x")
    assert ds["npf_k22"].dims == ("z", "y", "x")
    assert ds["welg_0_q"].dims == ("time", "z", "y", "x")
    assert ds.dims["time"] == 2
    assert ds.dims["z"] == 4
    assert ds.dims["y"] == 3
    assert ds.dims["x"] == 2
    assert len(ds) == 3

    nc_fpath = Path.cwd() / "twri.input.nc"
    ds.to_netcdf(
        nc_fpath,
        format="NETCDF4",
        engine="netcdf4",
    )

    assert nc_fpath.is_file()


def test_xarray_layered_mesh():
    nc_input = NetCDFModelInput(
        name="twri",
        type="gwf",
        grid_type="structured",
        mesh_type="layered",
        dims=[2, 4, 6],  # ["time", "z", "nmesh_face"]
    )

    nc_input.packages.append(NetCDFPackageCfg("npf", "npf", params=["k", "k22"]))
    nc_input.packages.append(NetCDFPackageCfg("welg_0", "welg", params=["q"]))

    ds = nc_input.to_xarray()

    assert ds.attrs["modflow_grid"] == "structured"
    assert ds.attrs["modflow_model"] == "gwf6: twri"
    assert ds.attrs["mesh"] == "layered"
    for k in range(4):
        layer = k + 1
        assert f"npf_k_l{layer}" in ds
        assert f"npf_k22_l{layer}" in ds
        assert f"welg_0_q_l{layer}" in ds
        assert np.allclose(ds[f"npf_k_l{layer}"].values, FILLNA_FLOAT64)
        assert np.allclose(ds[f"npf_k22_l{layer}"].values, FILLNA_FLOAT64)
        assert np.allclose(ds[f"welg_0_q_l{layer}"].values, DNODATA)
        assert ds[f"npf_k_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"npf_k22_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"welg_0_q_l{layer}"].dims == ("time", "z", "nmesh_face")
    assert ds.dims["time"] == 2
    assert ds.dims["z"] == 4
    assert ds.dims["nmesh_face"] == 6
    assert len(ds) == 12

    nc_fpath = Path.cwd() / "twri.input.nc"
    ds.to_netcdf(
        nc_fpath,
        format="NETCDF4",
        engine="netcdf4",
    )

    assert nc_fpath.is_file()


def test_xarray_disv():
    nc_input = NetCDFModelInput(
        name="twri",
        type="gwf",
        grid_type="vertex",
        mesh_type="layered",
        dims=[2, 4, 6],
    )

    nc_input.packages.append(NetCDFPackageCfg("npf", "npf", params=["k", "k22"]))
    nc_input.packages.append(NetCDFPackageCfg("welg_0", "welg", params=["q"]))

    ds = nc_input.to_xarray()

    assert ds.attrs["modflow_grid"] == "vertex"
    assert ds.attrs["modflow_model"] == "gwf6: twri"
    assert ds.attrs["mesh"] == "layered"
    for k in range(4):
        layer = k + 1
        assert f"npf_k_l{layer}" in ds
        assert f"npf_k22_l{layer}" in ds
        assert f"welg_0_q_l{layer}" in ds
        assert np.allclose(ds[f"npf_k_l{layer}"].values, FILLNA_FLOAT64)
        assert np.allclose(ds[f"npf_k22_l{layer}"].values, FILLNA_FLOAT64)
        assert np.allclose(ds[f"welg_0_q_l{layer}"].values, DNODATA)
        assert ds[f"npf_k_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"npf_k22_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"welg_0_q_l{layer}"].dims == ("time", "z", "nmesh_face")
    assert ds.dims["time"] == 2
    assert ds.dims["z"] == 4
    assert ds.dims["nmesh_face"] == 6
    assert len(ds) == 12

    nc_fpath = Path.cwd() / "disv.input.nc"
    ds.to_netcdf(
        nc_fpath,
        format="NETCDF4",
        engine="netcdf4",
    )

    assert nc_fpath.is_file()


def test_xarray_disv_aux():
    nc_input = NetCDFModelInput(
        name="twri",
        type="gwf6",
        grid_type="vertex",
        mesh_type="layered",
        dims=[2, 4, 6],
    )

    nc_input.packages.append(NetCDFPackageCfg("npf", "npf", params=["k", "k22"]))
    nc_input.packages.append(
        NetCDFPackageCfg(
            "welg_0",
            "welg",
            auxiliary=["concentration", "temperature"],
            params=["q", "aux"],
        )
    )

    ds = nc_input.to_xarray()

    assert ds.attrs["modflow_grid"] == "vertex"
    assert ds.attrs["modflow_model"] == "gwf6: twri"
    assert ds.attrs["mesh"] == "layered"
    for k in range(4):
        layer = k + 1
        assert f"npf_k_l{layer}" in ds
        assert f"npf_k22_l{layer}" in ds
        assert f"welg_0_q_l{layer}" in ds
        assert f"welg_0_concentration_l{layer}" in ds
        assert f"welg_0_temperature_l{layer}" in ds
        assert np.allclose(ds[f"npf_k_l{layer}"].values, FILLNA_FLOAT64)
        assert np.allclose(ds[f"npf_k22_l{layer}"].values, FILLNA_FLOAT64)
        assert np.allclose(ds[f"welg_0_q_l{layer}"].values, DNODATA)
        assert np.allclose(ds[f"welg_0_concentration_l{layer}"].values, DNODATA)
        assert np.allclose(ds[f"welg_0_temperature_l{layer}"].values, DNODATA)
        assert ds[f"npf_k_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"npf_k22_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"welg_0_q_l{layer}"].dims == ("time", "z", "nmesh_face")
        assert ds[f"welg_0_concentration_l{layer}"].dims == ("time", "z", "nmesh_face")
        assert ds[f"welg_0_temperature_l{layer}"].dims == ("time", "z", "nmesh_face")
        assert ds[f"welg_0_concentration_l{layer}"].attrs["modflow_iaux"] == 1
        assert ds[f"welg_0_temperature_l{layer}"].attrs["modflow_iaux"] == 2
    assert ds.dims["time"] == 2
    assert ds.dims["z"] == 4
    assert ds.dims["nmesh_face"] == 6
    assert len(ds) == 20

    nc_fpath = Path.cwd() / "disv_aux.input.nc"
    ds.to_netcdf(
        nc_fpath,
        format="NETCDF4",
        engine="netcdf4",
    )

    assert nc_fpath.is_file()


def test_xarray_disv_all_params():
    nc_input = NetCDFModelInput(
        name="twri",
        type="gwf",
        grid_type="vertex",
        mesh_type="layered",
        dims=[2, 4, 6],
    )

    nc_input.packages.append(NetCDFPackageCfg("npf", "npf"))
    nc_input.packages.append(NetCDFPackageCfg("welg_0", "welg"))
    # TODO: rcha and evta need netcdf annotation in dfns
    # nc_cfg.packages.append(NetCDFPackageCfg("rch0", "rcha"))

    ds = nc_input.to_xarray()

    assert ds.attrs["modflow_grid"] == "vertex"
    assert ds.attrs["modflow_model"] == "gwf6: twri"
    assert ds.attrs["mesh"] == "layered"
    for k in range(4):
        layer = k + 1
        assert f"npf_icelltype_l{layer}" in ds
        assert f"npf_k_l{layer}" in ds
        assert f"npf_k22_l{layer}" in ds
        assert f"npf_k33_l{layer}" in ds
        assert f"npf_angle1_l{layer}" in ds
        assert f"npf_angle2_l{layer}" in ds
        assert f"npf_angle3_l{layer}" in ds
        assert f"npf_wetdry_l{layer}" in ds
        assert f"welg_0_q_l{layer}" in ds
        assert np.allclose(ds[f"npf_icelltype_l{layer}"].values, FILLNA_INT32)
        assert np.allclose(ds[f"npf_k_l{layer}"].values, FILLNA_FLOAT64)
        assert np.allclose(ds[f"npf_k22_l{layer}"].values, FILLNA_FLOAT64)
        assert np.allclose(ds[f"npf_k33_l{layer}"].values, FILLNA_FLOAT64)
        assert np.allclose(ds[f"npf_angle1_l{layer}"].values, FILLNA_FLOAT64)
        assert np.allclose(ds[f"npf_angle2_l{layer}"].values, FILLNA_FLOAT64)
        assert np.allclose(ds[f"npf_angle3_l{layer}"].values, FILLNA_FLOAT64)
        assert np.allclose(ds[f"npf_wetdry_l{layer}"].values, FILLNA_FLOAT64)
        assert np.allclose(ds[f"welg_0_q_l{layer}"].values, DNODATA)
        assert ds[f"npf_icelltype_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"npf_k_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"npf_k22_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"npf_k33_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"npf_angle1_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"npf_angle2_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"npf_angle3_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"npf_wetdry_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"welg_0_q_l{layer}"].dims == ("time", "z", "nmesh_face")
    assert ds.dims["time"] == 2
    assert ds.dims["z"] == 4
    assert ds.dims["nmesh_face"] == 6
    assert len(ds) == 36

    nc_fpath = Path.cwd() / "disv_all.input.nc"
    ds.to_netcdf(
        nc_fpath,
        format="NETCDF4",
        engine="netcdf4",
    )

    assert nc_fpath.is_file()


def test_jsonschema():
    from jsonschema import Draft7Validator

    nc_input = NetCDFModelInput(
        name="twri",
        type="gwf",
        grid_type="vertex",
        mesh_type="layered",
        dims=[2, 4, 6],
    )

    nc_input.packages.append(NetCDFPackageCfg("npf", "npf"))
    nc_input.packages.append(NetCDFPackageCfg("welg_0", "welg"))

    schema = nc_input.jsonschema
    assert isinstance(schema, dict)
    Draft7Validator.check_schema(schema)  # raises if not valid
    validator = Draft7Validator(schema)
    assert validator.is_valid(nc_input.meta)
