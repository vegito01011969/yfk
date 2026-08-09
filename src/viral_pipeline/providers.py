from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import requests

from viral_pipeline.config import Settings
from viral_pipeline.domain import (
    ClipCandidate,
    NarrationScript,
    Trend,
    VoiceoverAsset,
    YouTubeVideo,
)
from viral_pipeline.source_history import SourceHistory

LOGGER = logging.getLogger(__name__)

YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"

STOPWORDS = {
    "about",
    "after",
    "again",
    "all",
    "and",
    "are",
    "asmr",
    "best",
    "biggest",
    "clips",
    "comedy",
    "compilation",
    "concert",
    "day",
    "does",
    "episode",
    "for",
    "from",
    "full",
    "funniest",
    "funny",
    "gets",
    "has",
    "have",
    "how",
    "into",
    "just",
    "latest",
    "movie",
    "movies",
    "moment",
    "moments",
    "music",
    "new",
    "not",
    "official",
    "of",
    "only",
    "out",
    "part",
    "performance",
    "reaction",
    "shorts",
    "song",
    "songs",
    "that",
    "the",
    "this",
    "today",
    "top",
    "tiktok",
    "trending",
    "viral",
    "video",
    "videos",
    "was",
    "watch",
    "when",
    "with",
    "trailer",
    "trailers",
    "upcoming",
    "you",
    "youtube",
}

COMPILATION_TERMS = {"compilation", "moments", "clips", "fails", "reactions"}
ACTIVITY_CONTEXT_TERMS = {
    "activity",
    "attempt",
    "challenge",
    "challenged",
    "challenges",
    "doing",
    "duet",
    "everyone",
    "fails",
    "guess",
    "hack",
    "prank",
    "react",
    "recreate",
    "recreated",
    "recreating",
    "stitch",
    "trend",
    "tried",
    "tries",
    "trying",
    "vs",
}
ENTITY_HINT_TERMS = {
    "album",
    "artist",
    "band",
    "brand",
    "channel",
    "company",
    "concert",
    "gameplay",
    "group",
    "interview",
    "label",
    "lyrics",
    "movie",
    "official",
    "performance",
    "song",
    "trailer",
}

LANGUAGE_LABELS = {
    "en": "english",
    "hi": "hindi",
}

HINDI_ROMANIZED_HINTS = {
    "bachcha",
    "bachche",
    "baccha",
    "bache",
    "bacha",
    "hindi",
    "desi",
    "mummy",
    "papa",
    "dadi",
    "nani",
}

KIDS_FUNNY_CHILD_TERMS = {
    "baby",
    "babies",
    "bachcha",
    "bachche",
    "bacha",
    "bache",
    "baccha",
    "boy",
    "brother",
    "child",
    "children",
    "daughter",
    "family",
    "kid",
    "kids",
    "little",
    "sibling",
    "sister",
    "son",
    "toddler",
}

KIDS_FUNNY_PAYOFF_TERMS = {
    "blooper",
    "bloopers",
    "cute",
    "fail",
    "fails",
    "funniest",
    "funny",
    "giggle",
    "giggling",
    "hilarious",
    "laugh",
    "laughing",
    "mispronounce",
    "mispronounces",
    "prank",
    "pranks",
    "react",
    "reaction",
    "reactions",
    "silly",
    "surprise",
}

KIDS_FUNNY_EXCLUDED_TERMS = {
    "animation",
    "cartoon",
    "cocomelon",
    "game",
    "gameplay",
    "minecraft",
    "movie",
    "nursery",
    "official",
    "rhyme",
    "rhymes",
    "roblox",
    "song",
    "trailer",
}


class YouTubeApiError(RuntimeError):
    """Raised when a YouTube API call fails without exposing credentials."""


def _redact_api_key(text: str) -> str:
    return re.sub(r"([?&]key=)[^&\s]+", r"\1[redacted]", text)


class TrendProvider(Protocol):
    def discover(self, limit: int) -> list[Trend]: ...


class YouTubeProvider(Protocol):
    def search_compilations(self, trend: Trend, limit: int) -> list[YouTubeVideo]: ...


class VideoDownloadProvider(Protocol):
    def download(self, video: YouTubeVideo, output_dir: Path) -> YouTubeVideo: ...


class MediaProvider(Protocol):
    def extract_clips(self, video: YouTubeVideo, output_dir: Path) -> list[ClipCandidate]: ...


class ScriptProvider(Protocol):
    def generate(self, trends: list[Trend], clips: list[ClipCandidate]) -> NarrationScript: ...


class VoiceProvider(Protocol):
    def synthesize(self, script: NarrationScript, output_dir: Path) -> VoiceoverAsset: ...


class YouTubeApiClient:
    def __init__(self, api_key: str, session: requests.Session | None = None) -> None:
        self.api_key = api_key
        self.session = session or requests.Session()

    def get(self, endpoint: str, params: dict[str, str | int]) -> dict[str, Any]:
        try:
            response = self.session.get(
                f"{YOUTUBE_API_BASE_URL}/{endpoint}",
                params={**params, "key": self.api_key},
                timeout=20,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise YouTubeApiError(
                f"YouTube API request failed for {endpoint}: {_redact_api_key(str(exc))}"
            ) from None
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected YouTube API response for {endpoint}")
        return payload

    def most_popular_videos(
        self,
        *,
        region_code: str,
        max_results: int,
        category_id: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str | int] = {
            "part": "snippet,statistics,contentDetails",
            "chart": "mostPopular",
            "regionCode": region_code,
            "maxResults": min(max_results, 50),
        }
        if category_id:
            params["videoCategoryId"] = category_id
        return list(self.get("videos", params).get("items", []))

    def search_videos(
        self,
        *,
        query: str,
        max_results: int,
        order: str = "relevance",
        published_after: datetime | None = None,
        region_code: str | None = None,
        video_duration: str | None = None,
        relevance_language: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str | int] = {
            "part": "snippet",
            "type": "video",
            "maxResults": min(max_results, 50),
            "q": query,
            "order": order,
            "safeSearch": "moderate",
        }
        if published_after:
            params["publishedAfter"] = (
                published_after.astimezone(UTC).isoformat().replace("+00:00", "Z")
            )
        if region_code:
            params["regionCode"] = region_code
        if video_duration:
            params["videoDuration"] = video_duration
        if relevance_language:
            params["relevanceLanguage"] = relevance_language
        return list(self.get("search", params).get("items", []))

    def videos_by_id(self, video_ids: list[str]) -> list[dict[str, Any]]:
        if not video_ids:
            return []
        params: dict[str, str | int] = {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(video_ids[:50]),
            "maxResults": len(video_ids[:50]),
        }
        return list(self.get("videos", params).get("items", []))


def _parse_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_rfc3339(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_iso8601_duration_seconds(value: str | None) -> int | None:
    if not value:
        return None
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?",
        value,
    )
    if not match:
        return None
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return int(timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds).total_seconds())


def _youtube_video_from_item(item: dict[str, Any], trend_id: str) -> YouTubeVideo:
    snippet = item.get("snippet", {})
    statistics = item.get("statistics", {})
    content_details = item.get("contentDetails", {})
    video_id = str(item["id"])
    return YouTubeVideo(
        id=video_id,
        trend_id=trend_id,
        title=str(snippet.get("title", "")),
        channel_title=snippet.get("channelTitle"),
        url=f"https://www.youtube.com/watch?v={video_id}",
        published_at=_parse_rfc3339(snippet.get("publishedAt")),
        duration_seconds=_parse_iso8601_duration_seconds(content_details.get("duration")),
        view_count=_parse_int(statistics.get("viewCount")),
        like_count=_parse_int(statistics.get("likeCount")),
        comment_count=_parse_int(statistics.get("commentCount")),
        metadata={
            "source": "youtube_data_api",
            "category_id": snippet.get("categoryId"),
            "description": snippet.get("description"),
            "tags": snippet.get("tags") or [],
            "default_language": snippet.get("defaultLanguage"),
            "default_audio_language": snippet.get("defaultAudioLanguage"),
        },
    )


def _source_languages(settings: Settings) -> list[str]:
    languages = [
        language.strip().lower()
        for language in settings.source_languages.split(",")
        if language.strip()
    ]
    return languages or ["en"]


def _language_label(language: str | None) -> str | None:
    if not language:
        return None
    return LANGUAGE_LABELS.get(language.lower(), language.lower())


def _append_language_to_query(query: str, language: str | None) -> str:
    label = _language_label(language)
    if not label or label in query.lower():
        return query
    return f"{query} {label}"


def _shorts_search_queries(
    query: str,
    language: str | None,
    settings: Settings | None,
) -> list[str]:
    base_query = query if "short" in query.lower() else f"{query} shorts"
    queries = [_append_language_to_query(base_query, language)]
    if settings and settings.content_domain == "kids_funny":
        lowered = query.lower()
        if "toddler" in lowered:
            fallback = "funny toddler shorts"
        elif "baby" in lowered or "babies" in lowered:
            fallback = "funny baby reactions shorts"
        elif "prank" in lowered:
            fallback = "funny kids pranks shorts"
        elif "fail" in lowered:
            fallback = "kids funny fails shorts"
        elif "blooper" in lowered:
            fallback = "kids bloopers shorts"
        else:
            fallback = "funny kids shorts"
        queries.append(_append_language_to_query(fallback, language))
        queries.append(_append_language_to_query("funny kids shorts", language))

    deduped: list[str] = []
    for item in queries:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _contains_devanagari(text: str) -> bool:
    return any("\u0900" <= char <= "\u097f" for char in text)


def _declared_language(video: YouTubeVideo) -> str | None:
    for key in ("default_audio_language", "default_language"):
        value = video.metadata.get(key)
        if isinstance(value, str) and value:
            return value.lower().split("-")[0]
    return None


def _video_matches_language(video: YouTubeVideo, language: str | None) -> bool:
    if not language:
        return True
    language = language.lower()
    declared = _declared_language(video)
    if declared:
        return declared == language

    text = f"{video.title} {video.channel_title or ''}".lower()
    has_devanagari = _contains_devanagari(text)
    if language == "hi":
        tokens = set(re.findall(r"[a-z]+", text))
        return has_devanagari or bool(tokens & HINDI_ROMANIZED_HINTS)
    if language == "en":
        tokens = set(re.findall(r"[a-z]+", text))
        return not has_devanagari and not bool(tokens & HINDI_ROMANIZED_HINTS)
    return True


def _video_search_text(video: YouTubeVideo) -> str:
    tags = video.metadata.get("tags")
    return " ".join(
        [
            video.title,
            video.channel_title or "",
            str(video.metadata.get("description") or ""),
            " ".join(str(tag) for tag in tags) if isinstance(tags, list) else "",
        ]
    ).lower()


def _kids_funny_relevance_score(video: YouTubeVideo, query: str) -> float:
    text = _video_search_text(video)
    tokens = set(re.findall(r"[a-z]+", text))
    query_tokens = set(re.findall(r"[a-z]+", query.lower()))
    query_tokens |= {token.rstrip("s") for token in query_tokens if len(token) > 3}
    comparable_tokens = tokens | {token.rstrip("s") for token in tokens if len(token) > 3}
    has_devanagari_child = any(hint in text for hint in ("बच्च", "बच्", "बेबी"))
    child_matches = tokens & KIDS_FUNNY_CHILD_TERMS
    payoff_matches = tokens & KIDS_FUNNY_PAYOFF_TERMS
    query_matches = comparable_tokens & query_tokens
    excluded_matches = tokens & KIDS_FUNNY_EXCLUDED_TERMS

    score = 0.0
    if child_matches or has_devanagari_child:
        score += 0.34
    if payoff_matches:
        score += min(0.36, 0.18 + len(payoff_matches) * 0.045)
    if query_matches:
        score += min(0.2, len(query_matches) * 0.04)
    if video.view_count:
        score += min(0.12, video.view_count / 1_000_000 * 0.12)
    if video.like_count:
        score += min(0.06, video.like_count / 100_000 * 0.06)
    if "short" in text or "#shorts" in text:
        score += 0.04

    if excluded_matches:
        score -= min(0.55, 0.28 + len(excluded_matches) * 0.06)
    if not child_matches and not has_devanagari_child:
        score -= 0.25
    if not payoff_matches:
        score -= 0.2

    return round(max(0.0, min(1.0, score)), 4)


def _video_ids_from_search_items(items: list[dict[str, Any]]) -> list[str]:
    return [
        item["id"]["videoId"]
        for item in items
        if isinstance(item.get("id"), dict) and item["id"].get("videoId")
    ]


def _snippet_text(item: dict[str, Any]) -> str:
    snippet = item.get("snippet", {})
    parts = [
        str(snippet.get("title", "")),
        str(snippet.get("description", "")),
        " ".join(str(tag) for tag in snippet.get("tags", []) or []),
    ]
    return " ".join(parts).lower()


def _activity_evidence_count(items: list[dict[str, Any]]) -> int:
    count = 0
    for item in items:
        text = _snippet_text(item)
        if any(term in text for term in ACTIVITY_CONTEXT_TERMS):
            count += 1
    return count


def _entity_hint_count(items: list[dict[str, Any]]) -> int:
    count = 0
    for item in items:
        text = _snippet_text(item)
        if any(term in text for term in ENTITY_HINT_TERMS):
            count += 1
    return count


def _activity_seed_queries(settings: Settings) -> list[str]:
    return [
        query.strip()
        for query in settings.youtube_activity_seed_queries.split(",")
        if query.strip()
    ]


def _normalize_terms(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9][a-z0-9'-]{2,}", text.lower())
        if token not in STOPWORDS and not token.isdigit()
    ]


def _is_useful_candidate_phrase(phrase: str) -> bool:
    raw_tokens = re.findall(r"[a-z0-9][a-z0-9'-]{2,}", phrase.lower())
    if any(token in STOPWORDS for token in raw_tokens):
        return False
    tokens = _normalize_terms(phrase)
    if len(tokens) < 2:
        return False
    if len(tokens) > 4:
        return False
    if any(token in STOPWORDS for token in tokens):
        return False
    return bool(re.search(r"[a-z]", phrase))


def _candidate_phrases(item: dict[str, Any]) -> Counter[str]:
    snippet = item.get("snippet", {})
    terms = _normalize_terms(str(snippet.get("title", "")))
    tags = snippet.get("tags") or []
    counts: Counter[str] = Counter()
    counts.update({term: 1.0 for term in terms})
    counts.update({" ".join(terms[index : index + 2]): 1.8 for index in range(len(terms) - 1)})
    counts.update({" ".join(terms[index : index + 3]): 2.2 for index in range(len(terms) - 2)})
    counts.update(
        {
            str(tag).lower().strip(): 2.5
            for tag in tags
            if 3 <= len(str(tag).strip()) <= 48
            and _is_useful_candidate_phrase(str(tag).lower().strip())
        }
    )
    return Counter(
        {
            phrase: count
            for phrase, count in counts.items()
            if _is_useful_candidate_phrase(phrase)
        }
    )


class LocalTrendProvider:
    def discover(self, limit: int) -> list[Trend]:
        seeds = [
            ("AI yearbook filters", 0.91),
            ("NPC livestream reactions", 0.86),
            ("tiny desk setup transformations", 0.78),
            ("airport tray aesthetic", 0.72),
            ("retro handheld gaming mods", 0.68),
        ]
        return [
            Trend(
                title=title,
                source="local_seed",
                velocity_score=velocity,
                audience_fit_score=max(0.5, velocity - 0.08),
            )
            for title, velocity in seeds[:limit]
        ]


class CompilationQueryProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.history = SourceHistory(settings.source_history_path)

    def discover(self, limit: int) -> list[Trend]:
        queries = [
            query.strip()
            for query in self.settings.compilation_queries.split(",")
            if query.strip()
        ]
        languages = (
            _source_languages(self.settings)
            if self.settings.source_language_mode == "cycle"
            else [_source_languages(self.settings)[0]]
        )
        candidates = [
            (query, language)
            for query in queries
            for language in languages
        ]
        candidates = sorted(
            candidates,
            key=lambda item: (
                int(self.history.query_stats(item[0], item[1]).get("run_count") or 0),
                str(self.history.query_stats(item[0], item[1]).get("last_used_at") or ""),
                queries.index(item[0]),
                languages.index(item[1]),
            ),
        )
        trends: list[Trend] = []
        for index, (query, language) in enumerate(candidates[:limit]):
            score = max(0.45, 1.0 - index * 0.06)
            trends.append(
                Trend(
                    title=query,
                    source="compilation_query",
                    velocity_score=score,
                    audience_fit_score=0.9,
                    metadata={
                        "domain": self.settings.content_domain,
                        "query_rank": index + 1,
                        "source_language": language,
                        "source_language_label": _language_label(language),
                        "query_run_count": int(
                            self.history.query_stats(query, language).get("run_count") or 0
                        ),
                    },
                )
            )
        return trends


class YouTubeTrendProvider:
    def __init__(self, settings: Settings, client: YouTubeApiClient) -> None:
        self.settings = settings
        self.client = client

    def discover(self, limit: int) -> list[Trend]:
        published_after = datetime.now(UTC) - timedelta(
            hours=self.settings.youtube_trend_lookback_hours
        )
        popular_videos = self.client.most_popular_videos(
            region_code=self.settings.youtube_region_code,
            max_results=self.settings.youtube_trend_source_video_count,
            category_id=self.settings.youtube_trend_category_id,
        )
        activity_seed_videos: list[dict[str, Any]] = []
        for query in _activity_seed_queries(self.settings):
            activity_seed_videos.extend(
                self.client.search_videos(
                    query=query,
                    max_results=self.settings.youtube_trend_probe_results,
                    order="date",
                    published_after=published_after,
                    region_code=self.settings.youtube_region_code,
                )
            )

        source_videos = [*activity_seed_videos, *popular_videos]
        candidates = self._rank_candidates(source_videos)
        trends: list[Trend] = []

        for phrase, base_score in candidates:
            topic_hits = self.client.search_videos(
                query=phrase,
                max_results=self.settings.youtube_trend_probe_results,
                order="date",
                published_after=published_after,
                region_code=self.settings.youtube_region_code,
            )
            compilation_hits = self.client.search_videos(
                query=f"{phrase} compilation",
                max_results=self.settings.youtube_trend_probe_results,
                order="date",
                published_after=published_after,
                region_code=self.settings.youtube_region_code,
            )
            topic_video_ids = _video_ids_from_search_items(topic_hits)
            compilation_video_ids = _video_ids_from_search_items(compilation_hits)
            activity_evidence_count = _activity_evidence_count([*topic_hits, *compilation_hits])
            entity_hint_count = _entity_hint_count([*topic_hits, *compilation_hits])
            compilation_ratio = (
                len(compilation_video_ids) / max(1, len(topic_video_ids))
                if topic_video_ids
                else 0.0
            )
            if (
                len(topic_video_ids) < self.settings.youtube_trend_min_topic_videos
                or len(compilation_video_ids)
                < self.settings.youtube_trend_min_compilation_videos
                or activity_evidence_count
                < self.settings.youtube_trend_min_compilation_videos
                or entity_hint_count > activity_evidence_count
            ):
                continue

            trend = Trend(
                title=phrase,
                source="youtube_most_popular_with_topic_and_compilation_probes",
                velocity_score=min(
                    1.0,
                    base_score * 0.65
                    + len(topic_video_ids) / self.settings.youtube_trend_probe_results * 0.35,
                ),
                audience_fit_score=min(
                    1.0,
                    0.35
                    + len(compilation_video_ids)
                    / self.settings.youtube_trend_probe_results
                    * 0.45
                    + min(0.2, compilation_ratio * 0.2),
                ),
                metadata={
                    "region_code": self.settings.youtube_region_code,
                    "source_video_count": len(source_videos),
                    "popular_source_video_count": len(popular_videos),
                    "activity_seed_source_video_count": len(activity_seed_videos),
                    "topic_probe_count": len(topic_video_ids),
                    "topic_probe_video_ids": topic_video_ids,
                    "compilation_probe_count": len(compilation_video_ids),
                    "compilation_probe_video_ids": compilation_video_ids,
                    "compilation_ratio": compilation_ratio,
                    "activity_evidence_count": activity_evidence_count,
                    "entity_hint_count": entity_hint_count,
                },
            )
            trends.append(trend)
            if len(trends) >= limit:
                break

        if trends:
            return trends

        LOGGER.warning("YouTube trend discovery returned no activity-backed trends")
        return []

    def _rank_candidates(
        self, source_videos: list[dict[str, Any]]
    ) -> list[tuple[str, float]]:
        weighted_counts: defaultdict[str, float] = defaultdict(float)
        for position, item in enumerate(source_videos):
            position_weight = max(0.15, 1.0 - position / max(1, len(source_videos)))
            statistics = item.get("statistics", {})
            view_weight = min(1.0, (_parse_int(statistics.get("viewCount")) or 0) / 2_000_000)
            phrase_weight = position_weight + view_weight
            for phrase, count in _candidate_phrases(item).items():
                if len(phrase.split()) > 4:
                    continue
                weighted_counts[phrase] += count * phrase_weight

        if not weighted_counts:
            return []

        max_score = max(weighted_counts.values()) or 1.0
        return [
            (phrase, score / max_score)
            for phrase, score in sorted(
                weighted_counts.items(), key=lambda item: item[1], reverse=True
            )[:40]
            if len(phrase) <= 60
        ]


class YouTubeDataProvider:
    def __init__(self, api_key: str, settings: Settings | None = None) -> None:
        self.api_key = api_key
        self.settings = settings
        self.client = YouTubeApiClient(api_key)
        self.history = SourceHistory(settings.source_history_path) if settings else None

    def search_compilations(self, trend: Trend, limit: int) -> list[YouTubeVideo]:
        if self.settings and self.settings.source_video_mode == "shorts":
            return self._search_short_videos(trend, limit)

        existing_video_ids = trend.metadata.get("compilation_probe_video_ids")
        if isinstance(existing_video_ids, list) and existing_video_ids:
            video_ids = [str(video_id) for video_id in existing_video_ids[:limit]]
            return [
                _youtube_video_from_item(item, trend.id)
                for item in self.client.videos_by_id(video_ids)
            ]

        published_after = datetime.now(UTC) - timedelta(
            hours=self.settings.youtube_trend_lookback_hours if self.settings else 168
        )
        search_items = self.client.search_videos(
            query=f"{trend.title} compilation",
            max_results=limit,
            order="date",
            published_after=published_after,
            region_code=self.settings.youtube_region_code if self.settings else None,
        )
        video_ids = _video_ids_from_search_items(search_items)
        videos = [
            _youtube_video_from_item(item, trend.id)
            for item in self.client.videos_by_id(video_ids)
        ]
        return [
            video
            for video in videos
            if any(term in video.title.lower() for term in COMPILATION_TERMS)
        ]

    def _search_short_videos(self, trend: Trend, limit: int) -> list[YouTubeVideo]:
        published_after = datetime.now(UTC) - timedelta(
            hours=self.settings.youtube_trend_lookback_hours if self.settings else 168
        )
        language = trend.metadata.get("source_language")
        language = str(language) if language else None
        pool_size = min(
            self.settings.youtube_search_pool_size if self.settings else 50,
            max(limit * 6, limit),
        )
        videos: list[YouTubeVideo] = []
        seen_search_ids: set[str] = set()
        search_queries = _shorts_search_queries(trend.title, language, self.settings)
        for search_query in search_queries:
            for attempt_published_after in (published_after, None):
                search_items = self.client.search_videos(
                    query=search_query,
                    max_results=pool_size,
                    order="relevance",
                    published_after=attempt_published_after,
                    region_code=self.settings.youtube_region_code if self.settings else None,
                    video_duration="short",
                    relevance_language=language,
                )
                video_ids = [
                    video_id
                    for video_id in _video_ids_from_search_items(search_items)
                    if video_id not in seen_search_ids
                ]
                seen_search_ids.update(video_ids)
                for item in self.client.videos_by_id(video_ids):
                    video = _youtube_video_from_item(item, trend.id)
                    video.metadata["search_query"] = search_query
                    video.metadata["search_published_after"] = (
                        attempt_published_after.isoformat()
                        if attempt_published_after
                        else None
                    )
                    videos.append(video)
                if len(videos) >= pool_size:
                    break
            if len(videos) >= pool_size:
                break
        max_seconds = self.settings.max_source_video_seconds if self.settings else 75
        short_videos = [
            video
            for video in videos
            if video.duration_seconds is not None
            and video.duration_seconds <= max_seconds
            and _video_matches_language(video, language)
        ]
        seen_ids = self.history.seen_video_ids() if self.history else set()
        fresh_videos: list[YouTubeVideo] = []
        for video in short_videos:
            updated = video.model_copy(deep=True)
            search_query = str(updated.metadata.get("search_query") or search_queries[0])
            relevance_score = (
                _kids_funny_relevance_score(updated, search_query)
                if self.settings and self.settings.content_domain == "kids_funny"
                else 0.75
            )
            updated.metadata["primary_search_query"] = search_queries[0]
            updated.metadata["source_language"] = language
            updated.metadata["search_relevance_score"] = relevance_score
            if updated.id in seen_ids:
                updated.metadata["filtered_reason"] = "previously_seen_source_video"
                continue
            if (
                self.settings
                and self.settings.content_domain == "kids_funny"
                and relevance_score < 0.45
            ):
                updated.metadata["filtered_reason"] = "low_kids_funny_relevance"
                continue
            fresh_videos.append(updated)
        return sorted(
            fresh_videos,
            key=lambda item: (
                float(item.metadata.get("search_relevance_score") or 0.0),
                item.view_count or 0,
                item.like_count or 0,
            ),
            reverse=True,
        )[:limit]


class LocalYouTubeProvider:
    def search_compilations(self, trend: Trend, limit: int) -> list[YouTubeVideo]:
        videos: list[YouTubeVideo] = []
        slug = trend.title.lower().replace(" ", "-")
        for index in range(limit):
            video_id = hashlib.sha1(f"{trend.id}:{index}".encode()).hexdigest()[:11]
            videos.append(
                YouTubeVideo(
                    id=video_id,
                    trend_id=trend.id,
                    title=f"{trend.title} short #{index + 1}",
                    channel_title="Local Fixtures",
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    view_count=100_000 - index * 7_500,
                    like_count=8_000 - index * 500,
                    comment_count=600 - index * 40,
                    duration_seconds=18 + index * 6,
                    metadata={"source": "local_fixture", "slug": slug},
                )
            )
        return videos


class YtDlpVideoDownloadProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def download(self, video: YouTubeVideo, output_dir: Path) -> YouTubeVideo:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_template = output_dir / f"{video.id}.%(ext)s"
        command = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-playlist",
            "--restrict-filenames",
            "--write-info-json",
            "--merge-output-format",
            "mp4",
            "-f",
            self.settings.yt_dlp_format,
            "-o",
            str(output_template),
        ]
        cookies_path = self.settings.yt_dlp_cookies_path
        if cookies_path and cookies_path.exists():
            command.extend(["--cookies", str(cookies_path)])
        if self.settings.yt_dlp_js_runtimes:
            command.extend(["--js-runtimes", self.settings.yt_dlp_js_runtimes])
        command.append(video.url)
        subprocess.run(command, check=True)
        downloaded = self._find_download(video.id, output_dir)
        updated = video.model_copy(deep=True)
        updated.downloaded_path = downloaded
        updated.metadata["download_provider"] = "yt-dlp"
        updated.metadata["downloaded_path"] = str(downloaded)
        return updated

    def _find_download(self, video_id: str, output_dir: Path) -> Path:
        candidates = [
            path
            for path in output_dir.glob(f"{video_id}.*")
            if path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
        ]
        if not candidates:
            raise FileNotFoundError(f"yt-dlp did not produce a media file for {video_id}")
        return sorted(candidates, key=lambda path: path.stat().st_size, reverse=True)[0]


class LocalVideoDownloadProvider:
    def download(self, video: YouTubeVideo, output_dir: Path) -> YouTubeVideo:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{video.id}.download.json"
        path.write_text(
            json.dumps(
                {
                    "video_id": video.id,
                    "url": video.url,
                    "title": video.title,
                    "note": "Placeholder download manifest. Set USE_REAL_MEDIA=true for yt-dlp.",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        updated = video.model_copy(deep=True)
        updated.downloaded_path = path
        updated.metadata["download_provider"] = "local_manifest"
        updated.metadata["downloaded_path"] = str(path)
        return updated


class YtDlpFfmpegMediaProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def extract_clips(self, video: YouTubeVideo, output_dir: Path) -> list[ClipCandidate]:
        output_dir.mkdir(parents=True, exist_ok=True)
        if video.downloaded_path is None:
            raise ValueError(f"Video {video.id} has not been downloaded")
        download_path = video.downloaded_path
        duration = self._probe_duration(download_path)
        if (
            self.settings.source_video_mode == "shorts"
            and duration <= self.settings.max_source_video_seconds
        ):
            return self._whole_video_clip(video, output_dir, download_path, duration)
        segments = self._candidate_segments(download_path, duration)
        clips: list[ClipCandidate] = []
        for index, (start, end, source) in enumerate(segments[: self.settings.max_clips_per_video]):
            clip_path = output_dir / f"{video.id}_{index:03d}_{start:.1f}-{end:.1f}.mp4"
            self._write_clip(download_path, clip_path, start, end)
            clip_duration = max(0.0, end - start)
            quality_score = min(1.0, 0.45 + clip_duration / self.settings.max_clip_seconds * 0.4)
            clips.append(
                ClipCandidate(
                    video_id=video.id,
                    trend_id=video.trend_id,
                    start_seconds=float(start),
                    end_seconds=float(end),
                    title=f"{video.title} clip {index + 1}",
                    path=clip_path,
                    perceptual_hash=hashlib.sha1(f"{video.id}:{start:.2f}:{end:.2f}".encode()).hexdigest()[:16],
                    quality_score=quality_score,
                    relevance_score=0.7,
                    metadata={
                        "source": "ffmpeg_scene_extraction",
                        "segment_source": source,
                        "source_video_path": str(download_path),
                        "source_video_duration_seconds": duration,
                    },
                )
            )
        return clips

    def _whole_video_clip(
        self,
        video: YouTubeVideo,
        output_dir: Path,
        download_path: Path,
        duration: float,
    ) -> list[ClipCandidate]:
        clip_path = output_dir / f"{video.id}_whole_0.0-{duration:.1f}.mp4"
        self._write_clip(download_path, clip_path, 0.0, duration)
        duration_component = (
            min(duration, self.settings.max_clip_seconds)
            / self.settings.max_clip_seconds
            * 0.35
        )
        quality_score = min(
            1.0,
            0.55 + duration_component,
        )
        return [
            ClipCandidate(
                video_id=video.id,
                trend_id=video.trend_id,
                start_seconds=0.0,
                end_seconds=float(duration),
                title=f"{video.title} short",
                path=clip_path,
                perceptual_hash=hashlib.sha1(f"{video.id}:whole:{duration:.2f}".encode()).hexdigest()[:16],
                quality_score=quality_score,
                relevance_score=0.75,
                metadata={
                    "source": "ffmpeg_whole_short_extraction",
                    "segment_source": "whole_short",
                    "source_video_path": str(download_path),
                    "source_video_duration_seconds": duration,
                },
            )
        ]

    def _probe_duration(self, path: Path) -> float:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return float(result.stdout.strip())

    def _candidate_segments(self, path: Path, duration: float) -> list[tuple[float, float, str]]:
        scene_times = self._detect_scene_times(path)
        scene_segments = self._segments_from_boundaries(scene_times, duration)
        if len(scene_segments) >= max(2, self.settings.max_clips_per_video // 2):
            return scene_segments
        return self._fallback_segments(duration)

    def _detect_scene_times(self, path: Path) -> list[float]:
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-i",
                str(path),
                "-vf",
                (
                    f"select='gt(scene,{self.settings.clip_scene_threshold})',"
                    "showinfo"
                ),
                "-an",
                "-f",
                "null",
                "-",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode not in {0, 255}:
            LOGGER.warning("ffmpeg scene detection failed for %s: %s", path, result.stderr[-500:])
            return []

        times: list[float] = []
        for match in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", result.stderr):
            value = float(match.group(1))
            if not times or value - times[-1] >= self.settings.min_clip_seconds:
                times.append(value)
        return times

    def _segments_from_boundaries(
        self, scene_times: list[float], duration: float
    ) -> list[tuple[float, float, str]]:
        boundaries = [0.0, *[time for time in scene_times if 0.0 < time < duration], duration]
        segments: list[tuple[float, float, str]] = []
        for start, end in zip(boundaries, boundaries[1:], strict=False):
            if end - start < self.settings.min_clip_seconds:
                continue
            segment_end = min(end, start + self.settings.max_clip_seconds)
            if segment_end - start >= self.settings.min_clip_seconds:
                segments.append((round(start, 2), round(segment_end, 2), "scene_boundary"))
        return segments

    def _fallback_segments(self, duration: float) -> list[tuple[float, float, str]]:
        clip_length = min(self.settings.max_clip_seconds, max(self.settings.min_clip_seconds, 12.0))
        stride = max(self.settings.min_clip_seconds, clip_length * 0.75)
        segments: list[tuple[float, float, str]] = []
        start = 0.0
        while start + self.settings.min_clip_seconds <= duration:
            end = min(duration, start + clip_length)
            segments.append((round(start, 2), round(end, 2), "fixed_window_fallback"))
            if len(segments) >= self.settings.max_clips_per_video:
                break
            start += stride
        return segments

    def _write_clip(self, source: Path, destination: Path, start: float, end: float) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{start:.3f}",
                "-t",
                f"{end - start:.3f}",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                str(destination),
            ],
            check=True,
            capture_output=True,
            text=True,
        )


class LocalMediaProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def extract_clips(self, video: YouTubeVideo, output_dir: Path) -> list[ClipCandidate]:
        output_dir.mkdir(parents=True, exist_ok=True)
        clips: list[ClipCandidate] = []
        clip_count = 1 if self.settings.source_video_mode == "shorts" else 3
        for index in range(clip_count):
            start = index * 12.0
            if self.settings.source_video_mode == "shorts":
                end = float(video.duration_seconds or min(self.settings.max_clip_seconds, 18.0))
            else:
                end = start + min(self.settings.max_clip_seconds, 10.0 + index)
            digest = hashlib.sha1(f"{video.id}:{index}".encode()).hexdigest()
            manifest_path = output_dir / f"{video.id}_{index}.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "video_url": str(video.url),
                        "start_seconds": start,
                        "end_seconds": end,
                        "note": (
                            "Placeholder clip manifest. Enable USE_REAL_MEDIA for "
                            "ffmpeg extraction."
                        ),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            clips.append(
                ClipCandidate(
                    video_id=video.id,
                    trend_id=video.trend_id,
                    start_seconds=start,
                    end_seconds=end,
                    title=f"{video.title} moment {index + 1}",
                    path=manifest_path,
                    perceptual_hash=digest[:16],
                    quality_score=0.55 + index * 0.1,
                    relevance_score=0.65,
                    transcript=f"Representative moment for {video.title}",
                    metadata={"source": "local_manifest"},
                )
            )
        return clips


class GroqMetadataScriptProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.fallback = LocalScriptProvider()

    def generate(self, trends: list[Trend], clips: list[ClipCandidate]) -> NarrationScript:
        from openai import OpenAI  # type: ignore[import-not-found]

        api_key = self.settings.llm_api_key
        if not api_key:
            return self.fallback.generate(trends, clips)

        client = OpenAI(
            api_key=api_key,
            base_url=self.settings.groqcloud_base_url,
        )
        system_prompt = (
            "You are a YouTube packaging assistant for short compilation videos. "
            "Generate publish metadata only. Do not invent claims about ownership, "
            "permission, or the people in the clips. Keep language platform-safe, "
            "concise, and suitable for a family/funny clips compilation. Return valid JSON only."
        )
        user_prompt = json.dumps(
            {
                "task": "Generate YouTube title, description, tags, hashtags, and summary.",
                "required_json_schema": {
                    "title": "string, <= 95 chars",
                    "description": "string, 2-4 short paragraphs",
                    "tags": "array of 8-15 short strings",
                    "hashtags": "array of 3-6 strings beginning with #",
                    "summary": "string, one sentence",
                },
                "content_domain": self.settings.content_domain,
                "content_label": self.settings.content_label,
                "source_language": (
                    trends[0].metadata.get("source_language") if trends else None
                ),
                "query_bucket": trends[0].title if trends else None,
                "clip_count": len(clips),
                "clips": [
                    {
                        "clip_id": clip.id,
                        "source_video_id": clip.video_id,
                        "title": clip.title,
                        "duration_seconds": round(clip.duration_seconds, 3),
                        "score": round(clip.final_score, 4),
                    }
                    for clip in clips
                ],
            },
            ensure_ascii=False,
        )
        full_prompt = f"""
SYSTEM:
{system_prompt}

USER:
{user_prompt}

IMPORTANT:
- Respond with VALID JSON ONLY
- No markdown
- No explanation
"""
        try:
            response = client.responses.create(
                model=self.settings.groqcloud_model,
                input=full_prompt,
            )
            youtube_metadata = _normalize_youtube_metadata(
                json.loads(response.output_text.strip()),
                clips,
            )
        except Exception as exc:
            fallback = self.fallback.generate(trends, clips)
            fallback.metadata["llm_metadata_error"] = str(exc)
            return fallback

        script = self.fallback.generate(trends, clips)
        script.title = youtube_metadata["title"]
        script.hook = youtube_metadata["summary"]
        script.metadata["provider"] = "groqcloud"
        script.metadata["youtube_metadata"] = youtube_metadata
        return script


class OpenAIScriptProvider(GroqMetadataScriptProvider):
    pass


def _normalize_youtube_metadata(
    payload: dict[str, Any],
    clips: list[ClipCandidate],
) -> dict[str, Any]:
    title = str(payload.get("title") or f"Top {len(clips)} Funny Kid Clips").strip()
    title = title[:95].strip()
    description = str(payload.get("description") or "").strip()
    if not description:
        description = f"Top {len(clips)} funny kid clips selected from short-video sources."

    raw_tags = payload.get("tags")
    tags = (
        [str(tag).strip() for tag in raw_tags if str(tag).strip()]
        if isinstance(raw_tags, list)
        else []
    )
    raw_hashtags = payload.get("hashtags")
    hashtags = (
        [str(tag).strip() for tag in raw_hashtags if str(tag).strip()]
        if isinstance(raw_hashtags, list)
        else []
    )
    hashtags = [
        tag if tag.startswith("#") else f"#{tag.lstrip('#')}"
        for tag in hashtags
    ][:6]
    summary = str(payload.get("summary") or title).strip()
    return {
        "title": title,
        "description": description,
        "tags": tags[:15],
        "hashtags": hashtags,
        "summary": summary,
    }


class LocalScriptProvider:
    def generate(self, trends: list[Trend], clips: list[ClipCandidate]) -> NarrationScript:
        ordered_clips = sorted(clips, key=lambda clip: clip.final_score, reverse=True)
        body = [
            (
                f"Moment {index + 1}: this clip stands out because the reaction "
                "is easy to understand immediately."
            )
            for index, clip in enumerate(ordered_clips)
        ]
        timeline = [
            {
                "type": "intro",
                "narration": (
                    "The best compilation clips work fast: a clear setup, a funny "
                    "reaction, and a payoff that lands immediately."
                ),
            },
            *[
                {
                    "type": "clip",
                    "clip_id": clip.id,
                    "clip_path": str(clip.path) if clip.path else None,
                    "source_video_id": clip.video_id,
                    "duration_seconds": clip.duration_seconds,
                    "narration": (
                        f"Moment {index + 1}: the setup is simple, and the reaction "
                        "is what makes the clip work."
                    ),
                }
                for index, clip in enumerate(ordered_clips)
            ],
            {
                "type": "outro",
                "narration": (
                    "That is what separates a random segment from a useful "
                    "compilation moment: the reaction is clear even without context."
                ),
            },
        ]
        return NarrationScript(
            title="Top funny moments",
            hook=(
                "These clips were selected from compilation sources as clear, "
                "self-contained funny moments."
            ),
            body=body or ["The strongest examples all share a simple visual payoff."],
            outro=(
                "The pattern is clear: easy participation, fast recognition, "
                "and a repeatable twist."
            ),
            metadata={"provider": "local_template", "timeline": timeline},
        )


class OpenAIVoiceProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def synthesize(self, script: NarrationScript, output_dir: Path) -> VoiceoverAsset:
        from openai import OpenAI  # type: ignore[import-not-found]

        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "voiceover.mp3"
        client = OpenAI(api_key=self.settings.openai_api_key)
        with client.audio.speech.with_streaming_response.create(
            model="gpt-4o-mini-tts",
            voice=self.settings.openai_voice,
            input=script.as_text(),
        ) as response:
            response.stream_to_file(path)
        return VoiceoverAsset(path=path, provider="openai")


class LocalVoiceProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def synthesize(self, script: NarrationScript, output_dir: Path) -> VoiceoverAsset:
        output_dir.mkdir(parents=True, exist_ok=True)
        text_path = output_dir / "voiceover.txt"
        text_path.write_text(script.as_text(), encoding="utf-8")
        if not self.settings.use_real_media:
            return VoiceoverAsset(path=text_path, provider="local_text_placeholder")

        aiff_path = output_dir / "voiceover.aiff"
        mp3_path = output_dir / "voiceover.mp3"
        try:
            subprocess.run(
                [
                    "say",
                    "-v",
                    self.settings.local_tts_voice,
                    "-o",
                    str(aiff_path),
                    script.as_text(),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(aiff_path),
                    "-codec:a",
                    "libmp3lame",
                    "-q:a",
                    "4",
                    str(mp3_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            duration = _probe_audio_duration(mp3_path)
            return VoiceoverAsset(
                path=mp3_path,
                duration_seconds=duration,
                provider="macos_say",
                metadata={"script_text_path": str(text_path)},
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            LOGGER.warning("Local TTS failed, keeping text placeholder: %s", exc)
            return VoiceoverAsset(path=text_path, provider="local_text_placeholder")


def _probe_audio_duration(path: Path) -> float | None:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def build_providers(
    settings: Settings,
) -> tuple[
    TrendProvider,
    YouTubeProvider,
    VideoDownloadProvider,
    MediaProvider,
    ScriptProvider,
    VoiceProvider,
]:
    youtube_client = (
        YouTubeApiClient(settings.youtube_api_key) if settings.youtube_api_key else None
    )
    trend_provider: TrendProvider = (
        CompilationQueryProvider(settings)
        if settings.content_domain in {"kids_funny", "compilation"}
        else YouTubeTrendProvider(settings, youtube_client)
        if youtube_client
        else LocalTrendProvider()
    )
    youtube_provider: YouTubeProvider = (
        YouTubeDataProvider(settings.youtube_api_key, settings)
        if settings.youtube_api_key
        else LocalYouTubeProvider()
    )
    download_provider: VideoDownloadProvider = (
        YtDlpVideoDownloadProvider(settings)
        if settings.use_real_media
        else LocalVideoDownloadProvider()
    )
    media_provider: MediaProvider = (
        YtDlpFfmpegMediaProvider(settings)
        if settings.use_real_media
        else LocalMediaProvider(settings)
    )
    script_provider: ScriptProvider = (
        GroqMetadataScriptProvider(settings) if settings.llm_api_key else LocalScriptProvider()
    )
    voice_provider: VoiceProvider = (
        OpenAIVoiceProvider(settings) if settings.openai_api_key else LocalVoiceProvider(settings)
    )
    return (
        trend_provider,
        youtube_provider,
        download_provider,
        media_provider,
        script_provider,
        voice_provider,
    )
