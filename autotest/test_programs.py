import pytest

from modflow_devtools.programs import get_program, get_programs, load_programs


def test_load_programs():
    programs = get_programs()
    assert isinstance(programs, dict)
    assert "mf6" in programs
    mf6 = get_program("mf6")
    assert mf6 == programs["mf6"]
    assert isinstance(mf6.version, str)
    assert isinstance(mf6.current, bool)
    assert isinstance(mf6.url, str)
    assert isinstance(mf6.dirname, str)
    assert isinstance(mf6.srcdir, str)
    assert isinstance(mf6.standard_switch, bool)
    assert isinstance(mf6.double_switch, bool)
    assert isinstance(mf6.shared_object, bool)


def test_strict_unrecognized_keys(function_tmpdir):
    tmp_path = function_tmpdir / "programs.csv"
    with tmp_path.open("w") as f:
        f.write(
            "target,version,current,url,dirname,srcdir,standard_switch,double_switch,shared_object,garbage\n"
        )
        f.write(
            "mf6,6.6.3,True,https://github.com/MODFLOW-ORG/modflow6/releases/download/6.6.3/mf6.6.3_linux.zip,mf6.6.3_linux,src,True,False,False,garbage\n"
        )

    with pytest.raises(ValueError) as e:
        load_programs(tmp_path, strict=True)
        assert "Unrecognized keys in program data: {'unrecognized_key'}" in e.message
