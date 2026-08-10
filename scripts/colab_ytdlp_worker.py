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


def main() -> None:
    job = json.loads(JOB_PATH.read_text(encoding="utf-8"))
    downloads_dir = REMOTE_DIR / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", job["yt_dlp_requirement"]],
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp-getpot-wpc==1.0.0"],
        check=True,
    )

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

    subprocess.run(command, check=True)

    with zipfile.ZipFile(RESULT_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in downloads_dir.iterdir():
            if path.is_file():
                archive.write(path, path.name)


if __name__ == "__main__":
    main()
