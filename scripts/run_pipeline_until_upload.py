from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

from summarize_pipeline_run import _read_json


def _latest_context() -> dict:
    paths = sorted(
        Path("workdir/runs").glob("*/context.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return _read_json(paths[0]) if paths else {}


def _upload_status(context: dict) -> tuple[str | None, str | None]:
    upload = context.get("youtube_upload") or {}
    if not isinstance(upload, dict):
        return None, None
    metadata = upload.get("metadata") or {}
    reason = metadata.get("reason") if isinstance(metadata, dict) else None
    return upload.get("status"), reason


def _download_auth_blocked(context: dict) -> tuple[bool, str | None]:
    summary = context.get("metadata", {}).get("download_summary") or {}
    if not isinstance(summary, dict):
        return False, None
    failure_counts = summary.get("failure_counts") or {}
    attempted = int(summary.get("attempted_count") or 0)
    downloaded = int(summary.get("downloaded_count") or 0)
    failed = int(summary.get("failed_count") or 0)
    bot_wall = int(failure_counts.get("youtube_bot_wall") or 0)
    challenge_failed = int(failure_counts.get("youtube_challenge_failed") or 0)
    if attempted and downloaded == 0 and failed and bot_wall == failed:
        return (
            True,
            (
                "All attempted yt-dlp downloads hit YouTube's bot-check wall. "
                "The current cookies/auth context is not accepted from the Colab runtime."
            ),
        )
    if attempted and downloaded == 0 and failed and challenge_failed == failed:
        return (
            True,
            (
                "All attempted yt-dlp downloads failed YouTube's JS/PO-token challenge. "
                "The Colab runtime cannot currently solve YouTube extraction challenges."
            ),
        )
    return False, None


def main() -> None:
    attempts = max(1, int(os.environ.get("PIPELINE_UPLOAD_ATTEMPTS", "3")))
    require_upload = os.environ.get("PIPELINE_REQUIRE_UPLOAD", "false").lower() == "true"
    attempt_timeout = max(60, int(os.environ.get("PIPELINE_ATTEMPT_TIMEOUT_SECONDS", "1800")))
    last_return_code = 0
    last_status: str | None = None
    last_reason: str | None = None
    attempts_run = 0

    for attempt in range(1, attempts + 1):
        attempts_run = attempt
        attempt_reason: str | None = None
        print(f"Pipeline attempt {attempt}/{attempts}")
        process = subprocess.Popen(
            ["viral-pipeline", "run", "--no-resume"],
            start_new_session=True,
        )
        try:
            last_return_code = process.wait(timeout=attempt_timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            last_return_code = 124
            attempt_reason = f"Pipeline attempt exceeded {attempt_timeout}s"
        context = _latest_context()
        last_status, context_reason = _upload_status(context)
        last_reason = attempt_reason or context_reason
        print(f"Pipeline attempt {attempt} exit={last_return_code} upload_status={last_status}")
        if last_reason:
            print(f"Upload skip reason: {last_reason}")
        auth_blocked, auth_reason = _download_auth_blocked(context)
        if auth_blocked:
            last_reason = auth_reason
            print(f"Download auth blocked: {auth_reason}")
            break
        if last_return_code == 0 and last_status == "uploaded":
            return

    if require_upload:
        reason = f" Last skip reason: {last_reason}." if last_reason else ""
        raise SystemExit(
            f"No video was uploaded after {attempts_run} pipeline attempt(s). "
            f"Last upload status: {last_status or 'unknown'}.{reason}"
        )
    if last_return_code:
        raise SystemExit(last_return_code)


if __name__ == "__main__":
    main()
