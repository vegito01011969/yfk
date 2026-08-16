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


def main() -> None:
    attempts = max(1, int(os.environ.get("PIPELINE_UPLOAD_ATTEMPTS", "3")))
    require_upload = os.environ.get("PIPELINE_REQUIRE_UPLOAD", "false").lower() == "true"
    attempt_timeout = max(60, int(os.environ.get("PIPELINE_ATTEMPT_TIMEOUT_SECONDS", "1800")))
    last_return_code = 0
    last_status: str | None = None
    last_reason: str | None = None

    for attempt in range(1, attempts + 1):
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
        if last_return_code == 0 and last_status == "uploaded":
            return

    if require_upload:
        reason = f" Last skip reason: {last_reason}." if last_reason else ""
        raise SystemExit(
            f"No video was uploaded after {attempts} pipeline attempt(s). "
            f"Last upload status: {last_status or 'unknown'}.{reason}"
        )
    if last_return_code:
        raise SystemExit(last_return_code)


if __name__ == "__main__":
    main()
