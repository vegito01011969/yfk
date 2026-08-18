from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from viral_pipeline.config import Settings
from viral_pipeline.domain import (
    ClipCandidate,
    ContentEvent,
    PipelineContext,
    PublishPackage,
    RenderAsset,
    StageName,
    YouTubeUploadResult,
    YouTubeVideo,
)
from viral_pipeline.providers import (
    MediaProvider,
    ScriptProvider,
    TrendProvider,
    VideoDownloadProvider,
    VoiceProvider,
    YouTubeProvider,
)
from viral_pipeline.source_history import SourceHistory

LOGGER = logging.getLogger(__name__)

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_BOT_WALL_MARKERS = (
    "sign in to confirm you",
    "not a bot",
)


def _called_process_output(exc: subprocess.CalledProcessError) -> str:
    return "\n".join(
        str(part)
        for part in (getattr(exc, "stdout", None), getattr(exc, "stderr", None))
        if part
    )


def _is_youtube_bot_wall(exc: BaseException) -> bool:
    if isinstance(exc, subprocess.CalledProcessError):
        haystack = f"{exc} {_called_process_output(exc)}".lower()
    else:
        haystack = str(exc).lower()
    return all(marker in haystack for marker in YOUTUBE_BOT_WALL_MARKERS)


def _dedupe_videos(videos: list[YouTubeVideo]) -> list[YouTubeVideo]:
    seen: set[str] = set()
    unique: list[YouTubeVideo] = []
    for video in videos:
        if video.id in seen:
            continue
        seen.add(video.id)
        unique.append(video)
    return unique


def _clip_hash_distance(left: str, right: str) -> int:
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return 64 if left != right else 0


def _clip_visual_hash(path: Path) -> str | None:
    if not path.exists() or path.suffix.lower() != ".mp4":
        return None
    media = _probe_clip_media(path)
    duration = float(media.get("duration_seconds") or 0.0)
    sample_times = [max(0.1, duration * fraction) for fraction in (0.25, 0.5, 0.75)]
    hashes: list[str] = []
    for sample_time in sample_times:
        frame_hash = _clip_frame_hash(path, sample_time)
        if frame_hash:
            hashes.append(frame_hash)
    return "".join(hashes) if hashes else None


def _clip_frame_hash(path: Path, sample_time: float) -> str | None:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{sample_time:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "scale=8:8:force_original_aspect_ratio=decrease,pad=8:8:-1:-1,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0 or len(result.stdout) < 64:
        return None
    pixels = result.stdout[:64]
    average = sum(pixels) / len(pixels)
    bits = "".join("1" if pixel >= average else "0" for pixel in pixels)
    return f"{int(bits, 2):016x}"


def _probe_clip_media(path: Path) -> dict[str, Any]:
    if not path.exists() or path.suffix.lower() != ".mp4":
        return {}
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}

    streams = payload.get("streams", [])
    video_stream: dict[str, Any] = next(
        (stream for stream in streams if stream.get("codec_type") == "video"), {}
    )
    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    return {
        "duration_seconds": float(payload.get("format", {}).get("duration") or 0.0),
        "width": int(video_stream.get("width") or 0),
        "height": int(video_stream.get("height") or 0),
        "has_audio": has_audio,
    }


def _clip_quality_score(clip: ClipCandidate, media: dict[str, Any]) -> float:
    duration = float(media.get("duration_seconds") or clip.duration_seconds)
    width = int(media.get("width") or 0)
    height = int(media.get("height") or 0)
    has_audio = bool(media.get("has_audio", True))
    duration_score = min(1.0, duration / 10.0)
    resolution_score = min(1.0, (width * height) / (1280 * 720)) if width and height else 0.6
    audio_score = 1.0 if has_audio else 0.65
    source_score = 1.0 if clip.metadata.get("segment_source") == "scene_boundary" else 0.72
    base = clip.quality_score or 0.5
    return round(
        base * 0.2
        + duration_score * 0.25
        + resolution_score * 0.25
        + audio_score * 0.15
        + source_score * 0.15,
        4,
    )


def _keywords(settings: Settings) -> list[str]:
    return [
        keyword.strip().lower()
        for keyword in settings.event_keywords.split(",")
        if keyword.strip()
    ]


def _source_video(context: PipelineContext, clip: ClipCandidate) -> YouTubeVideo | None:
    return next((video for video in context.analyzed_videos if video.id == clip.video_id), None)


def _event_terms(text: str, settings: Settings) -> list[str]:
    lowered = text.lower()
    return [keyword for keyword in _keywords(settings) if keyword in lowered]


def _event_key_for_clip(context: PipelineContext, clip: ClipCandidate, settings: Settings) -> str:
    source = _source_video(context, clip)
    title = source.title if source else clip.title
    terms = _event_terms(f"{title} {clip.title}", settings)
    terms_key = "-".join(terms[:2]) if terms else "moment"
    if clip.perceptual_hash:
        return f"visual:{clip.perceptual_hash[:16]}"
    bucket = int(clip.start_seconds // 30)
    return f"{terms_key}:time:{bucket}"


def _event_title(event_key: str, clips: list[ClipCandidate], context: PipelineContext) -> str:
    first = clips[0]
    source = _source_video(context, first)
    if source:
        return source.title
    return first.title


def _default_script_timeline(
    script: Any, clips: list[ClipCandidate]
) -> list[dict[str, Any]]:
    return [
        {"type": "intro", "narration": script.hook},
        *[
            {
                "type": "clip",
                "clip_id": clip.id,
                "clip_path": str(clip.path) if clip.path else None,
                "source_video_id": clip.video_id,
                "duration_seconds": clip.duration_seconds,
                "narration": script.body[index] if index < len(script.body) else clip.title,
            }
            for index, clip in enumerate(clips)
        ],
        {"type": "outro", "narration": script.outro},
    ]


def _ordered_clips_from_timeline(
    timeline: list[dict[str, Any]], clips: list[ClipCandidate]
) -> list[ClipCandidate]:
    clips_by_id = {clip.id: clip for clip in clips}
    ordered: list[ClipCandidate] = []
    for item in timeline:
        clip_id = item.get("clip_id")
        if isinstance(clip_id, str) and clip_id in clips_by_id:
            ordered.append(clips_by_id[clip_id])
    remaining = [clip for clip in clips if clip.id not in {item.id for item in ordered}]
    return [*ordered, *remaining]


def _concat_file_line(path: Path) -> str:
    escaped = str(path.resolve()).replace("'", "'\\''")
    return f"file '{escaped}'\n"


def _run_render_command(command: list[str], settings: Settings) -> None:
    subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=settings.render_command_timeout_seconds,
    )


def _render_final_video(context: PipelineContext, settings: Settings, render_dir: Path) -> Path:
    if context.script is None:
        raise ValueError("Cannot render final video before script generation")

    timeline = context.script.metadata.get("timeline", [])
    ordered_clips = _ordered_clips_from_timeline(
        timeline if isinstance(timeline, list) else [], context.selected_clips
    )
    media_clips = [
        clip
        for clip in ordered_clips
        if clip.path and clip.path.exists() and clip.path.suffix == ".mp4"
    ]
    if not media_clips:
        raise ValueError("No rendered clip files available for assembly")

    if settings.render_mode == "numbered_compilation":
        rendered_path = _render_numbered_compilation(context, settings, render_dir, media_clips)
        return _apply_provenance_transform_if_enabled(rendered_path, settings, render_dir)

    segment_dir = render_dir / "segments"
    segment_dir.mkdir(parents=True, exist_ok=True)
    normalized_paths: list[Path] = []
    for index, clip in enumerate(media_clips):
        normalized_path = segment_dir / f"{index:03d}_{clip.id}.mp4"
        _normalize_clip_for_render(clip.path, normalized_path, settings)
        normalized_paths.append(normalized_path)

    concat_path = render_dir / "concat.txt"
    concat_path.write_text(
        "".join(_concat_file_line(path) for path in normalized_paths),
        encoding="utf-8",
    )
    stitched_path = render_dir / "stitched_video.mp4"
    _run_render_command(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-c",
            "copy",
            str(stitched_path),
        ],
        settings,
    )

    final_path = render_dir / "final_video.mp4"
    voiceover_suffixes = {".mp3", ".wav", ".m4a", ".aiff"}
    if context.voiceover and context.voiceover.path.suffix.lower() in voiceover_suffixes:
        _mux_voiceover(stitched_path, context.voiceover.path, final_path, settings)
    else:
        stitched_path.replace(final_path)
    return _apply_provenance_transform_if_enabled(final_path, settings, render_dir)


def _apply_provenance_transform_if_enabled(
    input_path: Path,
    settings: Settings,
    render_dir: Path,
) -> Path:
    if not settings.apply_provenance_transform:
        return input_path

    script_path = settings.provenance_transform_script
    if not script_path.is_absolute():
        script_path = Path.cwd() / script_path
    if not script_path.exists():
        raise FileNotFoundError(f"Provenance transform script not found: {script_path}")

    transformed_path = render_dir / "final_video.mp4"
    source_path = render_dir / "pre_provenance_final_video.mp4"
    if input_path.resolve() == transformed_path.resolve():
        input_path.replace(source_path)
    else:
        source_path = input_path

    try:
        subprocess.run(
            [
                sys.executable,
                str(script_path),
                str(source_path),
                "--output",
                str(transformed_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=settings.provenance_transform_timeout_seconds,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        debug_path = transformed_path.with_suffix(transformed_path.suffix + ".debug.json")
        details = (
            _called_process_output(exc)[-3000:]
            if isinstance(exc, subprocess.CalledProcessError)
            else str(exc)
        )
        if debug_path.exists():
            debug_text = debug_path.read_text(encoding="utf-8")[-3000:]
            details = f"{details}\nTransform debug:\n{debug_text}"
        if settings.provenance_transform_fail_open:
            shutil.copy2(source_path, transformed_path)
            fallback_debug = {
                "status": "provenance_transform_failed_open",
                "error": details,
                "source_path": str(source_path),
                "output_path": str(transformed_path),
            }
            debug_path.write_text(json.dumps(fallback_debug, indent=2), encoding="utf-8")
            LOGGER.warning(
                "Provenance transform failed; using pre-provenance render: %s",
                details[-1000:],
            )
            return transformed_path
        raise RuntimeError(
            f"Provenance transform failed for {source_path}. {details}"
        ) from exc
    return transformed_path


def _render_numbered_compilation(
    context: PipelineContext,
    settings: Settings,
    render_dir: Path,
    media_clips: list[ClipCandidate],
) -> Path:
    segment_dir = render_dir / "segments"
    segment_dir.mkdir(parents=True, exist_ok=True)

    title_card_path = segment_dir / "000_title_card.mp4"
    _render_title_card(title_card_path, settings, len(media_clips))

    normalized_paths = [title_card_path]
    for index, clip in enumerate(media_clips, start=1):
        normalized_path = segment_dir / f"{index:03d}_{clip.id}.mp4"
        _normalize_numbered_clip_for_render(clip.path, normalized_path, settings, index)
        normalized_paths.append(normalized_path)

    concat_path = render_dir / "concat.txt"
    concat_path.write_text(
        "".join(_concat_file_line(path) for path in normalized_paths),
        encoding="utf-8",
    )
    final_path = render_dir / "final_video.mp4"
    _run_render_command(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(final_path),
        ],
        settings,
    )
    return final_path


def _render_title_card(destination: Path, settings: Settings, clip_count: int) -> None:
    title = f"TOP {clip_count} {settings.content_label.upper()}"
    video_filter = (
        f"drawtext=text='{title}':fontcolor=white:fontsize=78:"
        "borderw=6:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2"
    )
    _run_render_command(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            (
                f"color=c=0x101010:s={settings.render_width}x{settings.render_height}:"
                f"r={settings.render_fps}:d={settings.render_intro_seconds}"
            ),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t",
            str(settings.render_intro_seconds),
            "-vf",
            video_filter,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(destination),
        ],
        settings,
    )


def _normalize_numbered_clip_for_render(
    source: Path | None,
    destination: Path,
    settings: Settings,
    number: int,
) -> None:
    if source is None:
        raise ValueError("Clip has no source path")
    media = _probe_clip_media(source)
    has_audio = bool(media.get("has_audio"))
    duration = float(media.get("duration_seconds") or settings.max_clip_seconds)
    video_filter = (
        f"scale={settings.render_width}:{settings.render_height}:"
        "force_original_aspect_ratio=decrease,"
        f"pad={settings.render_width}:{settings.render_height}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={settings.render_fps},setsar=1,"
        f"drawtext=text='{number}':fontcolor=white:fontsize=180:"
        "borderw=8:bordercolor=black:x=(w-text_w)/2:y=52"
    )
    if has_audio:
        _run_render_command(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                "-vf",
                video_filter,
                "-map",
                "0:v:0",
                "-map",
                "0:a:0",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "22",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-shortest",
                "-movflags",
                "+faststart",
                str(destination),
            ],
            settings,
        )
        return

    _run_render_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-f",
            "lavfi",
            "-t",
            str(duration),
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-vf",
            video_filter,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(destination),
        ],
        settings,
    )


def _normalize_clip_for_render(source: Path | None, destination: Path, settings: Settings) -> None:
    if source is None:
        raise ValueError("Clip has no source path")
    media = _probe_clip_media(source)
    has_audio = bool(media.get("has_audio"))
    duration = float(media.get("duration_seconds") or settings.max_clip_seconds)
    video_filter = (
        f"scale={settings.render_width}:{settings.render_height}:"
        "force_original_aspect_ratio=decrease,"
        f"pad={settings.render_width}:{settings.render_height}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={settings.render_fps},setsar=1"
    )
    command = ["ffmpeg", "-y", "-i", str(source)]
    if not has_audio:
        command.extend(
            [
                "-f",
                "lavfi",
                "-t",
                f"{duration:.3f}",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
            ]
        )
    command.extend(
        [
            "-vf",
            video_filter,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0" if has_audio else "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
            "-movflags",
            "+faststart",
            str(destination),
        ]
    )
    _run_render_command(command, settings)


def _mux_voiceover(
    video_path: Path,
    voiceover_path: Path,
    destination: Path,
    settings: Settings,
) -> None:
    _run_render_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(voiceover_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(destination),
        ],
        settings,
    )


class PipelineStage(ABC):
    name: StageName

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abstractmethod
    def run(self, context: PipelineContext) -> PipelineContext:
        raise NotImplementedError


class DiscoverTrendsStage(PipelineStage):
    name = StageName.DISCOVER_TRENDS

    def __init__(self, settings: Settings, provider: TrendProvider) -> None:
        super().__init__(settings)
        self.provider = provider

    def run(self, context: PipelineContext) -> PipelineContext:
        context.trends = self.provider.discover(self.settings.max_trends)
        return context


class SelectTrendsStage(PipelineStage):
    name = StageName.SELECT_TRENDS

    def run(self, context: PipelineContext) -> PipelineContext:
        context.selected_trends = sorted(
            context.trends,
            key=lambda trend: trend.velocity_score * 0.7 + trend.audience_fit_score * 0.3,
            reverse=True,
        )[: self.settings.selected_trend_count]
        return context


class SearchYouTubeStage(PipelineStage):
    name = StageName.SEARCH_YOUTUBE

    def __init__(self, settings: Settings, provider: YouTubeProvider) -> None:
        super().__init__(settings)
        self.provider = provider

    def run(self, context: PipelineContext) -> PipelineContext:
        videos: list[YouTubeVideo] = []
        for trend in context.selected_trends:
            videos.extend(
                self.provider.search_compilations(trend, self.settings.max_videos_per_trend)
            )
        context.videos = _dedupe_videos(videos)
        return context


class AnalyzeVideosStage(PipelineStage):
    name = StageName.ANALYZE_VIDEOS

    def run(self, context: PipelineContext) -> PipelineContext:
        def score(video: YouTubeVideo) -> float:
            views = float(video.view_count or 0)
            likes = float(video.like_count or 0)
            comments = float(video.comment_count or 0)
            return views * 0.00001 + likes * 0.0001 + comments * 0.001

        analyzed: list[YouTubeVideo] = []
        for video in context.videos:
            payload = video.model_copy(deep=True)
            payload.metadata["analysis_score"] = score(video)
            analyzed.append(payload)
        context.analyzed_videos = sorted(
            _dedupe_videos(analyzed),
            key=lambda video: video.metadata.get("analysis_score", 0.0),
            reverse=True,
        )[
            : max(
                self.settings.max_videos_per_trend,
                self.settings.max_download_videos,
                self.settings.max_clips + 5,
            )
        ]
        return context


class DownloadVideosStage(PipelineStage):
    name = StageName.DOWNLOAD_VIDEOS

    def __init__(self, settings: Settings, provider: VideoDownloadProvider) -> None:
        super().__init__(settings)
        self.provider = provider

    def run(self, context: PipelineContext) -> PipelineContext:
        download_dir = context.workdir / "downloads"
        downloaded: list[YouTubeVideo] = []
        failed: list[YouTubeVideo] = []
        query = context.selected_trends[0].title if context.selected_trends else None
        selected_language = (
            context.selected_trends[0].metadata.get("source_language")
            if context.selected_trends
            else None
        )
        language = str(selected_language) if selected_language else None
        attempts = 0
        max_attempts = self.settings.max_download_attempts or len(context.analyzed_videos)
        download_started_at = time.monotonic()
        max_stage_seconds = max(0, self.settings.max_download_stage_seconds)
        candidates = _dedupe_videos(context.analyzed_videos)
        batch_download = getattr(self.provider, "download_many", None)
        if callable(batch_download):
            batch_candidates = candidates[:max_attempts]
            downloaded, failed = batch_download(
                batch_candidates,
                download_dir,
                max_successes=self.settings.max_download_videos,
            )
            attempts = len(batch_candidates)
        else:
            for video in candidates:
                if len(downloaded) >= self.settings.max_download_videos:
                    break
                if attempts >= max_attempts:
                    break
                if (
                    max_stage_seconds
                    and time.monotonic() - download_started_at >= max_stage_seconds
                ):
                    LOGGER.warning(
                        "Stopping downloads after %s attempt(s); "
                        "download stage budget of %ss expired",
                        attempts,
                        max_stage_seconds,
                    )
                    break
                attempts += 1
                try:
                    downloaded.append(self.provider.download(video, download_dir / video.id))
                except (
                    subprocess.CalledProcessError,
                    subprocess.TimeoutExpired,
                    FileNotFoundError,
                ) as exc:
                    failed_video = video.model_copy(deep=True)
                    failed_video.metadata["download_failed"] = True
                    failed_video.metadata["download_error"] = str(exc)
                    if isinstance(exc, subprocess.CalledProcessError):
                        failed_video.metadata["download_stderr"] = _called_process_output(exc)[
                            -2000:
                        ]
                    failed_video.metadata["download_error_kind"] = (
                        "youtube_bot_wall" if _is_youtube_bot_wall(exc) else "download_error"
                    )
                    failed.append(failed_video)
                    output = (
                        f"\n{_called_process_output(exc)[-1200:]}"
                        if isinstance(exc, subprocess.CalledProcessError)
                        and _called_process_output(exc)
                        else ""
                    )
                    LOGGER.warning("Skipping failed download for %s: %s%s", video.id, exc, output)
                    continue
        min_downloads = max(1, self.settings.min_download_videos_for_upload)
        if len(downloaded) < min_downloads:
            if failed:
                SourceHistory(self.settings.source_history_path).mark_videos_seen(
                    failed,
                    run_id=context.run_id,
                    query=query,
                    language=language,
                    stage="download_failed",
                )
            if downloaded:
                SourceHistory(self.settings.source_history_path).mark_videos_seen(
                    downloaded,
                    run_id=context.run_id,
                    query=query,
                    language=language,
                    stage="downloaded_below_publish_minimum",
                )
            if not self.settings.fail_on_no_source_downloads:
                LOGGER.warning(
                    "Only %s source video(s) could be downloaded; minimum for upload is %s. "
                    "Continuing as a skipped media run.",
                    len(downloaded),
                    min_downloads,
                )
                context.analyzed_videos = []
                return context
            if failed and all(
                video.metadata.get("download_error_kind") == "youtube_bot_wall"
                for video in failed
            ):
                raise RuntimeError(
                    f"Only {len(downloaded)} source video(s) could be downloaded; minimum "
                    f"for upload is {min_downloads}. YouTube returned its bot-check wall "
                    "for every failed candidate on this runner. GitHub-hosted runner IPs "
                    "are still blocked even with cookies, alternate YouTube clients, and "
                    "the configured PO-token provider."
                )
            raise RuntimeError(
                f"Only {len(downloaded)} source video(s) could be downloaded; minimum "
                f"for upload is {min_downloads}"
            )
        context.analyzed_videos = downloaded
        SourceHistory(self.settings.source_history_path).mark_videos_seen(
            downloaded,
            run_id=context.run_id,
            query=query,
            language=language,
            stage="downloaded",
        )
        if failed:
            SourceHistory(self.settings.source_history_path).mark_videos_seen(
                failed,
                run_id=context.run_id,
                query=query,
                language=language,
                stage="download_failed",
            )
        return context


class ExtractClipsStage(PipelineStage):
    name = StageName.EXTRACT_CLIPS

    def __init__(self, settings: Settings, provider: MediaProvider) -> None:
        super().__init__(settings)
        self.provider = provider

    def run(self, context: PipelineContext) -> PipelineContext:
        clip_dir = context.workdir / "clips"
        clips: list[ClipCandidate] = []
        for video in context.analyzed_videos:
            clips.extend(self.provider.extract_clips(video, clip_dir / video.id))
        context.clips = [
            clip
            for clip in clips
            if self.settings.min_clip_seconds
            <= clip.duration_seconds
            <= self.settings.max_clip_seconds + 0.05
        ]
        return context


class DedupeClipsStage(PipelineStage):
    name = StageName.DEDUPE_CLIPS

    def run(self, context: PipelineContext) -> PipelineContext:
        seen_keys: set[str] = set()
        seen_hashes: list[str] = []
        unique: list[ClipCandidate] = []
        for clip in sorted(context.clips, key=lambda item: item.quality_score, reverse=True):
            updated = clip.model_copy(deep=True)
            media = _probe_clip_media(updated.path) if updated.path else {}
            visual_hash = _clip_visual_hash(updated.path) if updated.path else None
            if visual_hash:
                updated.perceptual_hash = visual_hash
            updated.metadata["media_probe"] = media
            updated.quality_score = _clip_quality_score(updated, media)
            updated.metadata["quality_filter_threshold"] = self.settings.min_clip_quality_score

            if updated.quality_score < self.settings.min_clip_quality_score:
                updated.metadata["filtered_reason"] = "low_quality"
                continue

            key = updated.perceptual_hash or (
                f"{updated.video_id}:{updated.start_seconds:.1f}:{updated.end_seconds:.1f}"
            )
            if key in seen_keys:
                updated.metadata["filtered_reason"] = "duplicate_exact"
                continue
            if updated.perceptual_hash and any(
                _clip_hash_distance(updated.perceptual_hash, existing)
                <= self.settings.duplicate_hash_distance
                for existing in seen_hashes
            ):
                updated.metadata["filtered_reason"] = "duplicate_visual"
                continue

            seen_keys.add(key)
            if updated.perceptual_hash:
                seen_hashes.append(updated.perceptual_hash)
            unique.append(updated)
        context.unique_clips = unique
        return context


class IdentifyMomentsStage(PipelineStage):
    name = StageName.IDENTIFY_MOMENTS

    def run(self, context: PipelineContext) -> PipelineContext:
        moments: list[ClipCandidate] = []
        for clip in context.unique_clips or context.clips:
            updated = clip.model_copy(deep=True)
            source = _source_video(context, updated)
            source_title = source.title if source else updated.title
            terms = _event_terms(f"{source_title} {updated.title}", self.settings)
            updated.metadata["moment_type_terms"] = terms or ["moment"]
            updated.metadata["event_key"] = _event_key_for_clip(context, updated, self.settings)
            updated.metadata["source_video_title"] = source_title
            moments.append(updated)
        context.moments = moments
        return context


class GroupEventsStage(PipelineStage):
    name = StageName.GROUP_EVENTS

    def run(self, context: PipelineContext) -> PipelineContext:
        grouped: dict[str, list[ClipCandidate]] = {}
        for moment in context.moments:
            key = str(moment.metadata.get("event_key") or moment.id)
            grouped.setdefault(key, []).append(moment)

        events: list[ContentEvent] = []
        for key, clips in grouped.items():
            representative = max(clips, key=lambda clip: clip.quality_score)
            source_ids = sorted({clip.video_id for clip in clips})
            events.append(
                ContentEvent(
                    title=_event_title(key, clips, context),
                    event_key=key,
                    evidence_clip_ids=[clip.id for clip in clips],
                    source_video_ids=source_ids,
                    representative_clip_id=representative.id,
                    frequency_score=min(
                        1.0,
                        len(source_ids) / max(1, self.settings.max_download_videos),
                    ),
                    quality_score=max(clip.quality_score for clip in clips),
                    story_score=min(
                        1.0,
                        0.45
                        + 0.12
                        * len(
                            {
                                term
                                for clip in clips
                                for term in clip.metadata.get("moment_type_terms", [])
                            }
                        ),
                    ),
                    metadata={
                        "evidence_count": len(clips),
                        "moment_terms": sorted(
                            {
                                term
                                for clip in clips
                                for term in clip.metadata.get("moment_type_terms", [])
                            }
                        ),
                    },
                )
            )
        context.events = events
        return context


class RankEventsStage(PipelineStage):
    name = StageName.RANK_EVENTS

    def run(self, context: PipelineContext) -> PipelineContext:
        moments_by_id = {clip.id: clip for clip in context.moments}
        ranked: list[ContentEvent] = []
        for event in context.events:
            updated = event.model_copy(deep=True)
            evidence = [
                moments_by_id[clip_id]
                for clip_id in event.evidence_clip_ids
                if clip_id in moments_by_id
            ]
            duration_score = 0.0
            if evidence:
                duration_score = max(
                    1.0 - min(1.0, abs(clip.duration_seconds - 10.0) / 10.0)
                    for clip in evidence
                )
            updated.final_score = (
                updated.quality_score * 0.35
                + updated.frequency_score * 0.25
                + updated.story_score * 0.25
                + duration_score * 0.15
            )
            updated.metadata["rank_components"] = {
                "quality": updated.quality_score,
                "frequency": updated.frequency_score,
                "story": updated.story_score,
                "duration": round(duration_score, 4),
            }
            ranked.append(updated)

        context.selected_events = sorted(
            ranked, key=lambda event: event.final_score, reverse=True
        )[: self.settings.max_clips]

        clips_by_id = {clip.id: clip for clip in context.moments}
        selected_clips: list[ClipCandidate] = []
        for event in context.selected_events:
            if event.representative_clip_id and event.representative_clip_id in clips_by_id:
                selected_clips.append(clips_by_id[event.representative_clip_id])
        context.selected_clips = selected_clips
        return context


class RankClipsStage(PipelineStage):
    name = StageName.RANK_CLIPS

    def run(self, context: PipelineContext) -> PipelineContext:
        ranked: list[ClipCandidate] = []
        source_counts: dict[str, int] = {}
        for clip in context.unique_clips:
            updated = clip.model_copy(deep=True)
            media = updated.metadata.get("media_probe", {})
            duration = float(media.get("duration_seconds") or updated.duration_seconds)
            duration_score = 1.0 - min(1.0, abs(duration - 10.0) / 10.0)
            scene_bonus = (
                1.0 if updated.metadata.get("segment_source") == "scene_boundary" else 0.75
            )
            source_penalty = min(0.25, source_counts.get(updated.video_id, 0) * 0.12)
            updated.relevance_score = max(updated.relevance_score, 0.75)
            updated.final_score = (
                updated.quality_score * 0.42
                + updated.relevance_score * 0.22
                + duration_score * 0.18
                + scene_bonus * 0.12
                - source_penalty
            )
            updated.novelty_score = max(0.0, 1.0 - source_penalty)
            updated.metadata["rank_components"] = {
                "quality": updated.quality_score,
                "relevance": updated.relevance_score,
                "duration": round(duration_score, 4),
                "scene": scene_bonus,
                "source_penalty": source_penalty,
            }
            ranked.append(updated)
            source_counts[updated.video_id] = source_counts.get(updated.video_id, 0) + 1
        context.selected_clips = sorted(ranked, key=lambda clip: clip.final_score, reverse=True)[
            : self.settings.max_clips
        ]
        return context


class GenerateScriptStage(PipelineStage):
    name = StageName.GENERATE_SCRIPT

    def __init__(self, settings: Settings, provider: ScriptProvider) -> None:
        super().__init__(settings)
        self.provider = provider

    def run(self, context: PipelineContext) -> PipelineContext:
        context.script = self.provider.generate(context.selected_trends, context.selected_clips)
        context.script.metadata.setdefault(
            "timeline", _default_script_timeline(context.script, context.selected_clips)
        )
        script_dir = context.workdir / "script"
        script_dir.mkdir(parents=True, exist_ok=True)
        script_path = script_dir / "narration_script.json"
        context.script.metadata["script_path"] = str(script_path)
        script_path.write_text(context.script.model_dump_json(indent=2), encoding="utf-8")
        return context


class GenerateVoiceoverStage(PipelineStage):
    name = StageName.GENERATE_VOICEOVER

    def __init__(self, settings: Settings, provider: VoiceProvider) -> None:
        super().__init__(settings)
        self.provider = provider

    def run(self, context: PipelineContext) -> PipelineContext:
        if context.script is None:
            raise ValueError("Cannot generate voiceover before script generation")
        context.voiceover = self.provider.synthesize(context.script, context.workdir / "audio")
        return context


class AssembleVideoStage(PipelineStage):
    name = StageName.ASSEMBLE_VIDEO

    def run(self, context: PipelineContext) -> PipelineContext:
        render_dir = context.workdir / "render"
        render_dir.mkdir(parents=True, exist_ok=True)
        if self.settings.render_mode in {"numbered_compilation", "plain_compilation"}:
            context.voiceover = None
        if self.settings.use_real_media and context.selected_clips:
            render_path = _render_final_video(context, self.settings, render_dir)
            context.render = RenderAsset(
                path=render_path,
                provider="ffmpeg",
                metadata={
                    "render_mode": self.settings.render_mode,
                    "clip_count": len(context.selected_clips),
                    "provenance_transform_applied": self.settings.apply_provenance_transform,
                    "pre_provenance_render_path": str(
                        render_dir / "pre_provenance_final_video.mp4"
                    )
                    if self.settings.apply_provenance_transform
                    else None,
                    "provenance_debug_path": str(
                        render_dir / "final_video.mp4.debug.json"
                    )
                    if self.settings.apply_provenance_transform
                    else None,
                    "voiceover": (
                        str(context.voiceover.path)
                        if self.settings.render_mode
                        not in {"numbered_compilation", "plain_compilation"}
                        and context.voiceover
                        else None
                    ),
                    "timeline": context.script.metadata.get("timeline") if context.script else [],
                },
            )
            return context

        manifest = {
            "run_id": context.run_id,
            "voiceover": str(context.voiceover.path) if context.voiceover else None,
            "clips": [
                {
                    "clip_id": clip.id,
                    "source_video_id": clip.video_id,
                    "path": str(clip.path) if clip.path else None,
                    "start_seconds": clip.start_seconds,
                    "end_seconds": clip.end_seconds,
                    "score": clip.final_score,
                }
                for clip in context.selected_clips
            ],
            "note": "Edit decision manifest. Enable a render adapter to create a binary video.",
        }
        path = render_dir / "edit_decision_manifest.json"
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        context.render = RenderAsset(path=path, provider="local_manifest", metadata=manifest)
        return context


class PreparePublishStage(PipelineStage):
    name = StageName.PREPARE_PUBLISH

    def run(self, context: PipelineContext) -> PipelineContext:
        package_dir = context.workdir / "publish"
        package_dir.mkdir(parents=True, exist_ok=True)
        if context.script is None:
            raise ValueError("Cannot prepare publish package before script generation")
        source_language = (
            context.selected_trends[0].metadata.get("source_language")
            if context.selected_trends
            else None
        )
        youtube_metadata = context.script.metadata.get("youtube_metadata")

        if isinstance(youtube_metadata, dict):
            title = str(youtube_metadata.get("title") or context.script.title)[:95]
            description = str(youtube_metadata.get("description") or context.script.hook)
            raw_tags = youtube_metadata.get("tags")
            tags = (
                [str(tag) for tag in raw_tags if str(tag).strip()]
                if isinstance(raw_tags, list)
                else []
            )
            raw_hashtags = youtube_metadata.get("hashtags")
            hashtags = (
                [str(tag) for tag in raw_hashtags if str(tag).strip()]
                if isinstance(raw_hashtags, list)
                else []
            )
            if hashtags:
                description = "\n\n".join([description, " ".join(hashtags)])
        elif self.settings.render_mode in {"numbered_compilation", "plain_compilation"}:
            title = f"Top {len(context.selected_clips)} {self.settings.content_label}"
            description = "\n\n".join(
                [
                    (
                        f"Top {len(context.selected_clips)} {self.settings.content_label} selected "
                        "from short-video sources."
                    ),
                    "Clips referenced:",
                    *[
                        f"{index}. {clip.title}"
                        for index, clip in enumerate(context.selected_clips, start=1)
                    ],
                ]
            )
            tags = [trend.title for trend in context.selected_trends][:10]
            hashtags = []
        else:
            title = context.script.title[:95]
            description = "\n\n".join(
                [
                    context.script.hook,
                    "Clips referenced:",
                    *[f"- {clip.title}" for clip in context.selected_clips],
                ]
            )
            tags = [trend.title for trend in context.selected_trends][:10]
            hashtags = []
        package = PublishPackage(
            path=package_dir / "publish_manifest.json",
            title=title,
            description=description,
            tags=tags,
            metadata={
                "render_path": str(context.render.path) if context.render else None,
                "rights_review_required": True,
                "source_language": source_language,
                "hashtags": hashtags,
                "llm_provider": context.script.metadata.get("provider"),
                "llm_metadata_error": context.script.metadata.get("llm_metadata_error"),
            },
        )
        package.path.write_text(package.model_dump_json(indent=2), encoding="utf-8")
        context.publish_package = package
        if context.selected_trends:
            language = context.selected_trends[0].metadata.get("source_language")
            query = str(
                context.selected_trends[0].metadata.get("raw_query")
                or context.selected_trends[0].title
            )
            SourceHistory(self.settings.source_history_path).mark_query_used(
                query,
                context.run_id,
                str(language) if language else None,
            )
        return context


class UploadYouTubeStage(PipelineStage):
    name = StageName.UPLOAD_YOUTUBE

    def run(self, context: PipelineContext) -> PipelineContext:
        upload_dir = context.workdir / "upload"
        upload_dir.mkdir(parents=True, exist_ok=True)
        result_path = upload_dir / "youtube_upload.json"

        existing_upload = context.youtube_upload
        if existing_upload is None and result_path.exists():
            try:
                existing_upload = YouTubeUploadResult.model_validate_json(
                    result_path.read_text(encoding="utf-8")
                )
            except ValueError:
                existing_upload = None
        if (
            existing_upload
            and existing_upload.status == "uploaded"
            and not self.settings.youtube_upload_allow_duplicate
        ):
            context.youtube_upload = existing_upload.model_copy(deep=True)
            context.youtube_upload.metadata["skipped_duplicate_upload"] = True
            result_path.write_text(
                context.youtube_upload.model_dump_json(indent=2),
                encoding="utf-8",
            )
            return context

        if not self.settings.enable_youtube_upload:
            context.youtube_upload = YouTubeUploadResult(
                path=result_path,
                status="skipped",
                privacy_status=self.settings.youtube_upload_privacy_status,
                metadata={"reason": "ENABLE_YOUTUBE_UPLOAD is false"},
            )
            result_path.write_text(
                context.youtube_upload.model_dump_json(indent=2),
                encoding="utf-8",
            )
            return context

        if not context.selected_clips:
            context.youtube_upload = YouTubeUploadResult(
                path=result_path,
                status="skipped",
                privacy_status=self.settings.youtube_upload_privacy_status,
                metadata={"reason": "No selected clips were produced for this run"},
            )
            result_path.write_text(
                context.youtube_upload.model_dump_json(indent=2),
                encoding="utf-8",
            )
            return context

        _require_expected_upload_channel_for_domain(self.settings)
        if context.publish_package is None:
            raise ValueError("Cannot upload before publish package is prepared")
        render_path = Path(context.publish_package.metadata.get("render_path") or "")
        if render_path.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm"}:
            context.youtube_upload = YouTubeUploadResult(
                path=result_path,
                status="skipped",
                privacy_status=self.settings.youtube_upload_privacy_status,
                metadata={
                    "reason": "Publish package did not reference a video render",
                    "render_path": str(render_path),
                },
            )
            result_path.write_text(
                context.youtube_upload.model_dump_json(indent=2),
                encoding="utf-8",
            )
            return context
        if not render_path.exists():
            raise FileNotFoundError(f"Upload render path not found: {render_path}")

        youtube = _authenticated_youtube_service(self.settings)
        _validate_expected_upload_channel(youtube, self.settings)
        body = {
            "snippet": {
                "title": context.publish_package.title,
                "description": context.publish_package.description,
                "tags": context.publish_package.tags,
                "categoryId": self.settings.youtube_upload_category_id,
            },
            "status": {
                "privacyStatus": self.settings.youtube_upload_privacy_status,
                "madeForKids": self.settings.youtube_video_made_for_kids,
                "selfDeclaredMadeForKids": (
                    self.settings.youtube_video_self_declared_made_for_kids
                ),
            },
        }

        response = _upload_video(
            youtube=youtube,
            video_path=render_path,
            body=body,
            notify_subscribers=self.settings.youtube_upload_notify_subscribers,
        )
        video_id = response.get("id")
        context.youtube_upload = YouTubeUploadResult(
            path=result_path,
            video_id=str(video_id) if video_id else None,
            url=f"https://www.youtube.com/watch?v={video_id}" if video_id else None,
            status="uploaded",
            privacy_status=self.settings.youtube_upload_privacy_status,
            metadata={
                "uploaded_at": datetime.now(UTC).isoformat(),
                "response": response,
                "request_body": body,
                "render_path": str(render_path),
            },
        )
        result_path.write_text(
            context.youtube_upload.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return context


def _require_expected_upload_channel_for_domain(settings: Settings) -> None:
    guarded_domains = {"football", "cricket"}
    if (
        settings.content_domain in guarded_domains
        and not settings.youtube_upload_expected_channel_id
    ):
        raise ValueError(
            "YOUTUBE_UPLOAD_EXPECTED_CHANNEL_ID is required for "
            f"{settings.content_domain} uploads. Set it to the expected channel ID "
            "before enabling upload."
        )


def authenticate_and_validate_youtube_upload(settings: Settings) -> dict[str, Any]:
    _require_expected_upload_channel_for_domain(settings)
    youtube = _authenticated_youtube_service(settings)
    return _validate_expected_upload_channel(youtube, settings)


def _validate_expected_upload_channel(youtube: Any, settings: Settings) -> dict[str, Any]:
    expected_channel_id = settings.youtube_upload_expected_channel_id
    if not expected_channel_id:
        return {"validated": False, "reason": "No expected channel configured"}
    response = (
        youtube.channels()
        .list(part="id,snippet", mine=True, maxResults=50)
        .execute()
    )
    channels = response.get("items") or []
    actual_ids = [str(channel.get("id")) for channel in channels if channel.get("id")]
    if expected_channel_id in actual_ids:
        return {
            "validated": True,
            "expected_channel_id": expected_channel_id,
            "authenticated_channels": channels,
        }
    titles = [
        str(channel.get("snippet", {}).get("title") or channel.get("id"))
        for channel in channels
    ]
    raise RuntimeError(
        "Authenticated YouTube upload token does not match expected channel "
        f"{expected_channel_id}. Available authenticated channels: {titles or actual_ids}"
    )


def _authenticated_youtube_service(settings: Settings) -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]
    from googleapiclient.discovery import build  # type: ignore[import-untyped]

    if settings.youtube_oauth_client_secrets is None:
        raise ValueError("YOUTUBE_OAUTH_CLIENT_SECRETS is required for upload")
    client_secret_path = settings.youtube_oauth_client_secrets
    if not client_secret_path.exists():
        raise FileNotFoundError(f"OAuth client secrets file not found: {client_secret_path}")

    token_path = settings.youtube_oauth_token_path
    scopes = _youtube_oauth_scopes(settings)
    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(
            str(token_path),
            scopes=scopes,
        )
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    if not credentials or not credentials.valid:
        if os.getenv("CI"):
            raise ValueError(
                "YouTube OAuth token is missing or invalid in CI. "
                "Refresh it locally and update the YOUTUBE_OAUTH_TOKEN_JSON secret."
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            str(client_secret_path),
            scopes=scopes,
        )
        credentials = flow.run_local_server(port=0)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=credentials)


def _youtube_oauth_scopes(settings: Settings) -> list[str]:
    scopes = [YOUTUBE_UPLOAD_SCOPE]
    if settings.youtube_upload_expected_channel_id:
        scopes.append(YOUTUBE_READONLY_SCOPE)
    return scopes


def _upload_video(
    *,
    youtube: Any,
    video_path: Path,
    body: dict[str, Any],
    notify_subscribers: bool,
) -> dict[str, Any]:
    from googleapiclient.http import MediaFileUpload  # type: ignore[import-untyped]

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
        notifySubscribers=notify_subscribers,
    )
    response = None
    while response is None:
        _, response = request.next_chunk()
    return dict(response)


def build_stages(
    settings: Settings,
    trend_provider: TrendProvider,
    youtube_provider: YouTubeProvider,
    download_provider: VideoDownloadProvider,
    media_provider: MediaProvider,
    script_provider: ScriptProvider,
    voice_provider: VoiceProvider,
) -> list[PipelineStage]:
    return [
        DiscoverTrendsStage(settings, trend_provider),
        SelectTrendsStage(settings),
        SearchYouTubeStage(settings, youtube_provider),
        AnalyzeVideosStage(settings),
        DownloadVideosStage(settings, download_provider),
        ExtractClipsStage(settings, media_provider),
        DedupeClipsStage(settings),
        IdentifyMomentsStage(settings),
        GroupEventsStage(settings),
        RankEventsStage(settings),
        GenerateScriptStage(settings, script_provider),
        *(
            [GenerateVoiceoverStage(settings, voice_provider)]
            if settings.enable_voiceover
            else []
        ),
        AssembleVideoStage(settings),
        PreparePublishStage(settings),
        UploadYouTubeStage(settings),
    ]


def write_debug_snapshot(context: PipelineContext) -> Path:
    path = context.workdir / "context.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(context.model_dump_json(indent=2), encoding="utf-8")
    return path
