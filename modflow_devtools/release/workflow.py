"""
The release workflow's stages, run by the release-start and release-finish
actions.

``start`` selects the stage from the triggering event:

- ``prepare``, on workflow_dispatch from the development branch: create
  release/vX.Y.Z, set the version, update CHANGELOG.md, and push the branch.
  If the branch already exists (e.g. a rerun after a failed build), it is
  reused as is.
- ``publish``, on push to the main branch, if the version there is X.Y.Z,
  untagged, and has a CHANGELOG.md section.
- nothing (empty stage) otherwise.

``finish`` completes the stage after the build:

- ``prepare``: open the release pull request into the main branch.
- ``publish``: check the archives, publish the GitHub release, and open a
  pull request on post-release/vX.Y.Z setting the next development version on
  the development branch.

Each step checks whether it has already been done, so a failed run can be
rerun.

Pull requests and releases go through the ``GitHub`` class, using the gh
CLI. Everything else uses git, so another forge needs only another class
with the same methods.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from modflow_devtools.release import changelog, version
from modflow_devtools.release.ci import error, notice

BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
ARCHIVES = {"linux.zip", "macarm.zip", "win64.zip"}
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
TAG = re.compile(r"^refs/tags/(v?(\d+)\.(\d+)\.(\d+))$")


def run(cmd, cwd, check=True):
    """Run a command, capturing its output, and fail with its stderr."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        sys.exit(f"{' '.join(cmd)} failed:\n{result.stderr.strip()}")
    return result


def git(root, *args, check=True):
    return run(["git", *args], root, check)


def release_branch(v):
    return f"release/v{v}"


def post_release_branch(v):
    return f"post-release/v{v}"


def tagged(root, v):
    return (
        git(
            root, "ls-remote", "--exit-code", "--tags", "origin", f"refs/tags/v{v}", check=False
        ).returncode
        == 0
    )


def remote_branch(root, branch):
    return (
        git(
            root,
            "ls-remote",
            "--exit-code",
            "--heads",
            "origin",
            f"refs/heads/{branch}",
            check=False,
        ).returncode
        == 0
    )


def latest_tag(root):
    """The origin's highest release tag (vX.Y.Z, or X.Y.Z from before the
    convention) and its version as a tuple, or None if there are none."""
    out = git(root, "ls-remote", "--tags", "origin").stdout
    tags = [m for ref in out.split()[1::2] if (m := TAG.match(ref))]
    if not tags:
        return None
    m = max(tags, key=lambda m: tuple(map(int, m.groups()[1:])))
    return m.group(1), tuple(map(int, m.groups()[1:]))


def fetch_history(root):
    """Fetch the full history and tags, which git-cliff and the checks on the
    last release need."""
    shallow = git(root, "rev-parse", "--is-shallow-repository").stdout.strip() == "true"
    git(root, "fetch", "--quiet", *(["--unshallow"] if shallow else []), "--tags", "origin")


def check_latest(root, v, develop, main):
    """Fail if the version isn't newer than the last release, or, in the
    dual-branch model, if the last release isn't merged into the development
    branch."""
    latest = latest_tag(root)
    if latest is None:
        return
    tag, last = latest
    if tuple(map(int, v.split("."))) <= last:
        sys.exit(f"version {v} is not newer than the last release, {tag}")
    if develop != main:
        fetch_history(root)
        if git(root, "merge-base", "--is-ancestor", tag, "HEAD", check=False).returncode:
            sys.exit(
                f"{tag} is not reachable from {develop}, so the changelog would repeat it. "
                f"Merge {main} into {develop} with a merge commit (not a squash) first."
            )


def commit(root, message, paths):
    """Commit just the given paths, as the actions bot."""
    git(root, "add", "--", *paths)
    git(
        root,
        "-c",
        f"user.name={BOT_NAME}",
        "-c",
        f"user.email={BOT_EMAIL}",
        "commit",
        "-m",
        message,
    )


class GitHub:
    """Pull requests and releases on GitHub, with the gh CLI."""

    def __init__(self, root, repository):
        self.root = root
        self.repository = repository

    def gh(self, *args, check=True):
        return run(["gh", *args, "-R", self.repository], self.root, check)

    def pr_states(self, head):
        """States (OPEN, MERGED, CLOSED) of the pull requests from a branch."""
        out = self.gh(
            "pr", "list", "--head", head, "--state", "all", "--json", "state", "--jq", ".[].state"
        )
        return out.stdout.split()

    def create_pr(self, base, head, title, body):
        self.gh("pr", "create", "-B", base, "-H", head, "--title", title, "--body", body)

    def release_state(self, tag):
        """None if there is no release for the tag, else 'draft' or 'published'."""
        result = self.gh(
            "release", "view", tag, "--json", "isDraft", "--jq", ".isDraft", check=False
        )
        if result.returncode != 0:
            if "not found" in result.stderr.lower():
                return None
            sys.exit(f"gh release view failed:\n{result.stderr.strip()}")
        return "draft" if json.loads(result.stdout) else "published"

    def delete_release(self, tag):
        self.gh("release", "delete", tag, "--yes")

    def create_release(self, tag, files, target, title, notes):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.md"
            path.write_text(notes)
            self.gh(
                "release", "create", tag, *map(str, files), "--target", target,
                "--title", title, "--notes-file", str(path),
            )  # fmt: skip


def open_pr(forge, base, head, title, body):
    """Open a pull request, unless one from the branch is open or merged."""
    states = forge.pr_states(head)
    if "OPEN" in states or "MERGED" in states:
        print(f"pull request from {head} already {'open' if 'OPEN' in states else 'merged'}")
        return False
    forge.create_pr(base, head, title, body)
    return True


def start(root, event, ref_name, sha, v, long_name, repository, main, develop=""):
    """Select the stage, preparing the release branch for ``prepare``.
    Returns the outputs: stage, ref and version."""
    develop = develop or main
    if event == "workflow_dispatch":
        if ref_name != develop:
            sys.exit(f"start a release from {develop}, not {ref_name}")
        if not VERSION.match(v or ""):
            sys.exit(f"version '{v}' is not X.Y.Z")
        if tagged(root, v):
            sys.exit(f"tag v{v} already exists")
        check_latest(root, v, develop, main)
        branch = release_branch(v)
        if remote_branch(root, branch):
            notice(f"{branch} exists, building it as is. Delete it to start over.")
        else:
            prepare(root, v, branch, repository, long_name)
        return {"stage": "prepare", "ref": branch, "version": v}
    if event == "push" and ref_name == main:
        v = version.get_version(root)
        if VERSION.match(v) and not tagged(root, v):
            # fail before the build if there are no release notes
            changelog.notes(root, v)
            return {"stage": "publish", "ref": sha, "version": v}
        print(f"version {v} on {main} is not an untagged release version, nothing to do")
    return {"stage": "", "ref": "", "version": v or ""}


def prepare(root, v, branch, repository, long_name):
    fetch_history(root)
    git(root, "switch", "-c", branch)
    version.set_version(root, v)
    changelog.update(root, v, repository, long_name)
    commit(
        root,
        f"chore(release): set version to {v} and update changelog",
        [*version.files(root), "CHANGELOG.md"],
    )
    git(root, "push", "origin", branch)


def finish_prepare(root, repository, ref, v, main, develop=""):
    develop = develop or main
    body = (
        f"Review the {v} section of CHANGELOG.md, it becomes the release notes. "
        f"Merging this publishes release v{v} and opens a pull request setting "
        f"the next development version on {develop}."
    )
    open_pr(GitHub(root, repository), main, ref, f"chore(release): {v}", body)


def expand(dirs, patterns):
    """Files matching each glob, relative to any of the directories. Each
    must match."""
    files = []
    for pattern in (p.strip() for p in patterns):
        if not pattern:
            continue
        matches = sorted(p for d in dirs if d.is_dir() for p in d.glob(pattern) if p.is_file())
        if not matches:
            sys.exit(f"extra asset pattern '{pattern}' matches no files")
        files += [p for p in matches if p not in files]
    return files


def assets(root, dist, name, platforms, extra=()):
    """The release's files: the archives in dist, each platform's present and
    nothing unexpected, then the extra assets, which are matched in the repo
    and in dist (for files built in other jobs and uploaded as dist-*
    artifacts)."""
    dist = Path(dist)
    allowed = ARCHIVES | {f"{name}_source.zip"}
    extras = expand([root, dist], extra)
    found = sorted(p for p in dist.iterdir() if p.is_file()) if dist.is_dir() else []
    archives = [p for p in found if p not in extras]
    ok = True
    for p in platforms:
        if not (dist / f"{p}.zip").is_file():
            error(f"missing {p}.zip")
            ok = False
    for path in archives:
        if path.name not in allowed:
            error(f"unexpected file {path.name}")
            ok = False
    files = archives + extras
    names = [f.name for f in files]
    for n in sorted({n for n in names if names.count(n) > 1}):
        error(f"more than one asset named {n}")
        ok = False
    if not ok:
        sys.exit("bad release assets")
    return files


def publish(root, repository, ref, v, name, long_name, dist, platforms, extra=()):
    files = assets(root, dist, name, platforms, extra)
    notes = changelog.notes(root, v, long_name)
    print(notes)
    tag = f"v{v}"
    forge = GitHub(root, repository)
    state = forge.release_state(tag)
    if state == "published":
        print(f"release {tag} already published")
        return False
    if state == "draft":
        # gh leaves a draft when an asset upload fails
        print(f"deleting draft release {tag} from an earlier run")
        forge.delete_release(tag)
    forge.create_release(tag, files, ref, f"{name} {v}", notes)
    return True


def post_release(root, repository, v, main, develop=""):
    """Open the pull request setting the next development version on the
    development branch. In the dual-branch model, this also merges the main
    branch into the development branch."""
    develop = develop or main
    branch = post_release_branch(v)
    forge = GitHub(root, repository)
    states = forge.pr_states(branch)
    if "OPEN" in states or "MERGED" in states:
        print(f"pull request from {branch} already {'open' if 'OPEN' in states else 'merged'}")
        return False
    nxt = version.next_version(v)
    if remote_branch(root, branch):
        print(f"{branch} exists, opening a pull request from it")
    else:
        git(root, "switch", "-c", branch)
        version.set_version(root, nxt)
        commit(root, f"chore(release): set version to {nxt}", version.files(root))
        git(root, "push", "origin", branch)
    body = f"Set the version on {develop} to {nxt} after the {v} release."
    if develop != main:
        body += (
            f" This also merges {main} into {develop}. Merge it with a merge commit, "
            f"not a squash, so the v{v} tag is reachable from {develop}."
        )
    open_pr(forge, develop, branch, f"chore(release): set version to {nxt}", body)
    return True


def finish(
    root, stage, repository, ref, v, name, long_name, main, develop, dist, platforms, extra=()
):
    if stage == "prepare":
        finish_prepare(root, repository, ref, v, main, develop)
    elif stage == "publish":
        publish(root, repository, ref, v, name, long_name, dist, platforms, extra)
        post_release(root, repository, v, main, develop)
    else:
        sys.exit(f"unexpected stage '{stage}', expected prepare or publish")


def write_outputs(outputs, path=None):
    for key, value in outputs.items():
        print(f"{key}={value}")
    if path:
        with Path(path).open("a", newline="\n") as f:
            for key, value in outputs.items():
                f.write(f"{key}={value}\n")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repo root")
    parser.add_argument("--repository", required=True, help="owner/repo")
    parser.add_argument("--main-branch", default="main")
    parser.add_argument("--develop-branch", default="")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("start", help="select the stage, preparing the release branch")
    s.add_argument("--event", required=True)
    s.add_argument("--ref-name", required=True)
    s.add_argument("--sha", required=True)
    s.add_argument("--version", default="")
    s.add_argument("--long-name", required=True)
    s.add_argument("--output", help="file to append outputs to, e.g. $GITHUB_OUTPUT")
    f = sub.add_parser("finish", help="open the release pull request, or publish")
    f.add_argument("--stage", required=True)
    f.add_argument("--ref", required=True)
    f.add_argument("--version", required=True)
    f.add_argument("--name", required=True)
    f.add_argument("--long-name", required=True)
    f.add_argument("--dist", type=Path, required=True, help="directory holding the archives")
    f.add_argument("--platforms", nargs="+", default=["linux", "macarm", "win64"])
    f.add_argument(
        "--extra-assets", nargs="*", default=[], help="globs relative to the repo root or dist"
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.command == "start":
        outputs = start(
            root,
            args.event,
            args.ref_name,
            args.sha,
            args.version,
            args.long_name,
            args.repository,
            args.main_branch,
            args.develop_branch,
        )
        write_outputs(outputs, args.output)
    else:
        finish(
            root,
            args.stage,
            args.repository,
            args.ref,
            args.version,
            args.name,
            args.long_name,
            args.main_branch,
            args.develop_branch,
            args.dist,
            args.platforms,
            args.extra_assets,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
