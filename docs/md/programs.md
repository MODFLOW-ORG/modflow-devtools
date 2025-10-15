# MODFLOW and related programs

The `modflow_devtools.programs` module provides a database of programs in the MODFLOW ecosystem. This has previously been housed in [`pymake`](https://github.com/modflowpy/pymake).

The database is accessible as a dictionary of programs:

```python
from modflow_devtools.programs import get_programs, get_program

programs = get_programs()
mf6 = programs["mf6"]
mf6 = get_program("mf6") # equivalent
```
