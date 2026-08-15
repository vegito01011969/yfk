# Architecture

The pipeline is organized around independently replaceable stages. Each stage receives a `PipelineContext`, enriches it, and returns it. The runner persists the context and stage status after every successful stage.

## Modules

- `viral_pipeline.domain`: shared models and stage names.
- `viral_pipeline.config`: environment-driven settings.
- `viral_pipeline.storage`: SQLite run, stage, and artifact persistence.
- `viral_pipeline.providers`: external provider protocols and default adapters.
- `viral_pipeline.source_history`: lightweight JSON catalog for previously used source videos and query buckets.
- `viral_pipeline.stages`: stage implementations.
- `viral_pipeline.runner`: orchestration and resume logic.
- `viral_pipeline.cli`: operator interface.

## Production Extension Points

Discovery:

- `kids_funny` mode uses configurable short-video searches such as funny toddler fails, kids pranks, baby reactions, toddler bloopers, sibling moments, and kid mispronunciations.
- `football` mode uses configurable short-video searches such as football goals, football skills, football saves, last-minute football goals, football fails, football celebrations, football comebacks, football referee moments, and football penalty saves.
- Football-mode search query generation defensively includes the literal word `football`, even when a custom query override omits it.
- Query candidates are represented by `Trend` records for compatibility with the runner, but they are discovery topics rather than channel strategy decisions.
- Query discovery prefers the least-used query+language bucket, so each run stays thematically and linguistically coherent while rotating across buckets over time.
- Add additional source adapters behind `TrendProvider` when useful.
- Store source-specific metrics in `Trend.metadata`.

YouTube collection:

- Expand `YouTubeDataProvider` with `videos.list` statistics and content details.
- In `kids_funny` mode, search results are scored for real kid/toddler presence, an obvious funny payoff, query-bucket fit, and popularity; cartoons, nursery rhymes, games, trailers, and songs are demoted.
- In `football` mode, search results are scored for real football/soccer terms, an obvious moment/payoff, query-bucket fit, and popularity; gameplay, transfer news, podcasts, trailers, cartoons, and songs are demoted.
- Add quota-aware pagination and backoff.
- In `SOURCE_VIDEO_MODE=shorts`, search requests ask YouTube for short videos and the collected details are filtered by `MAX_SOURCE_VIDEO_SECONDS`.
- Search requests pass `relevanceLanguage` and local filters keep only videos matching the selected run language when metadata or title signals are strong enough.
- Previously downloaded source video IDs are filtered out using `SOURCE_HISTORY_PATH`, so fresh runs avoid reusing the same Shorts.
- Download failures are skipped and recorded in source history so unavailable Shorts do not repeatedly break scheduled runs.
- Add filters for language, channel-level allow/deny lists, and stricter consent/rights review.

Clip extraction:

- The media adapter downloads selected Shorts or very short videos with `yt-dlp`. In shorts mode, each source is kept as a whole candidate clip.
- For longer-source modes, improve extraction with transcript segmentation, speech/music changes, face/object detection, repeated-replay detection, and audio peak/laughter cues.
- Compute stronger perceptual hashes, embeddings, and audio fingerprints for cross-source matching.

Event modeling:

- `ClipCandidate` records are evidence segments.
- `ContentEvent` records are the important ranked object. They hold an event key, evidence clip IDs, source video IDs, representative clip, frequency score, quality score, story score, and final score.
- Current grouping uses configurable event terms and visual fingerprints when available, then falls back to type/time buckets. Future versions should add OCR, transcript cues, object/action embeddings, and visual embeddings so the same moment can be merged even when it appears in different uploads or crops.

Ranking:

- Rank individual events/shorts, not only source-video search position.
- Blend source frequency, visual/audio quality, story potential, novelty, recency, and source-video engagement.
- Add explicit policy, rights, consent, and privacy-review gates before final selection.

Assembly:

- The default renderer creates an ffmpeg-assembled clip-only compilation with no title card, numbering overlays, or voiceover. Voiceover remains available as an opt-in mode.
- The default canvas is vertical `1080x1920`, so short compilations uploaded through YouTube are Shorts-compatible by format and duration.
- After assembly, the renderer can pass the compiled video through `provenance_robustness_tool/transform.py`; when enabled, the transformed derivative becomes `render/final_video.mp4`, while the untransformed assembly is retained as `render/pre_provenance_final_video.mp4`.
- Keep renderers behind a narrow adapter so timeline generation remains testable.

Publishing:

- `generate_script` uses a Groq/OpenAI-compatible provider when `GROQCLOUD_API_KEY`, `GROQ_API_KEY`, or `OPENAI_API_KEY` is configured. It asks the model for JSON-only YouTube packaging metadata: title, description, tags, hashtags, and summary.
- `prepare_publish` consumes that structured metadata when present and falls back to deterministic local metadata when the LLM is unavailable or returns invalid JSON.
- `upload_youtube` uses OAuth and `videos.insert` when `ENABLE_YOUTUBE_UPLOAD=true`. The upload result is stored under the run's `upload/` directory.
- The kids and football GitHub Actions workflows use separate OAuth token/client secrets, source-history files, cache keys, and concurrency groups. Football uploads additionally require `YOUTUBE_UPLOAD_EXPECTED_CHANNEL_ID` to match the authenticated channel before upload.
- Add YouTube upload only after title/description policy checks, consent checks, and rights clearance are formalized.

## Resume Model

The SQLite database stores:

- `runs`: one row per pipeline execution.
- `stage_runs`: one row per run/stage with status and error information.
- `artifacts`: JSON snapshots, including the latest `PipelineContext`.

The runner skips completed stages by default when resuming a full run. Single-stage execution is available for debugging and intentionally bypasses the full dependency graph, so operators should use it only after prerequisite artifacts exist.
