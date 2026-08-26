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
import wave
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
    audio_spectral_eq_bands: list[dict[str, Any]]
    audio_bass_gain_db: float
    audio_treble_gain_db: float
    audio_stereo_mix: float
    audio_phase_invert_mix: float
    audio_echo_delay_ms: int
    audio_echo_decay: float
    audio_compand_points: str
    audio_limiter_level: float
    audio_tremolo_rate_hz: float
    audio_tremolo_depth: float
    audio_noise_color: str
    audio_noise_amplitude: float
    audio_hum_frequency_hz: int
    audio_hum_amplitude: float
    audio_tone_frequency_hz: int
    audio_tone_amplitude: float
    audio_fft_noise_reduction: float
    audio_fft_noise_floor: float
    audio_phase_shift: float
    audio_phase_order: int
    audio_frequency_shift_enabled: bool
    audio_frequency_shift_hz: float
    audio_frequency_shift_level: float
    audio_tilt_frequency_hz: int
    audio_tilt_slope: float
    audio_crystalizer_intensity: float
    audio_extra_stereo_mult: float
    audio_phaser_delay_ms: float
    audio_phaser_decay: float
    audio_phaser_speed: float
    audio_flanger_enabled: bool
    audio_flanger_delay_ms: float
    audio_flanger_depth_ms: float
    audio_flanger_width: float
    audio_flanger_speed: float
    audio_haas_enabled: bool
    audio_haas_left_delay_ms: float
    audio_haas_right_delay_ms: float
    audio_haas_side_gain: float
    audio_crossfeed_enabled: bool
    audio_crossfeed_strength: float
    audio_crossfeed_range: float
    audio_dynamic_eq_enabled: bool
    audio_dynamic_eq_frequency_hz: int
    audio_dynamic_eq_ratio: float
    audio_dynamic_eq_range: float
    audio_dynamic_eq_mode: str
    audio_rubberband_enabled: bool
    audio_rubberband_tempo: float
    audio_rubberband_pitch: float
    audio_crusher_enabled: bool
    audio_crusher_bits: float
    audio_crusher_samples: float
    audio_crusher_mix: float
    audio_dynaudnorm_enabled: bool
    audio_dynaudnorm_frame_ms: int
    audio_dynaudnorm_compress: float
    audio_speechnorm_enabled: bool
    audio_room_enabled: bool
    audio_room_wet: float
    audio_room_decay: float
    audio_room_tail_ms: int
    audio_bed_noise_amplitude: float
    audio_bed_mod_frequency_hz: float
    audio_generated_layers: list[dict[str, Any]]
    audio_harmonic_layers: list[dict[str, Any]]
    audio_spectral_inversion_layers: list[dict[str, Any]]
    audio_spectrogram_perturbation_layers: list[dict[str, Any]]
    audio_chop_layers: list[dict[str, Any]]
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
    audio_codec_generations: list[str]


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
    audio_codec_generations: list[str] = []
    if stress_level >= 4 and profile.name != VALIDATION_RESCUE_PROFILE.name:
        audio_codec_generations = rng.choice(
            [
                [],
                ["libmp3lame"],
                ["libopus"],
                ["aac", "libmp3lame"],
                ["libmp3lame", "libopus"],
            ]
        )
    spectral_band_count = 1 if stress_level < 3 else rng.randint(3, 7)
    if stress_level >= 5:
        spectral_band_count = rng.randint(6, 10)
    audio_spectral_eq_bands = [
        {
            "frequency_hz": rng.choice(
                [70, 95, 140, 210, 330, 510, 760, 1100, 1650, 2400, 3600, 5200, 7600, 10800]
            ),
            "width": rng.uniform(0.28, 1.8),
            "gain_db": rng.uniform(
                -1.6 if stress_level < 4 else -4.8,
                1.6 if stress_level < 4 else 4.8,
            ),
        }
        for _ in range(spectral_band_count)
    ]
    audio_generated_layers: list[dict[str, Any]] = []
    if stress_level >= 3:
        layer_count = rng.randint(1, 2)
        if stress_level >= 5:
            layer_count = rng.randint(2, 4)
        for _ in range(layer_count):
            kind = rng.choice(["air", "rumble", "tone", "texture"])
            if kind == "air":
                audio_generated_layers.append(
                    {
                        "kind": kind,
                        "color": rng.choice(["white", "pink"]),
                        "amplitude": rng.uniform(0.00015, 0.0011),
                        "highpass_hz": rng.randint(1800, 4200),
                        "lowpass_hz": rng.randint(7200, 15500),
                        "tremolo_hz": rng.uniform(0.10, 0.32),
                        "tremolo_depth": rng.uniform(0.18, 0.55),
                        "volume_db": rng.uniform(-9.0, -2.5),
                    }
                )
            elif kind == "rumble":
                audio_generated_layers.append(
                    {
                        "kind": kind,
                        "color": rng.choice(["brown", "pink"]),
                        "amplitude": rng.uniform(0.00018, 0.0014),
                        "highpass_hz": rng.randint(24, 80),
                        "lowpass_hz": rng.randint(160, 520),
                        "tremolo_hz": rng.uniform(0.10, 0.22),
                        "tremolo_depth": rng.uniform(0.12, 0.42),
                        "volume_db": rng.uniform(-10.0, -3.5),
                    }
                )
            elif kind == "tone":
                audio_generated_layers.append(
                    {
                        "kind": kind,
                        "frequency_hz": rng.choice([73, 82, 98, 147, 196, 294, 523, 659]),
                        "amplitude": rng.uniform(0.00008, 0.00065),
                        "tremolo_hz": rng.uniform(0.10, 0.45),
                        "tremolo_depth": rng.uniform(0.18, 0.70),
                        "volume_db": rng.uniform(-12.0, -4.0),
                    }
                )
            else:
                audio_generated_layers.append(
                    {
                        "kind": kind,
                        "color": rng.choice(["white", "pink", "violet"]),
                        "amplitude": rng.uniform(0.00012, 0.0012),
                        "highpass_hz": rng.randint(280, 1200),
                        "lowpass_hz": rng.randint(2400, 6800),
                        "tremolo_hz": rng.uniform(0.16, 0.85),
                        "tremolo_depth": rng.uniform(0.22, 0.68),
                        "volume_db": rng.uniform(-11.0, -3.0),
                    }
                )
    audio_harmonic_layers: list[dict[str, Any]] = []
    if stress_level >= 4:
        harmonic_count = rng.randint(1, 2)
        if stress_level >= 6:
            harmonic_count = rng.randint(2, 4)
        for _ in range(harmonic_count):
            pitch_factor = rng.choice(
                [
                    rng.uniform(0.925, 0.972),
                    rng.uniform(1.028, 1.085),
                    rng.uniform(0.965, 0.992),
                    rng.uniform(1.008, 1.038),
                ]
            )
            audio_harmonic_layers.append(
                {
                    "pitch_factor": pitch_factor,
                    "volume_db": rng.uniform(-24.0, -13.0),
                    "delay_ms": rng.uniform(5.0, 38.0),
                    "pan": rng.uniform(-0.62, 0.62),
                    "highpass_hz": rng.randint(120, 850),
                    "lowpass_hz": rng.randint(2600, 11500),
                }
            )
    audio_spectral_inversion_layers: list[dict[str, Any]] = []
    if stress_level >= 5:
        inversion_count = rng.randint(1, 2)
        if stress_level >= 6:
            inversion_count = rng.randint(2, 3)
        for _ in range(inversion_count):
            audio_spectral_inversion_layers.append(
                {
                    "carrier_hz": rng.choice([2400, 3200, 4100, 5200, 6400, 7800]),
                    "highpass_hz": rng.randint(120, 900),
                    "lowpass_hz": rng.randint(3600, 11800),
                    "volume_db": rng.uniform(-32.0, -18.0),
                    "delay_ms": rng.uniform(6.0, 46.0),
                    "pan": rng.uniform(-0.70, 0.70),
                }
            )
    audio_spectrogram_perturbation_layers: list[dict[str, Any]] = []
    if stress_level >= 4:
        perturb_count = rng.randint(1, 2)
        if stress_level >= 6:
            perturb_count = rng.randint(2, 4)
        for _ in range(perturb_count):
            center_hz = rng.choice([180, 260, 420, 700, 1100, 1800, 2900, 4700, 7600])
            width_hz = rng.randint(90, 980 if center_hz < 2000 else 1800)
            audio_spectrogram_perturbation_layers.append(
                {
                    "color": rng.choice(["white", "pink", "violet"]),
                    "amplitude": rng.uniform(0.00008, 0.0009),
                    "highpass_hz": max(20, center_hz - width_hz),
                    "lowpass_hz": min(16000, center_hz + width_hz),
                    "tremolo_hz": rng.uniform(0.35, 4.8),
                    "tremolo_depth": rng.uniform(0.28, 0.82),
                    "delay_ms": rng.uniform(0.0, 85.0),
                    "volume_db": rng.uniform(-28.0, -14.0),
                }
            )
    audio_chop_layers: list[dict[str, Any]] = []
    if stress_level >= 5 and info.duration >= 4.0:
        chop_count = rng.randint(1, 2)
        if stress_level >= 6 and info.duration >= 7.0:
            chop_count = rng.randint(2, 4)
        safe_duration = max(0.5, info.duration - 0.75)
        for _ in range(chop_count):
            segment_duration = rng.uniform(0.055, 0.22)
            audio_chop_layers.append(
                {
                    "start_seconds": rng.uniform(0.25, safe_duration),
                    "duration_seconds": min(segment_duration, max(0.04, safe_duration / 5)),
                    "delay_ms": rng.uniform(120.0, max(160.0, info.duration * 870.0)),
                    "volume_db": rng.uniform(-30.0, -16.0),
                    "reverse": rng.random() < 0.35,
                    "tempo": rng.uniform(0.92, 1.10),
                    "pan": rng.uniform(-0.85, 0.85),
                }
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
    if audio_codec_generations:
        operations.append(
            {
                "category": "audio",
                "name": "audio_codec_round_trip",
                "severity": audio_codec_generations,
            }
        )
    if audio_generated_layers:
        operations.append(
            {
                "category": "audio",
                "name": "random_low_volume_synthetic_audio_layers",
                "severity": len(audio_generated_layers),
            }
        )
    if audio_harmonic_layers:
        operations.append(
            {
                "category": "audio",
                "name": "parallel_multi_pitch_harmonic_layers",
                "severity": len(audio_harmonic_layers),
            }
        )
    if audio_spectral_inversion_layers:
        operations.append(
            {
                "category": "audio",
                "name": "low_volume_spectral_inversion_layers",
                "severity": len(audio_spectral_inversion_layers),
            }
        )
    if audio_spectrogram_perturbation_layers:
        operations.append(
            {
                "category": "audio",
                "name": "spectrogram_perturbation_noise_bands",
                "severity": len(audio_spectrogram_perturbation_layers),
            }
        )
    if audio_chop_layers:
        operations.append(
            {
                "category": "audio",
                "name": "micro_chop_reordered_audio_snippets",
                "severity": len(audio_chop_layers),
            }
        )
    if audio_spectral_eq_bands:
        operations.append(
            {
                "category": "audio",
                "name": "dense_spectral_analyzer_style_eq",
                "severity": len(audio_spectral_eq_bands),
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
    if stress_level >= 2:
        operations.append(
            {
                "category": "audio",
                "name": "low_volume_generated_noise_hum_tone_mix",
                "severity": "low",
            }
        )
        operations.append(
            {
                "category": "audio",
                "name": "phase_fft_tilt_stereo_spectral_processing",
                "severity": "medium",
            }
        )
    if stress_level >= 4:
        operations.append(
            {
                "category": "audio",
                "name": "optional_phaser_flanger_modulation",
                "severity": "medium",
            }
        )
        operations.append(
            {
                "category": "audio",
                "name": "room_convolution_spatial_codec_texture",
                "severity": "high",
            }
        )
    if stress_level >= 5:
        operations.append(
            {
                "category": "audio",
                "name": "rubberband_dynamic_eq_bit_sample_stress",
                "severity": "high",
            }
        )
        operations.append(
            {
                "category": "audio",
                "name": "frequency_shift_spectral_phase_stress",
                "severity": "high",
            }
        )
    audio_pitch_span = 0.0 if stress_level < 2 else 0.006 + stress_level * 0.0028
    audio_pitch_factor = rng.uniform(1.0 - audio_pitch_span, 1.0 + audio_pitch_span)
    audio_sample_rate = rng.choice(
        [44100, 48000]
        if stress_level < 3
        else [24000, 32000, 44100, 48000, 48000, 88200, 96000]
    )
    audio_echo_delay_ms = 0
    audio_echo_decay = 0.0
    if stress_level >= 4:
        audio_echo_delay_ms = rng.choice([0, 0, 18, 24, 32, 45, 64])
        audio_echo_decay = rng.uniform(0.025, 0.095) if audio_echo_delay_ms else 0.0
    audio_noise_amplitude = 0.0
    audio_hum_amplitude = 0.0
    audio_tone_amplitude = 0.0
    if stress_level >= 2:
        audio_noise_amplitude = rng.uniform(0.00065, 0.0025)
        audio_hum_amplitude = rng.choice([0.0, rng.uniform(0.00025, 0.0012)])
        audio_tone_amplitude = rng.choice([0.0, 0.0, rng.uniform(0.0002, 0.0009)])
    if stress_level >= 4:
        audio_noise_amplitude = rng.uniform(0.0008, 0.0045)
        audio_hum_amplitude = rng.choice([0.0, rng.uniform(0.0005, 0.0025)])
        audio_tone_amplitude = rng.choice([0.0, 0.0, rng.uniform(0.00035, 0.0016)])
    audio_flanger_enabled = stress_level >= 4 and rng.random() < 0.55
    audio_haas_enabled = stress_level >= 3 and rng.random() < 0.72
    audio_crossfeed_enabled = stress_level >= 4 and rng.random() < 0.55
    audio_dynamic_eq_enabled = stress_level >= 4 and rng.random() < 0.78
    audio_rubberband_enabled = stress_level >= 5 and rng.random() < 0.72
    audio_crusher_enabled = stress_level >= 4 and rng.random() < 0.58
    audio_frequency_shift_enabled = stress_level >= 5 and rng.random() < 0.82
    audio_dynaudnorm_enabled = stress_level >= 3 and rng.random() < 0.72
    audio_speechnorm_enabled = stress_level >= 5 and rng.random() < 0.42
    audio_room_enabled = stress_level >= 4 and rng.random() < 0.80
    audio_bed_noise_amplitude = 0.0
    if stress_level >= 4:
        audio_bed_noise_amplitude = rng.uniform(0.00035, 0.0023)
    if stress_level >= 6:
        audio_bed_noise_amplitude = rng.uniform(0.0008, 0.0040)

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
        audio_compressor_threshold_db=rng.uniform(-34.0, -10.0),
        audio_compressor_ratio=rng.uniform(1.12, 3.4 if stress_level >= 5 else 2.25),
        audio_eq_frequency_hz=rng.choice([120, 180, 240, 320, 480, 3600, 5200, 7200]),
        audio_eq_gain_db=rng.uniform(-3.0, 3.0),
        audio_eq2_frequency_hz=rng.choice([700, 950, 1400, 2200, 4200, 6800, 9200]),
        audio_eq2_gain_db=rng.uniform(-2.4, 2.4),
        audio_spectral_eq_bands=audio_spectral_eq_bands,
        audio_bass_gain_db=rng.uniform(-2.5, 2.5),
        audio_treble_gain_db=rng.uniform(-2.5, 2.5),
        audio_stereo_mix=rng.uniform(0.015, 0.105 if stress_level >= 4 else 0.055),
        audio_phase_invert_mix=(
            0.0 if stress_level < 3 else rng.uniform(0.010, 0.095 if stress_level >= 5 else 0.045)
        ),
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
        audio_tremolo_rate_hz=rng.uniform(0.10, 0.55),
        audio_tremolo_depth=0.0 if stress_level < 3 else rng.uniform(0.006, 0.035),
        audio_noise_color=rng.choice(["white", "pink", "brown"]),
        audio_noise_amplitude=audio_noise_amplitude,
        audio_hum_frequency_hz=rng.choice([50, 60, 100, 120]),
        audio_hum_amplitude=audio_hum_amplitude,
        audio_tone_frequency_hz=rng.choice([174, 220, 247, 330, 392, 440]),
        audio_tone_amplitude=audio_tone_amplitude,
        audio_fft_noise_reduction=(
            0.01 if stress_level < 2 else rng.uniform(1.4, 6.5 if stress_level >= 4 else 4.2)
        ),
        audio_fft_noise_floor=rng.uniform(-64.0, -38.0),
        audio_phase_shift=0.0 if stress_level < 2 else rng.uniform(-0.18, 0.18),
        audio_phase_order=rng.choice([4, 6, 8, 10, 12]),
        audio_frequency_shift_enabled=audio_frequency_shift_enabled,
        audio_frequency_shift_hz=rng.choice(
            [
                rng.uniform(-18.0, -4.0),
                rng.uniform(4.0, 18.0),
                rng.uniform(-42.0, -16.0),
                rng.uniform(16.0, 42.0),
            ]
        ),
        audio_frequency_shift_level=rng.uniform(0.82, 0.97),
        audio_tilt_frequency_hz=rng.choice([1800, 2600, 4200, 6200, 9000]),
        audio_tilt_slope=0.0 if stress_level < 2 else rng.uniform(-0.18, 0.18),
        audio_crystalizer_intensity=(
            0.0 if stress_level < 2 else rng.uniform(-0.45, 0.75)
        ),
        audio_extra_stereo_mult=1.0 if stress_level < 2 else rng.uniform(0.72, 1.58),
        audio_phaser_delay_ms=0.0 if stress_level < 4 else rng.uniform(0.6, 2.8),
        audio_phaser_decay=0.0 if stress_level < 4 else rng.uniform(0.05, 0.22),
        audio_phaser_speed=0.1 if stress_level < 4 else rng.uniform(0.12, 0.65),
        audio_flanger_enabled=audio_flanger_enabled,
        audio_flanger_delay_ms=rng.uniform(0.4, 2.5),
        audio_flanger_depth_ms=rng.uniform(0.4, 2.8),
        audio_flanger_width=rng.uniform(8.0, 26.0),
        audio_flanger_speed=rng.uniform(0.10, 0.42),
        audio_haas_enabled=audio_haas_enabled,
        audio_haas_left_delay_ms=rng.uniform(1.2, 9.5),
        audio_haas_right_delay_ms=rng.uniform(1.2, 11.5),
        audio_haas_side_gain=rng.uniform(0.55, 1.38),
        audio_crossfeed_enabled=audio_crossfeed_enabled,
        audio_crossfeed_strength=rng.uniform(0.08, 0.36),
        audio_crossfeed_range=rng.uniform(0.18, 0.78),
        audio_dynamic_eq_enabled=audio_dynamic_eq_enabled,
        audio_dynamic_eq_frequency_hz=rng.choice([180, 260, 420, 900, 1800, 3200, 5200]),
        audio_dynamic_eq_ratio=rng.uniform(0.35, 2.4),
        audio_dynamic_eq_range=rng.uniform(2.0, 9.0),
        audio_dynamic_eq_mode=rng.choice(["cutbelow", "cutabove", "boostbelow", "boostabove"]),
        audio_rubberband_enabled=audio_rubberband_enabled,
        audio_rubberband_tempo=rng.uniform(0.992, 1.010),
        audio_rubberband_pitch=rng.uniform(0.982, 1.022),
        audio_crusher_enabled=audio_crusher_enabled,
        audio_crusher_bits=rng.uniform(7.5 if stress_level >= 6 else 10.5, 15.5),
        audio_crusher_samples=rng.uniform(1.0, 4.8 if stress_level >= 6 else 2.8),
        audio_crusher_mix=rng.uniform(0.018, 0.145 if stress_level >= 6 else 0.085),
        audio_dynaudnorm_enabled=audio_dynaudnorm_enabled,
        audio_dynaudnorm_frame_ms=rng.choice([80, 120, 160, 240, 320]),
        audio_dynaudnorm_compress=rng.uniform(1.2, 5.0),
        audio_speechnorm_enabled=audio_speechnorm_enabled,
        audio_room_enabled=audio_room_enabled,
        audio_room_wet=rng.uniform(0.035, 0.16),
        audio_room_decay=rng.uniform(0.18, 0.58),
        audio_room_tail_ms=rng.choice([55, 80, 110, 150, 220]),
        audio_bed_noise_amplitude=audio_bed_noise_amplitude,
        audio_bed_mod_frequency_hz=rng.uniform(0.10, 0.18),
        audio_generated_layers=audio_generated_layers,
        audio_harmonic_layers=audio_harmonic_layers,
        audio_spectral_inversion_layers=audio_spectral_inversion_layers,
        audio_spectrogram_perturbation_layers=audio_spectrogram_perturbation_layers,
        audio_chop_layers=audio_chop_layers,
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
        audio_codec_generations=audio_codec_generations,
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
    phase_keep = 1.0 - plan.audio_phase_invert_mix
    phase_flip = plan.audio_phase_invert_mix
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
        *spectral_eq_filters(plan),
        (
            "pan=stereo|"
            f"c0={left_mix:.5f}*c0+{cross_mix:.5f}*c1|"
            f"c1={cross_mix:.5f}*c0+{left_mix:.5f}*c1"
        ),
        (
            "pan=stereo|"
            f"c0={phase_keep:.5f}*c0-{phase_flip:.5f}*c1|"
            f"c1={phase_keep:.5f}*c1-{phase_flip:.5f}*c0"
        ),
        (
            f"afftdn=nr={plan.audio_fft_noise_reduction:.5f}:"
            f"nf={plan.audio_fft_noise_floor:.5f}:tn=1:gs=6"
        ),
        (
            f"aphaseshift=shift={plan.audio_phase_shift:.5f}:"
            f"level=0.985:order={plan.audio_phase_order}"
        ),
        (
            f"atilt=freq={plan.audio_tilt_frequency_hz}:"
            f"slope={plan.audio_tilt_slope:.5f}:width=1800:order=5:level=1"
        ),
        f"crystalizer=i={plan.audio_crystalizer_intensity:.5f}:c=0",
        f"extrastereo=m={plan.audio_extra_stereo_mult:.5f}:c=0",
        f"asetrate={48000 * plan.audio_pitch_factor:.3f}",
        (
            f"aresample={plan.audio_sample_rate}:async=1:first_pts=0:resampler=soxr:"
            f"precision=20:dither_method={plan.audio_dither_method}"
        ),
        f"atempo={pitch_inverse:.8f}",
        "aresample=48000:async=1:first_pts=0:resampler=soxr:precision=20",
        f"volume={plan.audio_volume_db:.3f}dB",
    ]
    if plan.audio_dynamic_eq_enabled:
        filters.append(
            "adynamicequalizer="
            f"threshold=0:"
            f"dfrequency={plan.audio_dynamic_eq_frequency_hz}:"
            "dqfactor=1.6:"
            f"tfrequency={plan.audio_dynamic_eq_frequency_hz}:"
            "tqfactor=1.2:"
            "attack=18:release=180:"
            f"ratio={plan.audio_dynamic_eq_ratio:.5f}:"
            f"range={plan.audio_dynamic_eq_range:.5f}:"
            f"mode={plan.audio_dynamic_eq_mode}:"
            "auto=adaptive"
        )
    if plan.audio_frequency_shift_enabled:
        filters.append(
            "afreqshift="
            f"shift={plan.audio_frequency_shift_hz:.5f}:"
            f"level={plan.audio_frequency_shift_level:.5f}:"
            f"order={plan.audio_phase_order}"
        )
    if plan.audio_dynaudnorm_enabled:
        filters.append(
            "dynaudnorm="
            f"f={plan.audio_dynaudnorm_frame_ms}:"
            "g=15:p=0.92:m=6:"
            f"s={plan.audio_dynaudnorm_compress:.5f}:"
            "t=0.012:c=1"
        )
    if plan.audio_speechnorm_enabled:
        filters.append(
            "speechnorm=p=0.90:e=1.45:c=1.35:t=0.012:r=0.0007:f=0.0009:l=1"
        )
    if plan.audio_crossfeed_enabled:
        filters.append(
            "crossfeed="
            f"strength={plan.audio_crossfeed_strength:.5f}:"
            f"range={plan.audio_crossfeed_range:.5f}:"
            "slope=0.55:level_in=0.92:level_out=1"
        )
    if plan.audio_haas_enabled:
        filters.append(
            "haas="
            "level_in=0.94:level_out=0.96:"
            f"side_gain={plan.audio_haas_side_gain:.5f}:"
            f"left_delay={plan.audio_haas_left_delay_ms:.5f}:"
            f"right_delay={plan.audio_haas_right_delay_ms:.5f}:"
            "left_balance=-0.82:right_balance=0.82:"
            "middle_source=mid:middle_phase=false:right_phase=true"
        )
    if plan.audio_rubberband_enabled:
        filters.append(
            "rubberband="
            f"tempo={plan.audio_rubberband_tempo:.8f}:"
            f"pitch={plan.audio_rubberband_pitch:.8f}:"
            "transients=mixed:detector=compound:phase=independent:"
            "window=short:smoothing=on:formant=preserved:pitchq=quality:channels=together"
        )
    if plan.audio_crusher_enabled:
        filters.append(
            "acrusher="
            "level_in=1:level_out=1:"
            f"bits={plan.audio_crusher_bits:.5f}:"
            f"samples={plan.audio_crusher_samples:.5f}:"
            f"mix={plan.audio_crusher_mix:.5f}:"
            "mode=log:aa=0.82:lfo=1:lforange=3:lforate=0.11"
        )
    if plan.audio_tremolo_depth:
        filters.append(
            f"tremolo=f={plan.audio_tremolo_rate_hz:.5f}:d={plan.audio_tremolo_depth:.5f}"
        )
    if plan.audio_phaser_decay:
        filters.append(
            "aphaser="
            "in_gain=0.72:out_gain=0.88:"
            f"delay={plan.audio_phaser_delay_ms:.5f}:"
            f"decay={plan.audio_phaser_decay:.5f}:"
            f"speed={plan.audio_phaser_speed:.5f}:type=s"
        )
    if plan.audio_flanger_enabled:
        filters.append(
            "flanger="
            f"delay={plan.audio_flanger_delay_ms:.5f}:"
            f"depth={plan.audio_flanger_depth_ms:.5f}:"
            "regen=0:"
            f"width={plan.audio_flanger_width:.5f}:"
            f"speed={plan.audio_flanger_speed:.5f}:"
            "shape=sinusoidal:phase=25:interp=linear"
        )
    filters.extend(
        [
        f"alimiter=level_in=1:level_out={plan.audio_limiter_level:.5f}:limit=0.98",
        f"atempo={plan.speed:.8f}",
        ]
    )
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


def spectral_eq_filters(plan: TransformPlan) -> list[str]:
    filters: list[str] = []
    for band in plan.audio_spectral_eq_bands:
        frequency_hz = int(band.get("frequency_hz") or 1000)
        width = float(band.get("width") or 1.0)
        gain_db = float(band.get("gain_db") or 0.0)
        filters.append(
            f"equalizer=f={frequency_hz}:width_type=o:width={width:.5f}:g={gain_db:.5f}"
        )
    return filters


def write_audio_impulse_response(path: Path, plan: TransformPlan) -> None:
    sample_rate = 48000
    sample_count = max(128, int(sample_rate * plan.audio_room_tail_ms / 1000))
    rng = random.Random(plan.seed ^ (plan.attempt * 104729) ^ 0xA17D10)
    taps = [
        0,
        int(sample_rate * rng.uniform(0.006, 0.018)),
        int(sample_rate * rng.uniform(0.024, 0.055)),
    ]
    max_amp = 0.78
    frames = bytearray()
    for index in range(sample_count):
        envelope = math.exp(-index / max(1.0, sample_count * plan.audio_room_decay))
        left = 0.0
        right = 0.0
        if index == 0:
            left += 1.0
            right += 1.0
        for tap_number, tap in enumerate(taps[1:], start=1):
            if index == tap:
                amp = envelope * rng.uniform(0.22, 0.52) / tap_number
                left += amp
                right += amp * rng.uniform(0.72, 1.18)
        if index > taps[0] and rng.random() < 0.18:
            noise = envelope * rng.uniform(-0.018, 0.018)
            left += noise
            right -= noise * rng.uniform(0.35, 0.85)
        left_int = int(max(-1.0, min(1.0, left * max_amp)) * 32767)
        right_int = int(max(-1.0, min(1.0, right * max_amp)) * 32767)
        frames.extend(left_int.to_bytes(2, "little", signed=True))
        frames.extend(right_int.to_bytes(2, "little", signed=True))

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(bytes(frames))


def generated_audio_layer_filter(layer: dict[str, Any], duration: float, label: str) -> str:
    kind = str(layer.get("kind") or "texture")
    amplitude = float(layer.get("amplitude") or 0.0003)
    tremolo_hz = max(0.10, float(layer.get("tremolo_hz") or 0.2))
    tremolo_depth = max(0.0, min(0.95, float(layer.get("tremolo_depth") or 0.3)))
    volume_db = float(layer.get("volume_db") or -6.0)
    if kind == "tone":
        frequency_hz = int(layer.get("frequency_hz") or 196)
        return (
            "sine="
            f"frequency={frequency_hz}:sample_rate=48000:duration={duration:.5f},"
            f"volume={amplitude:.7f},"
            f"tremolo=f={tremolo_hz:.6f}:d={tremolo_depth:.5f},"
            f"volume={volume_db:.5f}dB,"
            f"asetpts=PTS-STARTPTS[{label}]"
        )

    color = str(layer.get("color") or "pink")
    highpass_hz = int(layer.get("highpass_hz") or 160)
    lowpass_hz = int(layer.get("lowpass_hz") or 6200)
    return (
        "anoisesrc="
        f"color={color}:amplitude={amplitude:.7f}:"
        f"sample_rate=48000:duration={duration:.5f},"
        f"highpass=f={highpass_hz},lowpass=f={lowpass_hz},"
        f"tremolo=f={tremolo_hz:.6f}:d={tremolo_depth:.5f},"
        f"volume={volume_db:.5f}dB,"
        f"asetpts=PTS-STARTPTS[{label}]"
    )


def harmonic_audio_layer_filter(layer: dict[str, Any], duration: float, label: str) -> str:
    pitch_factor = max(0.72, min(1.35, float(layer.get("pitch_factor") or 1.0)))
    pitch_inverse = 1.0 / pitch_factor
    volume_db = float(layer.get("volume_db") or -18.0)
    delay_ms = max(0.0, float(layer.get("delay_ms") or 0.0))
    pan = max(-0.95, min(0.95, float(layer.get("pan") or 0.0)))
    highpass_hz = int(layer.get("highpass_hz") or 180)
    lowpass_hz = int(layer.get("lowpass_hz") or 7200)
    left_gain = 1.0 - max(0.0, pan)
    right_gain = 1.0 + min(0.0, pan)
    return (
        "[0:a:0]"
        "aformat=sample_fmts=fltp:channel_layouts=stereo,"
        "aresample=48000:async=1:first_pts=0:resampler=soxr:precision=20,"
        f"highpass=f={highpass_hz},lowpass=f={lowpass_hz},"
        f"asetrate={48000 * pitch_factor:.5f},"
        "aresample=48000:async=1:first_pts=0:resampler=soxr:precision=20,"
        f"atempo={pitch_inverse:.8f},"
        f"adelay={delay_ms:.5f}:all=1,"
        f"volume={volume_db:.5f}dB,"
        "pan=stereo|"
        f"c0={left_gain:.5f}*c0|"
        f"c1={right_gain:.5f}*c1,"
        f"atrim=duration={duration:.5f},asetpts=PTS-STARTPTS[{label}]"
    )


def spectral_inversion_layer_filter(layer: dict[str, Any], duration: float, label: str) -> str:
    carrier_hz = int(layer.get("carrier_hz") or 4100)
    highpass_hz = int(layer.get("highpass_hz") or 180)
    lowpass_hz = int(layer.get("lowpass_hz") or 7200)
    volume_db = float(layer.get("volume_db") or -24.0)
    delay_ms = max(0.0, float(layer.get("delay_ms") or 0.0))
    pan = max(-0.95, min(0.95, float(layer.get("pan") or 0.0)))
    left_gain = 1.0 - max(0.0, pan)
    right_gain = 1.0 + min(0.0, pan)
    source_label = f"{label}src"
    oscillator_label = f"{label}osc"
    return (
        "[0:a:0]"
        "aformat=sample_fmts=fltp:channel_layouts=stereo,"
        "aresample=48000:async=1:first_pts=0:resampler=soxr:precision=20,"
        f"highpass=f={highpass_hz},lowpass=f={lowpass_hz},"
        f"atrim=duration={duration:.5f},asetpts=PTS-STARTPTS[{source_label}];"
        "sine="
        f"frequency={carrier_hz}:sample_rate=48000:duration={duration:.5f},"
        "pan=stereo|c0=c0|c1=c0,"
        f"asetpts=PTS-STARTPTS[{oscillator_label}];"
        f"[{source_label}][{oscillator_label}]"
        "amultiply,"
        "aformat=sample_fmts=fltp:channel_layouts=stereo,"
        "highpass=f=90,lowpass=f=14500,"
        f"adelay={delay_ms:.3f}:all=1,"
        f"volume={volume_db:.5f}dB,"
        "pan=stereo|"
        f"c0={left_gain:.5f}*c0|"
        f"c1={right_gain:.5f}*c1,"
        f"atrim=duration={duration:.5f},asetpts=PTS-STARTPTS[{label}]"
    )


def spectrogram_perturbation_layer_filter(
    layer: dict[str, Any],
    duration: float,
    label: str,
) -> str:
    color = str(layer.get("color") or "pink")
    amplitude = float(layer.get("amplitude") or 0.00025)
    highpass_hz = int(layer.get("highpass_hz") or 300)
    lowpass_hz = int(layer.get("lowpass_hz") or 4000)
    tremolo_hz = max(0.1, float(layer.get("tremolo_hz") or 1.4))
    tremolo_depth = max(0.0, min(0.95, float(layer.get("tremolo_depth") or 0.45)))
    delay_ms = max(0.0, float(layer.get("delay_ms") or 0.0))
    volume_db = float(layer.get("volume_db") or -20.0)
    return (
        "anoisesrc="
        f"color={color}:amplitude={amplitude:.7f}:"
        f"sample_rate=48000:duration={duration:.5f},"
        f"highpass=f={highpass_hz},lowpass=f={lowpass_hz},"
        f"tremolo=f={tremolo_hz:.6f}:d={tremolo_depth:.5f},"
        f"adelay={delay_ms:.3f}:all=1,"
        f"volume={volume_db:.5f}dB,"
        f"atrim=duration={duration:.5f},asetpts=PTS-STARTPTS[{label}]"
    )


def chopped_audio_layer_filter(layer: dict[str, Any], duration: float, label: str) -> str:
    start_seconds = max(0.0, float(layer.get("start_seconds") or 0.0))
    segment_duration = max(0.025, float(layer.get("duration_seconds") or 0.08))
    delay_ms = max(0.0, float(layer.get("delay_ms") or 0.0))
    volume_db = float(layer.get("volume_db") or -22.0)
    tempo = max(0.5, min(2.0, float(layer.get("tempo") or 1.0)))
    pan = max(-0.95, min(0.95, float(layer.get("pan") or 0.0)))
    left_gain = 1.0 - max(0.0, pan)
    right_gain = 1.0 + min(0.0, pan)
    reverse_filter = "areverse," if bool(layer.get("reverse")) else ""
    return (
        "[0:a:0]"
        "aformat=sample_fmts=fltp:channel_layouts=stereo,"
        "aresample=48000:async=1:first_pts=0:resampler=soxr:precision=20,"
        f"atrim=start={start_seconds:.5f}:duration={segment_duration:.5f},"
        "asetpts=PTS-STARTPTS,"
        f"{reverse_filter}"
        f"atempo={tempo:.8f},"
        f"adelay={delay_ms:.3f}:all=1,"
        f"volume={volume_db:.5f}dB,"
        "pan=stereo|"
        f"c0={left_gain:.5f}*c0|"
        f"c1={right_gain:.5f}*c1,"
        f"atrim=duration={duration:.5f},asetpts=PTS-STARTPTS[{label}]"
    )


def audio_filter_graph(
    plan: TransformPlan,
    duration_seconds: float,
    ir_input_index: int | None = None,
) -> str:
    duration = max(0.5, duration_seconds + 2.0)
    parts = [f"[0:a:0]{audio_filter(plan)}[a0base]"]
    if ir_input_index is not None:
        parts.extend(
            [
                (
                    f"[{ir_input_index}:a:0]"
                    "aformat=sample_fmts=fltp:channel_layouts=stereo,"
                    "aresample=48000:async=1:first_pts=0[air]"
                ),
                (
                    "[a0base][air]"
                    f"afir=dry=1:wet={plan.audio_room_wet:.5f}:"
                    "gtype=none:irfmt=input:maxir=1:precision=float,"
                    f"alimiter=level_in=1:level_out={plan.audio_limiter_level:.5f}:limit=0.98"
                    "[a0]"
                ),
            ]
        )
    else:
        parts.append("[a0base]anull[a0]")
    mix_inputs = ["[a0]"]
    if plan.audio_noise_amplitude:
        parts.append(
            "anoisesrc="
            f"color={plan.audio_noise_color}:"
            f"amplitude={plan.audio_noise_amplitude:.7f}:"
            f"sample_rate=48000:duration={duration:.5f},"
            "asetpts=PTS-STARTPTS[anoise]"
        )
        mix_inputs.append("[anoise]")
    if plan.audio_hum_amplitude:
        parts.append(
            "sine="
            f"frequency={plan.audio_hum_frequency_hz}:"
            f"sample_rate=48000:duration={duration:.5f},"
            f"volume={plan.audio_hum_amplitude:.7f},"
            "asetpts=PTS-STARTPTS[ahum]"
        )
        mix_inputs.append("[ahum]")
    if plan.audio_tone_amplitude:
        parts.append(
            "sine="
            f"frequency={plan.audio_tone_frequency_hz}:"
            f"sample_rate=48000:duration={duration:.5f},"
            f"volume={plan.audio_tone_amplitude:.7f},"
            "asetpts=PTS-STARTPTS[atone]"
        )
        mix_inputs.append("[atone]")
    if plan.audio_bed_noise_amplitude:
        parts.append(
            "anoisesrc="
            "color=violet:"
            f"amplitude={plan.audio_bed_noise_amplitude:.7f}:"
            f"sample_rate=48000:duration={duration:.5f},"
            "highpass=f=180,lowpass=f=6200,"
            f"tremolo=f={plan.audio_bed_mod_frequency_hz:.6f}:d=0.45,"
            "asetpts=PTS-STARTPTS[abed]"
        )
        mix_inputs.append("[abed]")
    for index, layer in enumerate(plan.audio_generated_layers):
        label = f"alayer{index}"
        parts.append(generated_audio_layer_filter(layer, duration, label))
        mix_inputs.append(f"[{label}]")
    for index, layer in enumerate(plan.audio_harmonic_layers):
        label = f"aharm{index}"
        parts.append(harmonic_audio_layer_filter(layer, duration, label))
        mix_inputs.append(f"[{label}]")
    for index, layer in enumerate(plan.audio_spectral_inversion_layers):
        label = f"ainvert{index}"
        parts.append(spectral_inversion_layer_filter(layer, duration, label))
        mix_inputs.append(f"[{label}]")
    for index, layer in enumerate(plan.audio_spectrogram_perturbation_layers):
        label = f"aperturb{index}"
        parts.append(spectrogram_perturbation_layer_filter(layer, duration, label))
        mix_inputs.append(f"[{label}]")
    for index, layer in enumerate(plan.audio_chop_layers):
        label = f"achop{index}"
        parts.append(chopped_audio_layer_filter(layer, duration, label))
        mix_inputs.append(f"[{label}]")
    if len(mix_inputs) == 1:
        parts.append("[a0]anull[aout]")
    else:
        parts.append(
            "".join(mix_inputs)
            + f"amix=inputs={len(mix_inputs)}:duration=first:"
            "dropout_transition=0:normalize=0,"
            f"alimiter=level_in=1:level_out={plan.audio_limiter_level:.5f}:limit=0.98"
            "[aout]"
        )
    return ";".join(parts)


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


def audio_codec_generation(
    input_path: Path,
    output_path: Path,
    codec: str,
    plan: TransformPlan,
    generation: int,
) -> None:
    bitrate = {
        "libopus": "80k",
        "libmp3lame": "112k",
        "aac": plan.audio_bitrate,
    }.get(codec, plan.audio_bitrate)
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
        "-c:v",
        "copy",
        "-map",
        "0:a?",
        "-c:a",
        codec,
    ]
    if codec == "libopus":
        command.extend(
            [
                "-application",
                "audio",
                "-vbr",
                "on",
                "-compression_level",
                "10",
            ]
        )
    elif codec == "libmp3lame":
        command.extend(["-compression_level", str(min(6, 2 + generation))])
    command.extend(
        [
            "-b:a",
            bitrate,
            "-ar",
            "48000",
            "-ac",
            "2",
            "-avoid_negative_ts",
            "make_zero",
            str(output_path),
        ]
    )
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
    if info.has_audio:
        for generation, codec in enumerate(plan.audio_codec_generations, start=1):
            generation_path = output_path.with_name(
                f"{output_path.stem}.audio_generation_{generation}.mkv"
            )
            audio_codec_generation(source_path, generation_path, codec, plan, generation)
            generation_paths.append(generation_path)
            source_path = generation_path
    ir_path: Path | None = None
    if info.has_audio and plan.audio_room_enabled:
        ir_path = output_path.with_name(f"{output_path.stem}.room_ir.wav")
        write_audio_impulse_response(ir_path, plan)
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-i",
        str(source_path),
    ]
    ir_input_index: int | None = None
    if ir_path is not None:
        command.extend(["-i", str(ir_path)])
        ir_input_index = 1
    command.extend(
        [
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        ]
    )
    if info.has_audio:
        command.extend(
            [
                "-filter_complex",
                (
                    f"[0:v:0]{video_filter(plan)}[vout];"
                    f"{audio_filter_graph(plan, info.duration, ir_input_index=ir_input_index)}"
                ),
                "-map",
                "[vout]",
                "-map",
                "[aout]",
            ]
        )
    else:
        command.extend(["-vf", video_filter(plan), "-map", "0:v:0", "-an"])
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
        if ir_path is not None:
            ir_path.unlink(missing_ok=True)
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
