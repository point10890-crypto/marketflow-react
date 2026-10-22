"""Release identity comes from bounded, project-owned Git metadata only."""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest


SHA = "a1b2c3d4e5f678901234567890abcdef12345678"
OTHER_SHA = "0123456789abcdef0123456789abcdef01234567"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="ascii")


def _repo(tmp_path: Path, head: str = SHA + "\n") -> Path:
    root = tmp_path / "project"
    _write(root / ".git" / "HEAD", head)
    return root


def _version(root: Path) -> str:
    return importlib.import_module("app.utils.release_version").get_release_version(root)


def _worktree(tmp_path: Path, *, relative: bool = False) -> tuple[Path, Path, Path]:
    common = tmp_path / "main" / ".git"
    admin = common / "worktrees" / "feature"
    checkout = tmp_path / "checkout"
    pointer = "../main/.git/worktrees/feature" if relative else admin.as_posix()
    _write(checkout / ".git", "gitdir: " + pointer + "\n")
    _write(admin / "gitdir", (checkout / ".git").as_posix() + "\n")
    _write(admin / "commondir", "../..\n")
    _write(admin / "HEAD", "ref: refs/heads/feature\n")
    return checkout, admin, common


def test_detached_head_is_exactly_twelve_lowercase_hex_characters(tmp_path):
    root = _repo(tmp_path, SHA.upper() + "\n")
    assert _version(root) == "a1b2c3d4e5f6"


def test_symbolic_head_uses_owned_loose_ref(tmp_path):
    root = _repo(tmp_path, "ref: refs/heads/codex/release\n")
    _write(root / ".git" / "refs/heads/codex/release", SHA + "\n")
    assert _version(root) == "a1b2c3d4e5f6"


def test_packed_ref_resolves_exact_name_and_accepts_peeled_tags(tmp_path):
    root = _repo(tmp_path, "ref: refs/heads/release\n")
    _write(root / ".git" / "packed-refs", (
        "# pack-refs with: peeled fully-peeled sorted\n"
        + OTHER_SHA + " refs/heads/release-extra\n"
        + SHA + " refs/heads/release\n"
        + OTHER_SHA + " refs/tags/v1\n^" + SHA + "\n"
    ))
    assert _version(root) == "a1b2c3d4e5f6"


def test_loose_ref_wins_over_older_packed_ref(tmp_path):
    root = _repo(tmp_path, "ref: refs/heads/release\n")
    _write(root / ".git" / "refs/heads/release", SHA + "\n")
    _write(root / ".git" / "packed-refs", OTHER_SHA + " refs/heads/release\n")
    assert _version(root) == "a1b2c3d4e5f6"


def test_unrelated_unicode_packed_ref_does_not_hide_current_version(tmp_path):
    root = _repo(tmp_path, "ref: refs/heads/main\n")
    (root / ".git" / "packed-refs").write_text(
        SHA + " refs/heads/main\n" + OTHER_SHA + " refs/heads/한글\n", encoding="utf-8"
    )
    assert _version(root) == "a1b2c3d4e5f6"


def test_unicode_head_resolves_only_its_owned_ref(tmp_path):
    root = _repo(tmp_path)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/검증\n", encoding="utf-8")
    _write(root / ".git" / "refs/heads/검증", SHA + "\n")
    assert _version(root) == "a1b2c3d4e5f6"


@pytest.mark.parametrize("relative", [False, True])
@pytest.mark.parametrize("packed", [False, True])
def test_linked_worktree_checks_backpointer_and_common_refs(tmp_path, relative, packed):
    root, _, common = _worktree(tmp_path, relative=relative)
    path = common / "packed-refs" if packed else common / "refs/heads/feature"
    content = SHA + " refs/heads/feature\n" if packed else SHA + "\n"
    _write(path, content)
    assert _version(root) == "a1b2c3d4e5f6"


def test_linked_worktree_detached_head_is_read_from_its_own_admin_directory(tmp_path):
    root, admin, common = _worktree(tmp_path)
    _write(admin / "HEAD", SHA + "\n")
    _write(common / "HEAD", OTHER_SHA + "\n")
    assert _version(root) == "a1b2c3d4e5f6"


@pytest.mark.parametrize("head", [
    "", "abc123\n", SHA + "extra\n", SHA + "\n" + OTHER_SHA + "\n",
    "ref: refs/heads/../../outside\n", "ref: ../outside\n",
    "ref: /outside\n", "ref: C:/outside\n", "ref: refs\\heads\\main\n",
    "ref: refs/heads//main\n", "ref: refs/heads/.hidden\n",
    "ref: refs/heads/main.lock\n", "ref: refs/heads/main@{1}\n",
    "ref: refs/heads/main with-space\n", "ref: refs/heads/main\x00\n",
    "0" * 40 + "\n", "\xff\n", SHA + "\v", SHA + "\r", "x" * 5000,
], ids=lambda value: "head-" + str(len(value)))
def test_malformed_or_oversize_head_is_unknown(tmp_path, head):
    root = tmp_path / "project"
    path = root / ".git" / "HEAD"
    path.parent.mkdir(parents=True)
    path.write_bytes(head.encode("latin1"))
    assert _version(root) == "unknown"


@pytest.mark.parametrize("loose", ["bad\n", SHA + "\n" + OTHER_SHA, "x" * 5000],
                         ids=["invalid", "multiple", "oversize"])
def test_corrupt_loose_ref_does_not_fall_back_to_packed_value(tmp_path, loose):
    root = _repo(tmp_path, "ref: refs/heads/main\n")
    _write(root / ".git" / "refs/heads/main", loose)
    _write(root / ".git" / "packed-refs", SHA + " refs/heads/main\n")
    assert _version(root) == "unknown"


@pytest.mark.parametrize("packed", [
    "garbage\n", "bad refs/heads/main\n", SHA + " refs/heads/main extra\n",
    SHA + " refs/heads/main\n" + OTHER_SHA + " refs/heads/main\n",
    SHA + " refs/heads/main\n" + SHA + " refs/heads/main\n",
    SHA + " refs/heads/main\v", SHA + " refs/heads/main\r",
    "#" + "x" * (1024 * 1024),
], ids=["invalid", "invalid-sha", "extra-field", "conflicting", "duplicate",
        "vertical-tab", "bare-cr", "oversize"])
def test_malformed_duplicate_or_oversize_packed_refs_is_unknown(tmp_path, packed):
    root = _repo(tmp_path, "ref: refs/heads/main\n")
    _write(root / ".git" / "packed-refs", packed)
    assert _version(root) == "unknown"


@pytest.mark.parametrize("kind", ["backpointer", "commondir", "outside", "oversize_pointer"])
def test_unowned_or_malformed_gitdir_pointer_is_unknown(tmp_path, kind):
    root, admin, common = _worktree(tmp_path)
    _write(common / "refs/heads/feature", SHA + "\n")
    if kind == "backpointer":
        _write(admin / "gitdir", (tmp_path / "other" / ".git").as_posix() + "\n")
    elif kind == "commondir":
        _write(admin / "commondir", "../../../outside\n")
    elif kind == "outside":
        _write(root / ".git", "gitdir: ../outside\n")
        _write(tmp_path / "outside" / "HEAD", SHA + "\n")
    else:
        _write(root / ".git", "gitdir: " + "x" * 5000)
    assert _version(root) == "unknown"


def test_missing_repository_or_unborn_ref_is_unknown(tmp_path):
    assert _version(tmp_path / "absent") == "unknown"
    root = _repo(tmp_path, "ref: refs/heads/unborn\n")
    assert _version(root) == "unknown"


def test_ref_symlink_cannot_read_outside_project_metadata(tmp_path):
    root = _repo(tmp_path, "ref: refs/heads/main\n")
    target = tmp_path / "outside"
    _write(target, SHA + "\n")
    ref = root / ".git" / "refs/heads/main"
    ref.parent.mkdir(parents=True)
    try:
        ref.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is not available")
    assert _version(root) == "unknown"


def test_resolution_does_not_read_git_config_or_environment(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    _write(root / ".git" / "config", "forbidden")
    import os
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        assert path.name != "config", "Git configuration must not be read"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(os, "getenv", lambda *args, **kwargs: pytest.fail("environment read"))
    assert _version(root) == "a1b2c3d4e5f6"


def test_health_version_works_without_invoking_git(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    import app as app_module
    import dotenv
    import subprocess

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    app = app_module.create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_ENGINE_OPTIONS": {},
    })
    monkeypatch.setattr(app_module, "__file__", str(root / "app" / "__init__.py"))
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("health must not invoke Git")
    ))
    response = app.test_client().get("/api/health")
    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok", "service": "MarketFlow API", "version": "a1b2c3d4e5f6",
        "data": {"signals_log": False},
    }
