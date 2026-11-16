import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from modflow_devtools.release import changelog, linkage, package, version, workflow

FIXTURE = Path(__file__).resolve().parent / "release"
IGNORE = shutil.ignore_patterns("builddir*", "bin", ".pixi")
HAS_CLIFF = bool(shutil.which("pipx") or shutil.which("uvx"))


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "hello"
    shutil.copytree(FIXTURE, root, ignore=IGNORE)
    return root


def git(root, *args):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


# version


def test_get(repo):
    assert version.get_version(repo) == "0.1.0.dev0"


def test_set_updates_every_target(repo):
    date = datetime(2026, 11, 10, tzinfo=UTC)
    version.set_version(repo, "1.2.3", date=date)
    assert version.get_version(repo) == "1.2.3"
    assert "version: '1.2.3'" in (repo / "meson.build").read_text()
    assert 'version = "1.2.3"' in (repo / "pixi.toml").read_text()
    assert "VERSION = '1.2.3 11/10/2026'" in (repo / "src" / "hello.f90").read_text()


def test_files(repo):
    assert version.files(repo) == ["meson.build", "pixi.toml", "src/hello.f90"]


def test_set_keeps_line_endings(repo):
    path = repo / "src" / "hello.f90"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    version.set_version(repo, "1.2.3")
    assert b"\r\n" in path.read_bytes()
    assert b"\n" not in path.read_bytes().replace(b"\r\n", b"")


@pytest.mark.parametrize("value", ["1.2", "v1.2.3", "1.2.3rc1", "1.2.3.dev"])
def test_set_rejects_bad_versions(repo, value):
    with pytest.raises(SystemExit):
        version.set_version(repo, value)


def test_next():
    assert version.next_version("1.5.0") == "1.6.0.dev0"
    assert version.next_version("1.5.2") == "1.6.0.dev2"
    assert version.next_version("1.6.0.dev0") == "1.7.0.dev0"


def test_is_release(repo):
    assert version.main(["--root", str(repo), "--is-release"]) == 1
    version.set_version(repo, "1.0.0")
    assert version.main(["--root", str(repo), "--is-release"]) == 0


def test_version_txt(repo):
    meson = repo / "meson.build"
    meson.write_text(
        meson.read_text().replace("version: '0.1.0.dev0'", "version: files('version.txt')")
    )
    (repo / "version.txt").write_text("1.0.03\n")
    assert version.get_version(repo) == "1.0.03"
    version.set_version(repo, "1.0.4")
    assert (repo / "version.txt").read_text() == "1.0.4\n"


def test_only_project_version(repo):
    """Only project()'s version keyword counts, not meson_version or another
    call's version keyword, even with parentheses in strings and comments."""
    meson = repo / "meson.build"
    text = meson.read_text().replace(
        "  license: 'CC0',",
        "  license: 'CC0', # a comment with a )\n  license_files: [')(.txt'],",
    )
    text += "\ndep = dependency(\n  'netcdf',\n  version: '>=4.9',\n  required: false,\n)\n"
    meson.write_text(text)
    assert version.get_version(repo) == "0.1.0.dev0"
    version.set_version(repo, "1.2.3")
    text = meson.read_text()
    assert "version: '1.2.3'" in text
    assert "version: '>=4.9'" in text
    assert "meson_version: '>= 1.7.0'" in text


def test_no_project_version(repo):
    meson = repo / "meson.build"
    meson.write_text(meson.read_text().replace("  version: '0.1.0.dev0',\n", ""))
    with pytest.raises(SystemExit):
        version.get_version(repo)


def test_without_pixi_or_config(repo):
    (repo / "pixi.toml").unlink()
    (repo / "release.toml").unlink()
    version.set_version(repo, "2.0.0")
    assert version.get_version(repo) == "2.0.0"


def test_missing_target_changes_nothing(repo):
    path = repo / "src" / "hello.f90"
    path.write_text(path.read_text().replace("VERSION =", "V ="))
    before = {p: p.read_bytes() for p in (repo / "meson.build", repo / "pixi.toml")}
    with pytest.raises(SystemExit):
        version.set_version(repo, "1.2.3")
    assert {p: p.read_bytes() for p in before} == before


# changelog

CHANGELOG = """\
# Changelog

## Version 1.2.0 (2026-11-10)

### Features

* Something new

## Version 1.1.0 (2026-01-01)

### Fixes

* Something old
"""


def test_notes(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG)
    assert changelog.notes(tmp_path, "1.2.0") == "### Features\n\n* Something new\n"
    assert changelog.notes(tmp_path, "1.1.0") == "### Fixes\n\n* Something old\n"
    with pytest.raises(SystemExit):
        changelog.notes(tmp_path, "1.0.0")


def test_notes_title(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG)
    notes = changelog.notes(tmp_path, "1.2.0", "Hello")
    assert notes == "Hello version 1.2.0\n\n### Features\n\n* Something new\n"


@pytest.mark.skipif(not HAS_CLIFF, reason="needs pipx or uvx")
def test_update(repo):
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "feat: first")
    git(repo, "tag", "v0.1.0")
    git(repo, "commit", "-q", "--allow-empty", "-m", "fix(io): read the thing")
    git(repo, "commit", "-q", "--allow-empty", "-m", "ci: skipped")
    git(repo, "commit", "-q", "--allow-empty", "-m", "fix(ci): also skipped")
    changelog.update(repo, "0.2.0", "MODFLOW-ORG/hello", "Hello")
    text = (repo / "CHANGELOG.md").read_text()
    assert "Features, fixes, and performance changes in each Hello release." in text
    assert "## Version 0.2.0" in text
    assert "io: Read the thing" in text
    assert "https://github.com/MODFLOW-ORG/hello/commit/" in text
    assert "first" not in text and "skipped" not in text
    assert changelog.notes(repo, "0.2.0").startswith("### Fixes")

    # a second release prepends, keeping the first
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "chore(release): 0.2.0")
    git(repo, "tag", "v0.2.0")
    git(repo, "commit", "-q", "--allow-empty", "-m", "perf: faster")
    changelog.update(repo, "0.3.0", "MODFLOW-ORG/hello", "Hello")
    text = (repo / "CHANGELOG.md").read_text()
    assert text.count("# Changelog") == 1
    assert b"\r\n" not in (repo / "CHANGELOG.md").read_bytes()
    assert text.index("## Version 0.3.0") < text.index("## Version 0.2.0")
    assert "Faster" in changelog.notes(repo, "0.3.0")


# package


def built(repo, *names):
    (repo / "bin").mkdir()
    for name in names:
        path = repo / "bin" / name
        path.write_text("exe")
        path.chmod(0o755)


def test_package(repo, tmp_path):
    built(repo, "hello", "hellodbl")
    dist = tmp_path / "dist"
    assert package.package(repo, "hello", dist, tag="linux") == "linux"
    with zipfile.ZipFile(dist / "linux.zip") as z:
        assert sorted(z.namelist()) == ["hello", "hellodbl"]
        if sys.platform != "win32":
            assert (z.getinfo("hello").external_attr >> 16) & 0o111
    with zipfile.ZipFile(dist / "hello_source.zip") as z:
        names = z.namelist()
    assert "meson.build" in names and "meson.options" in names and "src/hello.f90" in names


def test_package_no_source(repo, tmp_path):
    built(repo, "hello")
    package.package(repo, "hello", tmp_path / "dist", source_paths=[], tag="linux")
    assert [p.name for p in (tmp_path / "dist").iterdir()] == ["linux.zip"]


def test_package_source_only_on_linux(repo, tmp_path):
    built(repo, "hello.exe")
    package.package(repo, "hello", tmp_path / "dist", tag="win64")
    assert [p.name for p in (tmp_path / "dist").iterdir()] == ["win64.zip"]


def test_package_optional_meson_options(repo, tmp_path):
    built(repo, "hello")
    (repo / "meson.options").unlink()
    package.package(repo, "hello", tmp_path / "dist", tag="linux")
    with pytest.raises(SystemExit):
        package.package(repo, "hello", tmp_path / "dist", ["meson.options"], tag="linux")


def test_package_tracked_source(repo, tmp_path):
    built(repo, "hello")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "first")
    (repo / "src" / "scratch.o").write_text("untracked")
    package.package(repo, "hello", tmp_path / "dist", tag="linux")
    with zipfile.ZipFile(tmp_path / "dist" / "hello_source.zip") as z:
        assert "src/scratch.o" not in z.namelist()


def test_package_empty_bin(repo, tmp_path):
    with pytest.raises(SystemExit):
        package.package(repo, "hello", tmp_path / "dist", tag="linux")


# workflow, against a local origin and a fake gh

FAKE_GH = """\
import json, os, sys
path = os.environ["FAKE_GH_STATE"]
with open(path) as f:
    state = json.load(f)
args = sys.argv[1:]
state["calls"].append(args)
def opt(name):
    return args[args.index(name) + 1]
out, code = "", 0
if args[:2] == ["pr", "list"]:
    out = "\\n".join(p["state"] for p in state["prs"] if p["head"] == opt("--head"))
elif args[:2] == ["pr", "create"]:
    state["prs"].append({"head": opt("-H"), "base": opt("-B"), "state": "OPEN"})
elif args[:2] == ["release", "view"]:
    release = state["releases"].get(args[2])
    if release is None:
        sys.stderr.write("release not found\\n")
        code = 1
    else:
        out = json.dumps(release["isDraft"])
elif args[:2] == ["release", "delete"]:
    del state["releases"][args[2]]
elif args[:2] == ["release", "create"]:
    files = [os.path.basename(a) for a in args[3 : args.index("-R")]]
    with open(opt("--notes-file")) as f:
        notes = f.read()
    state["releases"][args[2]] = {
        "isDraft": False, "files": files, "target": opt("--target"),
        "title": opt("--title"), "notes": notes,
    }
with open(path, "w") as f:
    json.dump(state, f)
print(out)
sys.exit(code)
"""


class Gh:
    """A fake gh on PATH, keeping pull requests and releases in a file."""

    def __init__(self, tmp_path, monkeypatch):
        bindir = tmp_path / "fakebin"
        bindir.mkdir()
        script = bindir / "fake_gh.py"
        script.write_text(FAKE_GH)
        gh = bindir / "gh"
        gh.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        gh.chmod(0o755)
        self.path = tmp_path / "gh.json"
        self.save({"prs": [], "releases": {}, "calls": []})
        monkeypatch.setenv("FAKE_GH_STATE", str(self.path))
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")

    def load(self):
        return json.loads(self.path.read_text())

    def save(self, state):
        self.path.write_text(json.dumps(state))

    def calls(self, *prefix):
        return [c for c in self.load()["calls"] if c[: len(prefix)] == list(prefix)]


@pytest.fixture
def gh(tmp_path, monkeypatch):
    # the workflow runs on Linux, and the real gh.exe would shadow a fake
    # gh.bat on Windows
    if sys.platform == "win32":
        pytest.skip("fake gh needs a POSIX shell")
    return Gh(tmp_path, monkeypatch)


@pytest.fixture
def origin(repo, tmp_path, monkeypatch):
    """The fixture as a git repo with a release history, pushed to a bare
    origin. changelog.update is stubbed so these tests don't need git-cliff."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "feat: first")
    git(repo, "tag", "v0.0.1")
    git(repo, "commit", "-q", "--allow-empty", "-m", "fix: second")
    git(repo, "push", "-q", "origin", "main", "--tags")

    def update(root, v, repository, long_name):
        path = root / "CHANGELOG.md"
        old = path.read_text() if path.is_file() else "# Changelog\n"
        path.write_text(old + f"\n## Version {v} (2026-11-15)\n\n### Fixes\n\n* Second\n")

    monkeypatch.setattr(changelog, "update", update)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t")
    return repo


def remote_file(repo, ref, path):
    return git(repo, "show", f"origin/{ref}:{path}")


def start(repo, event="workflow_dispatch", ref_name="main", v="0.1.0", develop=""):
    sha = git(repo, "rev-parse", "HEAD")
    return workflow.start(repo, event, ref_name, sha, v, "Hello", "o/hello", "main", develop)


def test_start_nothing_to_do(origin, gh):
    assert start(origin, "push")["stage"] == ""
    assert start(origin, "push", ref_name="feature")["stage"] == ""
    assert start(origin, "pull_request")["stage"] == ""


@pytest.mark.parametrize(
    "kwargs",
    [{"ref_name": "feature"}, {"v": "0.1"}, {"v": ""}, {"v": "0.0.1"}, {"develop": "develop"}],
    ids=["wrong-branch", "bad-version", "no-version", "tagged", "not-develop"],
)
def test_start_rejects(origin, gh, kwargs):
    with pytest.raises(SystemExit):
        start(origin, **kwargs)


def test_prepare(origin, gh):
    (origin / "stray.txt").write_text("not for the release")
    out = start(origin)
    assert out == {"stage": "prepare", "ref": "release/v0.1.0", "version": "0.1.0"}
    git(origin, "fetch", "-q", "origin")
    assert "version: '0.1.0'" in remote_file(origin, "release/v0.1.0", "meson.build")
    assert "## Version 0.1.0" in remote_file(origin, "release/v0.1.0", "CHANGELOG.md")
    changed = git(origin, "show", "--name-only", "--format=", "origin/release/v0.1.0")
    assert sorted(changed.split()) == ["CHANGELOG.md", "meson.build", "pixi.toml", "src/hello.f90"]

    # a rerun reuses the branch
    head = git(origin, "rev-parse", "origin/release/v0.1.0")
    git(origin, "switch", "-q", "main")
    assert start(origin)["stage"] == "prepare"
    git(origin, "fetch", "-q", "origin")
    assert git(origin, "rev-parse", "origin/release/v0.1.0") == head

    # the release pull request is opened once
    for _ in range(2):
        workflow.finish_prepare(origin, "o/hello", "release/v0.1.0", "0.1.0", "main")
    creates = gh.calls("pr", "create")
    assert len(creates) == 1
    assert creates[0][creates[0].index("-B") + 1] == "main"


def merged_release(origin, v="0.1.0"):
    """Simulate merging the release pull request into main."""
    start(origin, v=v)
    git(origin, "switch", "-q", "main")
    git(origin, "merge", "-q", "--ff-only", f"release/v{v}")
    git(origin, "push", "-q", "origin", "main")


def dist(tmp_path, *names):
    path = tmp_path / "dist"
    path.mkdir(exist_ok=True)
    for name in names:
        (path / name).write_text("zip")
    return path


ARCHIVES = ("linux.zip", "macarm.zip", "win64.zip", "hello_source.zip")
PLATFORMS = ["linux", "macarm", "win64"]


def test_start_publish(origin, gh):
    merged_release(origin)
    out = start(origin, "push")
    assert out == {"stage": "publish", "ref": git(origin, "rev-parse", "HEAD"), "version": "0.1.0"}


def test_start_publish_needs_notes(origin, gh):
    """An untagged release version without release notes fails before the build."""
    version.set_version(origin, "0.1.0")
    git(origin, "commit", "-q", "-am", "chore: set version")
    with pytest.raises(SystemExit, match=r"no CHANGELOG\.md"):
        start(origin, "push")


def test_publish(origin, gh, tmp_path):
    merged_release(origin)
    (origin / "doc").mkdir()
    (origin / "doc" / "guide.pdf").write_text("pdf")
    sha = git(origin, "rev-parse", "HEAD")
    d = dist(tmp_path, *ARCHIVES)
    for _ in range(2):
        workflow.finish(
            origin, "publish", "o/hello", sha, "0.1.0", "hello", "Hello", "main", "",
            d, PLATFORMS, ["doc/*.pdf"],
        )  # fmt: skip
    state = gh.load()
    assert len(gh.calls("release", "create")) == 1
    release = state["releases"]["v0.1.0"]
    assert sorted(release["files"]) == sorted([*ARCHIVES, "guide.pdf"])
    assert release["target"] == sha
    assert release["title"] == "hello 0.1.0"
    assert release["notes"].startswith("Hello version 0.1.0\n\n### Fixes")
    assert "--latest" not in gh.calls("release", "create")[0]

    # the next version pull request is opened once, from post-release/v0.1.0
    creates = gh.calls("pr", "create")
    assert len(creates) == 1
    assert creates[0][creates[0].index("-H") + 1] == "post-release/v0.1.0"
    assert creates[0][creates[0].index("-B") + 1] == "main"
    git(origin, "fetch", "-q", "origin")
    meson = remote_file(origin, "post-release/v0.1.0", "meson.build")
    assert "version: '0.2.0.dev0'" in meson


def test_publish_dual(origin, gh, tmp_path):
    merged_release(origin)
    sha = git(origin, "rev-parse", "HEAD")
    d = dist(tmp_path, *ARCHIVES)
    workflow.finish(
        origin, "publish", "o/hello", sha, "0.1.0", "hello", "Hello", "main", "develop",
        d, PLATFORMS,
    )  # fmt: skip
    create = gh.calls("pr", "create")[0]
    assert create[create.index("-B") + 1] == "develop"
    assert "merge commit" in create[create.index("--body") + 1]


def test_publish_replaces_draft(origin, gh, tmp_path):
    merged_release(origin)
    state = gh.load()
    state["releases"]["v0.1.0"] = {"isDraft": True}
    gh.save(state)
    sha = git(origin, "rev-parse", "HEAD")
    workflow.publish(
        origin, "o/hello", sha, "0.1.0", "hello", "Hello", dist(tmp_path, *ARCHIVES), PLATFORMS
    )
    assert len(gh.calls("release", "delete")) == 1
    assert not gh.load()["releases"]["v0.1.0"]["isDraft"]


def test_post_release_reuses_branch(origin, gh, tmp_path):
    """A rerun after pushing the branch but failing to open the pull request."""
    merged_release(origin)
    git(origin, "push", "-q", "origin", "HEAD:refs/heads/post-release/v0.1.0")
    workflow.post_release(origin, "o/hello", "0.1.0", "main")
    assert len(gh.calls("pr", "create")) == 1


def test_post_release_after_merge(origin, gh):
    state = gh.load()
    state["prs"].append({"head": "post-release/v0.1.0", "base": "main", "state": "MERGED"})
    gh.save(state)
    assert not workflow.post_release(origin, "o/hello", "0.1.0", "main")
    assert not gh.calls("pr", "create")


@pytest.mark.parametrize(
    "names,extra",
    [
        (("linux.zip", "win64.zip"), []),
        ((*ARCHIVES, "mac.zip"), []),
        ((*ARCHIVES, "other.txt"), []),
        (ARCHIVES, ["doc/*.pdf"]),
        (ARCHIVES, ["*.zip"]),
    ],
    ids=["missing", "intel-mac", "unexpected", "no-match", "duplicate-name"],
)
def test_bad_assets(repo, tmp_path, names, extra):
    (repo / "hello_source.zip").write_text("zip")
    with pytest.raises(SystemExit):
        workflow.assets(repo, dist(tmp_path, *names), "hello", PLATFORMS, extra)


def test_finish_bad_stage(origin, gh, tmp_path):
    with pytest.raises(SystemExit):
        workflow.finish(
            origin, "", "o/hello", "x", "0.1.0", "hello", "Hello", "main", "", tmp_path, PLATFORMS
        )


def test_cli_outputs(origin, gh, tmp_path):
    output = tmp_path / "github_output"
    sha = git(origin, "rev-parse", "HEAD")
    args = ["--root", str(origin), "--repository", "o/hello", "start", "--event", "push"]
    args += ["--ref-name", "main", "--sha", sha, "--long-name", "Hello", "--output", str(output)]
    assert workflow.main(args) == 0
    assert output.read_text() == "stage=\nref=\nversion=0.1.0.dev0\n"


# linkage, on sample tool output

OBJDUMP_ELF = """
hello:     file format elf64-x86-64

Dynamic Section:
  NEEDED               libm.so.6
  NEEDED               libc.so.6
  NEEDED               {extra}
  INIT                 0x0000000000001000

Version References:
  required from libc.so.6:
    0x09691a75 0x00 03 GLIBC_2.2.5
    0x069691b4 0x00 02 GLIBC_{glibc}
"""


@pytest.mark.parametrize(
    "extra,glibc,problems",
    [
        ("libgcc_s.so.1", "2.34", []),
        ("libgfortran.so.5", "2.34", ["links libgfortran.so.5"]),
        ("libstdc++.so.6", "2.34", ["links libstdc++.so.6"]),
        ("libifcore.so.5", "2.17", ["links libifcore.so.5"]),
        ("libgcc_s.so.1", "2.35", ["needs glibc 2.35, newer than 2.34"]),
    ],
)
def test_linkage_linux(extra, glibc, problems):
    assert linkage.check_linux(OBJDUMP_ELF.format(extra=extra, glibc=glibc)) == problems


def test_linkage_linux_static():
    assert linkage.check_linux("hello:     file format elf64-x86-64\n") == []


def test_linkage_linux_dynamic_without_libraries():
    assert linkage.check_linux("Dynamic Section:\n  INIT 0x1000\n") != []


OTOOL_L = """\
bin/hello:
\t@rpath/libgfortran.5.dylib (compatibility version 6.0.0, current version 6.0.0)
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1359.0.0)
"""

OTOOL_l = """\
Load command 11
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform 1
    minos {minos}
      sdk 15.5
"""


def test_linkage_macos_parse():
    assert linkage.parse_otool_L(OTOOL_L) == [
        "@rpath/libgfortran.5.dylib",
        "/usr/lib/libSystem.B.dylib",
    ]
    assert linkage.parse_otool_L(OTOOL_L, dylib=True) == ["/usr/lib/libSystem.B.dylib"]
    assert linkage.parse_otool_l(OTOOL_l.format(minos="14.0")) == (14, 0)
    old = "      cmd LC_VERSION_MIN_MACOSX\n  cmdsize 16\n  version 10.13\n"
    assert linkage.parse_otool_l(old) == (10, 13)
    assert linkage.parse_otool_l("") is None


SYSTEM = "/usr/lib/libSystem.B.dylib"


@pytest.mark.parametrize(
    "libs,archs,minos,problems",
    [
        ([SYSTEM, "/usr/lib/libc++.1.dylib"], ["arm64"], (14, 0), 0),
        ([SYSTEM, "/System/Library/Frameworks/Foo.framework/Foo"], ["arm64"], (11, 0), 0),
        ([SYSTEM, "@rpath/libgfortran.5.dylib"], ["arm64"], (14, 0), 1),
        ([SYSTEM, "/opt/homebrew/lib/libquadmath.0.dylib"], ["arm64"], (14, 0), 1),
        ([SYSTEM], ["x86_64"], (14, 0), 1),
        ([SYSTEM], ["arm64"], (26, 0), 1),
        ([SYSTEM], ["arm64"], None, 1),
        ([], ["arm64"], (14, 0), 1),
    ],
    ids=["ok", "framework", "rpath", "homebrew", "intel", "too-new", "no-minos", "no-libs"],
)  # fmt: skip
def test_linkage_macos(libs, archs, minos, problems):
    assert len(linkage.check_macos(libs, archs, minos)) == problems


OBJDUMP_PE = """
The Import Tables (interpreted .idata section contents)
 vma:            Hint/Ord Member-Name Bound-To
\tDLL Name: KERNEL32.dll
\tDLL Name: api-ms-win-crt-runtime-l1-1-0.dll
\tDLL Name: {extra}
"""

DUMPBIN = """\
Dump of file hello.exe

File Type: EXECUTABLE IMAGE

  Image has the following dependencies:

    KERNEL32.dll
    libifcoremd.dll

  Summary

        1000 .data
"""


@pytest.mark.parametrize(
    "extra,problems",
    [
        ("msvcrt.dll", []),
        ("ucrtbase.dll", []),
        ("libgfortran-5.dll", ["links libgfortran-5.dll"]),
        ("libwinpthread-1.dll", ["links libwinpthread-1.dll"]),
        ("VCRUNTIME140.dll", ["links VCRUNTIME140.dll"]),
        ("libmmd.dll", ["links libmmd.dll"]),
    ],
)
def test_linkage_windows(extra, problems):
    dlls = linkage.parse_objdump_pe(OBJDUMP_PE.format(extra=extra))
    assert len(dlls) == 3
    assert linkage.check_windows(dlls) == problems


def test_linkage_windows_dumpbin():
    dlls = linkage.parse_dumpbin(DUMPBIN)
    assert dlls == ["KERNEL32.dll", "libifcoremd.dll"]
    assert linkage.check_windows(dlls) == ["links libifcoremd.dll"]
    assert linkage.check_windows([]) != []


def test_linkage_finds_binaries(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "hello").write_bytes(b"\x7fELF\x02\x01")
    (tmp_path / "sub" / "libhello.so").write_bytes(b"\x7fELF\x02\x01")
    (tmp_path / "hello.exe").write_bytes(b"MZ\x90\x00")
    (tmp_path / "run.sh").write_text("#!/bin/sh\n")
    names = lambda os_: [p.name for p in linkage.binaries(tmp_path, os_)]  # noqa: E731
    assert names("linux") == ["hello", "libhello.so"]
    assert names("windows") == ["hello.exe"]
    assert names("macos") == []


def test_linkage_nothing_to_check(tmp_path, capsys):
    (tmp_path / "readme.txt").write_text("not a binary")
    assert not linkage.check(tmp_path)
    assert "no " in capsys.readouterr().err


def test_linkage_tool_failure(tmp_path, monkeypatch):
    (tmp_path / "hello").write_bytes(b"\x7fELF\x02\x01")

    def fail(cmd):
        raise RuntimeError("objdump failed")

    monkeypatch.setattr(linkage, "tool", fail)
    assert not linkage.check(tmp_path, "linux")


# release order checks


def push_tag(repo, tag, ref="HEAD"):
    git(repo, "tag", tag, ref)
    git(repo, "push", "-q", "origin", tag)


@pytest.mark.parametrize("tag", ["v0.2.0", "0.2.0", "v0.1.0-rc"], ids=["v", "unprefixed", "other"])
def test_start_rejects_older_version(origin, gh, tag):
    push_tag(origin, tag)
    if tag == "v0.1.0-rc":
        assert start(origin, v="0.1.0")["stage"] == "prepare"
    else:
        with pytest.raises(SystemExit, match="not newer than the last release"):
            start(origin, v="0.1.0")


def test_start_dual(origin, gh):
    git(origin, "switch", "-q", "-c", "develop")
    git(origin, "push", "-q", "origin", "develop")
    out = start(origin, ref_name="develop", develop="develop")
    assert out["stage"] == "prepare"


def test_start_dual_rejects_unmerged_release(origin, gh):
    """A squash-merged post-release pull request leaves the tag off develop."""
    git(origin, "switch", "-q", "-c", "develop")
    git(origin, "push", "-q", "origin", "develop")
    git(origin, "switch", "-q", "-c", "side", "main")
    git(origin, "commit", "-q", "--allow-empty", "-m", "chore(release): 0.0.2")
    push_tag(origin, "v0.0.2")
    git(origin, "switch", "-q", "develop")
    with pytest.raises(SystemExit, match="not reachable from develop"):
        start(origin, ref_name="develop", develop="develop")


def test_extra_assets_from_dist(repo, tmp_path):
    d = dist(tmp_path, *ARCHIVES, "notes.pdf")
    files = workflow.assets(repo, d, "hello", PLATFORMS, ["*.pdf"])
    assert sorted(f.name for f in files) == sorted([*ARCHIVES, "notes.pdf"])
    with pytest.raises(SystemExit):
        workflow.assets(repo, d, "hello", PLATFORMS)
