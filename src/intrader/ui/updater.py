"""Safe GitHub update checks for development checkouts and packaged builds."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from urllib import error, request
import zipfile

from intrader import __version__

REPOSITORY = "KaranBarua01/Intrader"
UPDATE_BRANCH = "intrader-phase4"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
WINDOWS_ASSET = "Intrader-Windows-x64.zip"
WINDOWS_CHECKSUM_ASSET = WINDOWS_ASSET + ".sha256"


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
    asset_url: str | None = None
    checksum_url: str | None = None


@dataclass(frozen=True, slots=True)
class UpdateApplyResult:
    message: str
    restart_required: bool
    exit_to_install: bool = False


def _version_key(value: str) -> tuple[int, ...] | None:
    text = value.strip().lower().lstrip("v")
    core = text.split("-", 1)[0]
    try:
        return tuple(int(part) for part in core.split("."))
    except ValueError:
        return None


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


def _download(url: str, target: Path) -> None:
    req = request.Request(url, headers={"User-Agent": "Intrader"})
    try:
        with request.urlopen(req, timeout=60) as response:
            target.write_bytes(response.read())
    except (error.URLError, TimeoutError, OSError):
        raise UpdateError("Update download failed") from None


def _ps_quote(path: Path) -> str:
    return str(path).replace("'", "''")


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

    def apply(self) -> UpdateApplyResult:
        if self.development_mode:
            return self._apply_git()
        status = self._check_release()
        return self._prepare_packaged_update(status)

    def _apply_git(self) -> UpdateApplyResult:
        assert self.root is not None
        branch = _run_git(self.root, "branch", "--show-current")
        if branch != UPDATE_BRANCH:
            raise UpdateError(f"Switch to {UPDATE_BRANCH} before updating.")
        if _run_git(self.root, "status", "--porcelain"):
            raise UpdateError("Tracked local changes must be committed or stashed first.")
        output = _run_git(
            self.root, "pull", "--ff-only", "origin", UPDATE_BRANCH
        )
        return UpdateApplyResult(
            output or "Update applied.",
            restart_required=True,
            exit_to_install=False,
        )

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
        release_url = str(payload.get("html_url") or "").strip() or None
        if not tag:
            return UpdateStatus("release", False, "No packaged release is published yet.")
        local_key = _version_key(__version__)
        remote_key = _version_key(tag)
        if local_key is not None and remote_key is not None and remote_key <= local_key:
            return UpdateStatus(
                "release", False, f"Intrader {__version__} is up to date.", remote_version=tag
            )
        assets = payload.get("assets") if isinstance(payload, dict) else None
        asset_url = None
        checksum_url = None
        if isinstance(assets, list):
            for asset in assets:
                if not isinstance(asset, dict):
                    continue
                name = str(asset.get("name") or "")
                url = str(asset.get("browser_download_url") or "") or None
                if name == WINDOWS_ASSET:
                    asset_url = url
                elif name == WINDOWS_CHECKSUM_ASSET:
                    checksum_url = url
        if not asset_url or not checksum_url:
            return UpdateStatus(
                mode="release",
                available=False,
                summary=f"Release {tag} exists but its verified Windows update package is not available.",
                remote_version=tag,
                release_url=release_url,
            )
        return UpdateStatus(
            mode="release",
            available=True,
            summary=f"Intrader {tag} is available.",
            remote_version=tag,
            release_url=release_url,
            asset_url=asset_url,
            checksum_url=checksum_url,
        )

    def _prepare_packaged_update(self, status: UpdateStatus) -> UpdateApplyResult:
        if not status.available or not status.asset_url or not status.checksum_url:
            raise UpdateError(status.summary or "No packaged update is available.")
        if os.name != "nt" or not getattr(sys, "frozen", False):
            raise UpdateError("Packaged self-update is supported only by the Windows executable.")

        temp_root = Path(tempfile.mkdtemp(prefix="intrader-update-"))
        archive = temp_root / WINDOWS_ASSET
        checksum_file = temp_root / WINDOWS_CHECKSUM_ASSET
        staging = temp_root / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        _download(status.asset_url, archive)
        _download(status.checksum_url, checksum_file)
        expected = checksum_file.read_text(encoding="utf-8").strip().split()[0].lower()
        actual = hashlib.sha256(archive.read_bytes()).hexdigest().lower()
        if not expected or actual != expected:
            raise UpdateError("Downloaded update failed SHA-256 verification.")
        try:
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(staging)
        except (OSError, zipfile.BadZipFile):
            raise UpdateError("Downloaded update package is invalid.") from None

        app_dir = Path(sys.executable).resolve().parent
        executable = app_dir / Path(sys.executable).name
        script = temp_root / "apply-update.ps1"
        source_q = _ps_quote(staging)
        target_q = _ps_quote(app_dir)
        exe_q = _ps_quote(executable)
        script.write_text(
            "\n".join(
                [
                    "param([int]$PidToWait)",
                    "$ErrorActionPreference = \"Stop\"",
                    "try { Wait-Process -Id $PidToWait -ErrorAction SilentlyContinue } catch {}",
                    "Start-Sleep -Milliseconds 700",
                    f"$source = '{source_q}'",
                    f"$target = '{target_q}'",
                    "Get-ChildItem -LiteralPath $source -Force | ForEach-Object {",
                    "    Copy-Item -LiteralPath $_.FullName -Destination $target -Recurse -Force",
                    "}",
                    f"Start-Process -FilePath '{exe_q}'",
                ]
            ),
            encoding="utf-8",
        )
        flags = 0
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        if hasattr(subprocess, "DETACHED_PROCESS"):
            flags |= subprocess.DETACHED_PROCESS
        try:
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-PidToWait",
                    str(os.getpid()),
                ],
                creationflags=flags,
                close_fds=True,
            )
        except OSError:
            raise UpdateError("Could not launch the Windows update helper.") from None
        return UpdateApplyResult(
            f"Intrader {status.remote_version} verified and staged. The app will close, update, and relaunch.",
            restart_required=True,
            exit_to_install=True,
        )
