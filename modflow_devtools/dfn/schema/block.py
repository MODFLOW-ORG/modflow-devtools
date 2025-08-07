from collections.abc import Mapping

from modflow_devtools.dfn.schema.field import Fields

Block = Fields
Blocks = Mapping[str, Block]


def block_sort_key(item) -> int:
    k, _ = item
    if k == "options":
        return 0
    elif k == "dimensions":
        return 1
    elif k == "griddata":
        return 2
    elif k == "packagedata":
        return 3
    elif "period" in k:
        return 4
    else:
        return 5
