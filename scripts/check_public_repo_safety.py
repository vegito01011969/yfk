"""Fail when tracked files or Git history contain likely credentials."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SENSITIVE_PATH_PATTERNS = (
    re.compile(r"(^|/)\.env(?:\.|$)"),
    re.compile(r"(^|/)(?:secrets|workdir|data)(?:/|$)"),
    re.compile(r"(^|/)(?:cookies\.txt|youtube_cookies\.txt)$"),
    re.compile(r"(^|/)(?:\.DS_Store|Thumbs\.db)$"),
    re.compile(r"\.(?:pem|key|p12|pfx|kdbx)$", re.IGNORECASE),
    re.compile(r"(?:oauth.*token|client.*secret|credential.*)\.json$", re.IGNORECASE),
)

SECRET_PATTERNS = (
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_-]{20,}")),
    ("OpenAI-style API key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}")),
    ("Google OAuth access token", re.compile(r"ya29\.[0-9A-Za-z_-]{20,}")),
    (
        "OAuth refresh token JSON",
        re.compile(r'''["']refresh_token["']\s*:\s*["'][^"'\s]{10,}["']'''),
    ),
    (
        "OAuth client secret JSON",
        re.compile(r'''["']client_secret["']\s*:\s*["'][^"'\s]{10,}["']'''),
    ),
    ("private key", re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")),
)


def _run_git(*args: str, text: bool = True) -> str | bytes:
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=text,
    ).stdout


def _is_sensitive_path(path: str) -> bool:
    normalized = Path(path).as_posix()
    if normalized == ".env.example":
        return False
    return any(pattern.search(normalized) for pattern in SENSITIVE_PATH_PATTERNS)


def _tracked_paths() -> list[str]:
    output = _run_git("ls-files", "-z", text=False)
    assert isinstance(output, bytes)
    return [path.decode("utf-8") for path in output.split(b"\0") if path]


def _history_blob_ids() -> set[str]:
    output = _run_git("rev-list", "--objects", "--all")
    assert isinstance(output, str)
    return {line.split(maxsplit=1)[0] for line in output.splitlines() if line}


def _is_probably_text(content: bytes) -> bool:
    if b"\0" in content:
        return False
    return len(content) <= 2_000_000


def _scan_history() -> list[str]:
    findings: list[str] = []
    for object_id in _history_blob_ids():
        object_type = _run_git("cat-file", "-t", object_id).strip()
        if object_type != "blob":
            continue
        content = _run_git("cat-file", "blob", object_id, text=False)
        assert isinstance(content, bytes)
        if not _is_probably_text(content):
            continue
        text = content.decode("utf-8", errors="ignore")
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(f"{label} in reachable history blob {object_id[:12]}")
    return findings


def _scan_worktree(paths: list[str]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        try:
            content = Path(path).read_bytes()
        except OSError:
            continue
        if not _is_probably_text(content):
            continue
        text = content.decode("utf-8", errors="ignore")
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(f"{label} in tracked working-tree file {path}")
    return findings


def main() -> int:
    paths = _tracked_paths()
    findings = [
        f"sensitive path is tracked: {path}"
        for path in paths
        if _is_sensitive_path(path)
    ]
    findings.extend(_scan_worktree(paths))
    findings.extend(_scan_history())
    if findings:
        print("Public-repository safety check failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("Public-repository safety check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
