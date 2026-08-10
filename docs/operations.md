# Operations

## GitHub Actions Automation

The production workflow is `.github/workflows/pipeline.yml`. It runs automatically every 4 hours and can also be started manually from the GitHub Actions UI.

The media workflow currently runs on GitHub-hosted Ubuntu runners with an experimental YouTube PO-token setup. YouTube commonly blocks shared runner IPs with “Sign in to confirm you’re not a bot,” even when valid cookies and a JavaScript runtime are provided, so this setup may still fail depending on YouTube's current enforcement and the runner IP assigned to the job.

Schedule:

```yaml
0 */4 * * *
```

Required GitHub repository secrets:

- `YOUTUBE_API_KEY`
- `GROQCLOUD_API_KEY`
- `YOUTUBE_OAUTH_CLIENT_SECRETS_JSON`
- `YOUTUBE_OAUTH_TOKEN_JSON`
- `YOUTUBE_COOKIES_TXT`

`YOUTUBE_OAUTH_CLIENT_SECRETS_JSON` is the full contents of the Google OAuth desktop client JSON file.

`YOUTUBE_OAUTH_TOKEN_JSON` is the full contents of the locally authorized YouTube OAuth token file. Generate or refresh it locally by running the upload stage once, then copy `data/youtube_oauth_token.json` into the GitHub secret. The Actions workflow is intentionally non-interactive; if this token is missing or invalid, the run fails instead of trying to open a browser.

`YOUTUBE_COOKIES_TXT` is a Netscape-format YouTube cookies export used by `yt-dlp` for downloads. Without this, YouTube may reject download traffic with “Sign in to confirm you’re not a bot.” Export cookies from the same browser/account you use for YouTube access and refresh this secret whenever YouTube invalidates the cookies.

Hosted-runner YouTube download setup:

1. Installs `yt-dlp>=2025.5.22`, which supports PO-token provider plugins.
2. Installs `bgutil-ytdlp-pot-provider==1.3.1` into the workflow Python environment.
3. Starts the matching `brainicism/bgutil-ytdlp-pot-provider:1.3.1` Docker service on port `4416`.
4. Uses multiline `YT_DLP_EXTRACTOR_ARGS` so `yt-dlp` receives both `youtube:player_client=mweb` and `youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416`.
5. Still passes `YOUTUBE_COOKIES_TXT`, Node.js, and `YT_DLP_JS_RUNTIMES=node`.

If hosted downloads keep failing with the same bot-wall error, the remaining reliable option is to run the workflow on a self-hosted runner or another controlled machine/network where `yt-dlp --cookies cookies.txt "https://www.youtube.com/watch?v=..."` works normally.

Runtime behavior:

- Installs Python dependencies, `ffmpeg`, and sets up Node.js for `yt-dlp` JavaScript challenges.
- Starts the bgutil PO-token provider service for `yt-dlp`.
- Sets `YT_DLP_JS_RUNTIMES=node` so `yt-dlp` actually uses the installed Node.js runtime.
- Sets multiline `YT_DLP_EXTRACTOR_ARGS` so YouTube downloads use the mobile-web client path and the local bgutil HTTP provider.
- Validates that `YOUTUBE_COOKIES_TXT` is raw Netscape cookies.txt content before the pipeline starts.
- Restores cached `data/source_video_history.json` so source-video history survives across scheduled runs.
- Writes OAuth JSON and YouTube cookies secrets into ignored files under `secrets/`.
- Runs `viral-pipeline run --no-resume` with real media and public YouTube upload enabled.
- Uploads metadata-only diagnostics for failed runs with 3-day retention.
- Runs `viral-pipeline cleanup --yes` to remove bulky/resumable state.
- Saves only updated `data/source_video_history.json` for the next scheduled run.
- Does not mark source videos as used when every download fails, because that usually indicates an infrastructure-wide download problem rather than bad individual source videos.

Tests and lint run separately in `.github/workflows/ci.yml` on push and pull request. They are intentionally not part of the 4-hour upload workflow.

The workflow uploads videos as public by default:

```bash
YOUTUBE_UPLOAD_PRIVACY_STATUS=public
YOUTUBE_VIDEO_MADE_FOR_KIDS=false
YOUTUBE_VIDEO_SELF_DECLARED_MADE_FOR_KIDS=false
```

## Local Development

```bash
pip install -e ".[dev]"
viral-pipeline init
viral-pipeline run --verbose
viral-pipeline status
```

For local production-equivalent runs:

```bash
pip install -e ".[media,ai,dev]"
export USE_REAL_MEDIA=true
export ENABLE_YOUTUBE_UPLOAD=true
viral-pipeline run --no-resume
```

## Download Stage

`download_videos` downloads only the top analyzed short videos for the selected query bucket. Current defaults are one selected query and up to ten downloaded videos:

```bash
export SELECTED_TREND_COUNT=1
export MAX_DOWNLOAD_VIDEOS=10
export USE_REAL_MEDIA=true
viral-pipeline run
```

For debugging, first run through discovery/search/analyze, then rerun a single stage:

```bash
viral-pipeline run --latest --stage download_videos
```

To extract clips from already-downloaded compilations:

```bash
export USE_REAL_MEDIA=true
export MAX_CLIPS_PER_VIDEO=4
export MAX_CLIPS=5
viral-pipeline run --latest --stage extract_clips
```

To filter duplicates and select the final examples:

```bash
viral-pipeline run --latest --stage dedupe_clips
viral-pipeline run --latest --stage identify_moments
viral-pipeline run --latest --stage group_events
viral-pipeline run --latest --stage rank_events
```

## Failure Recovery

1. Inspect run status with `viral-pipeline status`.
2. Inspect context with `viral-pipeline show latest`.
3. Fix the failed provider or bad artifact.
4. Resume with `viral-pipeline run --latest`.

## Scheduled Automation Notes

The workflow intentionally uses `--no-resume` so every 4-hour schedule creates a new run. Cross-run duplicate avoidance comes from the cached `data/source_video_history.json`, not from resuming the previous pipeline run. Only successful downloads, and failed downloads from a partially successful run, are recorded as source history.

After each scheduled run, cleanup removes:

- `workdir/`, including downloads, clips, renders, and per-run snapshots.
- `data/pipeline.sqlite3`, because scheduled runs do not resume old runs.

Cleanup keeps:

- `data/source_video_history.json`, because it is the minimal state needed to avoid repeated source videos and rotate query buckets.

Uploads are public. Review rights, consent, and policy status before each production schedule remains enabled.
