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
