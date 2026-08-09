# Operations

## Local Development

```bash
pip install -e ".[dev]"
viral-pipeline init
viral-pipeline run --verbose
viral-pipeline status
```

## CI Candidate

The local providers make CI deterministic. A scheduled GitHub Actions job can run:

```bash
pip install -e ".[dev]"
pytest
viral-pipeline run
```

For production runs, configure secrets:

- `YOUTUBE_API_KEY`
- `OPENAI_API_KEY`

Then install optional extras:

```bash
pip install -e ".[media,ai]"
```

The media mode also requires `ffmpeg` and `yt-dlp` to be available on the runner.

## Download Stage

`download_videos` downloads only the top analyzed compilation videos for the selected activity trend. By default this is three videos and one selected trend:

```bash
export SELECTED_TREND_COUNT=1
export MAX_DOWNLOAD_VIDEOS=3
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
viral-pipeline run --latest --stage rank_clips
```

## Failure Recovery

1. Inspect run status with `viral-pipeline status`.
2. Inspect context with `viral-pipeline show latest`.
3. Fix the failed provider or bad artifact.
4. Resume with `viral-pipeline run --latest`.

## Scheduled Automation Shape

A production GitHub Actions workflow should:

1. Restore or attach persistent storage for `data/` and `workdir/`.
2. Run tests and lint.
3. Execute `viral-pipeline run --latest`.
4. Upload the publish package as an artifact.
5. Stop before upload unless rights and policy gates pass.
