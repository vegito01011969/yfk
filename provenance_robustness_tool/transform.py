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

MAX_ATTEMPTS = 6
MIN_SSIM_SAMPLE = 0.68
DEFAULT_STRESS_LEVEL = 4


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
    stress_level: int
    profile: str
    operations: list[dict[str, Any]]
    crop_left: int
    crop_top: int
    crop_width: int
    crop_height: int
    output_width: int
    output_height: int
    working_width: int
    working_height: int
    scale_flags_primary: str
    scale_flags_final: str
    rotate_degrees: float
    translate_x: float
    translate_y: float
    shear_x: float
    shear_y: float
    perspective_px: int
    h_stretch: float
    v_stretch: float
    fps: float
    brightness: float
    contrast: float
    saturation: float
    gamma: float
    hue_degrees: float
    temperature_shift: float
    vignette_strength: float
    spatial_gradient_strength: float
    channel_rr: float
    channel_gg: float
    channel_bb: float
    channel_rg: float
    channel_gb: float
    channel_br: float
    chroma_shift_cb_h: int
    chroma_shift_cb_v: int
    chroma_shift_cr_h: int
    chroma_shift_cr_v: int
    gradfun_strength: float
    gradfun_radius: int
    edge_matte_px: int
    denoise_luma: float
    denoise_chroma: float
    noise_strength: int
    grain_mix_frames: int
    unsharp_amount: float
    blur_sigma: float
    posterize_bits: int
    fade_frames: int
    flash_frame: str | None
    flash_opacity: float
    progress_bar_height: int
    progress_bar_opacity: float
    watermark_enabled: bool
    watermark_opacity: float
    watermark_size_pct: float
    watermark_x_pct: float
    watermark_y_pct: float
    speed: float
    audio_delay_ms: int
    audio_pitch_factor: float
    audio_sample_rate: int
    audio_volume_db: float
    audio_highpass_hz: int
    audio_lowpass_hz: int
    audio_compressor_threshold_db: float
    audio_compressor_ratio: float
    audio_eq_frequency_hz: int
    audio_eq_gain_db: float
    audio_eq2_frequency_hz: int
    audio_eq2_gain_db: float
    audio_bass_gain_db: float
    audio_treble_gain_db: float
    audio_stereo_mix: float
    audio_echo_delay_ms: int
    audio_echo_decay: float
    audio_compand_points: str
    audio_limiter_level: float
    crf: int
    preset: str
    tune: str | None
    x264_profile: str
    x264_level: str
    video_bitrate: str | None
    audio_bitrate: str
    audio_dither_method: str
    gop: int
    bframes: int
    refs: int
    aq_strength: float
    deblock_alpha: int
    deblock_beta: int
    psy_rd: float
    psy_trellis: float
    trellis: int
    rc_lookahead: int
    video_track_timescale: int
    movflags: str
    metadata_padding_bytes: int
    codec_generations: list[str]


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
        crop_pct_range=(0.018, 0.046),
        rotate_abs_max=0.42,
        fps_jitter_choices=(-0.5, -0.35, -0.2, 0.2, 0.35, 0.5),
        speed_range=(0.992, 1.008),
        brightness_range=(-0.028, 0.028),
        contrast_range=(0.955, 1.06),
        saturation_range=(0.94, 1.09),
        gamma_range=(0.97, 1.035),
        hue_abs_max=3.2,
        denoise_luma_range=(0.35, 0.95),
        denoise_chroma_range=(0.3, 0.8),
        noise_strength_range=(3, 6),
        unsharp_range=(0.06, 0.34),
        crf_range=(21, 27),
    ),
    TransformProfile(
        name="perceptual_shift",
        crop_pct_range=(0.026, 0.064),
        rotate_abs_max=0.58,
        fps_jitter_choices=(-0.75, -0.5, -0.25, 0.25, 0.5, 0.75),
        speed_range=(0.988, 1.012),
        brightness_range=(-0.04, 0.04),
        contrast_range=(0.93, 1.085),
        saturation_range=(0.9, 1.14),
        gamma_range=(0.955, 1.05),
        hue_abs_max=4.5,
        denoise_luma_range=(0.45, 1.15),
        denoise_chroma_range=(0.36, 0.95),
        noise_strength_range=(4, 8),
        unsharp_range=(0.04, 0.38),
        crf_range=(22, 29),
    ),
)

VALIDATION_RESCUE_PROFILE = TransformProfile(
    name="validation_rescue",
    crop_pct_range=(0.0, 0.0),
    rotate_abs_max=0.0,
    fps_jitter_choices=(-0.1, 0.1),
    speed_range=(0.9998, 1.0002),
    brightness_range=(-0.003, 0.003),
    contrast_range=(0.996, 1.006),
    saturation_range=(0.996, 1.008),
    gamma_range=(0.997, 1.004),
    hue_abs_max=0.2,
    denoise_luma_range=(0.04, 0.12),
    denoise_chroma_range=(0.04, 0.1),
    noise_strength_range=(1, 1),
    unsharp_range=(0.02, 0.08),
    crf_range=(19, 21),
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


def even_or_zero(value: int) -> int:
    if value <= 0:
        return 0
    return even(value)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clamp_stress_level(value: int) -> int:
    return max(0, min(6, value))


def build_plan(
    info: VideoInfo,
    seed: int,
    attempt: int,
    stress_level: int = DEFAULT_STRESS_LEVEL,
) -> TransformPlan:
    stress_level = clamp_stress_level(stress_level)
    rng = random.Random(seed + attempt * 7919)
    if stress_level == 0:
        profile = VALIDATION_RESCUE_PROFILE
    elif attempt == MAX_ATTEMPTS:
        profile = VALIDATION_RESCUE_PROFILE
    elif attempt <= 2:
        profile_weights = {
            1: [0.70, 0.25, 0.05, 0.00],
            2: [0.35, 0.45, 0.18, 0.02],
            3: [0.16, 0.38, 0.34, 0.12],
            4: [0.05, 0.20, 0.35, 0.40],
            5: [0.02, 0.14, 0.34, 0.50],
            6: [0.00, 0.10, 0.32, 0.58],
        }.get(stress_level, [0.05, 0.20, 0.35, 0.40])
        profile = rng.choices(PROFILES, weights=profile_weights, k=1)[0]
    elif attempt <= 4:
        profile_weights = {
            1: [0.82, 0.18, 0.00, 0.00],
            2: [0.48, 0.40, 0.12, 0.00],
            3: [0.25, 0.44, 0.25, 0.06],
            4: [0.12, 0.36, 0.34, 0.18],
            5: [0.07, 0.28, 0.42, 0.23],
            6: [0.05, 0.22, 0.43, 0.30],
        }.get(stress_level, [0.12, 0.36, 0.34, 0.18])
        profile = rng.choices(PROFILES, weights=profile_weights, k=1)[0]
    else:
        profile = PROFILES[0]
    crop_pct = rng.uniform(*profile.crop_pct_range)
    crop_x_total = even_or_zero(int(info.width * crop_pct))
    crop_y_total = even_or_zero(int(info.height * crop_pct))
    crop_left = even_or_zero(rng.randint(0, max(0, crop_x_total)))
    crop_top = even_or_zero(rng.randint(0, max(0, crop_y_total)))
    crop_width = even(info.width - crop_x_total)
    crop_height = even(info.height - crop_y_total)

    fps_jitter = rng.choice(profile.fps_jitter_choices)
    target_fps = max(12.0, min(60.0, round(info.fps + fps_jitter, 3)))
    speed = rng.uniform(*profile.speed_range)
    rotate_degrees = rng.uniform(-profile.rotate_abs_max, profile.rotate_abs_max)
    rotate_radians = abs(math.radians(rotate_degrees))
    overscan = (
        1.0
        if profile.name == VALIDATION_RESCUE_PROFILE.name
        else 1.0 + abs(math.sin(rotate_radians)) + rng.uniform(0.006, 0.018)
    )
    working_width = even(math.ceil(info.width * overscan))
    working_height = even(math.ceil(info.height * overscan))
    level_factor = stress_level / 6.0
    shear_x = 0.0 if stress_level < 3 else rng.uniform(-0.018, 0.018) * level_factor
    shear_y = 0.0 if stress_level < 4 else rng.uniform(-0.010, 0.010) * level_factor
    perspective_px = (
        0
        if stress_level < 4 or profile.name == VALIDATION_RESCUE_PROFILE.name
        else rng.choice([0, 0, 1, 2, 3, 4, 6, 8])
    )
    h_stretch = 1.0 if stress_level < 3 else rng.uniform(0.985, 1.018)
    v_stretch = 1.0 if stress_level < 3 else rng.uniform(0.985, 1.018)
    spatial_gradient_strength = (
        0.0 if stress_level < 3 else rng.uniform(-0.08, 0.08) * level_factor
    )
    fade_frames = 0 if stress_level < 3 else rng.choice([0, 0, 3, 5, 8, 12])
    flash_frame = None
    flash_opacity = 0.0
    if stress_level >= 5 and rng.random() < 0.35:
        flash_frame = rng.choice(["black", "white"])
        flash_opacity = rng.uniform(0.10, 0.22)
    progress_bar_height = 0
    progress_bar_opacity = 0.0
    if stress_level >= 4 and rng.random() < 0.45:
        progress_bar_height = max(2, even(int(info.height * rng.uniform(0.004, 0.012))))
        progress_bar_opacity = rng.uniform(0.16, 0.34)
    watermark_enabled = stress_level >= 5 and rng.random() < 0.45
    watermark_opacity = rng.uniform(0.10, 0.24) if watermark_enabled else 0.0
    watermark_size_pct = rng.uniform(0.035, 0.075) if watermark_enabled else 0.0
    watermark_x_pct = rng.choice([rng.uniform(0.025, 0.08), rng.uniform(0.82, 0.93)])
    watermark_y_pct = rng.choice([rng.uniform(0.04, 0.10), rng.uniform(0.80, 0.90)])
    codec_generations = []
    if stress_level >= 5 and profile.name != VALIDATION_RESCUE_PROFILE.name:
        codec_generations = rng.choice(
            [
                [],
                ["libx265"],
                ["libx264", "libx265"],
                ["libx265", "libx264"],
            ]
        )
    operations = [
        {"category": "benchmark", "name": f"level_{stress_level}", "severity": stress_level},
        {
            "category": "geometry",
            "name": "crop_resize_rotate_pad_crop",
            "severity": round(crop_pct, 4),
        },
        {"category": "geometry", "name": "subpixel_translate", "severity": "low"},
        {
            "category": "color",
            "name": "color_grade_channel_mix_chroma_shift",
            "severity": profile.name,
        },
        {"category": "temporal", "name": "speed_fps_conversion", "severity": profile.name},
        {"category": "audio", "name": "eq_compress_resample_tempo", "severity": profile.name},
        {"category": "codec", "name": "h264_aac_reencode", "severity": f"crf_{profile.crf_range}"},
        {
            "category": "container",
            "name": "metadata_strip_timescale_mux_variation",
            "severity": "low",
        },
    ]
    if abs(shear_x) > 0.0001 or abs(shear_y) > 0.0001:
        operations.append({"category": "geometry", "name": "mild_affine_shear", "severity": "low"})
    if perspective_px:
        operations.append(
            {
                "category": "geometry",
                "name": "mild_perspective_keystone",
                "severity": perspective_px,
            }
        )
    if abs(h_stretch - 1.0) > 0.002 or abs(v_stretch - 1.0) > 0.002:
        operations.append({"category": "geometry", "name": "non_uniform_scale", "severity": "low"})
    if spatial_gradient_strength:
        operations.append(
            {"category": "color", "name": "spatial_brightness_gradient", "severity": "low"}
        )
    if fade_frames:
        operations.append(
            {"category": "editing", "name": "short_fade_in_out", "severity": fade_frames}
        )
    if flash_frame:
        operations.append(
            {
                "category": "editing",
                "name": f"{flash_frame}_flash_overlay",
                "severity": "low",
            }
        )
    if progress_bar_height:
        operations.append({"category": "overlay", "name": "subtle_progress_bar", "severity": "low"})
    if watermark_enabled:
        operations.append(
            {"category": "overlay", "name": "subtle_corner_watermark", "severity": "low"}
        )
    if codec_generations:
        operations.append(
            {
                "category": "codec",
                "name": "multi_generation_transcode",
                "severity": codec_generations,
            }
        )
    if stress_level >= 2:
        operations.append(
            {
                "category": "audio",
                "name": "multi_band_eq_pitch_stereo_dynamics",
                "severity": profile.name,
            }
        )
    if stress_level >= 4:
        operations.append(
            {
                "category": "audio",
                "name": "micro_echo_sample_rate_limiter",
                "severity": "medium",
            }
        )
    audio_pitch_span = 0.0 if stress_level < 2 else 0.006 + stress_level * 0.0028
    audio_pitch_factor = rng.uniform(1.0 - audio_pitch_span, 1.0 + audio_pitch_span)
    audio_sample_rate = rng.choice(
        [44100, 48000]
        if stress_level < 3
        else [32000, 44100, 48000, 48000, 88200]
    )
    audio_echo_delay_ms = 0
    audio_echo_decay = 0.0
    if stress_level >= 4:
        audio_echo_delay_ms = rng.choice([0, 0, 18, 24, 32, 45, 64])
        audio_echo_decay = rng.uniform(0.025, 0.095) if audio_echo_delay_ms else 0.0

    return TransformPlan(
        seed=seed,
        attempt=attempt,
        stress_level=stress_level,
        profile=profile.name,
        operations=operations,
        crop_left=crop_left,
        crop_top=crop_top,
        crop_width=crop_width,
        crop_height=crop_height,
        output_width=even(info.width),
        output_height=even(info.height),
        working_width=working_width,
        working_height=working_height,
        scale_flags_primary=rng.choice(["lanczos", "bicubic", "spline", "area"]),
        scale_flags_final=rng.choice(["lanczos+accurate_rnd", "bicubic+accurate_rnd", "spline"]),
        rotate_degrees=rotate_degrees,
        translate_x=rng.uniform(-1.35, 1.35),
        translate_y=rng.uniform(-1.35, 1.35),
        shear_x=shear_x,
        shear_y=shear_y,
        perspective_px=perspective_px,
        h_stretch=h_stretch,
        v_stretch=v_stretch,
        fps=target_fps,
        brightness=rng.uniform(*profile.brightness_range),
        contrast=rng.uniform(*profile.contrast_range),
        saturation=rng.uniform(*profile.saturation_range),
        gamma=rng.uniform(*profile.gamma_range),
        hue_degrees=rng.uniform(-profile.hue_abs_max, profile.hue_abs_max),
        temperature_shift=rng.uniform(-0.035, 0.035) * level_factor,
        vignette_strength=0.0 if stress_level < 4 else rng.uniform(0.0, 0.18) * level_factor,
        spatial_gradient_strength=spatial_gradient_strength,
        channel_rr=rng.uniform(0.988, 1.014),
        channel_gg=rng.uniform(0.988, 1.014),
        channel_bb=rng.uniform(0.988, 1.014),
        channel_rg=rng.uniform(-0.008, 0.008),
        channel_gb=rng.uniform(-0.008, 0.008),
        channel_br=rng.uniform(-0.008, 0.008),
        chroma_shift_cb_h=rng.choice([-2, -1, 0, 0, 1, 2]),
        chroma_shift_cb_v=rng.choice([-2, -1, 0, 0, 1, 2]),
        chroma_shift_cr_h=rng.choice([-2, -1, 0, 0, 1, 2]),
        chroma_shift_cr_v=rng.choice([-2, -1, 0, 0, 1, 2]),
        gradfun_strength=rng.uniform(0.6, 1.35),
        gradfun_radius=rng.choice([8, 12, 16]),
        edge_matte_px=rng.choice([0, 0, 2, 3, 4, 6, 8]),
        denoise_luma=rng.uniform(*profile.denoise_luma_range),
        denoise_chroma=rng.uniform(*profile.denoise_chroma_range),
        noise_strength=rng.randint(*profile.noise_strength_range),
        grain_mix_frames=rng.choice([1, 1, 2]),
        unsharp_amount=rng.uniform(*profile.unsharp_range),
        blur_sigma=0.0 if stress_level < 3 else rng.choice([0.0, 0.0, 0.25, 0.35, 0.50]),
        posterize_bits=0 if stress_level < 5 else rng.choice([0, 0, 0, 5, 6]),
        fade_frames=fade_frames,
        flash_frame=flash_frame,
        flash_opacity=flash_opacity,
        progress_bar_height=progress_bar_height,
        progress_bar_opacity=progress_bar_opacity,
        watermark_enabled=watermark_enabled,
        watermark_opacity=watermark_opacity,
        watermark_size_pct=watermark_size_pct,
        watermark_x_pct=watermark_x_pct,
        watermark_y_pct=watermark_y_pct,
        speed=speed,
        audio_delay_ms=0 if stress_level < 5 else rng.choice([0, 0, -30, -20, 20, 35, 50]),
        audio_pitch_factor=audio_pitch_factor,
        audio_sample_rate=audio_sample_rate,
        audio_volume_db=rng.uniform(-2.2, 2.2),
        audio_highpass_hz=rng.randint(14, 95 if stress_level >= 4 else 55),
        audio_lowpass_hz=rng.randint(11800 if stress_level >= 4 else 14500, 20500),
        audio_compressor_threshold_db=rng.uniform(-30.0, -12.0),
        audio_compressor_ratio=rng.uniform(1.12, 2.25 if stress_level >= 4 else 1.55),
        audio_eq_frequency_hz=rng.choice([120, 180, 240, 320, 480, 3600, 5200, 7200]),
        audio_eq_gain_db=rng.uniform(-3.0, 3.0),
        audio_eq2_frequency_hz=rng.choice([700, 950, 1400, 2200, 4200, 6800, 9200]),
        audio_eq2_gain_db=rng.uniform(-2.4, 2.4),
        audio_bass_gain_db=rng.uniform(-2.5, 2.5),
        audio_treble_gain_db=rng.uniform(-2.5, 2.5),
        audio_stereo_mix=rng.uniform(0.015, 0.105 if stress_level >= 4 else 0.055),
        audio_echo_delay_ms=audio_echo_delay_ms,
        audio_echo_decay=audio_echo_decay,
        audio_compand_points=rng.choice(
            [
                "-80/-80|-45/-38|-18/-16|0/-1.5",
                "-90/-90|-50/-44|-24/-20|-6/-5|0/-1",
                "-70/-70|-36/-32|-12/-10|0/-1.2",
            ]
        ),
        audio_limiter_level=rng.uniform(0.82, 0.98),
        crf=rng.randint(*profile.crf_range),
        preset=rng.choice(["medium", "slow", "veryslow"]),
        tune=rng.choice([None, None, "film", "grain", "fastdecode"]),
        x264_profile=rng.choice(["main", "high"]),
        x264_level=rng.choice(["4.0", "4.1", "4.2", "5.0"]),
        video_bitrate=None,
        audio_bitrate=rng.choice(["96k", "112k", "128k", "160k", "192k"]),
        audio_dither_method=rng.choice(["triangular", "triangular_hp", "lipshitz", "shibata"]),
        gop=max(24, int(target_fps * rng.uniform(1.7, 3.5))),
        bframes=rng.randint(2, 5),
        refs=rng.randint(2, 5),
        aq_strength=rng.uniform(0.55, 1.35),
        deblock_alpha=rng.randint(-4, 4),
        deblock_beta=rng.randint(-4, 4),
        psy_rd=rng.uniform(0.65, 1.35),
        psy_trellis=rng.uniform(0.0, 0.28),
        trellis=rng.randint(1, 2),
        rc_lookahead=rng.randint(24, 60),
        video_track_timescale=rng.choice([24000, 30000, 60000, 90000]),
        movflags=rng.choice(["+faststart", "+faststart+use_metadata_tags"]),
        metadata_padding_bytes=rng.choice([0, 4096, 8192, 16384]),
        codec_generations=codec_generations,
    )


def video_filter(plan: TransformPlan) -> str:
    stretch_width = even(int(plan.working_width * plan.h_stretch))
    stretch_height = even(int(plan.working_height * plan.v_stretch))
    perspective_px = min(plan.perspective_px, plan.working_width // 20, plan.working_height // 20)
    filters = [
        f"crop={plan.crop_width}:{plan.crop_height}:{plan.crop_left}:{plan.crop_top}",
        (
            f"scale={plan.working_width}:{plan.working_height}:"
            f"flags={plan.scale_flags_primary}:force_original_aspect_ratio=decrease"
        ),
        (
            f"pad={plan.working_width}:{plan.working_height}:"
            "(ow-iw)/2:(oh-ih)/2:color=black"
        ),
        f"scale={stretch_width}:{stretch_height}:flags={plan.scale_flags_primary}",
        (
            f"scale={plan.working_width}:{plan.working_height}:"
            f"flags={plan.scale_flags_final}"
        ),
    ]
    if perspective_px:
        top_left_x = perspective_px
        top_right_x = plan.working_width - 1 - max(0, int(perspective_px * 0.35))
        bottom_left_x = max(0, int(perspective_px * 0.35))
        bottom_right_x = plan.working_width - 1 - perspective_px
        filters.append(
            "perspective="
            f"x0={top_left_x}:y0=0:"
            f"x1={top_right_x}:y1={perspective_px}:"
            f"x2={bottom_left_x}:y2={plan.working_height - 1 - perspective_px}:"
            f"x3={bottom_right_x}:y3={plan.working_height - 1}:"
            "sense=destination"
        )
    filters.extend(
        [
        f"rotate={math.radians(plan.rotate_degrees):.8f}:fillcolor=black",
        (
            f"crop={plan.output_width}:{plan.output_height}:"
            f"(iw-ow)/2+{plan.translate_x:.5f}:(ih-oh)/2+{plan.translate_y:.5f}"
        ),
        (
            f"scale={plan.output_width}:{plan.output_height}:"
            f"flags={plan.scale_flags_final}"
        ),
        (
            f"eq=brightness={plan.brightness:.5f}:contrast={plan.contrast:.5f}:"
            f"saturation={plan.saturation:.5f}:gamma={plan.gamma:.5f}"
        ),
            f"hue=h={plan.hue_degrees:.5f}",
        (
            f"colorchannelmixer=rr={plan.channel_rr:.5f}:gg={plan.channel_gg:.5f}:"
            f"bb={plan.channel_bb + plan.temperature_shift:.5f}:"
            f"rg={plan.channel_rg:.5f}:gb={plan.channel_gb:.5f}:"
            f"br={plan.channel_br - plan.temperature_shift:.5f}"
        ),
        (
            f"hqdn3d={plan.denoise_luma:.3f}:{plan.denoise_chroma:.3f}:"
            f"{plan.denoise_luma * 1.8:.3f}:{plan.denoise_chroma * 1.8:.3f}"
        ),
        ]
    )
    if any(
        value
        for value in (
            plan.chroma_shift_cb_h,
            plan.chroma_shift_cb_v,
            plan.chroma_shift_cr_h,
            plan.chroma_shift_cr_v,
        )
    ):
        filters.append(
            "chromashift="
            f"cbh={plan.chroma_shift_cb_h}:cbv={plan.chroma_shift_cb_v}:"
            f"crh={plan.chroma_shift_cr_h}:crv={plan.chroma_shift_cr_v}"
        )
    filters.append(
        f"gradfun=strength={plan.gradfun_strength:.3f}:radius={plan.gradfun_radius}"
    )
    if plan.grain_mix_frames > 1:
        weights = " ".join("1" for _ in range(plan.grain_mix_frames))
        filters.append(f"tmix=frames={plan.grain_mix_frames}:weights='{weights}'")
    if plan.blur_sigma:
        filters.append(f"gblur=sigma={plan.blur_sigma:.3f}:steps=1")
    if plan.posterize_bits:
        posterize_step = 2 ** (8 - plan.posterize_bits)
        filters.append(
            "format=rgb24,lutrgb="
            f"r='trunc(val/{posterize_step})*{posterize_step}':"
            f"g='trunc(val/{posterize_step})*{posterize_step}':"
            f"b='trunc(val/{posterize_step})*{posterize_step}'"
        )
    if plan.vignette_strength:
        filters.append("vignette=angle=PI/5:eval=frame:mode=forward")
    filters.extend(
        [
            f"noise=alls={plan.noise_strength}:allf=t+u",
            f"unsharp=5:5:{plan.unsharp_amount:.4f}:3:3:0.0",
            f"setpts={1 / plan.speed:.8f}*PTS",
            f"fps={plan.fps:.3f}",
        ]
    )
    if plan.fade_frames:
        fade_duration = max(0.03, plan.fade_frames / max(plan.fps, 1.0))
        filters.append(f"fade=t=in:st=0:d={fade_duration:.4f}:alpha=0")
    filters.extend(["format=yuv420p", "setsar=1"])
    if plan.edge_matte_px:
        filters.append(
            f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.18:t={plan.edge_matte_px}"
        )
    if plan.spatial_gradient_strength:
        overlay_color = "white" if plan.spatial_gradient_strength > 0 else "black"
        opacity = min(0.12, abs(plan.spatial_gradient_strength))
        filters.append(
            f"drawbox=x=0:y=0:w=iw:h=ih/3:color={overlay_color}@{opacity:.3f}:t=fill"
        )
    if plan.progress_bar_height:
        filters.append(
            "drawbox="
            f"x=0:y=ih-{plan.progress_bar_height}:"
            f"w=iw*0.78:h={plan.progress_bar_height}:"
            f"color=white@{plan.progress_bar_opacity:.3f}:t=fill"
        )
    if plan.watermark_enabled:
        box_size = max(
            8,
            even(int(min(plan.output_width, plan.output_height) * plan.watermark_size_pct)),
        )
        filters.append(
            "drawbox="
            f"x=iw*{plan.watermark_x_pct:.4f}:"
            f"y=ih*{plan.watermark_y_pct:.4f}:"
            f"w={box_size}:h={box_size}:"
            f"color=white@{plan.watermark_opacity:.3f}:t=fill"
        )
    if plan.flash_frame:
        flash_color = plan.flash_frame
        filters.append(
            f"drawbox=x=0:y=0:w=iw:h=ih:color={flash_color}@{plan.flash_opacity:.3f}:"
            f"t=fill:enable='between(t,0.12,0.16)'"
        )
    return ",".join(filters)


def audio_filter(plan: TransformPlan) -> str:
    pitch_inverse = 1.0 / max(0.5, min(2.0, plan.audio_pitch_factor))
    left_mix = 1.0 - plan.audio_stereo_mix
    cross_mix = plan.audio_stereo_mix
    filters = [
        "aformat=sample_fmts=fltp:channel_layouts=stereo",
        "aresample=48000:async=1:first_pts=0:resampler=soxr:precision=20",
        f"highpass=f={plan.audio_highpass_hz}",
        f"lowpass=f={plan.audio_lowpass_hz}",
        f"bass=g={plan.audio_bass_gain_db:.3f}:f=110:w=0.7",
        f"treble=g={plan.audio_treble_gain_db:.3f}:f=6500:w=0.8",
        (
            "acompressor="
            f"threshold={plan.audio_compressor_threshold_db:.3f}dB:"
            f"ratio={plan.audio_compressor_ratio:.3f}:"
            "attack=12:release=120:makeup=1"
        ),
        (
            "compand="
            "attacks=0.008:decays=0.18:"
            f"points={plan.audio_compand_points}:soft-knee=0.018:gain=0:volume=0"
        ),
        (
            f"equalizer=f={plan.audio_eq_frequency_hz}:"
            f"width_type=o:width=1.2:g={plan.audio_eq_gain_db:.3f}"
        ),
        (
            f"equalizer=f={plan.audio_eq2_frequency_hz}:"
            f"width_type=o:width=0.9:g={plan.audio_eq2_gain_db:.3f}"
        ),
        (
            "pan=stereo|"
            f"c0={left_mix:.5f}*c0+{cross_mix:.5f}*c1|"
            f"c1={cross_mix:.5f}*c0+{left_mix:.5f}*c1"
        ),
        f"asetrate={48000 * plan.audio_pitch_factor:.3f}",
        (
            f"aresample={plan.audio_sample_rate}:async=1:first_pts=0:resampler=soxr:"
            f"precision=20:dither_method={plan.audio_dither_method}"
        ),
        f"atempo={pitch_inverse:.8f}",
        "aresample=48000:async=1:first_pts=0:resampler=soxr:precision=20",
        f"volume={plan.audio_volume_db:.3f}dB",
        f"alimiter=level_in=1:level_out={plan.audio_limiter_level:.5f}:limit=0.98",
        f"atempo={plan.speed:.8f}",
    ]
    if plan.audio_echo_delay_ms:
        filters.append(
            "aecho="
            f"in_gain=0.94:out_gain=0.96:"
            f"delays={plan.audio_echo_delay_ms}:decays={plan.audio_echo_decay:.5f}"
        )
    if plan.audio_delay_ms > 0:
        filters.append(f"adelay={plan.audio_delay_ms}:all=1")
    elif plan.audio_delay_ms < 0:
        filters.extend(
            [
                f"atrim=start={abs(plan.audio_delay_ms) / 1000:.4f}",
                "asetpts=PTS-STARTPTS",
            ]
        )
    return ",".join(filters)


def transcode_generation(
    input_path: Path,
    output_path: Path,
    codec: str,
    plan: TransformPlan,
    generation: int,
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
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        codec,
        "-preset",
        "fast" if codec == "libx265" else "medium",
        "-crf",
        str(min(32, plan.crf + generation + 1)),
        "-g",
        str(max(24, plan.gop + generation * 7)),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        plan.audio_bitrate,
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    run(command)


def transform_once(
    input_path: Path,
    output_path: Path,
    info: VideoInfo,
    plan: TransformPlan,
) -> None:
    source_path = input_path
    generation_paths: list[Path] = []
    for generation, codec in enumerate(plan.codec_generations, start=1):
        generation_path = output_path.with_name(
            f"{output_path.stem}.generation_{generation}{output_path.suffix}"
        )
        transcode_generation(source_path, generation_path, codec, plan, generation)
        generation_paths.append(generation_path)
        source_path = generation_path
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-i",
        str(source_path),
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
            "-profile:v",
            plan.x264_profile,
            "-level:v",
            plan.x264_level,
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
            (
                f"aq-mode=3:aq-strength={plan.aq_strength:.3f}:"
                f"psy-rd={plan.psy_rd:.3f},{plan.psy_trellis:.3f}:"
                f"deblock={plan.deblock_alpha},{plan.deblock_beta}:"
                f"trellis={plan.trellis}:rc-lookahead={plan.rc_lookahead}:"
                "me=umh:subme=8:direct=auto"
            ),
            "-pix_fmt",
            "yuv420p",
        ]
    )
    if plan.tune:
        command.extend(["-tune", plan.tune])
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
            "-metadata",
            f"encoder=Lavf-{plan.seed:x}-{plan.attempt}",
            "-movflags",
            plan.movflags,
        ]
    )
    if plan.metadata_padding_bytes:
        command.extend(["-moov_size", str(plan.metadata_padding_bytes)])
    command.append(str(output_path))
    try:
        run(command)
    finally:
        for path in generation_paths:
            path.unlink(missing_ok=True)


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
    parser.add_argument(
        "--level",
        type=int,
        default=DEFAULT_STRESS_LEVEL,
        choices=range(0, 7),
        metavar="0-6",
        help=(
            "Benchmark stress level: 0 identical-style rescue, 1 light, "
            "4 composed default, 6 strongest detector-agnostic stress."
        ),
    )
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
    stress_level = clamp_stress_level(args.level)
    output_path = (
        args.output.expanduser().resolve() if args.output else default_output_path(input_path, seed)
    )
    debug_path = output_path.with_suffix(output_path.suffix + ".debug.json")
    input_info = inspect_video(input_path)
    attempts: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="video_robustness_") as tmp:
        tmpdir = Path(tmp)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            plan = build_plan(input_info, seed, attempt, stress_level=stress_level)
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
                            "stress_level": stress_level,
                            "input": str(input_path),
                            "output": str(output_path),
                            "selected_attempt": attempt,
                            "selected_operations": plan.operations,
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
            "stress_level": stress_level,
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
