"""Migrate MODFLOW 6 DFN files from v1 format to schema version 2.0.0.dev3.

2.0.0.dev3 differs from dev2 mainly in the addition of a ``memory`` section
to each component, documenting runtime API-accessible variables. These are
derived from three sources:

  1. ``mf6internal`` annotations in v1 fields, which map input field names to
     IDM/simulation variable names. Option keywords become ``logical`` memory
     variables marked ``readonly = true``.

  2. Griddata and packagedata fields without ``mf6internal``, for which the
     memory variable name matches the DFN field name (the dominant convention
     in the MF6 codebase).

  3. Standard variables for all boundary (i.e. stress) packages (``NBOUND``,
     ``NODELIST``, ``BOUND``, ``HCOF``, ``RHS``, ``SIMVALS``, etc.), with BOUND
     column names derived from the period block field order.

Package-specific variables that are not captured by the above (e.g. ``k → k11``,
``condsat``, ``area``) are hardcoded and override any entry with the same name.
"""

from typing import Literal

from boltons.dictutils import OMD

from modflow_devtools.dfns import schema as v2
from modflow_devtools.dfns.migrate_to_v2_0_0_dev2 import to_v2_0_0_dev2, try_parse_bool

# ---------------------------------------------------------------------------
# dtype translation
# ---------------------------------------------------------------------------

_DTYPE_MAP: dict[str, Literal["integer", "double", "string", "logical"]] = {
    "keyword": "logical",
    "integer": "integer",
    "double": "double",
    "double precision": "double",
    "string": "string",
}

# Keyword-derived mf6internal variables that are i-prefixed (which normally
# signals integer(I4B) in the Fortran source) but are actually logical(LGP)
# because they live only in IDM found-struct fields, not in package memory.
_LOGICAL_KEYWORD_EXCEPTIONS = frozenset({"icubicsfac", "icompress", "imbalancecorrect"})

# Block types whose fields are loaded into simulation memory at AR time and
# whose names conventionally match the Fortran memory variable name.
_GRIDDATA_LIKE = frozenset({"griddata", "packagedata", "dimensions"})

# Field types to skip when deriving same-name memory variables from griddata /
# packagedata blocks. Keywords are boolean flags handled via mf6internal;
# record/recarray/keystring are composite types without a direct memory path.
_SKIP_FIELD_TYPES = frozenset({"keyword", "record", "recarray", "keystring"})

# Period-block item fields that do not map to BOUND columns.
_BOUND_SKIP = frozenset({"cellid", "aux", "auxiliary", "boundname"})

# Packages whose packagedata field names differ from Fortran memory variable
# names (handled instead via _EXTRA_MEMORY).
_SKIP_PACKAGEDATA_SAME_NAME = frozenset({"sfr"})

# Per-package griddata field names to exclude from the same-name convention
# (Step 3) because they are renamed or replaced by _EXTRA_MEMORY entries.
_SKIP_SAME_NAME_GRIDDATA: dict[str, frozenset[str]] = {
    "npf": frozenset({"k"}),  # k → k11 via _EXTRA_MEMORY; no memory path named K
}

# Packages excluded from the generic BoundaryPackage stress template because
# their runtime memory structure differs fundamentally from BoundaryPackage.
# HFB modifies intercell conductance rather than contributing standard boundary
# flows (no SIMVALS, no SIMTOMVR, NODELIST is 2 x nbound via nodesrc/nodedst).
# MVR redistributes flows between packages and has no BoundaryPackage lineage.
_SKIP_STRESS_TEMPLATE = frozenset({"hfb", "mvr"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_shape(shape_str: str) -> list[str]:
    """Parse a v1 shape string into a list of dimension name strings."""
    if not shape_str:
        return []
    s = shape_str.strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    result = []
    for part in (p.strip() for p in s.split(",") if p.strip()):
        if ";" in part:
            # semicolon grid-type-dependent shape — collapse to ncpl
            result.append("ncpl")
        elif part in ("any1d", "unknown") or part[:1] in ("<", ">"):
            pass  # drop unknowable or bound-annotated placeholders
        else:
            result.append(part)
    return result


def _infer_hook(block: str, time_series: bool) -> Literal["ar", "rp", "ad", "fc", "cq"] | None:
    if "period" in block:
        return "ad" if time_series else "rp"
    if block in ("options", "griddata", "packagedata", "dimensions"):
        return "ar"
    return None


def _bound_cols(component: v2.Component) -> list[str]:
    """Return period-block scalar field names that map to BOUND columns."""
    for bname, block in (component.blocks or {}).items():
        if "period" not in bname:
            continue
        for field in block.fields.values():
            if not isinstance(field, v2.List):
                continue
            item = field.item
            if not isinstance(item, v2.Record):
                continue
            return [
                n
                for n, f in item.fields.items()
                if n not in _BOUND_SKIP and isinstance(f, (v2.Double, v2.Integer, v2.String))
            ]
    return []


def _mem_var(dtype: str, shape: list[str], **kwargs) -> "v2.MemoryScalar | v2.MemoryArray":
    """Construct the appropriate MemoryScalar or MemoryArray."""
    if shape:
        return v2.MemoryArray(dtype=dtype, shape=shape, **kwargs)  # type: ignore
    return v2.MemoryScalar(type=dtype, **kwargs)  # type: ignore


# ---------------------------------------------------------------------------
# Standard BoundaryPackage memory variables (all stress packages)
# ---------------------------------------------------------------------------

# Per-package output metadata for stress packages: (budget_term, obs_type, to_mvr_budget | None).
# Budget terms and obs types are as declared in each package's Fortran source.
# The output gate is always `ipakcb`, derived from `mf6internal ipakcb` on `save_flows`.
# `to_mvr_budget` is None for packages that do not support the Water Mover provider role.
_STRESS_OUTPUT: dict[str, tuple[str, str, "str | None"]] = {
    # GWF
    "chd": ("CHD", "CHD", None),
    "chdg": ("CHD", "CHD", None),
    "wel": ("WEL", "WEL", "WEL-TO-MVR"),
    "welg": ("WEL", "WEL", "WEL-TO-MVR"),
    "drn": ("DRN", "DRN", "DRN-TO-MVR"),
    "drng": ("DRN", "DRN", "DRN-TO-MVR"),
    "riv": ("RIV", "RIV", "RIV-TO-MVR"),
    "rivg": ("RIV", "RIV", "RIV-TO-MVR"),
    "ghb": ("GHB", "GHB", "GHB-TO-MVR"),
    "ghbg": ("GHB", "GHB", "GHB-TO-MVR"),
    "rch": ("RCH", "RCH", None),
    "rcha": ("RCHA", "RCH", None),
    "evt": ("EVT", "EVT", None),
    "evta": ("EVTA", "EVT", None),
    # GWT
    "cnc": ("CNC", "CNC", None),
    "src": ("SRC", "SRC", "SRC-TO-MVR"),
    # GWE
    "ctp": ("CTP", "CTP", None),
    "esl": ("ESL", "ESL", "ESL-TO-MVR"),
    # SWF / CHF / OLF (same short names across all three model types)
    "cdb": ("CDB", "CDB", "CDB-TO-MVR"),
    "flw": ("FLW", "FLW", "FLW-TO-MVR"),
    "evp": ("EVP", "EVP", None),
    "pcp": ("PCP", "PCP", None),
    "zdg": ("ZDG", "ZDG", "ZDG-TO-MVR"),
    # PRT
    "prp": ("PRP", "PRP", "PRP-TO-MVR"),
}


def _stress_pkg_memory(
    bound_cols: list[str],
    budget: "str | None" = None,
    obs_type: "str | None" = None,
    to_mvr_budget: "str | None" = None,
) -> dict[str, "v2.MemoryScalar | v2.MemoryArray"]:
    col_desc = (
        "Columns (0-indexed): " + ", ".join(f"{i}: {c}" for i, c in enumerate(bound_cols)) + "."
        if bound_cols
        else ""
    )
    return {
        # ipakcb is set from the SAVE_FLOWS keyword. GWF stress packages declare
        # `mf6internal ipakcb` on save_flows in the v1 DFN, so step 2 of the
        # migration creates ipakcb naturally. Non-GWF stress packages lacked this
        # annotation in released DFN versions, so the template provides it as a
        # fallback to ensure the output gate reference in simvals is always valid.
        "ipakcb": _mem_var(
            "integer",
            [],
            set_in="ar",
            source="save_flows",
            description="Flag controlling whether boundary flows are written to the budget file.",
        ),
        "maxbound": _mem_var(
            "integer",
            [],
            set_in="ar",
            readonly=True,
            description="Maximum number of boundary entries per stress period.",
        ),
        "nbound": _mem_var(
            "integer",
            [],
            set_in="rp",
            description="Number of active boundaries for the current stress period.",
        ),
        "ncolbnd": _mem_var(
            "integer", [], set_in="ar", readonly=True, description="Number of columns in BOUND."
        ),
        "nodelist": _mem_var(
            "integer",
            ["nbound"],
            set_in="rp",
            source="cellid",
            description="Reduced node number for each active boundary, derived from CELLID.",
        ),
        "bound": _mem_var(
            "double",
            ["ncolbnd", "nbound"],
            set_in="rp",
            description=f"Boundary data for the current stress period. {col_desc}".strip(),
        ),
        "hcof": _mem_var(
            "double",
            ["nbound"],
            set_in="fc",
            readonly=True,
            description="Diagonal coefficient contribution to the system matrix.",
        ),
        "rhs": _mem_var(
            "double",
            ["nbound"],
            set_in="fc",
            readonly=True,
            description="Right-hand-side contribution to the system matrix.",
        ),
        "simvals": _mem_var(
            "double",
            ["nbound"],
            set_in="cq",
            readonly=True,
            description="Simulated boundary flow values for the current time step.",
            **({"budget": budget, "obs_type": obs_type, "output": True} if budget else {}),
        ),
        "simtomvr": _mem_var(
            "double",
            ["nbound"],
            set_in="cq",
            readonly=True,
            description="Flow diverted to the Water Mover for each boundary.",
            **({"budget": to_mvr_budget, "output": True} if to_mvr_budget else {}),
        ),
        "naux": _mem_var(
            "integer", [], set_in="ar", readonly=True, description="Number of auxiliary variables."
        ),
        "auxname_cst": _mem_var(
            "string",
            ["naux"],
            set_in="ar",
            readonly=True,
            description="Names of auxiliary variables.",
        ),
        "auxvar": _mem_var(
            "double",
            ["naux", "nbound"],
            set_in=["rp", "ad"],
            source="aux",
            description="Auxiliary variable values for each boundary.",
        ),
    }


# ---------------------------------------------------------------------------
# Advanced Package Transport (APT) helpers
# All APT packages (gwt-lkt/sft/mwt/uzt and gwe-lke/sfe/mwe/uze) inherit
# from tsp-apt.f90.  NCV is a runtime scalar assigned from the linked flow
# package during AR and has no DFN input field counterpart; it is injected
# as a runtime dim by Step 6.
# ---------------------------------------------------------------------------


def _apt_common_memory(
    state_var: str,
) -> "dict[str, v2.MemoryScalar | v2.MemoryArray]":
    """Memory variables common to all APT packages.

    ``state_var`` is the dependent-variable label used in descriptions,
    e.g. ``'concentration'`` for GWT packages or ``'temperature'`` for GWE.
    """
    cap = state_var.capitalize()
    return {
        "ncv": _mem_var(
            "integer",
            [],
            set_in="ar",
            readonly=True,
            description=(
                "Number of control volumes. Assigned from the linked flow package during AR."
            ),
        ),
        "strt": _mem_var(
            "double",
            ["ncv"],
            set_in="ar",
            source="strt",
            description=f"Starting {state_var} for each control volume.",
        ),
        "xnewpak": _mem_var(
            "double",
            ["ncv"],
            set_in="ca",
            description=(
                f"Current {state_var} for each control volume. "
                "Initialized from STRT during AR; updated by the solver at each "
                "Picard iteration (CA). "
                "API-written values serve as initial guesses and are overwritten by the solver."
            ),
        ),
        "xoldpak": _mem_var(
            "double",
            ["ncv"],
            set_in="ad",
            readonly=True,
            description=(
                f"{cap} from the end of the previous time step. "
                "Copied from XNEWPAK at the start of advance (AD)."
            ),
        ),
        "ibound": _mem_var(
            "integer",
            ["ncv"],
            set_in="ar",
            description="Boundary activity flag for each control volume.",
        ),
        "concfeat": _mem_var(
            "double",
            ["ncv"],
            set_in="cq",
            readonly=True,
            description=(
                f"Computed {state_var} for each feature. Set from XNEWPAK after solver convergence."
            ),
        ),
        "qsto": _mem_var(
            "double",
            ["ncv"],
            set_in="cq",
            readonly=True,
            description=f"Storage {state_var} flow contribution for each control volume.",
        ),
    }


# ---------------------------------------------------------------------------
# Exchange package connection memory variables
# Model-pair exchanges built on DisConnExchange (GWF-GWF, GWT-GWT, GWE-GWE)
# allocate NODEM1/NODEM2/IHC/CL1/CL2/HWVA from the EXCHANGEDATA recarray
# (cellidm1/cellidm2/ihc/cl1/cl2/hwva DFN fields), plus NAUX/AUXNAME_CST/
# AUXVAR for auxiliary columns. Confirmed from DisConnExchange.f90
# (allocate_scalars/allocate_arrays). These are the fields silently
# truncated by modflowapi's tuple-presence heuristic (they were previously
# uncataloged here entirely, so modflowapi had no declared shape to fall
# back on).
#
# The SWF-family exchanges (CHF-GWF, OLF-GWF) extend SwfGwfExchangeType
# rather than DisConnExchangeType; they still register connection nodes as
# NODEM1/NODEM2 (the Fortran fields are named nodeswf/nodegwf, but
# mem_allocate registers them under NODEM1/NODEM2 for API consistency with
# the DisConnExchange family) but replace IHC/CL1/CL2/HWVA with
# BEDLEAK/CFACT and do not support auxiliary variables (confirmed from
# exg-swfgwf.f90; the AUXVAR-handling code there is commented out).
# ---------------------------------------------------------------------------


def _disconn_exg_memory() -> "dict[str, v2.MemoryScalar | v2.MemoryArray]":
    """Connection memory for DisConnExchange-derived exchanges: gwfgwf/gwtgwt/gwegwe."""
    return {
        "nodem1": _mem_var(
            "integer",
            ["nexg"],
            set_in="ar",
            source="cellidm1",
            description="Reduced node number in model 1 for each exchange, derived from CELLIDM1.",
        ),
        "nodem2": _mem_var(
            "integer",
            ["nexg"],
            set_in="ar",
            source="cellidm2",
            description="Reduced node number in model 2 for each exchange, derived from CELLIDM2.",
        ),
        "ihc": _mem_var(
            "integer",
            ["nexg"],
            set_in="ar",
            source="ihc",
            description=(
                "Connection type flag for each exchange: 0 vertical, 1 horizontal, "
                "2 horizontal for a vertically staggered grid."
            ),
        ),
        "cl1": _mem_var(
            "double",
            ["nexg"],
            set_in="ar",
            source="cl1",
            description="Distance between the center of the model 1 cell and its shared face.",
        ),
        "cl2": _mem_var(
            "double",
            ["nexg"],
            set_in="ar",
            source="cl2",
            description="Distance between the center of the model 2 cell and its shared face.",
        ),
        "hwva": _mem_var(
            "double",
            ["nexg"],
            set_in="ar",
            source="hwva",
            description=(
                "Horizontal width of the connection if IHC > 0, or the area "
                "perpendicular to flow of the vertical connection if IHC = 0."
            ),
        ),
        "naux": _mem_var(
            "integer", [], set_in="ar", readonly=True, description="Number of auxiliary variables."
        ),
        "auxname_cst": _mem_var(
            "string",
            ["naux"],
            set_in="ar",
            readonly=True,
            description="Names of auxiliary variables.",
        ),
        "auxvar": _mem_var(
            "double",
            ["naux", "nexg"],
            set_in="ar",
            source="aux",
            description="Auxiliary variable values for each exchange.",
        ),
    }


def _swf_gwf_exg_memory() -> "dict[str, v2.MemoryScalar | v2.MemoryArray]":
    """Connection memory for SwfGwfExchange-derived exchanges: chfgwf/olfgwf."""
    return {
        "nodem1": _mem_var(
            "integer",
            ["nexg"],
            set_in="ar",
            source="cellidm1",
            description=(
                "Reduced node number in the surface water model for each exchange, "
                "derived from CELLIDM1. Registered as NODEM1 in memory though the "
                "Fortran field is named NODESWF."
            ),
        ),
        "nodem2": _mem_var(
            "integer",
            ["nexg"],
            set_in="ar",
            source="cellidm2",
            description=(
                "Reduced node number in the GWF model for each exchange, derived "
                "from CELLIDM2. Registered as NODEM2 in memory though the Fortran "
                "field is named NODEGWF."
            ),
        ),
        "bedleak": _mem_var(
            "double",
            ["nexg"],
            set_in="ar",
            source="bedleak",
            description="Bed leakance for each exchange.",
        ),
        "cfact": _mem_var(
            "double",
            ["nexg"],
            set_in="ar",
            source="cfact",
            description="Factor used in the conductance calculation for each exchange.",
        ),
    }


# ---------------------------------------------------------------------------
# Transport Mover (MVT/MVE) memory variables
# gwt-mvt and gwe-mve are both generic instantiations of the single
# TspMvtType (tsp-mvt.f90) — their v1 DFNs are identical apart from a
# longname string. print_input/print_flows/save_flows are parsed by hand
# in read_options() (not routed through the IDM found-struct, so the v1 DFN
# carries no mf6internal annotation) but still land in the inherited
# NumericalPackageType scalars IPRPAK/IPRFLOW/IPAKCB. MAXPACKAGES is
# computed internally (count of packages with an active mover) and has no
# DFN field counterpart. IBUDGETOUT/IBUDCSV (output file unit numbers) and
# PAKNAMES (bookkeeping array of provider/receiver package names) are
# omitted, consistent with no other package in this catalog exposing raw
# file units.
# ---------------------------------------------------------------------------


def _mvt_memory() -> "dict[str, v2.MemoryScalar | v2.MemoryArray]":
    return {
        "iprpak": _mem_var(
            "integer",
            [],
            set_in="ar",
            source="print_input",
            description="Flag controlling whether mover input is echoed to the listing file.",
        ),
        "iprflow": _mem_var(
            "integer",
            [],
            set_in="ar",
            source="print_flows",
            description=(
                "Flag controlling whether mover flow rates are printed to the listing file."
            ),
        ),
        "ipakcb": _mem_var(
            "integer",
            [],
            set_in="ar",
            source="save_flows",
            description="Flag controlling whether mover flows are written to the budget file.",
        ),
        "maxpackages": _mem_var(
            "integer",
            [],
            set_in="ar",
            readonly=True,
            description=(
                "Number of packages participating in the mover. "
                "Computed from the packages that supply or receive moved water."
            ),
        ),
    }


def _dis_node_maps() -> "dict[str, v2.MemoryScalar | v2.MemoryArray]":
    """NODEUSER/NODEREDUCED, common to every discretization package."""
    return {
        "nodeuser": _mem_var(
            "integer",
            ["nodes"],
            set_in="ar",
            readonly=True,
            description=(
                "Maps each packed (active-cell) node position to its full-grid "
                "user node number. Index map for the runtime 'nodes' dimension."
            ),
        ),
        "nodereduced": _mem_var(
            "integer",
            ["nodesuser"],
            set_in="ar",
            readonly=True,
            description=(
                "Maps each full-grid user node number to its packed (active-cell) "
                "node position, or a nonpositive sentinel if the cell is inactive."
            ),
        ),
    }


# ---------------------------------------------------------------------------
# Package-specific extra memory variables
# For derived or renamed variables not covered by mf6internal or same-name
# griddata convention. Merged last so they intentionally override.
# ---------------------------------------------------------------------------

_EXTRA_MEMORY: dict[str, dict[str, "v2.MemoryScalar | v2.MemoryArray"]] = {
    # Exchange connection data (see banner above).
    "gwfgwf": _disconn_exg_memory(),
    "gwtgwt": _disconn_exg_memory(),
    "gwegwe": _disconn_exg_memory(),
    "chfgwf": _swf_gwf_exg_memory(),
    "olfgwf": _swf_gwf_exg_memory(),
    # Transport mover (see banner above).
    "mvt": _mvt_memory(),
    "mve": _mvt_memory(),
    # NPF: k is loaded as K11; condsat and sat are derived/computed.
    "npf": {
        "k11": _mem_var(
            "double",
            ["nodes"],
            set_in=["ar", "ad"],
            source="k",
            description=(
                "Hydraulic conductivity along the major (K11) axis. "
                "Loaded from the K griddata field. "
                "Used directly when XT3D is active; otherwise feeds into CONDSAT. "
                "Recomputed each time step when TVK is active."
            ),
        ),
        "condsat": _mem_var(
            "double",
            ["njas"],
            set_in=["ar", "ad"],
            source=["k11", "k22", "k33"],
            description=(
                "Saturated intercell conductance. "
                "Computed once during AR from hydraulic conductivity and cell geometry. "
                "Recomputed each time step when TVK or VSC is active. "
                "Inoperative under XT3D."
            ),
        ),
        "sat": _mem_var(
            "double",
            ["nodes"],
            set_in="fc",
            readonly=True,
            description="Cell saturation (0-1). Recomputed each solver iteration.",
        ),
    },
    # DIS/DISV/DISU: area is computed from grid geometry, not a DFN field.
    #
    # NODEUSER/NODEREDUCED (see _dis_node_maps): confirmed from mem_allocate
    # calls in Dis.f90, Dis2d.f90, Disv.f90, Disv1d.f90, Disv2d.f90, and
    # Disu.f90 — every discretization package allocates both, uniformly.
    "dis": {
        "area": _mem_var(
            "double",
            ["ncpl"],
            set_in="ar",
            readonly=True,
            description="Horizontal cell area, computed from grid geometry.",
        ),
        **_dis_node_maps(),
    },
    "disv": {
        "area": _mem_var(
            "double",
            ["ncpl"],
            set_in="ar",
            readonly=True,
            description="Horizontal cell area, computed from grid geometry.",
        ),
        **_dis_node_maps(),
    },
    "disu": {
        "area": _mem_var(
            "double",
            ["nodesuser"],
            set_in="ar",
            readonly=True,
            description="Horizontal cell area, computed from grid geometry.",
        ),
        **_dis_node_maps(),
    },
    "dis2d": _dis_node_maps(),
    "disv1d": _dis_node_maps(),
    "disv2d": _dis_node_maps(),
    # SFR: packagedata field names differ from Fortran memory variable names.
    "sfr": {
        "length": _mem_var(
            "double", ["maxbound"], set_in="ar", source="rlen", description="Reach length (L)."
        ),
        "width": _mem_var(
            "double", ["maxbound"], set_in="ar", source="rwid", description="Reach width (L)."
        ),
        "slope": _mem_var(
            "double",
            ["maxbound"],
            set_in="ar",
            source="rgrd",
            description="Reach gradient (dimensionless).",
        ),
        "strtop": _mem_var(
            "double",
            ["maxbound"],
            set_in="ar",
            source="rtp",
            description="Top elevation of the reach streambed (L).",
        ),
        "bthick": _mem_var(
            "double",
            ["maxbound"],
            set_in="ar",
            source="rbth",
            description="Thickness of the reach streambed (L).",
        ),
        "hk": _mem_var(
            "double",
            ["maxbound"],
            set_in="ar",
            source="rhk",
            description="Hydraulic conductivity of the reach streambed (L/T).",
        ),
        "rough": _mem_var(
            "double",
            ["maxbound"],
            set_in="ar",
            source="man",
            description="Manning's roughness coefficient.",
        ),
        "nconnreach": _mem_var(
            "integer",
            ["maxbound"],
            set_in="ar",
            readonly=True,
            source="ncon",
            description="Number of connections for each reach.",
        ),
        "ustrf": _mem_var(
            "double",
            ["maxbound"],
            set_in="ar",
            source="ustrf",
            description="Upstream fraction of flow for each reach.",
        ),
        "ndiv": _mem_var(
            "integer",
            ["maxbound"],
            set_in="ar",
            readonly=True,
            source="ndv",
            description="Number of diversions for each reach.",
        ),
    },
    # ---------------------------------------------------------------------------
    # GWT Advanced Package Transport (APT)
    # Confirmed from Fortran mem_allocate calls in gwt-lkt.f90, gwt-sft.f90,
    # gwt-mwt.f90, gwt-uzt.f90 and their shared base class tsp-apt.f90.
    # Period arrays (CONC*) have no direct DFN field counterpart because the
    # period data uses a union of keyword-tagged settings; source is omitted.
    # ---------------------------------------------------------------------------
    "lkt": {
        **_apt_common_memory("concentration"),
        "concrain": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="Rainfall concentration for each lake.",
        ),
        "concevap": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="Evaporation concentration for each lake.",
        ),
        "concroff": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="Runoff concentration for each lake.",
        ),
        "conciflw": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="External inflow concentration for each lake.",
        ),
    },
    "sft": {
        **_apt_common_memory("concentration"),
        "concrain": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="Rainfall concentration for each reach.",
        ),
        "concevap": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="Evaporation concentration for each reach.",
        ),
        "concroff": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="Runoff concentration for each reach.",
        ),
        "conciflw": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="Inflow concentration for each reach.",
        ),
        "vnew": _mem_var(
            "double",
            ["ncv"],
            set_in="cq",
            readonly=True,
            description="Reach water volume at the end of the current time step.",
        ),
        "vold": _mem_var(
            "double",
            ["ncv"],
            set_in="ad",
            readonly=True,
            description="Reach water volume at the start of the current time step.",
        ),
    },
    "mwt": {
        **_apt_common_memory("concentration"),
        "concrate": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="Pumping-rate concentration for each multi-aquifer well.",
        ),
    },
    "uzt": {
        **_apt_common_memory("concentration"),
        "concinfl": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="Infiltration concentration for each UZF cell.",
        ),
        "concuzet": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="ET concentration for each UZF cell.",
        ),
    },
    # ---------------------------------------------------------------------------
    # GWE Advanced Package Transport (APT)
    # Confirmed from Fortran mem_allocate calls in gwe-lke.f90, gwe-sfe.f90,
    # gwe-mwe.f90, gwe-uze.f90 and their shared base class tsp-apt.f90.
    # KTF and RFEATTHK are loaded from packagedata fields during AR.
    # For gwe-mwe the thickness field is named FTHK (vs RBTHCND elsewhere).
    # Note: the feature-state variable in memory is named CONCFEAT in all APT
    # packages (including GWE), because the name is set by the tsp-apt base class.
    # ---------------------------------------------------------------------------
    "lke": {
        **_apt_common_memory("temperature"),
        "temprain": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="Rainfall temperature for each lake.",
        ),
        "tempevap": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="Evaporation temperature for each lake.",
        ),
        "temproff": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="Runoff temperature for each lake.",
        ),
        "tempiflw": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="External inflow temperature for each lake.",
        ),
        "ktf": _mem_var(
            "double",
            ["ncv"],
            set_in="ar",
            source="ktf",
            description="Thermal conductivity of the lakebed (E/T/L/Deg).",
        ),
        "rfeatthk": _mem_var(
            "double",
            ["ncv"],
            set_in="ar",
            source="rbthcnd",
            description="Thickness of the lakebed conduction layer (L).",
        ),
    },
    "sfe": {
        **_apt_common_memory("temperature"),
        "temprain": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="Rainfall temperature for each reach.",
        ),
        "tempevap": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="Evaporation temperature for each reach.",
        ),
        "temproff": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="Runoff temperature for each reach.",
        ),
        "tempiflw": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="Inflow temperature for each reach.",
        ),
        "vnew": _mem_var(
            "double",
            ["ncv"],
            set_in="cq",
            readonly=True,
            description="Reach water volume at the end of the current time step.",
        ),
        "vold": _mem_var(
            "double",
            ["ncv"],
            set_in="ad",
            readonly=True,
            description="Reach water volume at the start of the current time step.",
        ),
        "ktf": _mem_var(
            "double",
            ["ncv"],
            set_in="ar",
            source="ktf",
            description="Thermal conductivity of the streambed (E/T/L/Deg).",
        ),
        "rfeatthk": _mem_var(
            "double",
            ["ncv"],
            set_in="ar",
            source="rbthcnd",
            description="Thickness of the streambed conduction layer (L).",
        ),
    },
    "mwe": {
        **_apt_common_memory("temperature"),
        "temprate": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="Pumping-rate temperature for each multi-aquifer well.",
        ),
        "ktf": _mem_var(
            "double",
            ["ncv"],
            set_in="ar",
            source="ktf",
            description="Thermal conductivity of the well casing (E/T/L/Deg).",
        ),
        "rfeatthk": _mem_var(
            "double",
            ["ncv"],
            set_in="ar",
            source="fthk",
            description="Thickness of the well casing conduction layer (L).",
        ),
    },
    "uze": {
        **_apt_common_memory("temperature"),
        "tempinfl": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="Infiltration temperature for each UZF cell.",
        ),
        "tempuzet": _mem_var(
            "double",
            ["ncv"],
            set_in="rp",
            description="ET temperature for each UZF cell.",
        ),
    },
    # ---------------------------------------------------------------------------
    # IMS solver (sln-ims)
    # Solution-level scalars live at <sln_name>; linear settings (iter1, rclose,
    # relax, droptol, north, iscl, iord, ipc) live at <sln_name>/IMSLINEAR.
    # ---------------------------------------------------------------------------
    "ims": {
        "mxiter": _mem_var(
            "integer",
            [],
            set_in="ar",
            source="outer_maximum",
            description="Maximum outer (nonlinear) iterations.",
        ),
        "dvclose": _mem_var(
            "double",
            [],
            set_in="ar",
            source="outer_dvclose",
            description="Outer dependent-variable change closure criterion.",
        ),
        "theta": _mem_var(
            "double",
            [],
            set_in="ar",
            source="under_relaxation_theta",
            description="Under-relaxation reduction factor (delta-bar-delta).",
        ),
        "akappa": _mem_var(
            "double",
            [],
            set_in="ar",
            source="under_relaxation_kappa",
            description="Under-relaxation increment for the learning rate (delta-bar-delta).",
        ),
        "gamma": _mem_var(
            "double",
            [],
            set_in="ar",
            source="under_relaxation_gamma",
            description="Under-relaxation memory factor (Cooley or delta-bar-delta).",
        ),
        "amomentum": _mem_var(
            "double",
            [],
            set_in="ar",
            source="under_relaxation_momentum",
            description="Momentum coefficient for the under-relaxation step (delta-bar-delta).",
        ),
        "numtrack": _mem_var(
            "integer",
            [],
            set_in="ar",
            source="backtracking_number",
            description="Maximum backtracking iterations; 0 disables backtracking.",
        ),
        "btol": _mem_var(
            "double",
            [],
            set_in="ar",
            source="backtracking_tolerance",
            description="Residual increase tolerance that triggers backtracking.",
        ),
        "breduc": _mem_var(
            "double",
            [],
            set_in="ar",
            source="backtracking_reduction_factor",
            description="Step-size reduction factor used during backtracking.",
        ),
        "res_lim": _mem_var(
            "double",
            [],
            set_in="ar",
            source="backtracking_residual_limit",
            description="Residual limit below which backtracking is not performed.",
        ),
        "icnvg": _mem_var(
            "integer",
            [],
            set_in="ar",
            readonly=True,
            description=(
                "Convergence flag. 1 if the solution converged in the last solve; "
                "0 otherwise. Updated after each call to the solver."
            ),
        ),
        "ttsoln": _mem_var(
            "double",
            [],
            set_in="ar",
            readonly=True,
            description="Cumulative CPU time (seconds) spent in the linear solver.",
        ),
        # Linear settings.
        # Currently live at <sln_name>/IMSLINEAR in the memory manager due to
        # ImsLinearSettings allocating its own sub-context. Pending MF6 fix to
        # flatten these to <sln_name>/<varname> (see variable-specification-design.md).
        "iter1": _mem_var(
            "integer",
            [],
            set_in="ar",
            source="inner_maximum",
            description="Maximum inner (linear) iterations.",
        ),
        "rclose": _mem_var(
            "double",
            [],
            set_in="ar",
            source="inner_rclose",
            description="Flow residual closure criterion for the linear solver.",
        ),
        "relax": _mem_var(
            "double",
            [],
            set_in="ar",
            source="relaxation_factor",
            description="ILU(T) relaxation factor.",
        ),
        "droptol": _mem_var(
            "double",
            [],
            set_in="ar",
            source="preconditioner_drop_tolerance",
            description="ILUT drop tolerance.",
        ),
        "north": _mem_var(
            "integer",
            [],
            set_in="ar",
            source="number_orthogonalizations",
            description="Interval for explicit residual recalculation.",
        ),
        "iscl": _mem_var(
            "integer",
            [],
            set_in="ar",
            source="scaling_method",
            description="Matrix scaling option (integer code derived from SCALING_METHOD).",
        ),
        "iord": _mem_var(
            "integer",
            [],
            set_in="ar",
            source="reordering_method",
            description="Matrix reordering option (integer code derived from REORDERING_METHOD).",
        ),
        "ipc": _mem_var(
            "integer",
            [],
            set_in="ar",
            description=(
                "Preconditioner type code, computed from LINEAR_ACCELERATION, "
                "PRECONDITIONER_LEVELS, and PRECONDITIONER_DROP_TOLERANCE."
            ),
        ),
    },
    # ---------------------------------------------------------------------------
    # EMS solver (sln-ems) — Explicit Matrix Solver used by PRT.
    # ---------------------------------------------------------------------------
    "ems": {
        "icnvg": _mem_var(
            "integer",
            [],
            set_in="ar",
            readonly=True,
            description=(
                "Convergence flag. 1 if the solution converged; 0 otherwise. "
                "Updated after each call to the solver."
            ),
        ),
        "ttsoln": _mem_var(
            "double",
            [],
            set_in="ar",
            readonly=True,
            description="Cumulative CPU time (seconds) spent in the solver.",
        ),
    },
}


# ---------------------------------------------------------------------------
# Model-level solution state variables
# ---------------------------------------------------------------------------

# Dependent-variable description and obs_type per numerical model component.
_MODEL_X: dict[str, tuple[str, str]] = {
    "gwf-nam": (
        "HEAD",
        (
            "Hydraulic head for each model cell. "
            "Checked in from the solution-level dependent-variable vector. "
            "Initialized by the IC package during AR; updated by the nonlinear "
            "solver at each Picard iteration (CA). "
            "API-written values serve as initial guesses and are overwritten by the solver."
        ),
    ),
    "gwt-nam": (
        "CONCENTRATION",
        (
            "Solute concentration for each model cell. "
            "Checked in from the solution-level dependent-variable vector. "
            "Initialized by the IC package during AR; updated by the nonlinear "
            "solver at each Picard iteration (CA). "
            "API-written values serve as initial guesses and are overwritten by the solver."
        ),
    ),
    "gwe-nam": (
        "TEMPERATURE",
        (
            "Temperature for each model cell. "
            "Checked in from the solution-level dependent-variable vector. "
            "Initialized by the IC package during AR; updated by the nonlinear "
            "solver at each Picard iteration (CA). "
            "API-written values serve as initial guesses and are overwritten by the solver."
        ),
    ),
    "chf-nam": (
        "STAGE",
        (
            "Stage for each model cell. "
            "Checked in from the solution-level dependent-variable vector "
            "(or directly allocated when the DFW package is absent). "
            "Initialized by the IC package during AR; updated by the nonlinear "
            "solver at each Picard iteration (CA). "
            "API-written values serve as initial guesses and are overwritten by the solver."
        ),
    ),
    "olf-nam": (
        "STAGE",
        (
            "Stage for each model cell. "
            "Checked in from the solution-level dependent-variable vector "
            "(or directly allocated when the DFW package is absent). "
            "Initialized by the IC package during AR; updated by the nonlinear "
            "solver at each Picard iteration (CA). "
            "API-written values serve as initial guesses and are overwritten by the solver."
        ),
    ),
    "swf-nam": (
        "STAGE",
        (
            "Stage for each model cell. "
            "Checked in from the solution-level dependent-variable vector "
            "(or directly allocated when the DFW package is absent). "
            "Initialized by the IC package during AR; updated by the nonlinear "
            "solver at each Picard iteration (CA). "
            "API-written values serve as initial guesses and are overwritten by the solver."
        ),
    ),
}

_FLOWJA_MEMORY = _mem_var(
    "double",
    ["nja"],
    set_in="cq",
    readonly=True,
    budget="FLOW-JA-FACE",
    description=(
        "Intercell flows in compressed sparse row (CSR) order, calculated "
        "after solution convergence. Diagonal entries hold the flow residual."
    ),
)

_IBOUND_MEMORY = _mem_var(
    "integer",
    ["nodes"],
    set_in="ar",
    description=(
        "Cell activity flag: positive values indicate active cells, "
        "zero indicates inactive (no-flow) cells. "
        "Set during model initialisation; may change when Newton-Raphson "
        "wet-dry logic activates or deactivates cells."
    ),
)


def _numerical_model_memory(
    obs_type: str, x_description: str
) -> dict[str, "v2.MemoryScalar | v2.MemoryArray"]:
    """Return solution-state memory variables common to all numerical models."""
    return {
        "x": _mem_var(
            "double", ["nodes"], set_in="ca", obs_type=obs_type, description=x_description
        ),
        "xold": _mem_var(
            "double",
            ["nodes"],
            set_in="ad",
            readonly=True,
            description=(
                "Dependent variable from the end of the previous time step. "
                "Copied from X at advance (AD); used to restore X if the adaptive "
                "time stepping scheme retries a failed time step."
            ),
        ),
        "flowja": _FLOWJA_MEMORY,
        "rhs": _mem_var(
            "double",
            ["nodes"],
            set_in="fc",
            readonly=True,
            description=(
                "Right-hand-side contribution for this model, sliced from the "
                "solution-level RHS vector. Rebuilt each solver iteration."
            ),
        ),
        "ibound": _IBOUND_MEMORY,
        "neq": _mem_var(
            "integer",
            [],
            set_in="ar",
            readonly=True,
            description=(
                "Number of equations (unknowns) for this model. "
                "Equal to the number of active cells (NODES) for standard models."
            ),
        ),
        "idxglo": _mem_var(
            "integer",
            ["nja"],
            set_in="mc",
            readonly=True,
            description=(
                "Maps each local CSR position to the corresponding row/column "
                "index in the global solution matrix. Populated during matrix "
                "connectivity (MC) and constant thereafter."
            ),
        ),
    }


# Per-component (full name) extra memory, merged after _EXTRA_MEMORY.
_MODEL_MEMORY: dict[str, dict[str, "v2.MemoryScalar | v2.MemoryArray"]] = {
    name: _numerical_model_memory(obs_type, desc) for name, (obs_type, desc) in _MODEL_X.items()
}
_MODEL_MEMORY["prt-nam"] = {
    "flowja": _FLOWJA_MEMORY,
    "ibound": _IBOUND_MEMORY,
}


# ---------------------------------------------------------------------------
# Main migration entry point
# ---------------------------------------------------------------------------


def to_v2_0_0_dev3(name: str, fields: OMD, meta: list[str]) -> v2.Component:
    """Map a component definition from the raw v1 schema to 2.0.0.dev3."""

    # Step 1: run the dev2 migration to get blocks, dims, parent, subtype, etc.
    component = to_v2_0_0_dev2(name, fields, meta)

    memory: dict[str, v2.MemoryScalar | v2.MemoryArray] = {}

    # Step 2: memory variables from mf6internal annotations.
    # These map DFN input field names to IDM/simulation variable names.
    # Record/recarray/keystring types are skipped (intermediate structures).
    # Option keywords become readonly logical variables.
    for field in fields.values(multi=True):
        internal = field.get("mf6internal")
        if not internal:
            continue

        raw_type = (field.get("type") or "").strip()
        base_type = raw_type.split()[0].lower()
        if base_type in ("record", "recarray", "keystring"):
            continue

        dtype = _DTYPE_MAP.get(base_type) or _DTYPE_MAP.get(raw_type.lower())
        if dtype is None:
            continue

        # Keyword options with i-prefix mf6internal names are declared as
        # integer(I4B) in the runtime package source (not as Fortran LOGICAL),
        # so they are accessible via the integer memory API path. The small
        # exceptions set covers i-prefix names that only exist in IDM found
        # structs (logical(LGP)) and are not redeclared as integers.
        if base_type == "keyword" and internal.startswith("i"):
            if internal not in _LOGICAL_KEYWORD_EXCEPTIONS:
                dtype = "integer"

        block = field.get("block") or "options"
        time_series = try_parse_bool(field.get("time_series"), False)
        shape = _parse_shape(field.get("shape") or "")
        set_in = _infer_hook(block, time_series)

        memory[internal] = _mem_var(dtype, shape, set_in=set_in, source=field["name"])

    # Step 3: same-name memory variables from griddata/packagedata fields.
    # The MF6 convention is that griddata and most packagedata array field names
    # match their Fortran memory variable names directly. Fields already covered
    # by mf6internal (step 2) are skipped to avoid duplicates. Keyword and
    # composite types are skipped.
    pkg_short = name.rsplit("-", 1)[-1]

    for field in fields.values(multi=True):
        if field.get("mf6internal"):
            continue
        if field.get("in_record"):
            continue

        block = field.get("block") or ""
        if block not in _GRIDDATA_LIKE:
            continue
        if block == "packagedata" and pkg_short in _SKIP_PACKAGEDATA_SAME_NAME:
            continue
        fname = field["name"]
        if fname in _SKIP_SAME_NAME_GRIDDATA.get(pkg_short, frozenset()):
            continue

        raw_type = (field.get("type") or "").strip()
        base_type = raw_type.split()[0].lower()
        if base_type in _SKIP_FIELD_TYPES:
            continue

        dtype = _DTYPE_MAP.get(base_type) or _DTYPE_MAP.get(raw_type.lower())
        if dtype is None:
            continue

        shape = _parse_shape(field.get("shape") or "")

        memory[fname] = _mem_var(dtype, shape, set_in="ar", source=fname)

    # Step 4: standard BoundaryPackage memory variables for stress packages.
    # The template is authoritative for these standard variables (correct shapes
    # and readonly flags), so it unconditionally overwrites any mf6internal-
    # derived entries for the same names. HFB and MVR are excluded because they
    # do not subclass BoundaryPackage and their runtime memory differs
    # fundamentally from the standard template.
    if (
        isinstance(component, v2.Package)
        and component.subtype == "stress"
        and pkg_short not in _SKIP_STRESS_TEMPLATE
    ):
        cols = _bound_cols(component)
        out = _STRESS_OUTPUT.get(pkg_short)
        pkg_budget, pkg_obs_type, pkg_to_mvr = out if out else (None, None, None)
        for vname, mv in _stress_pkg_memory(
            cols,
            budget=pkg_budget,
            obs_type=pkg_obs_type,
            to_mvr_budget=pkg_to_mvr,
        ).items():
            memory[vname] = mv

    # Step 5: package-specific extras (derived / renamed variables).
    # These are merged last and override any earlier entry intentionally.
    for vname, mv in _EXTRA_MEMORY.get(pkg_short, {}).items():
        memory[vname] = mv

    # Step 5b: model-level solution state variables (keyed by full component name).
    # Merged after _EXTRA_MEMORY so per-model entries take final precedence.
    for vname, mv in _MODEL_MEMORY.get(name, {}).items():
        memory[vname] = mv

    # Step 5c: clear stale string source references.
    # Some v1 field names are renamed by dev2 transforms (e.g. _collapse_sto_keywords
    # replaces "steady-state"/"transient" with "storage"). The stress template also
    # sets nodelist.source = "cellid" for all stress packages, including gridded
    # variants that have no cellid field. Clear any source that no longer resolves.
    v2_field_names = set(component.get_fields(recurse=True).keys())
    for var_name, mv in list(memory.items()):
        if isinstance(mv.source, str) and mv.source not in v2_field_names:
            memory[var_name] = mv.model_copy(update={"source": None})

    # Step 6: inject dims for any shape elements used by memory variables that
    # are not already declared in the component's dims/runtime_dims sections.
    # Shape elements that resolve to an existing dim (input or runtime) are
    # left alone; everything else is injected as a RuntimeDim. Special cases:
    #   naux        → derived from len(auxiliary) when that field exists (InputDim)
    #   njas (disu) → expressible as (nja - nodes) / 2, both DFN fields (InputDim)
    #   nbound      → set_in "rp" (reset each stress period from period input)
    #   all others  → set_in "ar" (established at grid allocation, then constant)
    existing_input_dims = dict(component.dims or {})
    existing_runtime_dims = dict(component.runtime_dims or {})
    if pkg_short == "disu" and "nja" in existing_input_dims and "nodes" in existing_input_dims:
        existing_input_dims.setdefault("njas", v2.InputDim(value="(nja - nodes) / 2"))
    if memory:
        all_field_names = set(component.get_fields(recurse=True).keys())
        mem_shape_dims = {elem for mv in memory.values() for elem in getattr(mv, "shape", [])}
        # "nodes" deliberately names both an InputDim (the full, pre-reduction grid
        # count that sizes input arrays) and a RuntimeDim (the post-IDOMAIN-reduction
        # active-cell count that sizes memory variables like NODEUSER) on the
        # discretization packages themselves — see _build_explicit_dims. A memory
        # variable's own "nodes" shape reference always means the RuntimeDim sense,
        # so it must not be treated as already satisfied by the same-named InputDim.
        known = (set(existing_input_dims) - {"nodes"}) | set(existing_runtime_dims)
        for dim_name in sorted(mem_shape_dims - known):
            if dim_name == "naux" and "auxiliary" in all_field_names:
                existing_input_dims[dim_name] = v2.InputDim(value="len(auxiliary)")
            elif dim_name == "nbound":
                existing_runtime_dims[dim_name] = v2.RuntimeDim(set_in="rp")
            else:
                existing_runtime_dims[dim_name] = v2.RuntimeDim(set_in="ar")

    # Step 7: drop the vestigial `maxbound` DIMENSIONS input on READARRAYGRID
    # ("G-variant") stress packages (gwf-chdg/drng/ghbg/rivg/welg and any future
    # sibling built the same way). Confirmed directly in the MF6 Fortran source
    # (src/Model/ModelUtilities/BoundaryPackageExt.f90, BndExtType%source_dimensions):
    #
    #   if (this%readasarrays) then
    #     this%maxbound = this%dis%get_ncpl()
    #   else
    #     call mem_set_value(this%maxbound, 'MAXBOUND', this%input_mempath, ...)
    #     ...
    #   end if
    #
    # When READARRAYGRID is set, the whole branch that reads a user-supplied
    # MAXBOUND from the input file is skipped unconditionally -- MAXBOUND is
    # always overwritten with NCPL instead. A MAXBOUND entry in a real .chdg
    # (etc.) file's DIMENSIONS block is accepted by the parser but silently
    # has zero effect: not read, not logged, not validated. This is distinct
    # from the ordinary (list-input) variant, where MAXBOUND is a real,
    # required sizing dimension (`shape (maxbound)` on stress_period_data) --
    # only the READARRAYGRID variant's copy of this field is dead input.
    #
    # `memory.maxbound` (from the Step 4 stress-package template, above) is
    # left untouched -- it still correctly documents the real runtime value
    # (readonly, set_in="ar"), just no longer as something a caller provides.
    blocks = component.blocks
    _options_fields = blocks["options"].fields if blocks and "options" in blocks else {}
    _dims_fields = blocks["dimensions"].fields if blocks and "dimensions" in blocks else {}
    if (
        isinstance(component, v2.Package)
        and component.subtype == "stress"
        and blocks
        and "readarraygrid" in _options_fields
        and "maxbound" in _dims_fields
    ):
        dims_block = blocks["dimensions"]
        new_dims_fields = {k: v for k, v in dims_block.fields.items() if k != "maxbound"}
        blocks = {
            **blocks,
            "dimensions": dims_block.model_copy(update={"fields": new_dims_fields}),
        }
        existing_input_dims.pop("maxbound", None)

    return component.model_copy(
        update={
            "schema_version": "2.0.0.dev3",
            "memory": memory or None,
            "dims": existing_input_dims or None,
            "runtime_dims": existing_runtime_dims or None,
            "blocks": blocks,
        }
    )
