#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ffprobe_json(path: Path) -> dict[str, Any]:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            (
                "format=format_name,duration,size,bit_rate:"
                "stream=index,codec_type,codec_name,width,height,avg_frame_rate,"
                "r_frame_rate,time_base,start_time,duration,bit_rate,pix_fmt,"
                "sample_rate,channels,channel_layout"
            ),
            "-of",
            "json",
            str(path),
        ]
    )
    return json.loads(result.stdout)


def parse_duration(payload: dict[str, Any]) -> float:
    return float(payload.get("format", {}).get("duration") or 0.0)


def metric_score(original: Path, derivative: Path, metric: str) -> float | None:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(original),
            "-i",
            str(derivative),
            "-filter_complex",
            (
                "[0:v]setpts=PTS-STARTPTS,scale=320:-2:flags=bicubic,"
                "fps=8,format=yuv420p[o];"
                "[1:v]setpts=PTS-STARTPTS,scale=320:-2:flags=bicubic,"
                "fps=8,format=yuv420p[d];"
                f"[o][d]{metric}"
            ),
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    text = result.stderr + result.stdout
    if metric == "ssim" and "All:" in text:
        try:
            return float(text.rsplit("All:", 1)[1].split(" ", 1)[0])
        except ValueError:
            return None
    if metric == "psnr" and "average:" in text:
        try:
            return float(text.rsplit("average:", 1)[1].split(" ", 1)[0])
        except ValueError:
            return None
    return None


def frame_md5(path: Path, tmpdir: Path, label: str) -> str:
    output = tmpdir / f"{label}.framemd5"
    run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-an",
            "-f",
            "framemd5",
            str(output),
        ]
    )
    return sha256(output)


def audio_md5(path: Path, tmpdir: Path, label: str) -> str | None:
    output = tmpdir / f"{label}.audiomd5"
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-vn",
            "-f",
            "framemd5",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not output.exists():
        return None
    return sha256(output)


def build_report(original: Path, derivative: Path) -> dict[str, Any]:
    original_probe = ffprobe_json(original)
    derivative_probe = ffprobe_json(derivative)
    original_duration = parse_duration(original_probe)
    derivative_duration = parse_duration(derivative_probe)
    with tempfile.TemporaryDirectory(prefix="video_compare_") as tmp:
        tmpdir = Path(tmp)
        original_frame_md5 = frame_md5(original, tmpdir, "original")
        derivative_frame_md5 = frame_md5(derivative, tmpdir, "derivative")
        original_audio_md5 = audio_md5(original, tmpdir, "original")
        derivative_audio_md5 = audio_md5(derivative, tmpdir, "derivative")

    return {
        "original": str(original),
        "derivative": str(derivative),
        "file_sha256": {
            "original": sha256(original),
            "derivative": sha256(derivative),
            "same": sha256(original) == sha256(derivative),
        },
        "decoded_stream_hashes": {
            "video_framemd5_sha256": {
                "original": original_frame_md5,
                "derivative": derivative_frame_md5,
                "same": original_frame_md5 == derivative_frame_md5,
            },
            "audio_framemd5_sha256": {
                "original": original_audio_md5,
                "derivative": derivative_audio_md5,
                "same": original_audio_md5 == derivative_audio_md5,
            },
        },
        "probe": {
            "original": original_probe,
            "derivative": derivative_probe,
        },
        "duration": {
            "original_seconds": original_duration,
            "derivative_seconds": derivative_duration,
            "delta_seconds": abs(original_duration - derivative_duration),
        },
        "perceptual_metrics_sampled": {
            "ssim": metric_score(original, derivative, "ssim"),
            "psnr_db": metric_score(original, derivative, "psnr"),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare an original video with a transformed derivative."
    )
    parser.add_argument("original", type=Path)
    parser.add_argument("derivative", type=Path)
    parser.add_argument("--output", "-o", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    original = args.original.expanduser().resolve()
    derivative = args.derivative.expanduser().resolve()
    report = build_report(original, derivative)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.expanduser().resolve().write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
