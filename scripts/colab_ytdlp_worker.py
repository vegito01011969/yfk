from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import zipfile
from importlib import util
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


def _wait_for_network(timeout_seconds: int) -> dict[str, object]:
    deadline = time.monotonic() + max(1, timeout_seconds)
    last_error = ""
    checks = 0
    while time.monotonic() < deadline:
        checks += 1
        try:
            socket.getaddrinfo("www.youtube.com", 443)
            with socket.create_connection(("www.youtube.com", 443), timeout=10):
                pass
            return {"ok": True, "checks": checks}
        except Exception as exc:
            last_error = repr(exc)
            time.sleep(5)
    return {
        "ok": False,
        "checks": checks,
        "timeout_seconds": timeout_seconds,
        "error": last_error,
    }


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


def _install_ytdlp_binary() -> Path | None:
    binary_path = REMOTE_DIR / "yt-dlp"
    result = _run_best_effort(
        [
            "bash",
            "-lc",
            (
                "set -e; "
                f"curl -fL --retry 3 -o {binary_path} "
                "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp; "
                f"chmod +x {binary_path}; "
                f"{binary_path} --version"
            ),
        ]
    )
    if result.returncode == 0 and binary_path.exists():
        return binary_path
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
        return f"deno:{deno_path}"
    return configured_text or None


def _patch_wpc_provider_for_colab() -> str | None:
    spec = util.find_spec("yt_dlp_plugins.extractor.getpot_wpc")
    if not spec or not spec.origin:
        return None
    provider_path = Path(spec.origin)
    text = provider_path.read_text(encoding="utf-8")
    patched = text
    if '"--no-sandbox"' not in patched:
        patched = patched.replace(
            "browser_args = []",
            (
                'browser_args = ["--no-sandbox", "--disable-dev-shm-usage", '
                '"--disable-gpu"]'
            ),
        )
    patched = patched.replace("headless=False,", "headless=True,")
    if patched != text:
        provider_path.write_text(patched, encoding="utf-8")
    return str(provider_path)


def _is_ejs_challenge_failure(text: str) -> bool:
    haystack = text.lower()
    return (
        "the page needs to be reloaded" in haystack
        or "challenge solving failed" in haystack
        or "challenge solver script distribution" in haystack
    )


def _download_one(
    *,
    video: dict[str, object],
    job: dict[str, object],
    downloads_dir: Path,
    ytdlp_binary_path: Path | None,
    deno_path: Path | None,
    chrome_path: Path | None,
    enable_browser_po_token: bool,
) -> dict[str, object]:
    video_id = str(video["id"])
    output_template = downloads_dir / f"{video_id}.%(ext)s"

    base_command = (
        [str(ytdlp_binary_path)]
        if ytdlp_binary_path
        else [sys.executable, "-m", "yt_dlp"]
    )
    base_command.extend(
        [
            "--no-playlist",
            "--restrict-filenames",
            "--write-info-json",
            "--merge-output-format",
            "mp4",
            "--retries",
            "10",
            "--fragment-retries",
            "10",
            "--socket-timeout",
            "20",
            "--retry-sleep",
            "exp=1:20",
            "-f",
            str(job["format"]),
            "-o",
            str(output_template),
        ]
    )

    cookies_path = REMOTE_DIR / "cookies.txt"
    if cookies_path.exists():
        base_command.extend(["--cookies", str(cookies_path)])
    js_runtime_arg = _js_runtime_arg(job.get("js_runtimes"), deno_path)
    if js_runtime_arg:
        base_command.extend(["--js-runtimes", js_runtime_arg])
    extractor_args_values = job.get("extractor_args") or [
        "youtube:player_client=tv_downgraded,tv_simply,web_embedded,android_vr,mweb,web_safari"
    ]
    if enable_browser_po_token and chrome_path:
        extractor_args_values.append(f"youtubepot-wpc:browser_path={chrome_path}")
    for extractor_args in extractor_args_values:
        base_command.extend(["--extractor-args", str(extractor_args)])
    if job.get("verbose"):
        base_command.append("--verbose")

    remote_component_attempts: list[list[str]] = [[]]
    remote_component_attempts.append(["--remote-components", "ejs:github"])
    if deno_path:
        remote_component_attempts.append(["--remote-components", "ejs:npm"])

    timeout_seconds = int(job.get("download_timeout_seconds") or 240)
    failures: list[dict[str, object]] = []
    for remote_component_args in remote_component_attempts:
        command = [*base_command, *remote_component_args, str(video["url"])]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "video_id": video_id,
                "status": "download_timeout",
                "command": command,
                "timeout_seconds": timeout_seconds,
                "stdout": str(exc.stdout or "")[-8000:],
                "stderr": str(exc.stderr or "")[-8000:],
                "attempts": failures,
            }

        if result.returncode == 0:
            return {
                "video_id": video_id,
                "status": "ok",
                "command": command,
                "remote_components": remote_component_args,
                "attempts": failures,
            }

        failure = {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
        }
        failures.append(failure)
        if not _is_ejs_challenge_failure(f"{result.stdout}\n{result.stderr}"):
            break

    stdout = "\n".join(str(failure.get("stdout") or "") for failure in failures)
    stderr = "\n".join(str(failure.get("stderr") or "") for failure in failures)
    attempt_summary = "attempts=" + ",".join(
        str(failure.get("command") or []) for failure in failures
    )
    return {
        "video_id": video_id,
        "status": "download_failed",
        "command": failures[-1].get("command") if failures else base_command,
        "returncode": failures[-1].get("returncode") if failures else None,
        "stdout": stdout[-8000:],
        "stderr": f"{stderr}\n{attempt_summary}"[-8000:],
        "attempts": failures,
    }


def main() -> None:
    job = json.loads(JOB_PATH.read_text(encoding="utf-8"))
    downloads_dir = REMOTE_DIR / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    videos = job.get("videos")
    if not isinstance(videos, list):
        videos = [{"id": job["video_id"], "url": job["url"]}]

    network_check = _wait_for_network(int(job.get("network_timeout_seconds") or 180))
    if not network_check.get("ok"):
        _write_result(
            "network_unavailable",
            network_check=network_check,
            successes=0,
            results=[
                {
                    "video_id": str(video.get("id") or ""),
                    "status": "network_unavailable",
                    "stderr": json.dumps(network_check, sort_keys=True),
                }
                for video in videos
                if isinstance(video, dict)
            ],
        )
        _write_archive(downloads_dir)
        return

    enable_browser_po_token = bool(job.get("enable_browser_po_token"))
    install_commands = []
    if not job.get("skip_yt_dlp_install"):
        install_commands.append(
            [sys.executable, "-m", "pip", "install", "--upgrade", job["yt_dlp_requirement"]]
        )
    if enable_browser_po_token:
        install_commands.append(
            [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp-getpot-wpc==1.1.2"]
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
    ytdlp_binary_path = _install_ytdlp_binary()
    chrome_path = _install_chrome() if enable_browser_po_token else None
    wpc_patch_path = _patch_wpc_provider_for_colab() if enable_browser_po_token else None

    max_successes = int(job.get("max_successes") or len(videos))
    batch_timeout_seconds = int(job.get("batch_timeout_seconds") or 0)
    batch_started_at = time.monotonic()
    results: list[dict[str, object]] = []
    successes = 0
    for video in videos:
        if not isinstance(video, dict):
            continue
        if (
            batch_timeout_seconds
            and time.monotonic() - batch_started_at >= batch_timeout_seconds
        ):
            results.append(
                {
                    "status": "batch_timeout",
                    "timeout_seconds": batch_timeout_seconds,
                }
            )
            break
        result = _download_one(
            video=video,
            job=job,
            downloads_dir=downloads_dir,
            ytdlp_binary_path=ytdlp_binary_path,
            deno_path=deno_path,
            chrome_path=chrome_path,
            enable_browser_po_token=enable_browser_po_token,
        )
        results.append(result)
        if result.get("status") == "ok":
            successes += 1
        if successes >= max_successes:
            break

    _write_result(
        "ok" if successes else "download_failed",
        deno_path=str(deno_path) if deno_path else None,
        ytdlp_binary_path=str(ytdlp_binary_path) if ytdlp_binary_path else None,
        chrome_path=str(chrome_path) if chrome_path else None,
        network_check=network_check,
        wpc_patch_path=wpc_patch_path,
        successes=successes,
        results=results,
    )
    _write_archive(downloads_dir)


if __name__ == "__main__":
    main()
