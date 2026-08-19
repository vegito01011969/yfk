from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class StageName(StrEnum):
    DISCOVER_TRENDS = "discover_trends"
    SELECT_TRENDS = "select_trends"
    SEARCH_YOUTUBE = "search_youtube"
    ANALYZE_VIDEOS = "analyze_videos"
    DOWNLOAD_VIDEOS = "download_videos"
    EXTRACT_CLIPS = "extract_clips"
    IDENTIFY_MOMENTS = "identify_moments"
    GROUP_EVENTS = "group_events"
    RANK_EVENTS = "rank_events"
    DEDUPE_CLIPS = "dedupe_clips"
    RANK_CLIPS = "rank_clips"
    GENERATE_SCRIPT = "generate_script"
    GENERATE_VOICEOVER = "generate_voiceover"
    ASSEMBLE_VIDEO = "assemble_video"
    PREPARE_PUBLISH = "prepare_publish"
    UPLOAD_YOUTUBE = "upload_youtube"


PIPELINE_ORDER: tuple[StageName, ...] = tuple(StageName)


class RunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"


class Trend(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    title: str
    source: str
    url: str | None = None
    velocity_score: float = 0.0
    audience_fit_score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class YouTubeVideo(BaseModel):
    id: str
    trend_id: str
    title: str
    channel_title: str | None = None
    url: str
    published_at: datetime | None = None
    duration_seconds: int | None = None
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    downloaded_path: Path | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClipCandidate(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    video_id: str
    trend_id: str
    start_seconds: float
    end_seconds: float
    title: str
    path: Path | None = None
    perceptual_hash: str | None = None
    transcript: str | None = None
    quality_score: float = 0.0
    relevance_score: float = 0.0
    novelty_score: float = 0.0
    final_score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)


class ContentEvent(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    title: str
    event_key: str
    evidence_clip_ids: list[str] = Field(default_factory=list)
    source_video_ids: list[str] = Field(default_factory=list)
    representative_clip_id: str | None = None
    frequency_score: float = 0.0
    quality_score: float = 0.0
    story_score: float = 0.0
    recency_score: float = 0.0
    final_score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class NarrationScript(BaseModel):
    title: str
    hook: str
    body: list[str]
    outro: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    def as_text(self) -> str:
        return "\n\n".join([self.title, self.hook, *self.body, self.outro])


class VoiceoverAsset(BaseModel):
    path: Path
    duration_seconds: float | None = None
    provider: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RenderAsset(BaseModel):
    path: Path
    provider: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class PublishPackage(BaseModel):
    path: Path
    title: str
    description: str
    tags: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict)


class YouTubeUploadResult(BaseModel):
    path: Path
    video_id: str | None = None
    url: str | None = None
    status: str
    privacy_status: str | None = None
    provider: str = "youtube_data_api"
    metadata: dict[str, Any] = Field(default_factory=dict)


class PipelineContext(BaseModel):
    run_id: str
    workdir: Path
    metadata: dict[str, Any] = Field(default_factory=dict)
    trends: list[Trend] = Field(default_factory=list)
    selected_trends: list[Trend] = Field(default_factory=list)
    videos: list[YouTubeVideo] = Field(default_factory=list)
    analyzed_videos: list[YouTubeVideo] = Field(default_factory=list)
    clips: list[ClipCandidate] = Field(default_factory=list)
    unique_clips: list[ClipCandidate] = Field(default_factory=list)
    selected_clips: list[ClipCandidate] = Field(default_factory=list)
    moments: list[ClipCandidate] = Field(default_factory=list)
    events: list[ContentEvent] = Field(default_factory=list)
    selected_events: list[ContentEvent] = Field(default_factory=list)
    script: NarrationScript | None = None
    voiceover: VoiceoverAsset | None = None
    render: RenderAsset | None = None
    publish_package: PublishPackage | None = None
    youtube_upload: YouTubeUploadResult | None = None
