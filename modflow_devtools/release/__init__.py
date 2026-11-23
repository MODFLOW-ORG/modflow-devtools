"""Release tooling for MODFLOW program repositories, used by the composite
actions in ``actions/``. The modules only use the standard library, so the
actions run them with ``python -m`` and ``PYTHONPATH`` pointing at the
action's checkout of this repository, without installing the package."""
