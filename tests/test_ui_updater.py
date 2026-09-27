from pathlib import Path
import zipfile

import pytest

from intrader.ui import updater


def test_version_key_handles_release_tags() -> None:
    assert updater._version_key("v0.4.1") == (0, 4, 1)
    assert updater._version_key("0.5.0-beta") == (0, 5, 0)
    assert updater._version_key("bad") is None


def test_development_update_requires_phase4_branch(monkeypatch, tmp_path) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(updater, "_run_git", lambda _root, *args: "intrader-phase3" if args == ("branch", "--show-current") else "")
    service = updater.UpdateService(root=tmp_path)

    status = service.check()

    assert status.available is False
    assert "intrader-phase4" in status.summary



def test_packaged_update_rejects_zip_path_traversal(tmp_path) -> None:
    archive = tmp_path / "unsafe.zip"
    staging = tmp_path / "staging"
    staging.mkdir()

    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.txt", "unsafe")

    with pytest.raises(updater.UpdateError, match="unsafe path"):
        updater._safe_extract_zip(archive, staging)

    assert not (tmp_path / "outside.txt").exists()


def test_git_error_includes_stderr(monkeypatch, tmp_path) -> None:
    def fail(*_args, **_kwargs):
        raise updater.subprocess.CalledProcessError(
            1,
            ["git", "merge"],
            stderr="fatal: Not possible to fast-forward, aborting.",
        )

    monkeypatch.setattr(updater.subprocess, "run", fail)

    with pytest.raises(
        updater.UpdateError,
        match="Not possible to fast-forward",
    ):
        updater._run_git(tmp_path, "merge", "--ff-only", "origin/intrader-phase4")


def test_apply_git_refuses_local_only_commits(monkeypatch, tmp_path) -> None:
    (tmp_path / ".git").mkdir()
    calls = []

    def fake_run(_root, *args):
        calls.append(args)
        if args == ("branch", "--show-current"):
            return updater.UPDATE_BRANCH
        if args == ("status", "--porcelain"):
            return ""
        if args == ("fetch", "origin", updater.UPDATE_BRANCH):
            return ""
        if args == (
            "rev-list",
            "--count",
            f"origin/{updater.UPDATE_BRANCH}..HEAD",
        ):
            return "1"
        if args == (
            "rev-list",
            "--count",
            f"HEAD..origin/{updater.UPDATE_BRANCH}",
        ):
            return "3"
        raise AssertionError(args)

    monkeypatch.setattr(updater, "_run_git", fake_run)
    service = updater.UpdateService(root=tmp_path)

    with pytest.raises(updater.UpdateError, match="not present on GitHub"):
        service.apply()

    assert not any(args and args[0] == "merge" for args in calls)


def test_apply_git_fast_forwards_clean_checkout(monkeypatch, tmp_path) -> None:
    (tmp_path / ".git").mkdir()

    def fake_run(_root, *args):
        if args == ("branch", "--show-current"):
            return updater.UPDATE_BRANCH
        if args == ("status", "--porcelain"):
            return ""
        if args == ("fetch", "origin", updater.UPDATE_BRANCH):
            return ""
        if args == (
            "rev-list",
            "--count",
            f"origin/{updater.UPDATE_BRANCH}..HEAD",
        ):
            return "0"
        if args == (
            "rev-list",
            "--count",
            f"HEAD..origin/{updater.UPDATE_BRANCH}",
        ):
            return "2"
        if args == (
            "merge",
            "--ff-only",
            f"origin/{updater.UPDATE_BRANCH}",
        ):
            return "Updating abc..def"
        raise AssertionError(args)

    monkeypatch.setattr(updater, "_run_git", fake_run)
    service = updater.UpdateService(root=tmp_path)

    result = service.apply()

    assert result.restart_required is True
    assert "Updating" in result.message
