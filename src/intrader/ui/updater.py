"""Safe GitHub update checks for development checkouts and packaged builds."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import subprocess
from urllib import error, request

REPOSITORY = "KaranBarua01/Intrader"
UPDATE_BRANCH = "intrader-phase4"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"

class UpdateError(Exception):
    """Update state cannot be checked or applied safely."""


@dataclass(frozen=True, slots=True)
class UpdateStatus:
    mode: str
    available: bool
    summary: str
    commits: tuple[str, ...] = ()
    remote_version: str | None = None
    release_url: str | None = None


def _run_git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=45,
        )
    except (OSError, subprocess.SubprocessError):
        raise UpdateError("Git update command failed") from None
    return completed.stdout.strip()


def repository_root(start: Path | None = None) -> Path | None:
    start = (start or Path.cwd()).resolve()
    try:
        output = _run_git(start, "rev-parse", "--show-toplevel")
    except UpdateError:
        return None
    root = Path(output)
    return root if (root / ".git").exists() else None


class UpdateService:
    """Check/apply updates without touching ignored data or secrets."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or repository_root()

    @property
    def development_mode(self) -> bool:
        return self.root is not None and (self.root / ".git").exists()

    def check(self) -> UpdateStatus:
        if self.development_mode:
            return self._check_git()
        return self._check_release()

    def _check_git(self) -> UpdateStatus:
        assert self.root is not None
        branch = _run_git(self.root, "branch", "--show-current")
        if branch != UPDATE_BRANCH:
            return UpdateStatus(
                mode="git",
                available=False,
                summary=f"Switch to {UPDATE_BRANCH} before applying development updates.",
            )
        _run_git(self.root, "fetch", "origin", UPDATE_BRANCH)
        dirty = _run_git(self.root, "status", "--porcelain")
        if dirty:
            return UpdateStatus(
                mode="git",
                available=False,
                summary="Local tracked changes detected. Commit or stash them before updating.",
            )
        count_text = _run_git(
            self.root, "rev-list", "--count", f"HEAD..origin/{UPDATE_BRANCH}"
        )
        count = int(count_text or "0")
        if count == 0:
            return UpdateStatus("git", False, "Intrader is up to date.")
        log = _run_git(
            self.root,
            "log",
            "--pretty=%h %s",
            f"HEAD..origin/{UPDATE_BRANCH}",
            "--max-count=12",
        )
        commits = tuple(line for line in log.splitlines() if line.strip())
        return UpdateStatus(
            mode="git",
            available=True,
            summary=f"{count} update commit(s) available.",
            commits=commits,
        )

    def apply(self) -> str:
        if not self.development_mode:
            raise UpdateError("Packaged updates require a published Windows release asset.")
        assert self.root is not None
        branch = _run_git(self.root, "branch", "--show-current")
        if branch != UPDATE_BRANCH:
            raise UpdateError(f"Switch to {UPDATE_BRANCH} before updating.")
        if _run_git(self.root, "status", "--porcelain"):
            raise UpdateError("Tracked local changes must be committed or stashed first.")
        output = _run_git(
            self.root, "pull", "--ff-only", "origin", UPDATE_BRANCH
        )
        return output or "Update applied. Restart Intrader."

    def _check_release(self) -> UpdateStatus:
        req = request.Request(
            LATEST_RELEASE_API,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "Intrader",
            },
        )
        try:
            with request.urlopen(req, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (error.URLError, TimeoutError, ValueError):
            raise UpdateError("GitHub release check failed") from None
        tag = str(payload.get("tag_name") or "").strip()
        url = str(payload.get("html_url") or "").strip() or None
        if not tag:
            return UpdateStatus("release", False, "No packaged release is published yet.")
        return UpdateStatus(
            mode="release",
            available=True,
            summary=f"Packaged release {tag} is available.",
            remote_version=tag,
            release_url=url,
        )

    def open_release(self, url: str) -> None:
        if not url:
            raise UpdateError("Release URL unavailable")
        import webbrowser
        if not webbrowser.open(url):
            raise UpdateError("Could not open release page")
