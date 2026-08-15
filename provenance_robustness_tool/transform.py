#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MAX_ATTEMPTS = 3
MIN_SSIM_SAMPLE = 0.78


@dataclass(frozen=True)
class VideoInfo:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    video_codec: str | None
    audio_codec: str | None


@dataclass(frozen=True)
class TransformPlan:
    seed: int
    attempt: int
    profile: str
    crop_left: int
    crop_top: int
    crop_width: int
    crop_height: int
    output_width: int
    output_height: int
    working_width: int
    working_height: int
    rotate_degrees: float
    fps: float
    brightness: float
    contrast: float
    saturation: float
    gamma: float
    hue_degrees: float
    denoise_luma: float
    denoise_chroma: float
    noise_strength: int
    grain_mix_frames: int
    unsharp_amount: float
    speed: float
    audio_volume_db: float
    audio_highpass_hz: int
    audio_lowpass_hz: int
    audio_compressor_threshold_db: float
    audio_compressor_ratio: float
    audio_eq_frequency_hz: int
    audio_eq_gain_db: float
    crf: int
    preset: str
    video_bitrate: str | None
    audio_bitrate: str
    gop: int
    bframes: int
    refs: int
    aq_strength: float
    video_track_timescale: int
    movflags: str


@dataclass(frozen=True)
class TransformProfile:
    name: str
    crop_pct_range: tuple[float, float]
    rotate_abs_max: float
    fps_jitter_choices: tuple[float, ...]
    speed_range: tuple[float, float]
    brightness_range: tuple[float, float]
    contrast_range: tuple[float, float]
    saturation_range: tuple[float, float]
    gamma_range: tuple[float, float]
    hue_abs_max: float
    denoise_luma_range: tuple[float, float]
    denoise_chroma_range: tuple[float, float]
    noise_strength_range: tuple[int, int]
    unsharp_range: tuple[float, float]
    crf_range: tuple[int, int]


PROFILES = (
    TransformProfile(
        name="perceptual_close",
        crop_pct_range=(0.004, 0.014),
        rotate_abs_max=0.08,
        fps_jitter_choices=(-0.12, -0.06, 0.0, 0.06, 0.12),
        speed_range=(0.9985, 1.0015),
        brightness_range=(-0.008, 0.008),
        contrast_range=(0.99, 1.018),
        saturation_range=(0.99, 1.025),
        gamma_range=(0.992, 1.012),
        hue_abs_max=0.6,
        denoise_luma_range=(0.12, 0.42),
        denoise_chroma_range=(0.12, 0.36),
        noise_strength_range=(1, 2),
        unsharp_range=(0.06, 0.18),
        crf_range=(18, 22),
    ),
    TransformProfile(
        name="balanced_stress",
        crop_pct_range=(0.008, 0.024),
        rotate_abs_max=0.18,
        fps_jitter_choices=(-0.2, -0.1, 0.0, 0.1, 0.2),
        speed_range=(0.9975, 1.0025),
        brightness_range=(-0.012, 0.012),
        contrast_range=(0.985, 1.028),
        saturation_range=(0.985, 1.04),
        gamma_range=(0.99, 1.016),
        hue_abs_max=1.1,
        denoise_luma_range=(0.18, 0.62),
        denoise_chroma_range=(0.16, 0.52),
        noise_strength_range=(1, 3),
        unsharp_range=(0.08, 0.24),
        crf_range=(19, 24),
    ),
    TransformProfile(
        name="representation_heavy",
        crop_pct_range=(0.012, 0.032),
        rotate_abs_max=0.26,
        fps_jitter_choices=(-0.3, -0.2, -0.1, 0.1, 0.2, 0.3),
        speed_range=(0.9965, 1.0035),
        brightness_range=(-0.016, 0.016),
        contrast_range=(0.98, 1.035),
        saturation_range=(0.98, 1.05),
        gamma_range=(0.986, 1.02),
        hue_abs_max=1.6,
        denoise_luma_range=(0.25, 0.75),
        denoise_chroma_range=(0.2, 0.6),
        noise_strength_range=(2, 4),
        unsharp_range=(0.1, 0.28),
        crf_range=(20, 25),
    ),
)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"Missing required dependency: {name}")


def ffprobe_json(path: Path) -> dict[str, Any]:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate",
            "-of",
            "json",
            str(path),
        ]
    )
    return json.loads(result.stdout)


def parse_fps(value: str | None) -> float:
    if not value or value == "0/0":
        return 30.0
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        denominator_value = float(denominator)
        if denominator_value == 0:
            return 30.0
        return float(numerator) / denominator_value
    return float(value)


def inspect_video(path: Path) -> VideoInfo:
    payload = ffprobe_json(path)
    streams = payload.get("streams", [])
    video_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "video"), None
    )
    if not video_stream:
        raise ValueError("Input does not contain a video stream")
    audio_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"), None
    )
    duration = float(payload.get("format", {}).get("duration") or 0.0)
    if duration <= 0:
        raise ValueError("Could not determine input duration")
    fps = parse_fps(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate"))
    return VideoInfo(
        duration=duration,
        width=int(video_stream["width"]),
        height=int(video_stream["height"]),
        fps=max(1.0, min(fps, 120.0)),
        has_audio=audio_stream is not None,
        video_codec=video_stream.get("codec_name"),
        audio_codec=audio_stream.get("codec_name") if audio_stream else None,
    )


def even(value: int) -> int:
    return max(2, value - (value % 2))


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_plan(info: VideoInfo, seed: int, attempt: int) -> TransformPlan:
    rng = random.Random(seed + attempt * 7919)
    profile = rng.choices(
        PROFILES,
        weights=[0.25, 0.5, 0.25],
        k=1,
    )[0]
    crop_pct = rng.uniform(*profile.crop_pct_range)
    crop_x_total = even(int(info.width * crop_pct))
    crop_y_total = even(int(info.height * crop_pct))
    crop_left = even(rng.randint(0, max(0, crop_x_total)))
    crop_top = even(rng.randint(0, max(0, crop_y_total)))
    crop_width = even(info.width - crop_x_total)
    crop_height = even(info.height - crop_y_total)

    fps_jitter = rng.choice(profile.fps_jitter_choices)
    target_fps = max(12.0, min(60.0, round(info.fps + fps_jitter, 3)))
    speed = rng.uniform(*profile.speed_range)
    rotate_degrees = rng.uniform(-profile.rotate_abs_max, profile.rotate_abs_max)
    rotate_radians = abs(math.radians(rotate_degrees))
    overscan = 1.0 + abs(math.sin(rotate_radians)) + rng.uniform(0.006, 0.018)
    working_width = even(math.ceil(info.width * overscan))
    working_height = even(math.ceil(info.height * overscan))

    return TransformPlan(
        seed=seed,
        attempt=attempt,
        profile=profile.name,
        crop_left=crop_left,
        crop_top=crop_top,
        crop_width=crop_width,
        crop_height=crop_height,
        output_width=even(info.width),
        output_height=even(info.height),
        working_width=working_width,
        working_height=working_height,
        rotate_degrees=rotate_degrees,
        fps=target_fps,
        brightness=rng.uniform(*profile.brightness_range),
        contrast=rng.uniform(*profile.contrast_range),
        saturation=rng.uniform(*profile.saturation_range),
        gamma=rng.uniform(*profile.gamma_range),
        hue_degrees=rng.uniform(-profile.hue_abs_max, profile.hue_abs_max),
        denoise_luma=rng.uniform(*profile.denoise_luma_range),
        denoise_chroma=rng.uniform(*profile.denoise_chroma_range),
        noise_strength=rng.randint(*profile.noise_strength_range),
        grain_mix_frames=rng.choice([1, 1, 2]),
        unsharp_amount=rng.uniform(*profile.unsharp_range),
        speed=speed,
        audio_volume_db=rng.uniform(-0.7, 0.7),
        audio_highpass_hz=rng.randint(18, 35),
        audio_lowpass_hz=rng.randint(17500, 20500),
        audio_compressor_threshold_db=rng.uniform(-22.0, -16.0),
        audio_compressor_ratio=rng.uniform(1.08, 1.28),
        audio_eq_frequency_hz=rng.choice([180, 240, 320, 3600, 5200, 7200]),
        audio_eq_gain_db=rng.uniform(-0.9, 0.9),
        crf=rng.randint(*profile.crf_range),
        preset=rng.choice(["medium", "slow", "veryslow"]),
        video_bitrate=None,
        audio_bitrate=rng.choice(["128k", "160k", "192k"]),
        gop=max(24, int(target_fps * rng.uniform(1.7, 3.5))),
        bframes=rng.randint(2, 5),
        refs=rng.randint(2, 5),
        aq_strength=rng.uniform(0.75, 1.15),
        video_track_timescale=rng.choice([24000, 30000, 60000, 90000]),
        movflags=rng.choice(["+faststart", "+faststart+use_metadata_tags"]),
    )


def video_filter(plan: TransformPlan) -> str:
    filters = [
        f"crop={plan.crop_width}:{plan.crop_height}:{plan.crop_left}:{plan.crop_top}",
        (
            f"scale={plan.working_width}:{plan.working_height}:"
            "flags=lanczos:force_original_aspect_ratio=decrease"
        ),
        (
            f"pad={plan.working_width}:{plan.working_height}:"
            "(ow-iw)/2:(oh-ih)/2:color=black"
        ),
        f"rotate={math.radians(plan.rotate_degrees):.8f}:fillcolor=black",
        f"crop={plan.output_width}:{plan.output_height}:(iw-ow)/2:(ih-oh)/2",
        (
            f"eq=brightness={plan.brightness:.5f}:contrast={plan.contrast:.5f}:"
            f"saturation={plan.saturation:.5f}:gamma={plan.gamma:.5f}"
        ),
        f"hue=h={plan.hue_degrees:.5f}",
        (
            f"hqdn3d={plan.denoise_luma:.3f}:{plan.denoise_chroma:.3f}:"
            f"{plan.denoise_luma * 1.8:.3f}:{plan.denoise_chroma * 1.8:.3f}"
        ),
    ]
    if plan.grain_mix_frames > 1:
        weights = " ".join("1" for _ in range(plan.grain_mix_frames))
        filters.append(f"tmix=frames={plan.grain_mix_frames}:weights='{weights}'")
    filters.extend(
        [
            f"noise=alls={plan.noise_strength}:allf=t+u",
            f"unsharp=5:5:{plan.unsharp_amount:.4f}:3:3:0.0",
            f"setpts={1 / plan.speed:.8f}*PTS",
            f"fps={plan.fps:.3f}",
            "format=yuv420p",
            "setsar=1",
        ]
    )
    return ",".join(filters)


def audio_filter(plan: TransformPlan) -> str:
    return ",".join(
        [
            f"highpass=f={plan.audio_highpass_hz}",
            f"lowpass=f={plan.audio_lowpass_hz}",
            (
                "acompressor="
                f"threshold={plan.audio_compressor_threshold_db:.3f}dB:"
                f"ratio={plan.audio_compressor_ratio:.3f}:"
                "attack=12:release=120:makeup=1"
            ),
            (
                f"equalizer=f={plan.audio_eq_frequency_hz}:"
                f"width_type=o:width=1.2:g={plan.audio_eq_gain_db:.3f}"
            ),
            "aresample=48000:async=1:first_pts=0:resampler=soxr:precision=20",
            f"volume={plan.audio_volume_db:.3f}dB",
            f"atempo={plan.speed:.8f}",
        ]
    )


def transform_once(
    input_path: Path,
    output_path: Path,
    info: VideoInfo,
    plan: TransformPlan,
) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-i",
        str(input_path),
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-vf",
        video_filter(plan),
    ]
    if info.has_audio:
        command.extend(["-af", audio_filter(plan), "-map", "0:v:0", "-map", "0:a:0"])
    else:
        command.extend(["-map", "0:v:0", "-an"])
    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            plan.preset,
            "-crf",
            str(plan.crf),
            "-g",
            str(plan.gop),
            "-keyint_min",
            str(max(1, plan.gop // 2)),
            "-bf",
            str(plan.bframes),
            "-refs",
            str(plan.refs),
            "-sc_threshold",
            "0",
            "-x264-params",
            f"aq-mode=3:aq-strength={plan.aq_strength:.3f}:psy-rd=1.00,0.10",
            "-pix_fmt",
            "yuv420p",
        ]
    )
    if info.has_audio:
        command.extend(
            [
                "-c:a",
                "aac",
                "-b:a",
                plan.audio_bitrate,
                "-ar",
                "48000",
                "-ac",
                "2",
            ]
        )
    command.extend(
        [
            "-video_track_timescale",
            str(plan.video_track_timescale),
            "-avoid_negative_ts",
            "make_zero",
            "-movflags",
            plan.movflags,
            str(output_path),
        ]
    )
    run(command)


def compare_ssim(input_path: Path, output_path: Path, tmpdir: Path, fps: float) -> float | None:
    scaled_input = tmpdir / "input_compare.mp4"
    scaled_output = tmpdir / "output_compare.mp4"
    compare_fps = min(8.0, max(2.0, fps))
    normalize_filter = (
        "scale=320:-2:flags=bicubic,fps="
        f"{compare_fps:.3f},trim=start=0:end=20,setpts=PTS-STARTPTS,format=yuv420p"
    )
    for source, destination in [(input_path, scaled_input), (output_path, scaled_output)]:
        run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-i",
                str(source),
                "-vf",
                normalize_filter,
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "28",
                str(destination),
            ]
        )
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(scaled_input),
            "-i",
            str(scaled_output),
            "-lavfi",
            "ssim",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    text = result.stderr + result.stdout
    marker = "All:"
    if marker not in text:
        return None
    try:
        tail = text.rsplit(marker, 1)[1].split(" ", 1)[0]
        return float(tail)
    except ValueError:
        return None


def validate(
    input_path: Path,
    output_path: Path,
    input_info: VideoInfo,
    tmpdir: Path,
) -> tuple[bool, dict[str, Any]]:
    if not output_path.exists() or output_path.stat().st_size <= 0:
        return False, {"error": "output file missing or empty"}

    try:
        output_info = inspect_video(output_path)
    except Exception as exc:
        return False, {"error": f"ffprobe failed: {exc}"}

    duration_delta = abs(output_info.duration - input_info.duration)
    duration_limit = max(0.75, input_info.duration * 0.015)
    dimensions_ok = output_info.width > 0 and output_info.height > 0
    audio_ok = True
    if input_info.has_audio:
        audio_ok = output_info.has_audio
    ssim = compare_ssim(input_path, output_path, tmpdir, input_info.fps)
    similarity_ok = ssim is None or ssim >= MIN_SSIM_SAMPLE
    file_hash_changed = hash_file(input_path) != hash_file(output_path)
    codec_changed = (
        output_info.video_codec != input_info.video_codec
        or output_info.audio_codec != input_info.audio_codec
    )
    fps_delta = abs(output_info.fps - input_info.fps)
    file_size_delta_ratio = abs(output_path.stat().st_size - input_path.stat().st_size) / max(
        1,
        input_path.stat().st_size,
    )
    technical_difference_score = sum(
        [
            file_hash_changed,
            codec_changed,
            fps_delta >= 0.05,
            file_size_delta_ratio >= 0.01,
            output_info.width == input_info.width and output_info.height == input_info.height,
            duration_delta > 0.005,
        ]
    )
    ok = (
        duration_delta <= duration_limit
        and dimensions_ok
        and audio_ok
        and similarity_ok
        and file_hash_changed
        and technical_difference_score >= 3
    )
    return ok, {
        "input": asdict(input_info),
        "output": asdict(output_info),
        "duration_delta_seconds": round(duration_delta, 4),
        "duration_limit_seconds": round(duration_limit, 4),
        "dimensions_ok": dimensions_ok,
        "audio_ok": audio_ok,
        "ssim_sample": ssim,
        "ssim_threshold": MIN_SSIM_SAMPLE,
        "similarity_ok": similarity_ok,
        "file_hash_changed": file_hash_changed,
        "codec_changed": codec_changed,
        "fps_delta": round(fps_delta, 4),
        "file_size_delta_ratio": round(file_size_delta_ratio, 4),
        "technical_difference_score": technical_difference_score,
        "technical_difference_score_threshold": 3,
    }


def default_output_path(input_path: Path, seed: int) -> Path:
    return input_path.with_name(f"{input_path.stem}_robustness_{seed:x}.mp4")


def write_debug(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a randomized perceptual robustness-test copy of one video."
    )
    parser.add_argument("input", type=Path, help="Input video path")
    parser.add_argument("--output", "-o", type=Path, help="Optional output path")
    parser.add_argument("--seed", type=int, help="Optional seed for reproducibility")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()
    if not input_path.exists():
        print(f"Input file does not exist: {input_path}", file=sys.stderr)
        return 2
    require_tool("ffmpeg")
    require_tool("ffprobe")

    seed = int(args.seed if args.seed is not None else time.time_ns() & 0xFFFFFFFF)
    output_path = (
        args.output.expanduser().resolve() if args.output else default_output_path(input_path, seed)
    )
    debug_path = output_path.with_suffix(output_path.suffix + ".debug.json")
    input_info = inspect_video(input_path)
    attempts: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="video_robustness_") as tmp:
        tmpdir = Path(tmp)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            plan = build_plan(input_info, seed, attempt)
            candidate_path = tmpdir / f"candidate_{attempt}.mp4"
            record: dict[str, Any] = {"attempt": attempt, "plan": asdict(plan)}
            try:
                transform_once(input_path, candidate_path, input_info, plan)
                ok, validation = validate(input_path, candidate_path, input_info, tmpdir)
                record["validation"] = validation
                record["ok"] = ok
                attempts.append(record)
                if ok:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(candidate_path), output_path)
                    write_debug(
                        debug_path,
                        {
                            "seed": seed,
                            "input": str(input_path),
                            "output": str(output_path),
                            "selected_attempt": attempt,
                            "attempts": attempts,
                        },
                    )
                    print(output_path)
                    print(f"debug: {debug_path}")
                    return 0
            except subprocess.CalledProcessError as exc:
                record["ok"] = False
                record["error"] = exc.stderr[-4000:] if exc.stderr else str(exc)
                attempts.append(record)
            except Exception as exc:
                record["ok"] = False
                record["error"] = str(exc)
                attempts.append(record)

    write_debug(
        debug_path,
        {
            "seed": seed,
            "input": str(input_path),
            "output": str(output_path),
            "selected_attempt": None,
            "attempts": attempts,
        },
    )
    print(f"Failed to produce a valid output after {MAX_ATTEMPTS} attempts", file=sys.stderr)
    print(f"debug: {debug_path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
