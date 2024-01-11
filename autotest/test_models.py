import modflow_devtools.models as examples
from modflow_devtools.markers import requires_github


@requires_github
def test_mf2005_freyberg():
    paths = examples.mf2005_freyberg()
    assert any(paths)
    names = [file.name for file in paths]
    assert "freyberg.nam" in names


@requires_github
def test_mf6_freyberg():
    paths = examples.mf6_freyberg()
    assert any(paths)
    names = [file.name for file in paths]
    assert "mfsim.nam" in names


@requires_github
def test_mfusg_freyberg():
    paths = examples.mfusg_freyberg()
    assert any(paths)
    names = [file.name for file in paths]
    assert "freyberg.usg.nam" in names
