from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from viral_pipeline.domain import YouTubeVideo, utc_now


class SourceHistory:
    def __init__(self, path: Path) -> None:
        self.path = path

    def seen_video_ids(self) -> set[str]:
        videos = self._data().get("videos", {})
        if not isinstance(videos, dict):
            return set()
        return {str(video_id) for video_id in videos}

    def query_stats(self, query: str, language: str | None = None) -> dict[str, Any]:
        queries = self._data().get("queries", {})
        if not isinstance(queries, dict):
            return {}
        payload = queries.get(self._query_key(query, language), {})
        return payload if isinstance(payload, dict) else {}

    def mark_query_used(
        self,
        query: str,
        run_id: str,
        language: str | None = None,
    ) -> None:
        data = self._data()
        queries = data.setdefault("queries", {})
        if not isinstance(queries, dict):
            queries = {}
            data["queries"] = queries
        payload = queries.setdefault(self._query_key(query, language), {})
        if not isinstance(payload, dict):
            payload = {}
            queries[self._query_key(query, language)] = payload
        payload["run_count"] = int(payload.get("run_count") or 0) + 1
        payload["last_run_id"] = run_id
        payload["last_used_at"] = utc_now().isoformat()
        payload["query"] = query
        payload["language"] = language
        self._write(data)

    def mark_videos_seen(
        self,
        videos: list[YouTubeVideo],
        *,
        run_id: str,
        query: str | None = None,
        language: str | None = None,
        stage: str = "downloaded",
    ) -> None:
        data = self._data()
        video_payloads = data.setdefault("videos", {})
        if not isinstance(video_payloads, dict):
            video_payloads = {}
            data["videos"] = video_payloads
        now = utc_now().isoformat()
        for video in videos:
            existing = video_payloads.setdefault(video.id, {})
            if not isinstance(existing, dict):
                existing = {}
                video_payloads[video.id] = existing
            existing.setdefault("first_seen_at", now)
            existing["last_seen_at"] = now
            existing["last_run_id"] = run_id
            existing["title"] = video.title
            existing["url"] = video.url
            existing["query"] = query
            existing["language"] = language
            existing["stage"] = stage
        self._write(data)

    def _query_key(self, query: str, language: str | None = None) -> str:
        return f"{query}::{language}" if language else query

    def _data(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"videos": {}, "queries": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"videos": {}, "queries": {}}
        return payload if isinstance(payload, dict) else {"videos": {}, "queries": {}}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data["updated_at"] = datetime.now().astimezone().isoformat()
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self.path)
