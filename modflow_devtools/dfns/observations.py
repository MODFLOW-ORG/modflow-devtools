"""Observation types each component accepts in its OBS file.

Transcribed from MF6: the obstypes each package registers (`StoreObsType`) and
how its id processor reads ID and ID2. Where the docs (`doc/Common/*obs.tex`)
disagree, the Fortran wins (e.g. the docs list an ID2 for GWE LKE's `lke`,
which MF6 doesn't read).

PRT's PRP registers obstypes but its DFN has no OBS file, so it's left out, as
are the SWF-GWF exchanges, which register none.
"""

from modflow_devtools.dfns import schema as v2

_Field = v2.ObservationField


def _index(name: str, fk: str | None = None) -> v2.Integer:
    return v2.Integer(name=name, tagged=False, index=True, fk=fk)


def _cellid(name: str = "cellid") -> v2.Array:
    return v2.Array(
        name=name, tagged=False, dtype="integer", shape=["ncelldim"], index=True, cellid=True
    )


def _record(
    *fields: "v2.Integer | v2.Double | v2.String | v2.Array | v2.Union",
) -> v2.Record:
    """ID and ID2, named after both (e.g. ``ifno_iconn``) so records that are
    arms of the same union get distinct names."""
    name = "_".join(f.name for f in fields)
    return v2.Record(name=name, tagged=False, fields={f.name: f for f in fields})


def _or_boundname(form: "v2.Integer | v2.Array | v2.Record") -> v2.Union:
    """``form``, or a boundname instead, after which MF6 reads no ID2."""
    boundname = v2.String(name="boundname", tagged=False)
    return v2.Union(name=form.name, tagged=False, arms={form.name: form, "boundname": boundname})


def _all(field: _Field, *obstypes: str) -> dict[str, _Field]:
    """Obstypes that all take ``field``."""
    return dict.fromkeys(obstypes, field)


_CELL = _cellid()
_CELL_OR_NAME = _or_boundname(_cellid())
# DFW reads a single node number, whatever the grid's cellid width.
_NODE = _index("node")


def _feature(pk: str) -> v2.Union:
    return _or_boundname(_index(pk, fk=f"packagedata.{pk}"))


def _connection(pk: str, iconn: str = "iconn") -> v2.Union:
    """A feature and one of its connections, or a boundname for all of them."""
    return _or_boundname(_record(_index(pk, fk=f"packagedata.{pk}"), _index(iconn)))


def _connection_or_name(pk: str, iconn: str = "iconn") -> v2.Union:
    """A feature and one of its connections, or a boundname for all of them,
    after a feature number or not (MF6 then ignores the number). LAK and MAW
    read a boundname as ID2; the APT packages read ID2 as a number only."""
    feature = _index(pk, fk=f"packagedata.{pk}")
    boundname = v2.String(name="boundname", tagged=False)
    arms = (_record(feature, _index(iconn)), _record(feature, boundname), boundname)
    return v2.Union(name=pk, tagged=False, arms={arm.name: arm for arm in arms})


# Stress packages
_CHD = _all(_CELL_OR_NAME, "chd")
_WEL = _all(_CELL_OR_NAME, "wel", "to-mvr", "wel-reduction")
_DRN = _all(_CELL_OR_NAME, "drn", "to-mvr")
_RIV = _all(_CELL_OR_NAME, "riv", "to-mvr")
_GHB = _all(_CELL_OR_NAME, "ghb", "to-mvr")
_RCH = _all(_CELL_OR_NAME, "rch")
_EVT = _all(_CELL_OR_NAME, "evt")
_API = _all(_CELL_OR_NAME, "api", "to-mvr")
_CNC = _all(_CELL_OR_NAME, "cnc")
_SRC = _all(_CELL_OR_NAME, "src", "to-mvr")
_CTP = _all(_CELL_OR_NAME, "ctp")
_ESL = _all(_CELL_OR_NAME, "esl", "to-mvr")
_CDB = _all(_CELL_OR_NAME, "cdb", "to-mvr")
_FLW = _all(_CELL_OR_NAME, "flw", "to-mvr")
_EVP = _all(_CELL_OR_NAME, "evp")
_PCP = _all(_CELL_OR_NAME, "pcp")
_ZDG = _all(_CELL_OR_NAME, "zdg", "to-mvr")
_DFW = _all(_NODE, "ext-outflow")


# Models
def _model(*depvars: str) -> dict[str, _Field]:
    return {**_all(_CELL, *depvars), "flow-ja-face": _record(_cellid(), _cellid("cellid2"))}


_GWF_MODEL = _model("head", "drawdown")
_GWT_MODEL = _model("concentration")
_GWE_MODEL = _model("temperature")
_SWF_MODEL = _model("stage")

# Exchanges: an id is a row number in EXCHANGEDATA, which has no pk column.
_EXCHANGE = _all(_or_boundname(_index("iexg")), "flow-ja-face")

# CSUB
_ICSUBNO = _index("icsubno", fk="packagedata.icsubno")
_CSUB = {
    **_all(_feature("icsubno"), "csub", "inelastic-csub", "elastic-csub"),
    **_all(_feature("icsubno"), "delay-flowtop", "delay-flowbot"),
    **_all(
        _ICSUBNO,
        "sk",
        "ske",
        "theta",
        "thickness",
        "interbed-compaction",
        "interbed-compaction-pct",
        "inelastic-compaction",
        "elastic-compaction",
    ),
    **{
        o: _record(_ICSUBNO, _index("idcellno"))
        for o in (
            "delay-head",
            "delay-gstress",
            "delay-estress",
            "delay-preconstress",
            "delay-compaction",
            "delay-thickness",
            "delay-theta",
        )
    },
    **_all(
        _CELL,
        "coarse-csub",
        "csub-cell",
        "wcomp-csub-cell",
        "sk-cell",
        "ske-cell",
        "estress-cell",
        "gstress-cell",
        "preconstress-cell",
        "coarse-compaction",
        "compaction-cell",
        "inelastic-compaction-cell",
        "elastic-compaction-cell",
        "coarse-thickness",
        "thickness-cell",
        "coarse-theta",
        "theta-cell",
    ),
}

# Advanced flow packages
_LAK_OUTLET = _or_boundname(_index("outletno", fk="outlets.outletno"))
_LAK = {
    **_all(
        _feature("ifno"),
        "stage",
        "ext-inflow",
        "outlet-inflow",
        "inflow",
        "from-mvr",
        "rainfall",
        "runoff",
        "withdrawal",
        "evaporation",
        "storage",
        "constant",
        "volume",
        "surface-area",
    ),
    **_all(_connection_or_name("ifno"), "lak", "wetted-area", "conductance"),
    **_all(_LAK_OUTLET, "ext-outflow", "to-mvr", "outlet"),
}
_MAW = {
    **_all(
        _feature("ifno"),
        "head",
        "from-mvr",
        "rate",
        "rate-to-mvr",
        "fw-rate",
        "fw-to-mvr",
        "storage",
        "constant",
        "fw-conductance",
    ),
    **_all(_connection_or_name("ifno", "icon"), "maw", "conductance"),
}
_SFR = _all(
    _feature("ifno"),
    "stage",
    "ext-inflow",
    "inflow",
    "from-mvr",
    "rainfall",
    "runoff",
    "sfr",
    "evaporation",
    "outflow",
    "ext-outflow",
    "to-mvr",
    "upstream-flow",
    "downstream-flow",
    "depth",
    "wet-perimeter",
    "wet-area",
    "wet-width",
)
_UZF = {
    **_all(
        _feature("ifno"),
        "uzf-gwrch",
        "uzf-gwd",
        "uzf-gwd-to-mvr",
        "uzf-gwet",
        "infiltration",
        "from-mvr",
        "rej-inf",
        "rej-inf-to-mvr",
        "uzet",
        "storage",
        "net-infiltration",
    ),
    # The depth follows a boundname too.
    "water-content": _record(_feature("ifno"), v2.Double(name="depth", tagged=False)),
}


# Advanced transport packages
def _apt(pk: str, depvar: str, *obstypes: str) -> dict[str, _Field]:
    """Obstypes common to every APT package plus ``obstypes``, all keyed by
    feature. Those taking an ID2 are added by the caller."""
    return _all(_feature(pk), depvar, "storage", "constant", "from-mvr", *obstypes)


def _flow_ja_face(pk: str) -> v2.Union:
    """Flow between two features, or all those with a boundname."""
    fk = f"packagedata.{pk}"
    return _or_boundname(_record(_index(pk, fk=fk), _index(f"{pk}2", fk=fk)))


# LKT/LKE's to-mvr is keyed by the flow package's outlet, not in this component.
_FLOW_OUTLET = _or_boundname(_index("outletno"))
_LAKE_TERMS = ("rainfall", "evaporation", "runoff", "ext-inflow", "withdrawal", "ext-outflow")
_STREAM_TERMS = ("to-mvr", "rainfall", "evaporation", "runoff", "ext-inflow", "ext-outflow")
_WELL_TERMS = ("rate", "fw-rate", "rate-to-mvr", "fw-rate-to-mvr")
_UZ_TERMS = ("infiltration", "rej-inf", "uzet", "rej-inf-to-mvr")

_LKT = {
    **_apt("ifno", "concentration", *_LAKE_TERMS),
    "flow-ja-face": _flow_ja_face("ifno"),
    "to-mvr": _FLOW_OUTLET,
    "lkt": _connection("ifno"),
}
_SFT = {
    **_apt("ifno", "concentration", "sft", *_STREAM_TERMS),
    "flow-ja-face": _flow_ja_face("ifno"),
}
_MWT = {
    **_apt("ifno", "concentration", *_WELL_TERMS),
    "mwt": _connection("ifno"),
}
_UZT = {
    **_apt("ifno", "concentration", "uzt", *_UZ_TERMS),
    "flow-ja-face": _flow_ja_face("ifno"),
}
_LKE = {
    **_apt("lakeno", "temperature", "lke", *_LAKE_TERMS),
    "flow-ja-face": _flow_ja_face("lakeno"),
    "to-mvr": _FLOW_OUTLET,
}
_SFE = {
    **_apt("rno", "temperature", "sfe", "strmbd-cond", *_STREAM_TERMS),
    "flow-ja-face": _flow_ja_face("rno"),
}
_MWE = {
    **_apt("mawno", "temperature", *_WELL_TERMS),
    "mwe": _connection("mawno"),
}
_UZE = {
    **_apt("uzfno", "temperature", "uze", "thermal-equil", *_UZ_TERMS),
    "flow-ja-face": _flow_ja_face("uzfno"),
}

_TABLES: dict[str, dict[str, _Field]] = {
    **{f"{m}-nam": _SWF_MODEL for m in ("chf", "olf", "swf")},
    **{f"{m}-chd": _CHD for m in ("gwf", "chf", "olf", "swf")},
    **{
        f"{m}-{p}": t
        for m in ("chf", "olf", "swf")
        for p, t in (
            ("cdb", _CDB),
            ("dfw", _DFW),
            ("evp", _EVP),
            ("flw", _FLW),
            ("pcp", _PCP),
            ("zdg", _ZDG),
        )
    },
    "exg-gwegwe": _EXCHANGE,
    "exg-gwfgwf": _EXCHANGE,
    "exg-gwtgwt": _EXCHANGE,
    "gwe-ctp": _CTP,
    "gwe-esl": _ESL,
    "gwe-lke": _LKE,
    "gwe-mwe": _MWE,
    "gwe-nam": _GWE_MODEL,
    "gwe-sfe": _SFE,
    "gwe-uze": _UZE,
    "gwf-api": _API,
    "gwf-chdg": _CHD,
    "gwf-csub": _CSUB,
    "gwf-drn": _DRN,
    "gwf-drng": _DRN,
    "gwf-evt": _EVT,
    "gwf-evta": _EVT,
    "gwf-ghb": _GHB,
    "gwf-ghbg": _GHB,
    "gwf-lak": _LAK,
    "gwf-maw": _MAW,
    "gwf-nam": _GWF_MODEL,
    "gwf-rch": _RCH,
    "gwf-rcha": _RCH,
    "gwf-riv": _RIV,
    "gwf-rivg": _RIV,
    "gwf-sfr": _SFR,
    "gwf-uzf": _UZF,
    "gwf-wel": _WEL,
    "gwf-welg": _WEL,
    "gwt-api": _API,
    "gwt-cnc": _CNC,
    "gwt-lkt": _LKT,
    "gwt-mwt": _MWT,
    "gwt-nam": _GWT_MODEL,
    "gwt-sft": _SFT,
    "gwt-src": _SRC,
    "gwt-uzt": _UZT,
}

# Observation types by component name, each field named after its obstype.
OBSERVATIONS: dict[str, dict[str, _Field]] = {
    component: {o: f.model_copy(update={"name": o}) for o, f in table.items()}
    for component, table in _TABLES.items()
}
