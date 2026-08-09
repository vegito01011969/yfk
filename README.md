# Automated Kids Funny-Moments Compilation Pipeline

This project is a modular pipeline for discovering kids/family funny-moment YouTube Shorts or very short videos, ranking the strongest moments, assembling a clean clip-only compilation video, and storing intermediate metadata for resume/debug workflows.

The code is structured as a production foundation rather than a one-off script. Each stage has a narrow interface and can be replaced independently as better providers, ranking models, or renderers are added.

## Current Capabilities

- Resumable run state stored in SQLite.
- Stage-by-stage CLI execution.
- Config via environment variables and `.env`.
- Provider abstraction for short-video query discovery, YouTube search, metadata generation, optional voiceover, media download, clip extraction, event ranking, and final assembly.
- YouTube Data API search when `YOUTUBE_API_KEY` is configured.
- Deterministic local fallback providers for development and CI.
- Optional real adapters for YouTube Data API, `yt-dlp`, `ffmpeg`, Groq/OpenAI-compatible metadata generation, and OpenAI voice generation.
- Downloads top Shorts or very short videos before clip extraction.
- Treats each short video as a candidate moment by default, then groups and ranks moments before final assembly.
- Produces a clip-only compilation by default: no title card, no numbering overlays, and no narration.
- Runs the final compilation through the local provenance robustness transform by default, then uses that transformed file as the publish-ready output.
- Tracks previously downloaded source video IDs in a small source-history file to avoid repeat runs reusing the same Shorts.
- Locks each run to one source language bucket, currently English or Hindi by default.
- Publishing package manifest with metadata, selected clips, and final render path.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
viral-pipeline init
viral-pipeline run
viral-pipeline status
```

The default configuration uses deterministic local providers so the pipeline can run without API keys. To enable real integrations:

```bash
pip install -e ".[media,ai]"
export YOUTUBE_API_KEY="..."
export USE_REAL_MEDIA=true
viral-pipeline run
```

## Pipeline Stages

1. `discover_trends` finds candidate short-video queries.
2. `select_trends` filters and prioritizes those queries.
3. `search_youtube` finds candidate Shorts or very short videos.
4. `analyze_videos` stores video-level signals.
5. `download_videos` downloads the strongest short videos.
6. `extract_clips` keeps short videos as whole candidate clips by default.
7. `dedupe_clips` removes duplicates and low-quality clips.
8. `identify_moments` annotates clips with moment terms and event keys.
9. `group_events` groups moments into unique events, with multiple evidence clips when possible.
10. `rank_events` scores events and selects representative clips.
11. `generate_script` creates title/manifest metadata.
12. `assemble_video` creates a plain compilation render or edit decision manifest.
13. `prepare_publish` writes a YouTube publishing package.

## Configuration

Key environment variables:

- `CONTENT_DOMAIN`: pipeline domain. Default: `kids_funny`.
- `CONTENT_LABEL`: label used for publish titles. Default: `Funny Kid Clips`.
- `SOURCE_LANGUAGE_MODE`: language selection strategy. Default: `cycle`.
- `SOURCE_LANGUAGES`: comma-separated source languages to rotate through. Default: `en,hi`.
- `SOURCE_HISTORY_PATH`: JSON source catalog used to avoid repeated YouTube source videos across runs. Default: `data/source_video_history.json`.
- `COMPILATION_QUERIES`: comma-separated searches such as `funny toddler fails shorts`, `kids pranks shorts`, and `funny baby reactions shorts`.
- `EVENT_KEYWORDS`: comma-separated moment terms used for grouping/ranking.
- `SOURCE_VIDEO_MODE`: source-video strategy. Default: `shorts`.
- `MAX_SOURCE_VIDEO_SECONDS`: maximum source duration kept in shorts mode. Default: `30`.
- `SELECTED_TREND_COUNT`: number of query candidates to process. Default: `1`.
- `MAX_DOWNLOAD_VIDEOS`: top short videos to download. Default: `10`.
- `MAX_CLIPS`: number of final selected clips. Default: `5`.
- `YOUTUBE_SEARCH_POOL_SIZE`: candidate pool requested before previous-source filtering. Default: `50`.
- `YOUTUBE_API_KEY`: enables YouTube Data API search.
- `YOUTUBE_OAUTH_CLIENT_SECRETS`: OAuth desktop client JSON for uploads.
- `YOUTUBE_OAUTH_TOKEN_PATH`: stored OAuth refresh token path.
- `ENABLE_YOUTUBE_UPLOAD`: enables the final YouTube upload stage. Default: `false`.
- `YOUTUBE_UPLOAD_PRIVACY_STATUS`: upload visibility. Default: `public`.
- `YOUTUBE_VIDEO_MADE_FOR_KIDS`: YouTube audience flag. Default: `false`.
- `GROQCLOUD_API_KEY` or `GROQ_API_KEY`: enables GroqCloud LLM metadata generation.
- `GROQCLOUD_MODEL`: OpenAI-compatible Groq model. Default: `openai/gpt-oss-20b`.
- `GROQCLOUD_BASE_URL`: default: `https://api.groq.com/openai/v1`.
- `USE_REAL_MEDIA`: enables `yt-dlp` and `ffmpeg` media operations.
- `YT_DLP_FORMAT`: yt-dlp format selector. Default caps downloads around 720p.
- `YT_DLP_COOKIES_PATH`: optional Netscape-format cookies file for `yt-dlp`; required on GitHub Actions if YouTube blocks anonymous runner downloads.
- `YT_DLP_JS_RUNTIMES`: optional `yt-dlp --js-runtimes` value. The scheduled workflow sets this to `node`.
- `YT_DLP_EXTRACTOR_ARGS`: optional `yt-dlp --extractor-args` value. The scheduled workflow sets this to `youtube:player_client=web`.
- `RENDER_MODE`: output style. Default: `plain_compilation`.
- `RENDER_WIDTH` / `RENDER_HEIGHT`: final canvas size. Default: `1080x1920` for YouTube Shorts-compatible vertical output.
- `APPLY_PROVENANCE_TRANSFORM`: run `provenance_robustness_tool` after assembly. Default: `true`.
- `PROVENANCE_TRANSFORM_SCRIPT`: path to the transform CLI. Default: `provenance_robustness_tool/transform.py`.
- `ENABLE_VOICEOVER`: opt into generated narration audio. Default: `false`.

## Real Media Output

With `USE_REAL_MEDIA=true`, downloaded videos are stored under:

```bash
workdir/runs/<run-id>/downloads/
```

Extracted clips are stored under:

```bash
workdir/runs/<run-id>/clips/<youtube-video-id>/
```

The final plain render is written to:

```bash
workdir/runs/<run-id>/render/final_video.mp4
```

By default the render is vertical `1080x1920`; with the current short source limits and `MAX_CLIPS=5`, the uploaded video is intended to be classified by YouTube as a Short.

When `APPLY_PROVENANCE_TRANSFORM=true`, `final_video.mp4` is the transformed publish-ready output. The untransformed assembly is kept for debugging at:

```bash
workdir/runs/<run-id>/render/pre_provenance_final_video.mp4
```

## Notes On Publishing

Uploads are controlled by `ENABLE_YOUTUBE_UPLOAD` and default to public visibility. Production use should include policy, copyright, consent, and rights-review checks as explicit gates.

Kids/family short-video content can involve additional consent, privacy, and platform-policy concerns. Treat this pipeline as an editing and research system; production use needs rights clearance, consent review where applicable, and platform-policy compliance.
