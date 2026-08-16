from __future__ import annotations

import os
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
    last_return_code = 0
    last_status: str | None = None
    last_reason: str | None = None

    for attempt in range(1, attempts + 1):
        print(f"Pipeline attempt {attempt}/{attempts}")
        completed = subprocess.run(["viral-pipeline", "run", "--no-resume"], check=False)
        last_return_code = completed.returncode
        context = _latest_context()
        last_status, last_reason = _upload_status(context)
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
