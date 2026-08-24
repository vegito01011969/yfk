from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from importlib import util
from pathlib import Path

from typer.testing import CliRunner

from viral_pipeline import cli
from viral_pipeline.config import Settings
from viral_pipeline.domain import (
    ClipCandidate,
    NarrationScript,
    PipelineContext,
    PublishPackage,
    RenderAsset,
    RunStatus,
    StageName,
    Trend,
    YouTubeVideo,
)
from viral_pipeline.providers import (
    ColabYtDlpVideoDownloadProvider,
    KaggleYtDlpVideoDownloadProvider,
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
    _apply_provenance_transform_if_enabled,
    _clip_hash_distance,
    _require_expected_upload_channel_for_domain,
    _validate_expected_upload_channel,
    _youtube_oauth_scopes,
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


def load_pipeline_retry_script():
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    script_path = scripts_dir / "run_pipeline_until_upload.py"
    spec = util.spec_from_file_location("run_pipeline_until_upload", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = util.module_from_spec(spec)
    sys.path.insert(0, str(scripts_dir))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(scripts_dir))
    return module


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


def test_provenance_transform_timeout_fails_open(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path)
    settings.apply_provenance_transform = True
    settings.provenance_transform_fail_open = True
    settings.provenance_transform_timeout_seconds = 1
    script_path = tmp_path / "transform.py"
    script_path.write_text("print('unused')\n", encoding="utf-8")
    settings.provenance_transform_script = script_path
    render_dir = tmp_path / "render"
    render_dir.mkdir()
    input_path = render_dir / "final_video.mp4"
    input_path.write_text("pre-transform-media", encoding="utf-8")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

    monkeypatch.setattr("viral_pipeline.stages.subprocess.run", fake_run)

    output_path = _apply_provenance_transform_if_enabled(input_path, settings, render_dir)

    assert output_path == render_dir / "final_video.mp4"
    assert output_path.read_text(encoding="utf-8") == "pre-transform-media"
    debug = json.loads((render_dir / "final_video.mp4.debug.json").read_text())
    assert debug["status"] == "provenance_transform_failed_open"


def test_provenance_transform_passes_configured_level(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path)
    settings.apply_provenance_transform = True
    settings.provenance_transform_level = 2
    script_path = tmp_path / "transform.py"
    script_path.write_text("print('unused')\n", encoding="utf-8")
    settings.provenance_transform_script = script_path
    render_dir = tmp_path / "render"
    render_dir.mkdir()
    input_path = render_dir / "final_video.mp4"
    input_path.write_text("pre-transform-media", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        output = Path(command[command.index("--output") + 1])
        output.write_text("transformed-media", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("viral_pipeline.stages.subprocess.run", fake_run)

    output_path = _apply_provenance_transform_if_enabled(input_path, settings, render_dir)

    assert output_path.read_text(encoding="utf-8") == "transformed-media"
    assert "--level" in commands[0]
    assert commands[0][commands[0].index("--level") + 1] == "2"


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
        timeout: int,
    ) -> None:
        commands.append(command)
        assert timeout == settings.yt_dlp_download_timeout_seconds
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
        timeout: int,
    ) -> None:
        commands.append(command)
        assert timeout == settings.yt_dlp_download_timeout_seconds
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
        timeout: int,
    ) -> None:
        commands.append(command)
        assert timeout == settings.yt_dlp_download_timeout_seconds
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


def test_build_providers_can_select_kaggle_download_backend(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.use_real_media = True
    settings.download_backend = "kaggle"

    providers = build_providers(settings)

    assert isinstance(providers[2], KaggleYtDlpVideoDownloadProvider)


def test_colab_batch_download_starts_worker_asynchronously(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = make_settings(tmp_path)
    settings.use_real_media = True
    settings.download_backend = "colab"
    settings.max_download_stage_seconds = 60
    provider = ColabYtDlpVideoDownloadProvider(settings)
    calls: list[list[str]] = []

    monkeypatch.setattr("viral_pipeline.providers.time.sleep", lambda seconds: None)

    def fake_run(
        args: list[str],
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:2] == ["exec", "-s"] and input_text and "RESULT_READY=" in input_text:
            return subprocess.CompletedProcess(args, 0, stdout="RESULT_READY=True\n")
        if args[:2] == ["download", "-s"]:
            result_zip = tmp_path / "downloads" / "colab_batch_result.zip"
            result_zip.parent.mkdir(parents=True, exist_ok=True)
            result_json = tmp_path / "result.json"
            result_json.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "successes": 1,
                        "results": [{"video_id": "video-1", "status": "ok"}],
                    }
                ),
                encoding="utf-8",
            )
            media_path = tmp_path / "video-1.mp4"
            media_path.write_text("media", encoding="utf-8")
            with zipfile.ZipFile(result_zip, "w") as archive:
                archive.write(result_json, "result.json")
                archive.write(media_path, "video-1.mp4")
        return subprocess.CompletedProcess(args, 0, stdout="worker_started\n")

    monkeypatch.setattr(provider, "_run", fake_run)

    downloaded, failed = provider.download_many(
        [
            YouTubeVideo(
                id="video-1",
                trend_id="trend-1",
                title="Cricket short",
                url="https://www.youtube.com/watch?v=video-1",
            )
        ],
        tmp_path / "downloads",
        max_successes=1,
    )

    assert [video.id for video in downloaded] == ["video-1"]
    assert failed == []
    assert any(call[0] == "upload" and call[-1].endswith("/worker.py") for call in calls)
    assert not any(call[:1] == ["exec"] and "-f" in call for call in calls)


def test_kaggle_batch_download_pushes_kernel_and_reads_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = make_settings(tmp_path)
    settings.use_real_media = True
    settings.download_backend = "kaggle"
    settings.kaggle_kernel_slug = "viral-pipeline-ytdlp-test"
    settings.kaggle_vendor_dataset_ref = "test-user/stable-vendor"
    settings.kaggle_command_timeout_seconds = 60
    provider = KaggleYtDlpVideoDownloadProvider(settings)
    calls: list[list[str]] = []

    monkeypatch.setenv("KAGGLE_USERNAME", "test-user")
    monkeypatch.setattr("viral_pipeline.providers.time.sleep", lambda seconds: None)

    def fake_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:2] == ["kernels", "status"]:
            return subprocess.CompletedProcess(args, 0, stdout="complete\n")
        if args[:2] == ["kernels", "output"]:
            output_dir = Path(args[-1])
            output_dir.mkdir(parents=True, exist_ok=True)
            result_json = tmp_path / "result.json"
            result_json.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "successes": 1,
                        "results": [{"video_id": "video-1", "status": "ok"}],
                    }
                ),
                encoding="utf-8",
            )
            media_path = tmp_path / "video-1.mp4"
            media_path.write_text("media", encoding="utf-8")
            with zipfile.ZipFile(output_dir / "result.zip", "w") as archive:
                archive.write(result_json, "result.json")
                archive.write(media_path, "video-1.mp4")
        return subprocess.CompletedProcess(args, 0, stdout="")

    monkeypatch.setattr(provider, "_run", fake_run)

    downloaded, failed = provider.download_many(
        [
            YouTubeVideo(
                id="video-1",
                trend_id="trend-1",
                title="Cricket short",
                url="https://www.youtube.com/watch?v=video-1",
            )
        ],
        tmp_path / "downloads",
        max_successes=1,
    )

    assert [video.id for video in downloaded] == ["video-1"]
    assert downloaded[0].metadata["download_provider"] == "kaggle-yt-dlp"
    assert failed == []
    kernel_source = (tmp_path / "downloads" / "kaggle_kernel" / "kernel.py").read_text(
        encoding="utf-8"
    )
    assert "VENDOR_DATASET_SLUG" in kernel_source
    assert "kaggle_prepare_failed" in kernel_source
    assert "stable-vendor" in kernel_source
    assert "kaggle-yt-dlp-vendor.zip" in kernel_source
    assert not any(call[:1] == ["datasets"] for call in calls)
    assert ["kernels", "push", "-p", str(tmp_path / "downloads" / "kaggle_kernel")] in calls
    assert ["kernels", "status", "test-user/viral-pipeline-ytdlp-test"] in calls
    assert calls[-1][:3] == ["kernels", "output", "test-user/viral-pipeline-ytdlp-test"]


def test_kaggle_batch_download_uses_configured_vendor_dataset(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = make_settings(tmp_path)
    settings.use_real_media = True
    settings.download_backend = "kaggle"
    settings.kaggle_kernel_slug = "viral-pipeline-ytdlp-test"
    settings.kaggle_vendor_dataset_ref = "test-user/stable-vendor"
    provider = KaggleYtDlpVideoDownloadProvider(settings)
    calls: list[list[str]] = []

    monkeypatch.setenv("KAGGLE_USERNAME", "test-user")
    monkeypatch.setattr("viral_pipeline.providers.time.sleep", lambda seconds: None)

    def fake_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:2] == ["kernels", "status"]:
            return subprocess.CompletedProcess(args, 0, stdout="complete\n")
        if args[:2] == ["kernels", "output"]:
            output_dir = Path(args[-1])
            output_dir.mkdir(parents=True, exist_ok=True)
            result_json = tmp_path / "result.json"
            result_json.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "successes": 1,
                        "results": [{"video_id": "video-1", "status": "ok"}],
                    }
                ),
                encoding="utf-8",
            )
            media_path = tmp_path / "video-1.mp4"
            media_path.write_text("media", encoding="utf-8")
            with zipfile.ZipFile(output_dir / "result.zip", "w") as archive:
                archive.write(result_json, "result.json")
                archive.write(media_path, "video-1.mp4")
        return subprocess.CompletedProcess(args, 0, stdout="")

    monkeypatch.setattr(provider, "_run", fake_run)

    downloaded, failed = provider.download_many(
        [
            YouTubeVideo(
                id="video-1",
                trend_id="trend-1",
                title="Funny short",
                url="https://www.youtube.com/watch?v=video-1",
            )
        ],
        tmp_path / "downloads",
        max_successes=1,
    )

    metadata = json.loads(
        (tmp_path / "downloads" / "kaggle_kernel" / "kernel-metadata.json").read_text(
            encoding="utf-8"
        )
    )
    assert [video.id for video in downloaded] == ["video-1"]
    assert failed == []
    assert metadata["dataset_sources"] == ["test-user/stable-vendor"]
    assert not any(call[:2] == ["datasets", "create"] for call in calls)
    assert not any(call[:2] == ["datasets", "files"] for call in calls)


def test_kaggle_batch_download_requires_vendor_dataset_ref(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = make_settings(tmp_path)
    settings.use_real_media = True
    settings.download_backend = "kaggle"
    provider = KaggleYtDlpVideoDownloadProvider(settings)

    monkeypatch.setenv("KAGGLE_USERNAME", "test-user")

    try:
        provider.download_many(
            [
                YouTubeVideo(
                    id="video-1",
                    trend_id="trend-1",
                    title="Funny short",
                    url="https://www.youtube.com/watch?v=video-1",
                )
            ],
            tmp_path / "downloads",
            max_successes=1,
        )
    except RuntimeError as exc:
        assert "KAGGLE_VENDOR_DATASET_REF is required" in str(exc)
    else:
        raise AssertionError("Expected missing Kaggle vendor dataset ref to fail")


def test_kaggle_vendor_dataset_ref_accepts_kaggle_url(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.kaggle_vendor_dataset_ref = (
        "https://www.kaggle.com/datasets/Test_User/viral-pipeline-yt-dlp-vendor"
    )
    provider = KaggleYtDlpVideoDownloadProvider(settings)

    assert provider._vendor_dataset_ref() == "test_user/viral-pipeline-yt-dlp-vendor"


def test_kaggle_vendor_dataset_ref_rejects_invalid_value(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.kaggle_vendor_dataset_ref = "viral-pipeline-yt-dlp-vendor"
    provider = KaggleYtDlpVideoDownloadProvider(settings)

    try:
        provider._vendor_dataset_ref()
    except RuntimeError as exc:
        assert "owner/dataset-slug" in str(exc)
    else:
        raise AssertionError("Expected invalid Kaggle vendor dataset ref to fail")


def test_kaggle_batch_download_marks_missing_result_as_infrastructure_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = make_settings(tmp_path)
    settings.use_real_media = True
    settings.download_backend = "kaggle"
    settings.kaggle_vendor_dataset_ref = "test-user/stable-vendor"
    provider = KaggleYtDlpVideoDownloadProvider(settings)

    monkeypatch.setenv("KAGGLE_USERNAME", "test-user")
    monkeypatch.setattr("viral_pipeline.providers.time.sleep", lambda seconds: None)

    def fake_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["kernels", "status"]:
            return subprocess.CompletedProcess(args, 0, stdout="complete\n")
        if args[:2] == ["kernels", "output"]:
            output_dir = Path(args[-1])
            output_dir.mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(args, 0, stdout="")

    monkeypatch.setattr(provider, "_run", fake_run)

    downloaded, failed = provider.download_many(
        [
            YouTubeVideo(
                id="video-1",
                trend_id="trend-1",
                title="Funny short",
                url="https://www.youtube.com/watch?v=video-1",
            )
        ],
        tmp_path / "downloads",
        max_successes=1,
    )

    assert downloaded == []
    assert len(failed) == 1
    assert failed[0].metadata["download_error"] == "kaggle_kernel_missing_result_json"
    assert failed[0].metadata["download_error_kind"] == "download_infrastructure_error"


def test_kaggle_missing_result_reports_log_content(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    provider = KaggleYtDlpVideoDownloadProvider(settings)
    output_dir = tmp_path / "kaggle_output"
    output_dir.mkdir()
    (output_dir / "kernel.log").write_text("important kaggle traceback", encoding="utf-8")

    listing = provider._kaggle_output_listing(output_dir)

    assert "kernel.log" in listing
    assert "important kaggle traceback" in listing


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
        assert "Only 0 source video" in str(exc)
    else:
        raise AssertionError("download stage should fail when no downloads succeed")

    history = SourceHistory(settings.source_history_path)._data()
    assert history["videos"]["video-1"]["stage"] == "download_failed"


def test_download_stage_respects_max_download_attempts(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.max_download_attempts = 2
    attempted: list[str] = []

    class AlwaysFailProvider:
        def download(self, video: YouTubeVideo, output_dir: Path) -> YouTubeVideo:
            attempted.append(video.id)
            raise FileNotFoundError(video.id)

    context = PipelineContext(
        run_id="download-attempt-limit-test",
        workdir=tmp_path,
        analyzed_videos=[
            YouTubeVideo(
                id=f"video-{index}",
                trend_id="trend-1",
                title=f"Funny toddler short {index}",
                url=f"https://www.youtube.com/watch?v=video-{index}",
            )
            for index in range(5)
        ],
    )

    try:
        DownloadVideosStage(settings, AlwaysFailProvider()).run(context)
    except RuntimeError:
        pass
    else:
        raise AssertionError("download stage should fail when all limited attempts fail")

    assert attempted == ["video-0", "video-1"]


def test_download_stage_can_continue_when_no_downloads_succeed(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.fail_on_no_source_downloads = False

    class AlwaysFailProvider:
        def download(self, video: YouTubeVideo, output_dir: Path) -> YouTubeVideo:
            raise FileNotFoundError(video.id)

    context = PipelineContext(
        run_id="download-skip-test",
        workdir=tmp_path,
        selected_trends=[
            Trend(
                title="football goals shorts",
                source="test",
                metadata={"source_language": "en"},
            )
        ],
        analyzed_videos=[
            YouTubeVideo(
                id="video-1",
                trend_id="trend-1",
                title="Football goal short",
                url="https://www.youtube.com/watch?v=video-1",
            )
        ],
    )

    context = DownloadVideosStage(settings, AlwaysFailProvider()).run(context)

    assert context.analyzed_videos == []
    assert context.metadata["download_summary"]["downloaded_count"] == 0
    assert context.metadata["download_summary"]["failed_count"] == 1
    assert context.metadata["download_summary"]["error_counts"] == {"video-1": 1}
    history = SourceHistory(settings.source_history_path)._data()
    assert history["videos"]["video-1"]["stage"] == "download_failed"


def test_download_stage_skips_when_below_minimum_downloads(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.max_download_videos = 5
    settings.min_download_videos_for_upload = 2
    settings.fail_on_no_source_downloads = False

    class OneSuccessProvider:
        def download(self, video: YouTubeVideo, output_dir: Path) -> YouTubeVideo:
            if video.id == "video-1":
                output_dir.mkdir(parents=True, exist_ok=True)
                path = output_dir / "video-1.mp4"
                path.write_text("media", encoding="utf-8")
                updated = video.model_copy(deep=True)
                updated.downloaded_path = path
                return updated
            raise FileNotFoundError(video.id)

    context = PipelineContext(
        run_id="download-below-minimum-test",
        workdir=tmp_path,
        selected_trends=[
            Trend(
                title="football goals shorts",
                source="test",
                metadata={"source_language": "en"},
            )
        ],
        analyzed_videos=[
            YouTubeVideo(
                id=f"video-{index}",
                trend_id="trend-1",
                title=f"Football goal short {index}",
                url=f"https://www.youtube.com/watch?v=video-{index}",
            )
            for index in range(1, 4)
        ],
    )

    context = DownloadVideosStage(settings, OneSuccessProvider()).run(context)

    assert context.analyzed_videos == []
    assert context.metadata["download_summary"]["downloaded_count"] == 1
    assert context.metadata["download_summary"]["failed_count"] == 2
    assert context.metadata["download_summary"]["downloaded_ids"] == ["video-1"]
    history = SourceHistory(settings.source_history_path)._data()
    assert history["videos"]["video-1"]["stage"] == "downloaded_below_publish_minimum"
    assert history["videos"]["video-2"]["stage"] == "download_failed"


def test_download_stage_stops_when_time_budget_expires(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path)
    settings.max_download_videos = 5
    settings.min_download_videos_for_upload = 2
    settings.fail_on_no_source_downloads = False
    settings.max_download_stage_seconds = 1

    class SlowFailProvider:
        attempts = 0

        def download(self, video: YouTubeVideo, output_dir: Path) -> YouTubeVideo:
            self.attempts += 1
            raise FileNotFoundError(video.id)

    provider = SlowFailProvider()
    times = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr("viral_pipeline.stages.time.monotonic", lambda: next(times))

    context = PipelineContext(
        run_id="download-budget-test",
        workdir=tmp_path,
        selected_trends=[Trend(title="cricket catches shorts", source="test")],
        analyzed_videos=[
            YouTubeVideo(
                id=f"video-{index}",
                trend_id="trend-1",
                title=f"Cricket short {index}",
                url=f"https://www.youtube.com/watch?v=video-{index}",
            )
            for index in range(1, 4)
        ],
    )

    context = DownloadVideosStage(settings, provider).run(context)

    assert provider.attempts == 1
    assert context.analyzed_videos == []


def test_download_stage_uses_batch_downloader_when_available(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.max_download_videos = 2
    settings.max_download_attempts = 3
    settings.min_download_videos_for_upload = 2

    class BatchProvider:
        calls = 0

        def download_many(
            self,
            videos: list[YouTubeVideo],
            output_dir: Path,
            *,
            max_successes: int,
        ) -> tuple[list[YouTubeVideo], list[YouTubeVideo]]:
            self.calls += 1
            assert [video.id for video in videos] == ["video-1", "video-2", "video-3"]
            assert max_successes == 2
            downloaded: list[YouTubeVideo] = []
            output_dir.mkdir(parents=True, exist_ok=True)
            for video in videos[:2]:
                path = output_dir / f"{video.id}.mp4"
                path.write_text("media", encoding="utf-8")
                updated = video.model_copy(deep=True)
                updated.downloaded_path = path
                downloaded.append(updated)
            failed = videos[2:]
            return downloaded, failed

        def download(self, video: YouTubeVideo, output_dir: Path) -> YouTubeVideo:
            raise AssertionError("single-video download should not be used")

    provider = BatchProvider()
    context = PipelineContext(
        run_id="batch-download-test",
        workdir=tmp_path,
        selected_trends=[Trend(title="football saves shorts", source="test")],
        analyzed_videos=[
            YouTubeVideo(
                id=f"video-{index}",
                trend_id="trend-1",
                title=f"Football short {index}",
                url=f"https://www.youtube.com/watch?v=video-{index}",
            )
            for index in range(1, 5)
        ],
    )

    context = DownloadVideosStage(settings, provider).run(context)

    assert provider.calls == 1
    assert [video.id for video in context.analyzed_videos] == ["video-1", "video-2"]
    history = SourceHistory(settings.source_history_path)._data()
    assert history["videos"]["video-3"]["stage"] == "download_failed"


def test_colab_batch_command_failure_returns_failed_videos(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    provider = ColabYtDlpVideoDownloadProvider(settings)
    video = YouTubeVideo(
        id="video-1",
        trend_id="trend-1",
        title="Football short",
        url="https://www.youtube.com/watch?v=video-1",
    )

    def fail_run(args: list[str], input_text: str | None = None) -> subprocess.CompletedProcess:
        raise subprocess.CalledProcessError(
            1,
            ["colab", *args],
            stderr="ReadTimeout: Colab did not respond",
        )

    provider._run = fail_run  # type: ignore[method-assign]

    downloaded, failed = provider.download_many([video], tmp_path / "downloads", max_successes=1)

    assert downloaded == []
    assert len(failed) == 1
    assert failed[0].metadata["download_error"] == "colab_batch_command_failed"
    assert failed[0].metadata["download_error_kind"] == "download_infrastructure_error"
    assert "ReadTimeout" in failed[0].metadata["download_stderr"]


def test_pipeline_retry_wrapper_detects_download_auth_block(tmp_path: Path) -> None:
    retry_script = load_pipeline_retry_script()

    blocked, reason = retry_script._download_auth_blocked(
        {
            "metadata": {
                "download_summary": {
                    "attempted_count": 10,
                    "downloaded_count": 0,
                    "failed_count": 10,
                    "failure_counts": {"youtube_bot_wall": 10},
                }
            }
        }
    )

    assert blocked is True
    assert reason is not None
    assert "bot-check wall" in reason


def test_pipeline_retry_wrapper_detects_youtube_challenge_failure(tmp_path: Path) -> None:
    retry_script = load_pipeline_retry_script()

    blocked, reason = retry_script._download_auth_blocked(
        {
            "metadata": {
                "download_summary": {
                    "attempted_count": 3,
                    "downloaded_count": 0,
                    "failed_count": 3,
                    "failure_counts": {"youtube_challenge_failed": 3},
                }
            }
        }
    )

    assert blocked is True
    assert reason is not None
    assert "JS/PO-token challenge" in reason


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


def test_download_stage_does_not_mark_bot_wall_failures_seen(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.fail_on_no_source_downloads = False

    class BotWallProvider:
        def download(self, video: YouTubeVideo, output_dir: Path) -> YouTubeVideo:
            raise subprocess.CalledProcessError(
                1,
                ["yt-dlp", video.url],
                stderr="ERROR: Sign in to confirm you’re not a bot.",
            )

    context = PipelineContext(
        run_id="download-bot-wall-skip-test",
        workdir=tmp_path,
        selected_trends=[Trend(title="football goals shorts", source="test")],
        analyzed_videos=[
            YouTubeVideo(
                id="video-1",
                trend_id="trend-1",
                title="Football short",
                url="https://www.youtube.com/watch?v=video-1",
            )
        ],
    )

    context = DownloadVideosStage(settings, BotWallProvider()).run(context)

    assert context.analyzed_videos == []
    assert context.metadata["download_summary"]["failure_counts"] == {"youtube_bot_wall": 1}
    assert SourceHistory(settings.source_history_path)._data()["videos"] == {}


def test_download_stage_does_not_mark_challenge_failures_seen(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.fail_on_no_source_downloads = False

    class ChallengeFailProvider:
        def download(self, video: YouTubeVideo, output_dir: Path) -> YouTubeVideo:
            raise subprocess.CalledProcessError(
                1,
                ["yt-dlp", video.url],
                stderr=(
                    "WARNING: n challenge solving failed\n"
                    "ERROR: [youtube] video-1: The page needs to be reloaded."
                ),
            )

    context = PipelineContext(
        run_id="download-challenge-failure-skip-test",
        workdir=tmp_path,
        selected_trends=[Trend(title="football goals shorts", source="test")],
        analyzed_videos=[
            YouTubeVideo(
                id="video-1",
                trend_id="trend-1",
                title="Football short",
                url="https://www.youtube.com/watch?v=video-1",
            )
        ],
    )

    context = DownloadVideosStage(settings, ChallengeFailProvider()).run(context)

    assert context.analyzed_videos == []
    assert context.metadata["download_summary"]["failure_counts"] == {
        "youtube_challenge_failed": 1
    }
    assert SourceHistory(settings.source_history_path)._data()["videos"] == {}


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


def test_upload_youtube_stage_skips_when_no_clips_were_selected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.enable_youtube_upload = True
    context = PipelineContext(run_id="upload-no-clips-test", workdir=tmp_path)

    context = UploadYouTubeStage(settings).run(context)

    assert context.youtube_upload is not None
    assert context.youtube_upload.status == "skipped"
    assert "No selected clips" in context.youtube_upload.metadata["reason"]


def test_upload_youtube_stage_skips_non_video_render_path(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.enable_youtube_upload = True
    manifest_path = tmp_path / "render" / "edit_decision_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}", encoding="utf-8")
    context = PipelineContext(
        run_id="upload-manifest-test",
        workdir=tmp_path,
        selected_clips=[
            ClipCandidate(
                video_id="video-1",
                trend_id="trend-1",
                start_seconds=0,
                end_seconds=10,
                title="Selected clip",
            )
        ],
        publish_package=PublishPackage(
            path=tmp_path / "publish" / "publish_manifest.json",
            title="Title",
            description="Description",
            tags=[],
            metadata={"render_path": str(manifest_path)},
        ),
    )

    context = UploadYouTubeStage(settings).run(context)

    assert context.youtube_upload is not None
    assert context.youtube_upload.status == "skipped"
    assert "did not reference a video render" in context.youtube_upload.metadata["reason"]


class FakeChannelsRequest:
    def __init__(self, channel_ids: list[str]) -> None:
        self.channel_ids = channel_ids

    def execute(self) -> dict[str, object]:
        return {
            "items": [
                {"id": channel_id, "snippet": {"title": f"Channel {channel_id}"}}
                for channel_id in self.channel_ids
            ]
        }


class FakeChannelsResource:
    def __init__(self, channel_ids: list[str]) -> None:
        self.channel_ids = channel_ids

    def list(self, **kwargs: object) -> FakeChannelsRequest:
        return FakeChannelsRequest(self.channel_ids)


class FakeYouTubeService:
    def __init__(self, channel_ids: list[str]) -> None:
        self.channel_ids = channel_ids

    def channels(self) -> FakeChannelsResource:
        return FakeChannelsResource(self.channel_ids)


def test_validate_expected_upload_channel_rejects_wrong_channel(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.youtube_upload_expected_channel_id = "expected-channel"

    try:
        _validate_expected_upload_channel(FakeYouTubeService(["other-channel"]), settings)
    except RuntimeError as exc:
        assert "expected-channel" in str(exc)
    else:
        raise AssertionError("Expected upload channel validation to fail")

    _validate_expected_upload_channel(FakeYouTubeService(["expected-channel"]), settings)


def test_niche_uploads_require_expected_channel_id(tmp_path: Path) -> None:
    for domain in ("football", "cricket"):
        settings = make_settings(tmp_path)
        settings.content_domain = domain
        settings.enable_youtube_upload = True

        try:
            _require_expected_upload_channel_for_domain(settings)
        except ValueError as exc:
            assert "YOUTUBE_UPLOAD_EXPECTED_CHANNEL_ID" in str(exc)
            assert domain in str(exc)
        else:
            raise AssertionError(f"Expected {domain} upload channel guard to fail")

        settings.youtube_upload_expected_channel_id = f"{domain}-channel"
        _require_expected_upload_channel_for_domain(settings)


def test_youtube_oauth_scopes_only_add_read_scope_for_channel_guard(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)

    assert _youtube_oauth_scopes(settings) == [
        "https://www.googleapis.com/auth/youtube.upload"
    ]

    settings.youtube_upload_expected_channel_id = "expected-channel"

    assert _youtube_oauth_scopes(settings) == [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
    ]


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
