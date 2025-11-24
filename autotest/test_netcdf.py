from pathlib import Path

import numpy as np

from modflow_devtools.netcdf import ModelNetCDFConfig, NetCDFInput, PkgNetCDFConfig
from modflow_devtools.netcdf_schema import validate

PROJ_ROOT = Path(__file__).parents[1]
DFN_DIR = PROJ_ROOT / "autotest" / "temp" / "dfn"
TOML_DIR = DFN_DIR / "toml"


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

    validate(nc_meta, TOML_DIR, grid_dims=[1, 1, 1])


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

    validate(nc_meta, TOML_DIR, grid_dims=[1, 1])


def test_xarray_structured_mesh():
    nc_cfg = ModelNetCDFConfig(
        name="twri",
        type="gwf",
        grid_type="structured",
        dims=[2, 4, 3, 2],  # ["time", "z", "y", "x"]
    )

    nc_cfg.packages.append(PkgNetCDFConfig("npf", "npf", ["k", "k22"]))
    nc_cfg.packages.append(PkgNetCDFConfig("welg_0", "welg", ["q"]))

    nc_input = NetCDFInput(TOML_DIR, nc_cfg)
    ds = nc_input.to_xarray()

    assert ds.attrs["modflow_grid"] == "structured"
    assert ds.attrs["modflow_model"] == "gwf: twri"
    assert "mesh" not in ds.attrs
    assert "npf_k" in ds
    assert "npf_k22" in ds
    assert "welg_0_q" in ds
    assert np.allclose(ds["npf_k"].values, 3.0e30)
    assert np.allclose(ds["npf_k22"].values, 3.0e30)
    assert np.allclose(ds["welg_0_q"].values, 3.0e30)
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
        # encoding=encoding,
    )

    assert nc_fpath.is_file()


def test_xarray_layered_mesh():
    nc_cfg = ModelNetCDFConfig(
        name="twri",
        type="gwf",
        grid_type="structured",
        mesh_type="layered",
        dims=[2, 4, 3],  # ["time", "z", "nmesh_face"]
    )

    nc_cfg.packages.append(PkgNetCDFConfig("npf", "npf", ["k", "k22"]))
    nc_cfg.packages.append(PkgNetCDFConfig("welg_0", "welg", ["q"]))

    nc_input = NetCDFInput(TOML_DIR, nc_cfg)
    ds = nc_input.to_xarray()

    assert ds.attrs["modflow_grid"] == "structured"
    assert ds.attrs["modflow_model"] == "gwf: twri"
    assert ds.attrs["mesh"] == "layered"
    for k in range(4):
        layer = k + 1
        assert f"npf_k_l{layer}" in ds
        assert f"npf_k22_l{layer}" in ds
        assert f"welg_0_q_l{layer}" in ds
        assert np.allclose(ds[f"npf_k_l{layer}"].values, 3.0e30)
        assert np.allclose(ds[f"npf_k22_l{layer}"].values, 3.0e30)
        assert np.allclose(ds[f"welg_0_q_l{layer}"].values, 3.0e30)
        assert ds[f"npf_k_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"npf_k22_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"welg_0_q_l{layer}"].dims == ("time", "z", "nmesh_face")
    assert ds.dims["time"] == 2
    assert ds.dims["z"] == 4
    assert ds.dims["nmesh_face"] == 3
    assert len(ds) == 12

    nc_fpath = Path.cwd() / "twri.input.nc"
    ds.to_netcdf(
        nc_fpath,
        format="NETCDF4",
        engine="netcdf4",
        # encoding=encoding,
    )

    assert nc_fpath.is_file()


def test_xarray_disv():
    nc_cfg = ModelNetCDFConfig(
        name="twri",
        type="gwf",
        grid_type="vertex",
        mesh_type="layered",
        dims=[2, 4, 3],
    )

    nc_cfg.packages.append(PkgNetCDFConfig("npf", "npf", ["k", "k22"]))
    nc_cfg.packages.append(PkgNetCDFConfig("welg_0", "welg", ["q"]))

    nc_input = NetCDFInput(TOML_DIR, nc_cfg)
    ds = nc_input.to_xarray()

    assert ds.attrs["modflow_grid"] == "vertex"
    assert ds.attrs["modflow_model"] == "gwf: twri"
    assert ds.attrs["mesh"] == "layered"
    for k in range(4):
        layer = k + 1
        assert f"npf_k_l{layer}" in ds
        assert f"npf_k22_l{layer}" in ds
        assert f"welg_0_q_l{layer}" in ds
        assert np.allclose(ds[f"npf_k_l{layer}"].values, 3.0e30)
        assert np.allclose(ds[f"npf_k22_l{layer}"].values, 3.0e30)
        assert np.allclose(ds[f"welg_0_q_l{layer}"].values, 3.0e30)
        assert ds[f"npf_k_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"npf_k22_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"welg_0_q_l{layer}"].dims == ("time", "z", "nmesh_face")
    assert ds.dims["time"] == 2
    assert ds.dims["z"] == 4
    assert ds.dims["nmesh_face"] == 3
    assert len(ds) == 12

    nc_fpath = Path.cwd() / "twri.input.nc"
    ds.to_netcdf(
        nc_fpath,
        format="NETCDF4",
        engine="netcdf4",
        # encoding=encoding,
    )

    assert nc_fpath.is_file()

    print(nc_input.to_meta())


def test_xarray_disv_all_params():
    nc_cfg = ModelNetCDFConfig(
        name="twri",
        type="gwf",
        grid_type="vertex",
        mesh_type="layered",
        dims=[2, 4, 3],
    )

    nc_cfg.packages.append(PkgNetCDFConfig("npf", "npf"))
    nc_cfg.packages.append(PkgNetCDFConfig("welg_0", "welg"))

    nc_input = NetCDFInput(TOML_DIR, nc_cfg)
    ds = nc_input.to_xarray()

    assert ds.attrs["modflow_grid"] == "vertex"
    assert ds.attrs["modflow_model"] == "gwf: twri"
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
        assert f"welg_0_aux_l{layer}" in ds
        # TODO
        # assert np.allclose(ds[f"npf_icelltype_l{layer}"].values, 3.0e30)
        assert np.allclose(ds[f"npf_k_l{layer}"].values, 3.0e30)
        assert np.allclose(ds[f"npf_k22_l{layer}"].values, 3.0e30)
        assert np.allclose(ds[f"npf_k33_l{layer}"].values, 3.0e30)
        assert np.allclose(ds[f"npf_angle1_l{layer}"].values, 3.0e30)
        assert np.allclose(ds[f"npf_angle2_l{layer}"].values, 3.0e30)
        assert np.allclose(ds[f"npf_angle3_l{layer}"].values, 3.0e30)
        assert np.allclose(ds[f"npf_wetdry_l{layer}"].values, 3.0e30)
        assert np.allclose(ds[f"welg_0_q_l{layer}"].values, 3.0e30)
        assert np.allclose(ds[f"welg_0_aux_l{layer}"].values, 3.0e30)
        assert ds[f"npf_icelltype_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"npf_k_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"npf_k22_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"npf_k33_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"npf_angle1_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"npf_angle2_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"npf_angle3_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"npf_wetdry_l{layer}"].dims == ("z", "nmesh_face")
        assert ds[f"welg_0_q_l{layer}"].dims == ("time", "z", "nmesh_face")
        assert ds[f"welg_0_aux_l{layer}"].dims == ("time", "z", "nmesh_face")
    assert ds.dims["time"] == 2
    assert ds.dims["z"] == 4
    assert ds.dims["nmesh_face"] == 3
    assert len(ds) == 40

    nc_fpath = Path.cwd() / "twri.input.nc"
    ds.to_netcdf(
        nc_fpath,
        format="NETCDF4",
        engine="netcdf4",
        # encoding=encoding,
    )

    assert nc_fpath.is_file()
