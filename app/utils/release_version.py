"""Read a checkout's release identity without invoking Git or reading its config.

Only ordinary .git directories and reciprocal linked-worktree metadata are
supported. Missing, malformed, redirected or oversized metadata is unknown.
This identifies the checkout's HEAD, not the identity of already loaded code.
"""
from __future__ import annotations

from pathlib import Path, PureWindowsPath
import re
import stat


_SMALL_LIMIT = 4096
_PACKED_LIMIT = 1024 * 1024
_SHA = re.compile(r"[0-9a-fA-F]{40}\Z")
_REF_PART = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\Z")
_REF_FORBIDDEN = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]")


def _line(text: str) -> str:
    value = text.removesuffix("\r\n") if text.endswith("\r\n") else text.removesuffix("\n")
    if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("invalid metadata line")
    return value


def _local_path(value: str) -> Path:
    if (not value or len(value) > _SMALL_LIMIT or value.startswith(("\\\\", "//"))
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError("invalid local path")
    windows = PureWindowsPath(value)
    if windows.drive and not windows.root:
        raise ValueError("drive-relative path")
    return Path(value)


def _read(path: Path, owner: Path, limit: int = _SMALL_LIMIT) -> str:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(owner):
        raise ValueError("metadata escapes owner")
    metadata = resolved.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
        raise ValueError("invalid metadata size or type")
    with resolved.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("metadata grew beyond limit")
    return data.decode("utf-8", errors="strict")


def _sha(value: str) -> str:
    if not _SHA.fullmatch(value) or value == "0" * 40:
        raise ValueError("invalid object id")
    return value.lower()


def _ref(value: str) -> str:
    parts = value.split("/")
    if (len(parts) < 3 or parts[0] != "refs" or len(value) > 1024
            or _REF_FORBIDDEN.search(value) or "@{" in value
            or any(not part or part.startswith(".") or ".." in part
                   or part.endswith((".", ".lock")) for part in parts)):
        raise ValueError("invalid reference name")
    return value


def _metadata_dirs(root: Path) -> tuple[Path, Path]:
    dotgit = root / ".git"
    if dotgit.is_dir():
        resolved = dotgit.resolve(strict=True)
        if resolved != dotgit:
            raise ValueError("redirected git directory")
        return resolved, resolved

    pointer = _line(_read(dotgit, root))
    if not pointer.startswith("gitdir: "):
        raise ValueError("invalid gitdir pointer")
    target = _local_path(pointer[len("gitdir: "):])
    admin = (root / target).resolve(strict=True)
    # A linked worktree may refer outside its checkout, but only to the
    # conventional common .git/worktrees/<entry> with a reciprocal backlink.
    if (not admin.is_dir() or admin.parent.name != "worktrees"
            or admin.parent.parent.name != ".git"
            or not _REF_PART.fullmatch(admin.name) or ".." in admin.name):
        raise ValueError("unsupported gitdir layout")
    expected_common = admin.parent.parent
    common_pointer = _local_path(_line(_read(admin / "commondir", admin)))
    common = (admin / common_pointer).resolve(strict=True)
    if common != expected_common or not common.is_dir():
        raise ValueError("invalid common git directory")
    backlink = _local_path(_line(_read(admin / "gitdir", admin)))
    if (admin / backlink).resolve(strict=True) != dotgit:
        raise ValueError("gitdir does not belong to checkout")
    return admin, common


def _packed_sha(common: Path, wanted: str) -> str:
    found = None
    can_peel = False
    for raw_line in _read(common / "packed-refs", common, _PACKED_LIMIT).splitlines(keepends=True):
        if raw_line in ("\n", "\r\n"):
            continue
        line = _line(raw_line)
        if line.startswith("#"):
            continue
        if len(line) > _SMALL_LIMIT:
            raise ValueError("oversize packed reference")
        if line.startswith("^"):
            if not can_peel:
                raise ValueError("orphan peeled object")
            _sha(line[1:])
            can_peel = False
            continue
        fields = line.split(" ")
        if len(fields) != 2:
            raise ValueError("invalid packed reference")
        object_id, name = _sha(fields[0]), _ref(fields[1])
        can_peel = True
        if name == wanted:
            if found is not None:
                raise ValueError("duplicate packed reference")
            found = object_id
    if found is None:
        raise ValueError("reference missing")
    return found


def get_release_version(project_root: str | Path) -> str:
    """Return twelve lowercase HEAD hex digits, or ``unknown`` on invalid metadata.

    Reads are capped at 4 KiB each (1 MiB total for packed-refs). No subprocess,
    environment, Git configuration, credentials, network or parent search is used.
    """
    try:
        root = _local_path(str(project_root)).resolve(strict=True)
        if not root.is_dir():
            return "unknown"
        admin, common = _metadata_dirs(root)
        head = _line(_read(admin / "HEAD", admin))
        if not head.startswith("ref: "):
            return _sha(head)[:12]
        name = _ref(head[len("ref: "):])
        try:
            object_id = _sha(_line(_read(common / name, common)))
        except FileNotFoundError:
            object_id = _packed_sha(common, name)
        return object_id[:12]
    except (OSError, ValueError, RuntimeError, TypeError):
        return "unknown"
