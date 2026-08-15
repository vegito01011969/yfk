from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REMOTE_DIR = Path("/content/viral_pipeline_download")
JOB_PATH = REMOTE_DIR / "job.json"
RESULT_ZIP = REMOTE_DIR / "result.zip"
RESULT_JSON = REMOTE_DIR / "result.json"


def _write_result(status: str, **payload: object) -> None:
    RESULT_JSON.write_text(
        json.dumps({"status": status, **payload}, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_archive(downloads_dir: Path) -> None:
    with zipfile.ZipFile(RESULT_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if RESULT_JSON.exists():
            archive.write(RESULT_JSON, RESULT_JSON.name)
        for path in downloads_dir.iterdir():
            if path.is_file():
                archive.write(path, path.name)


def main() -> None:
    job = json.loads(JOB_PATH.read_text(encoding="utf-8"))
    downloads_dir = REMOTE_DIR / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)

    install_commands = [
        [sys.executable, "-m", "pip", "install", "--upgrade", job["yt_dlp_requirement"]],
        [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp-getpot-wpc==1.0.0"],
    ]
    for install_command in install_commands:
        result = subprocess.run(install_command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            _write_result(
                "install_failed",
                command=install_command,
                returncode=result.returncode,
                stdout=result.stdout[-4000:],
                stderr=result.stderr[-4000:],
            )
            _write_archive(downloads_dir)
            return

    output_template = downloads_dir / f"{job['video_id']}.%(ext)s"
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--restrict-filenames",
        "--write-info-json",
        "--merge-output-format",
        "mp4",
        "-f",
        job["format"],
        "-o",
        str(output_template),
    ]

    cookies_path = REMOTE_DIR / "cookies.txt"
    if cookies_path.exists():
        command.extend(["--cookies", str(cookies_path)])
    if job.get("js_runtimes"):
        command.extend(["--js-runtimes", str(job["js_runtimes"])])
    extractor_args_values = job.get("extractor_args") or [
        "youtube:player_client=mweb,web_safari,web_embedded,tv_simply,android_vr"
    ]
    chrome_path = (
        shutil.which("google-chrome")
        or shutil.which("chromium")
        or shutil.which("chromium-browser")
    )
    if chrome_path:
        extractor_args_values.append(f"youtubepot-wpc:browser_path={chrome_path}")
    for extractor_args in extractor_args_values:
        command.extend(["--extractor-args", str(extractor_args)])
    if job.get("verbose"):
        command.append("--verbose")
    command.append(job["url"])

    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        _write_result(
            "download_failed",
            command=command,
            returncode=result.returncode,
            stdout=result.stdout[-8000:],
            stderr=result.stderr[-8000:],
        )
        _write_archive(downloads_dir)
        return

    _write_result("ok", command=command)
    _write_archive(downloads_dir)


if __name__ == "__main__":
    main()
