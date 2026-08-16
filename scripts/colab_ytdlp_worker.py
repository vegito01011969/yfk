from __future__ import annotations

import json
import os
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


def _run_best_effort(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def _install_deno() -> Path | None:
    existing = shutil.which("deno")
    if existing:
        return Path(existing)
    result = _run_best_effort(
        [
            "bash",
            "-lc",
            "curl -fsSL https://deno.land/install.sh | sh -s -- -y",
        ]
    )
    deno_path = Path.home() / ".deno" / "bin" / "deno"
    if result.returncode == 0 and deno_path.exists():
        os.environ["PATH"] = f"{deno_path.parent}:{os.environ.get('PATH', '')}"
        return deno_path
    return None


def _install_chrome() -> Path | None:
    existing = _chrome_path()
    if existing:
        return Path(existing)
    result = _run_best_effort(
        [
            "bash",
            "-lc",
            (
                "set -e; "
                "wget -q -O /tmp/google-chrome-stable_current_amd64.deb "
                "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb; "
                "apt-get update -y >/tmp/chrome-apt-update.log 2>&1; "
                "apt-get install -y /tmp/google-chrome-stable_current_amd64.deb "
                ">/tmp/chrome-apt-install.log 2>&1"
            ),
        ]
    )
    if result.returncode == 0:
        existing = _chrome_path()
        if existing:
            return Path(existing)
    return None


def _chrome_path() -> str | None:
    return (
        shutil.which("google-chrome")
        or shutil.which("google-chrome-stable")
        or shutil.which("chromium")
        or shutil.which("chromium-browser")
    )


def _js_runtime_arg(configured: object, deno_path: Path | None) -> str | None:
    configured_text = str(configured or "").strip()
    if deno_path:
        deno_arg = f"deno:{deno_path}"
        if not configured_text:
            return deno_arg
        if "deno" not in configured_text:
            return f"{deno_arg},{configured_text}"
    return configured_text or None


def main() -> None:
    job = json.loads(JOB_PATH.read_text(encoding="utf-8"))
    downloads_dir = REMOTE_DIR / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)

    enable_browser_po_token = bool(job.get("enable_browser_po_token"))
    install_commands = [
        [sys.executable, "-m", "pip", "install", "--upgrade", job["yt_dlp_requirement"]],
    ]
    if enable_browser_po_token:
        install_commands.append(
            [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp-getpot-wpc==1.0.0"]
        )
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

    deno_path = _install_deno()
    chrome_path = _install_chrome() if enable_browser_po_token else None
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
    js_runtime_arg = _js_runtime_arg(job.get("js_runtimes"), deno_path)
    if js_runtime_arg:
        command.extend(["--js-runtimes", js_runtime_arg])
    extractor_args_values = job.get("extractor_args") or [
        "youtube:player_client=mweb,web_safari,web_embedded,tv_simply,android_vr"
    ]
    if enable_browser_po_token and chrome_path:
        extractor_args_values.append(f"youtubepot-wpc:browser_path={chrome_path}")
    for extractor_args in extractor_args_values:
        command.extend(["--extractor-args", str(extractor_args)])
    if job.get("verbose"):
        command.append("--verbose")
    command.append(job["url"])

    timeout_seconds = int(job.get("download_timeout_seconds") or 240)
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        _write_result(
            "download_timeout",
            command=command,
            deno_path=str(deno_path) if deno_path else None,
            chrome_path=str(chrome_path) if chrome_path else None,
            timeout_seconds=timeout_seconds,
            stdout=str(exc.stdout or "")[-8000:],
            stderr=str(exc.stderr or "")[-8000:],
        )
        _write_archive(downloads_dir)
        return
    if result.returncode != 0:
        _write_result(
            "download_failed",
            command=command,
            deno_path=str(deno_path) if deno_path else None,
            chrome_path=str(chrome_path) if chrome_path else None,
            returncode=result.returncode,
            stdout=result.stdout[-8000:],
            stderr=result.stderr[-8000:],
        )
        _write_archive(downloads_dir)
        return

    _write_result(
        "ok",
        command=command,
        deno_path=str(deno_path) if deno_path else None,
        chrome_path=str(chrome_path) if chrome_path else None,
    )
    _write_archive(downloads_dir)


if __name__ == "__main__":
    main()
