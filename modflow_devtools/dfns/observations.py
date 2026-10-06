"""Observation types each component accepts in its OBS file.

Transcribed from MF6: the obstypes each package registers (`StoreObsType`) and
how its id processor reads ID and ID2. Where the docs (`doc/Common/*obs.tex`)
disagree, the Fortran wins (e.g. the docs list an ID2 for GWE LKE's `lke`,
which MF6 doesn't read).

PRT's PRP registers obstypes but its DFN has no OBS file, so it's left out, as
are the SWF-GWF exchanges, which register none.
"""

from modflow_devtools.dfns import schema as v2


def _id(*arms: str, fk: str | None = None, name: str | None = None) -> v2.ObservationId:
    return v2.ObservationId(arms=list(arms), fk=fk, name=name)


def _obs(id: v2.ObservationId, id2: v2.ObservationId | None = None) -> v2.Observation:
    return v2.Observation(id=id, id2=id2)


def _all(id: v2.ObservationId, *obstypes: str) -> dict[str, v2.Observation]:
    """Obstypes that all take the same ID and no ID2."""
    return {o: _obs(id) for o in obstypes}


_CELL = _id("cellid")
_CELL_OR_NAME = _id("cellid", "boundname")
_INDEX_OR_NAME = _id("index", "boundname")
# DFW reads a single node number, whatever the grid's cellid width.
_NODE = _id("index", name="node")
_ICONN = _id("index", name="iconn")


def _feature(pk: str) -> v2.ObservationId:
    return _id("index", "boundname", fk=f"packagedata.{pk}")


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
def _model(*depvars: str) -> dict[str, v2.Observation]:
    return {**_all(_CELL, *depvars), "flow-ja-face": _obs(_CELL, _CELL)}


_GWF_MODEL = _model("head", "drawdown")
_GWT_MODEL = _model("concentration")
_GWE_MODEL = _model("temperature")
_SWF_MODEL = _model("stage")

# Exchanges: an id is a row number in EXCHANGEDATA, which has no pk column.
_EXCHANGE = _all(_INDEX_OR_NAME, "flow-ja-face")

# CSUB
_ICSUBNO = _id("index", fk="packagedata.icsubno")
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
        o: _obs(_ICSUBNO, _id("index", name="idcellno"))
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
_LAK_OUTLET = _id("index", "boundname", fk="outlets.outletno")
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
    **{o: _obs(_feature("ifno"), _ICONN) for o in ("lak", "wetted-area", "conductance")},
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
    **{o: _obs(_feature("ifno"), _id("index", name="icon")) for o in ("maw", "conductance")},
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
    "water-content": _obs(
        _feature("ifno"),
        v2.ObservationId(type="double", name="depth", with_boundname=True),
    ),
}


# Advanced transport packages
def _apt(pk: str, depvar: str, *obstypes: str) -> dict[str, v2.Observation]:
    """Obstypes common to every APT package plus ``obstypes``, all keyed by
    feature. Those taking an ID2 are added by the caller."""
    return _all(_feature(pk), depvar, "storage", "constant", "from-mvr", *obstypes)


def _flow_ja_face(pk: str) -> v2.Observation:
    # ID2 is the other feature.
    return _obs(_feature(pk), _id("index", fk=f"packagedata.{pk}"))


# LKT/LKE's to-mvr is keyed by the flow package's outlet, not in this component.
_FLOW_OUTLET = _id("index", "boundname", name="outletno")
_LAKE_TERMS = ("rainfall", "evaporation", "runoff", "ext-inflow", "withdrawal", "ext-outflow")
_STREAM_TERMS = ("to-mvr", "rainfall", "evaporation", "runoff", "ext-inflow", "ext-outflow")
_WELL_TERMS = ("rate", "fw-rate", "rate-to-mvr", "fw-rate-to-mvr")
_UZ_TERMS = ("infiltration", "rej-inf", "uzet", "rej-inf-to-mvr")

_LKT = {
    **_apt("ifno", "concentration", *_LAKE_TERMS),
    "flow-ja-face": _flow_ja_face("ifno"),
    "to-mvr": _obs(_FLOW_OUTLET),
    "lkt": _obs(_feature("ifno"), _ICONN),
}
_SFT = {
    **_apt("ifno", "concentration", "sft", *_STREAM_TERMS),
    "flow-ja-face": _flow_ja_face("ifno"),
}
_MWT = {
    **_apt("ifno", "concentration", *_WELL_TERMS),
    "mwt": _obs(_feature("ifno"), _ICONN),
}
_UZT = {
    **_apt("ifno", "concentration", "uzt", *_UZ_TERMS),
    "flow-ja-face": _flow_ja_face("ifno"),
}
_LKE = {
    **_apt("lakeno", "temperature", "lke", *_LAKE_TERMS),
    "flow-ja-face": _flow_ja_face("lakeno"),
    "to-mvr": _obs(_FLOW_OUTLET),
}
_SFE = {
    **_apt("rno", "temperature", "sfe", "strmbd-cond", *_STREAM_TERMS),
    "flow-ja-face": _flow_ja_face("rno"),
}
_MWE = {
    **_apt("mawno", "temperature", *_WELL_TERMS),
    "mwe": _obs(_feature("mawno"), _ICONN),
}
_UZE = {
    **_apt("uzfno", "temperature", "uze", "thermal-equil", *_UZ_TERMS),
    "flow-ja-face": _flow_ja_face("uzfno"),
}

# Observation types by component name.
OBSERVATIONS: dict[str, dict[str, v2.Observation]] = {
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
