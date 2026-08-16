from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def main() -> None:
    label = os.environ.get("PIPELINE_SUMMARY_LABEL", "Pipeline")
    summary_path = Path(os.environ.get("GITHUB_STEP_SUMMARY", "pipeline_summary.md"))
    context_paths = sorted(
        Path("workdir/runs").glob("*/context.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not context_paths:
        summary_path.open("a", encoding="utf-8").write(
            f"## {label}\n\nNo pipeline context was created.\n"
        )
        return

    context_path = context_paths[0]
    run_dir = context_path.parent
    context = _read_json(context_path)
    upload = _read_json(run_dir / "upload" / "youtube_upload.json")
    publish = _read_json(run_dir / "publish" / "publish_manifest.json")

    trends = context.get("selected_trends") or []
    trend = trends[0] if trends else {}
    trend_metadata = trend.get("metadata") or {}
    selected_clips = context.get("selected_clips") or []
    downloaded = [
        video
        for video in context.get("analyzed_videos") or []
        if (video.get("local_path") or video.get("metadata", {}).get("download_backend"))
    ]
    primary_query = (
        trend_metadata.get("primary_search_query") or trend.get("title") or "unknown"
    )
    analyzed_count = _count(context.get("analyzed_videos"))
    render_path = publish.get("video_path") or context.get("final_video_path") or "none"

    lines = [
        f"## {label}",
        "",
        f"- Run ID: `{context.get('run_id') or run_dir.name}`",
        f"- Search theme: `{trend.get('title') or 'unknown'}`",
        f"- Primary query: `{primary_query}`",
        f"- Candidate videos: `{_count(context.get('videos'))}`",
        f"- Analyzed/downloaded source videos: `{analyzed_count}` / `{len(downloaded)}`",
        f"- Selected clips: `{_count(selected_clips)}`",
        f"- Render path: `{render_path}`",
        f"- Upload status: `{upload.get('status') or 'not reached'}`",
    ]
    if upload.get("reason"):
        lines.append(f"- Upload skip reason: `{upload['reason']}`")
    if upload.get("video_id"):
        lines.append(f"- YouTube video ID: `{upload['video_id']}`")
    lines.append("")
    summary_path.open("a", encoding="utf-8").write("\n".join(lines))


if __name__ == "__main__":
    main()
