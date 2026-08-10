from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from viral_pipeline import cli
from viral_pipeline.config import Settings
from viral_pipeline.domain import (
    ClipCandidate,
    NarrationScript,
    PipelineContext,
    RenderAsset,
    RunStatus,
    StageName,
    Trend,
    YouTubeVideo,
)
from viral_pipeline.providers import (
    ColabYtDlpVideoDownloadProvider,
    YtDlpFfmpegMediaProvider,
    YtDlpVideoDownloadProvider,
    build_providers,
)
from viral_pipeline.runner import PipelineRunner
from viral_pipeline.source_history import SourceHistory
from viral_pipeline.stages import (
    DownloadVideosStage,
    GroupEventsStage,
    IdentifyMomentsStage,
    PreparePublishStage,
    RankEventsStage,
    UploadYouTubeStage,
    _clip_hash_distance,
)
from viral_pipeline.storage import PipelineStore


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        pipeline_db_path=tmp_path / "pipeline.sqlite3",
        pipeline_workdir=tmp_path / "workdir",
        source_history_path=tmp_path / "source_video_history.json",
        max_trends=2,
        selected_trend_count=1,
        max_videos_per_trend=2,
        max_download_videos=2,
        max_clips=4,
        use_real_media=False,
        enable_youtube_upload=False,
    )


def test_full_local_pipeline_persists_publish_package(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = PipelineStore(settings.pipeline_db_path)
    runner = PipelineRunner(settings, store)

    context = runner.run()

    assert context.trends
    assert context.videos
    assert len(context.selected_trends) == 1
    assert len(context.analyzed_videos) == 2
    assert all(
        video.downloaded_path and video.downloaded_path.exists()
        for video in context.analyzed_videos
    )
    assert context.selected_clips
    assert context.moments
    assert context.events
    assert context.selected_events
    assert len(context.selected_clips) == len(context.selected_events)
    assert context.script is not None
    assert context.voiceover is None
    assert context.render is not None
    assert context.publish_package is not None
    assert context.publish_package.path.exists()
    assert store.get_run(context.run_id)["status"] == RunStatus.COMPLETE.value
    assert StageName.PREPARE_PUBLISH in store.completed_stages(context.run_id)


def test_resume_skips_completed_stages(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = PipelineStore(settings.pipeline_db_path)
    runner = PipelineRunner(settings, store)

    context = runner.run()
    first_context_mtime = (context.workdir / "context.json").stat().st_mtime

    resumed = runner.run(run_id=context.run_id, resume=True)

    assert resumed.run_id == context.run_id
    assert (context.workdir / "context.json").stat().st_mtime == first_context_mtime


def test_cleanup_removes_bulky_state_and_keeps_source_history(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path)
    settings.pipeline_workdir.mkdir(parents=True)
    (settings.pipeline_workdir / "artifact.mp4").write_text("media", encoding="utf-8")
    settings.pipeline_db_path.write_text("sqlite", encoding="utf-8")
    settings.source_history_path.write_text(
        '{"videos": {"abc": {}}, "queries": {}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "_settings", lambda: settings)

    result = CliRunner().invoke(cli.app, ["cleanup", "--yes"])

    assert result.exit_code == 0
    assert not settings.pipeline_workdir.exists()
    assert not settings.pipeline_db_path.exists()
    assert settings.source_history_path.exists()
    assert '"abc"' in settings.source_history_path.read_text(encoding="utf-8")


def test_single_stage_can_be_rerun_for_debugging(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = PipelineStore(settings.pipeline_db_path)
    runner = PipelineRunner(settings, store)

    context = runner.run()
    rerun = runner.run(run_id=context.run_id, only_stage=StageName.RANK_EVENTS, resume=False)

    assert rerun.selected_clips
    assert rerun.selected_events[0].final_score >= rerun.selected_events[-1].final_score


def test_ffmpeg_extractor_builds_segments_from_scene_boundaries(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.max_clips_per_video = 4
    provider = YtDlpFfmpegMediaProvider(settings)

    segments = provider._segments_from_boundaries([5.0, 10.0, 28.0], duration=45.0)

    assert segments == [
        (0.0, 5.0, "scene_boundary"),
        (5.0, 10.0, "scene_boundary"),
        (10.0, 28.0, "scene_boundary"),
        (28.0, 45.0, "scene_boundary"),
    ]


def test_ytdlp_download_uses_configured_cookies_file(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path)
    cookies_path = tmp_path / "cookies.txt"
    cookies_path.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    settings.yt_dlp_cookies_path = cookies_path
    settings.yt_dlp_js_runtimes = "node"
    settings.yt_dlp_extractor_args = "youtube:player_client=web"
    provider = YtDlpVideoDownloadProvider(settings)
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> None:
        commands.append(command)
        output_dir = tmp_path / "downloads"
        (output_dir / "video-1.mp4").write_text("media", encoding="utf-8")

    monkeypatch.setattr("viral_pipeline.providers.subprocess.run", fake_run)

    provider.download(
        YouTubeVideo(
            id="video-1",
            trend_id="trend-1",
            title="Funny toddler short",
            url="https://www.youtube.com/watch?v=video-1",
        ),
        tmp_path / "downloads",
    )

    assert "--cookies" in commands[0]
    assert str(cookies_path) in commands[0]
    assert "--js-runtimes" in commands[0]
    assert "node" in commands[0]
    assert "--extractor-args" in commands[0]
    assert "youtube:player_client=web" in commands[0]


def test_ytdlp_download_supports_multiple_extractor_args(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path)
    settings.yt_dlp_extractor_args = "\n".join(
        [
            "youtube:player_client=mweb",
            "youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416",
        ]
    )
    provider = YtDlpVideoDownloadProvider(settings)
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> None:
        commands.append(command)
        output_dir = tmp_path / "downloads"
        (output_dir / "video-1.mp4").write_text("media", encoding="utf-8")

    monkeypatch.setattr("viral_pipeline.providers.subprocess.run", fake_run)

    provider.download(
        YouTubeVideo(
            id="video-1",
            trend_id="trend-1",
            title="Funny toddler short",
            url="https://www.youtube.com/watch?v=video-1",
        ),
        tmp_path / "downloads",
    )

    assert commands[0].count("--extractor-args") == 2
    assert "youtube:player_client=mweb" in commands[0]
    assert "youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416" in commands[0]


def test_ytdlp_download_can_enable_verbose_output(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path)
    settings.yt_dlp_verbose = True
    provider = YtDlpVideoDownloadProvider(settings)
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> None:
        commands.append(command)
        output_dir = tmp_path / "downloads"
        (output_dir / "video-1.mp4").write_text("media", encoding="utf-8")

    monkeypatch.setattr("viral_pipeline.providers.subprocess.run", fake_run)

    provider.download(
        YouTubeVideo(
            id="video-1",
            trend_id="trend-1",
            title="Funny toddler short",
            url="https://www.youtube.com/watch?v=video-1",
        ),
        tmp_path / "downloads",
    )

    assert "--verbose" in commands[0]


def test_build_providers_can_select_colab_download_backend(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.use_real_media = True
    settings.download_backend = "colab"

    providers = build_providers(settings)

    assert isinstance(providers[2], ColabYtDlpVideoDownloadProvider)


def test_download_stage_records_failures_when_no_downloads_succeed(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)

    class AlwaysFailProvider:
        def download(self, video: YouTubeVideo, output_dir: Path) -> YouTubeVideo:
            raise subprocess.CalledProcessError(1, ["yt-dlp", video.url])

    context = PipelineContext(
        run_id="download-failure-test",
        workdir=tmp_path,
        selected_trends=[
            Trend(
                title="funny toddler fails shorts",
                source="test",
                metadata={"source_language": "en"},
            )
        ],
        analyzed_videos=[
            YouTubeVideo(
                id="video-1",
                trend_id="trend-1",
                title="Funny toddler short",
                url="https://www.youtube.com/watch?v=video-1",
            )
        ],
    )

    try:
        DownloadVideosStage(settings, AlwaysFailProvider()).run(context)
    except RuntimeError as exc:
        assert "No source videos" in str(exc)
    else:
        raise AssertionError("download stage should fail when no downloads succeed")

    history = SourceHistory(settings.source_history_path)._data()
    assert history["videos"] == {}


def test_download_stage_reports_youtube_bot_wall(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)

    class BotWallProvider:
        def download(self, video: YouTubeVideo, output_dir: Path) -> YouTubeVideo:
            raise subprocess.CalledProcessError(
                1,
                ["yt-dlp", video.url],
                stderr="ERROR: Sign in to confirm you’re not a bot.",
            )

    context = PipelineContext(
        run_id="download-bot-wall-test",
        workdir=tmp_path,
        selected_trends=[
            Trend(
                title="funny toddler fails shorts",
                source="test",
                metadata={"source_language": "en"},
            )
        ],
        analyzed_videos=[
            YouTubeVideo(
                id="video-1",
                trend_id="trend-1",
                title="Funny toddler short",
                url="https://www.youtube.com/watch?v=video-1",
            )
        ],
    )

    try:
        DownloadVideosStage(settings, BotWallProvider()).run(context)
    except RuntimeError as exc:
        assert "bot-check wall" in str(exc)
        assert "configured PO-token provider" in str(exc)
    else:
        raise AssertionError("download stage should report the YouTube bot wall")


def test_clip_hash_distance_detects_exact_and_near_duplicates() -> None:
    assert _clip_hash_distance("00ff", "00ff") == 0
    assert _clip_hash_distance("00ff", "00fe") == 1
    assert _clip_hash_distance("00ff", "ff00") == 16


def test_content_event_stages_select_representative_clips(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    context = PipelineContext(
        run_id="event-test",
        workdir=tmp_path,
        analyzed_videos=[
            YouTubeVideo(
                id="video-1",
                trend_id="trend-1",
                title="Funny kids moments compilation",
                url="https://www.youtube.com/watch?v=video-1",
            )
        ],
        unique_clips=[
            ClipCandidate(
                id="clip-1",
                video_id="video-1",
                trend_id="trend-1",
                start_seconds=0,
                end_seconds=10,
                title="funny toddler reaction",
                quality_score=0.8,
            ),
            ClipCandidate(
                id="clip-2",
                video_id="video-1",
                trend_id="trend-1",
                start_seconds=35,
                end_seconds=45,
                title="another funny kid reaction",
                quality_score=0.9,
            ),
        ],
    )

    context = IdentifyMomentsStage(settings).run(context)
    context = GroupEventsStage(settings).run(context)
    context = RankEventsStage(settings).run(context)

    assert len(context.events) == 2
    assert context.selected_events
    assert context.selected_clips
    assert context.selected_clips[0].id in {
        event.representative_clip_id for event in context.selected_events
    }


def test_content_event_grouping_merges_same_visual_moment_across_sources(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)
    context = PipelineContext(
        run_id="event-merge-test",
        workdir=tmp_path,
        analyzed_videos=[
            YouTubeVideo(
                id="video-1",
                trend_id="trend-1",
                title="Funny toddler moments compilation",
                url="https://www.youtube.com/watch?v=video-1",
            ),
            YouTubeVideo(
                id="video-2",
                trend_id="trend-1",
                title="Cute funny kids videos",
                url="https://www.youtube.com/watch?v=video-2",
            ),
        ],
        unique_clips=[
            ClipCandidate(
                id="clip-1",
                video_id="video-1",
                trend_id="trend-1",
                start_seconds=5,
                end_seconds=15,
                title="same funny toddler reaction",
                perceptual_hash="abcdef1234567890aaa",
                quality_score=0.75,
            ),
            ClipCandidate(
                id="clip-2",
                video_id="video-2",
                trend_id="trend-1",
                start_seconds=90,
                end_seconds=100,
                title="same funny toddler reaction different upload",
                perceptual_hash="abcdef1234567890bbb",
                quality_score=0.92,
            ),
        ],
    )

    context = IdentifyMomentsStage(settings).run(context)
    context = GroupEventsStage(settings).run(context)
    context = RankEventsStage(settings).run(context)

    assert len(context.events) == 1
    event = context.events[0]
    assert event.source_video_ids == ["video-1", "video-2"]
    assert event.evidence_clip_ids == ["clip-1", "clip-2"]
    assert event.representative_clip_id == "clip-2"
    assert context.selected_clips[0].id == "clip-2"


def test_prepare_publish_uses_llm_youtube_metadata(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    context = PipelineContext(
        run_id="publish-test",
        workdir=tmp_path,
        selected_trends=[
            Trend(
                title="funny kids shorts",
                source="test",
                metadata={"source_language": "en"},
            )
        ],
        selected_clips=[
            ClipCandidate(
                id="clip-1",
                video_id="video-1",
                trend_id="trend-1",
                start_seconds=0,
                end_seconds=10,
                title="funny kid reaction",
            )
        ],
        script=NarrationScript(
            title="Fallback title",
            hook="Fallback hook",
            body=[],
            outro="",
            metadata={
                "provider": "groqcloud",
                "youtube_metadata": {
                    "title": "Tiny Laughs That Escalate Fast",
                    "description": "Five quick funny kid moments with simple visual payoffs.",
                    "tags": ["funny kids", "kids shorts", "family funny moments"],
                    "hashtags": ["#FunnyKids", "#Shorts"],
                    "summary": "A quick funny kids compilation.",
                },
            },
        ),
        render=RenderAsset(path=tmp_path / "render" / "final_video.mp4", provider="ffmpeg"),
    )

    context = PreparePublishStage(settings).run(context)

    assert context.publish_package is not None
    assert context.publish_package.title == "Tiny Laughs That Escalate Fast"
    assert "Five quick funny kid moments" in context.publish_package.description
    assert "#FunnyKids #Shorts" in context.publish_package.description
    assert context.publish_package.tags == [
        "funny kids",
        "kids shorts",
        "family funny moments",
    ]
    assert context.publish_package.metadata["llm_provider"] == "groqcloud"


def test_upload_youtube_stage_skips_when_disabled(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.enable_youtube_upload = False
    context = PipelineContext(run_id="upload-test", workdir=tmp_path)

    context = UploadYouTubeStage(settings).run(context)

    assert context.youtube_upload is not None
    assert context.youtube_upload.status == "skipped"
    assert context.youtube_upload.path.exists()


def test_upload_youtube_stage_does_not_reupload_existing_result(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.enable_youtube_upload = True
    upload_dir = tmp_path / "upload"
    upload_dir.mkdir()
    existing = {
        "path": str(upload_dir / "youtube_upload.json"),
        "video_id": "video-123",
        "url": "https://www.youtube.com/watch?v=video-123",
        "status": "uploaded",
        "privacy_status": "private",
        "provider": "youtube_data_api",
        "metadata": {},
    }
    (upload_dir / "youtube_upload.json").write_text(
        __import__("json").dumps(existing),
        encoding="utf-8",
    )
    context = PipelineContext(run_id="upload-test", workdir=tmp_path)

    context = UploadYouTubeStage(settings).run(context)

    assert context.youtube_upload is not None
    assert context.youtube_upload.video_id == "video-123"
    assert context.youtube_upload.metadata["skipped_duplicate_upload"] is True
