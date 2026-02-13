import sys

import pytest

from modflow_devtools.version import get_version, set_version, update_file

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_dir(tmp_path):
    """A minimal project directory with version.txt, meson.build, pixi.toml."""
    (tmp_path / "version.txt").write_text("1.0.0")
    (tmp_path / "meson.build").write_text(
        "project(\n  'testproj',\n  version: '1.0.0',\n  meson_version: '>= 1.0',\n)\n"
    )
    (tmp_path / "pixi.toml").write_text(
        '[project]\nname = "testproj"\nversion = "1.0.0"\n\n[dependencies]\n'
    )
    return tmp_path


@pytest.fixture
def fortran_file(tmp_path):
    """A file with a Fortran-style version string."""
    path = tmp_path / "src" / "prog.f"
    path.parent.mkdir()
    path.write_text("      PARAMETER (VERSION='1.0.0  01/01/2020')\n")
    return path


# ---------------------------------------------------------------------------
# Unit tests: get_version
# ---------------------------------------------------------------------------


class TestGetVersion:
    def test_reads_version(self, project_dir):
        assert get_version(project_dir) == "1.0.0"

    def test_missing_version_txt(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            get_version(tmp_path)

    def test_strips_whitespace(self, tmp_path):
        (tmp_path / "version.txt").write_text("  2.3.4\n")
        assert get_version(tmp_path) == "2.3.4"


# ---------------------------------------------------------------------------
# Unit tests: _update_version_txt, _update_meson_build, _update_pixi_toml
# (tested indirectly through set_version)
# ---------------------------------------------------------------------------


class TestSetVersion:
    def test_updates_all_three_files(self, project_dir):
        set_version("2.0.0", project_dir)
        assert (project_dir / "version.txt").read_text() == "2.0.0"
        assert "version: '2.0.0'" in (project_dir / "meson.build").read_text()
        assert 'version = "2.0.0"' in (project_dir / "pixi.toml").read_text()

    def test_does_not_modify_meson_version_line(self, project_dir):
        set_version("2.0.0", project_dir)
        meson = (project_dir / "meson.build").read_text()
        assert "meson_version: '>= 1.0'" in meson

    def test_invalid_version_raises(self, project_dir):
        with pytest.raises(ValueError, match="Invalid version"):
            set_version("not-a-version", project_dir)

    def test_missing_version_txt_raises(self, tmp_path):
        # No version.txt in tmp_path
        (tmp_path / "meson.build").write_text("project(\n  version: '1.0.0',\n)\n")
        (tmp_path / "pixi.toml").write_text('[project]\nversion = "1.0.0"\n')
        with pytest.raises(FileNotFoundError):
            set_version("2.0.0", tmp_path)

    def test_missing_meson_build_warns(self, tmp_path, capsys):
        (tmp_path / "version.txt").write_text("1.0.0")
        (tmp_path / "pixi.toml").write_text('[project]\nversion = "1.0.0"\n')
        set_version("2.0.0", tmp_path)
        assert "meson.build" in capsys.readouterr().err

    def test_missing_pixi_toml_warns(self, tmp_path, capsys):
        (tmp_path / "version.txt").write_text("1.0.0")
        (tmp_path / "meson.build").write_text("project(\n  version: '1.0.0',\n)\n")
        set_version("2.0.0", tmp_path)
        assert "pixi.toml" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Unit tests: dry_run
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_no_files_modified(self, project_dir, capsys):
        set_version("9.9.9", project_dir, dry_run=True)
        assert (project_dir / "version.txt").read_text() == "1.0.0"
        assert "version: '1.0.0'" in (project_dir / "meson.build").read_text()
        assert 'version = "1.0.0"' in (project_dir / "pixi.toml").read_text()

    def test_prints_expected_changes(self, project_dir, capsys):
        set_version("9.9.9", project_dir, dry_run=True)
        out = capsys.readouterr().out
        assert "9.9.9" in out
        assert "1.0.0" in out


# ---------------------------------------------------------------------------
# Unit tests: update_file
# ---------------------------------------------------------------------------


class TestUpdateFile:
    def test_fortran_parameter_style(self, fortran_file):
        pattern = r"PARAMETER \(VERSION='([^']+)'\)"
        fmt = "PARAMETER (VERSION='{version}  06/25/2013')"
        update_file(fortran_file, pattern, fmt, "2.0.0")
        assert "PARAMETER (VERSION='2.0.0  06/25/2013')" in fortran_file.read_text()

    def test_provisional_suffix_preserved(self, tmp_path):
        f = tmp_path / "prog.f90"
        f.write_text("      version = '7.2.001 PROVISIONAL'\n")
        pattern = r"version = '([^']+)'"
        fmt = "version = '{version} PROVISIONAL'"
        update_file(f, pattern, fmt, "7.2.002")
        assert "version = '7.2.002 PROVISIONAL'" in f.read_text()

    def test_dry_run_no_modification(self, fortran_file, capsys):
        pattern = r"PARAMETER \(VERSION='([^']+)'\)"
        fmt = "PARAMETER (VERSION='{version}')"
        original = fortran_file.read_text()
        update_file(fortran_file, pattern, fmt, "9.9.9", dry_run=True)
        assert fortran_file.read_text() == original

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            update_file(
                tmp_path / "nonexistent.f", r"VERSION='([^']+)'", "VERSION='{version}'", "1.0.0"
            )

    def test_no_capture_group_raises(self, fortran_file):
        with pytest.raises(ValueError, match="exactly one capture group"):
            update_file(
                fortran_file,
                r"PARAMETER \(VERSION='[^']+'\)",
                "PARAMETER (VERSION='{version}')",
                "1.0.0",
            )

    def test_multiple_capture_groups_raises(self, fortran_file):
        with pytest.raises(ValueError, match="exactly one capture group"):
            update_file(fortran_file, r"(PARAMETER) \(VERSION='([^']+)'\)", "{version}", "1.0.0")

    def test_format_missing_version_placeholder_raises(self, fortran_file):
        with pytest.raises(ValueError, match="must contain"):
            update_file(
                fortran_file,
                r"PARAMETER \(VERSION='([^']+)'\)",
                "PARAMETER (VERSION='hardcoded')",
                "1.0.0",
            )

    def test_pattern_not_found_warns(self, tmp_path, capsys):
        f = tmp_path / "file.f"
        f.write_text("no version here\n")
        update_file(f, r"VERSION='([^']+)'", "VERSION='{version}'", "1.0.0")
        assert "not found" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Integration tests: set_version with --file/--pattern/--format
# ---------------------------------------------------------------------------


class TestSetVersionWithFile:
    def test_updates_all_files_including_fortran(self, project_dir, fortran_file):
        pattern = r"PARAMETER \(VERSION='([^']+)'\)"
        fmt = "PARAMETER (VERSION='{version}')"
        set_version("2.0.0", project_dir, file=fortran_file, pattern=pattern, fmt=fmt)
        assert (project_dir / "version.txt").read_text() == "2.0.0"
        assert "VERSION='2.0.0'" in fortran_file.read_text()

    def test_file_without_pattern_raises(self, project_dir, fortran_file):
        with pytest.raises(ValueError, match="--file requires"):
            set_version("2.0.0", project_dir, file=fortran_file, pattern=None, fmt=None)


# ---------------------------------------------------------------------------
# Integration tests: CLI via __main__
# ---------------------------------------------------------------------------


class TestCLI:
    def _run(self, monkeypatch, capsys, *argv):
        from modflow_devtools.version.__main__ import main

        monkeypatch.setattr(sys, "argv", ["mf version", *argv])
        try:
            main()
        except SystemExit as e:
            return e.code, capsys.readouterr()
        return 0, capsys.readouterr()

    def test_get(self, project_dir, monkeypatch, capsys):
        code, captured = self._run(monkeypatch, capsys, "get", "--root", str(project_dir))
        assert code == 0
        assert captured.out.strip() == "1.0.0"

    def test_get_root_option(self, project_dir, monkeypatch, capsys):
        code, captured = self._run(monkeypatch, capsys, "get", "--root", str(project_dir))
        assert code == 0
        assert "1.0.0" in captured.out

    def test_get_missing_version_txt(self, tmp_path, monkeypatch, capsys):
        code, captured = self._run(monkeypatch, capsys, "get", "--root", str(tmp_path))
        assert code == 1
        assert "Error" in captured.err

    def test_set(self, project_dir, monkeypatch, capsys):
        code, _ = self._run(monkeypatch, capsys, "set", "2.0.0", "--root", str(project_dir))
        assert code == 0
        assert (project_dir / "version.txt").read_text() == "2.0.0"

    def test_set_dry_run(self, project_dir, monkeypatch, capsys):
        code, captured = self._run(
            monkeypatch, capsys, "set", "9.9.9", "--root", str(project_dir), "--dry-run"
        )
        assert code == 0
        assert (project_dir / "version.txt").read_text() == "1.0.0"
        assert "9.9.9" in captured.out

    def test_set_with_file(self, project_dir, fortran_file, monkeypatch, capsys):
        code, _ = self._run(
            monkeypatch,
            capsys,
            "set",
            "2.0.0",
            "--root",
            str(project_dir),
            "--file",
            str(fortran_file),
            "--pattern",
            r"PARAMETER \(VERSION='([^']+)'\)",
            "--format",
            "PARAMETER (VERSION='{version}')",
        )
        assert code == 0
        assert "VERSION='2.0.0'" in fortran_file.read_text()

    def test_set_file_missing_pattern_errors(self, project_dir, fortran_file, monkeypatch, capsys):
        code, _ = self._run(
            monkeypatch,
            capsys,
            "set",
            "2.0.0",
            "--root",
            str(project_dir),
            "--file",
            str(fortran_file),
            # --pattern and --format omitted
        )
        assert code != 0

    def test_no_command_exits(self, monkeypatch, capsys):
        code, _ = self._run(monkeypatch, capsys)
        assert code == 1
