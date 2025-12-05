import sys

from pydantic import ValidationError

from modflow_devtools.netcdf_schema import validate


def test_validate_model():
    variables = [
        {
            "param": "gwf/welg/aux",
            "attrs": {"modflow_input": "GWFMODEL/WELG0/AUX", "modflow_iaux": 1},
            "encodings": {"_FillValue": 3e30},
            "shape": ["time", "z", "y", "x"],
            "varname": "welg_0_aux",
            "numeric_type": "f8",
        },
        {
            "param": "gwf/welg/q",
            "attrs": {"modflow_input": "GWFMODEL/WELG0/Q"},
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
                "modflow_input": "GWFMODEL/WELG0/AUX",
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
            "attrs": {"modflow_input": "GWFMODEL/WELG0/Q", "layer": 1},
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
            "mesh": "LAYERED",
        },
        "variables": variables,
    }

    validate(nc_meta, dims=[1, 1])


def test_fail_invalid_param():
    variables = [
        {
            "param": "gwf/wel/q",
            "attrs": {"modflow_input": "GWFMODEL/WELG0/Q"},
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
            "attrs": {"modflow_input": "GWFMODEL/WELG0/Q"},
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
            "attrs": {"modflow_input": "GWFMODEL/WELG0/Q"},
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
            "attrs": {"modflow_input": "GWFMODEL/WELG0/Q", "layer": 2},
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
