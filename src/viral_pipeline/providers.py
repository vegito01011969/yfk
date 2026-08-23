from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import subprocess
import sys
import time
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

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
COMMAND_OUTPUT_SNIPPET_CHARS = 4000
YOUTUBE_BOT_WALL_MARKERS = (
    "sign in to confirm you",
    "not a bot",
)
YOUTUBE_CHALLENGE_FAILURE_MARKERS = (
    "challenge solving failed",
    "the page needs to be reloaded",
)
YOUTUBE_WEBPO_FAILURE_MARKERS = (
    "could not find webpoclient in browser",
    "timed out waiting for webpoclient",
)


def _is_youtube_bot_wall_text(text: str) -> bool:
    haystack = text.lower()
    return all(marker in haystack for marker in YOUTUBE_BOT_WALL_MARKERS)


def _is_youtube_challenge_failure_text(text: str) -> bool:
    haystack = text.lower()
    return (
        all(marker in haystack for marker in YOUTUBE_CHALLENGE_FAILURE_MARKERS)
        or any(marker in haystack for marker in YOUTUBE_WEBPO_FAILURE_MARKERS)
    )


def _called_process_output(exc: subprocess.CalledProcessError | subprocess.TimeoutExpired) -> str:
    stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout
    stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
    return "\n".join(part for part in (stdout, stderr) if part)

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

FOOTBALL_CORE_TERMS = {
    "assist",
    "ball",
    "club",
    "corner",
    "cup",
    "defender",
    "fans",
    "football",
    "free",
    "freekick",
    "futsal",
    "goal",
    "goalkeeper",
    "goals",
    "header",
    "keeper",
    "league",
    "match",
    "penalty",
    "player",
    "referee",
    "save",
    "saves",
    "soccer",
    "stadium",
    "striker",
    "tackle",
    "team",
    "volley",
}

FOOTBALL_MOMENT_TERMS = {
    "amazing",
    "best",
    "celebration",
    "comeback",
    "crazy",
    "dribble",
    "dribbling",
    "epic",
    "fail",
    "fails",
    "funniest",
    "funny",
    "impossible",
    "incredible",
    "insane",
    "last",
    "minute",
    "moments",
    "nutmeg",
    "red",
    "save",
    "saves",
    "skill",
    "skills",
    "stoppage",
    "unbelievable",
    "unexpected",
    "viral",
}

FOOTBALL_EXCLUDED_TERMS = {
    "asmr",
    "career",
    "cartoon",
    "eafc",
    "edit",
    "edits",
    "efootball",
    "fc24",
    "fc25",
    "fifa",
    "game",
    "gameplay",
    "gaming",
    "highlights",
    "history",
    "interview",
    "ishowspeed",
    "lyrics",
    "minecraft",
    "news",
    "pack",
    "packs",
    "podcast",
    "reaction",
    "roblox",
    "rumor",
    "rumors",
    "song",
    "talk",
    "talks",
    "total",
    "transfer",
    "transfers",
    "trailer",
}

FOOTBALL_THEME_QUERIES: dict[str, list[str]] = {
    "saves": [
        "unreal football saves shorts",
        "crazy football goalkeeper saves shorts",
        "impossible football saves shorts",
        "best football penalty saves shorts",
    ],
    "penalties": [
        "epic football penalties shorts",
        "dramatic football penalty shootout shorts",
        "football penalty goals shorts",
        "football penalty saves shorts",
    ],
    "passes": [
        "insane football passes shorts",
        "unbelievable football assists shorts",
        "football through ball assists shorts",
        "football no look passes shorts",
    ],
    "goals": [
        "best football goals shorts",
        "unbelievable football goals shorts",
        "impossible football goals shorts",
        "football long range goals shorts",
    ],
    "free_kicks": [
        "impossible football free kicks shorts",
        "best football free kick goals shorts",
        "unbelievable football free kicks shorts",
        "football curved free kick goals shorts",
    ],
    "comebacks": [
        "legendary football comebacks shorts",
        "football last minute comeback goals shorts",
        "football stoppage time goals shorts",
        "football last minute goals shorts",
    ],
    "skills": [
        "football skills that shocked everyone shorts",
        "football nutmeg skills shorts",
        "insane football dribbling skills shorts",
        "football skill moves shorts",
    ],
    "volleys": [
        "football volley goals shorts",
        "best football volleys shorts",
        "unbelievable football volley goals shorts",
        "football bicycle kick goals shorts",
    ],
    "clearances": [
        "football goal line clearances shorts",
        "unbelievable football clearances shorts",
        "last second football clearances shorts",
        "football defender goal line saves shorts",
    ],
    "cards": [
        "football red card drama shorts",
        "crazy football red cards shorts",
        "football referee drama shorts",
        "controversial football moments shorts",
    ],
    "moments": [
        "unforgettable football moments shorts",
        "emotional football moments shorts",
        "shocking football moments shorts",
        "football moments that shocked everyone shorts",
    ],
}

CRICKET_CORE_TERMS = {
    "ball",
    "batter",
    "batting",
    "batsman",
    "boundary",
    "bowler",
    "bowling",
    "bouncer",
    "catch",
    "catches",
    "cricket",
    "fielder",
    "fielding",
    "four",
    "googly",
    "innings",
    "match",
    "over",
    "run",
    "runout",
    "runs",
    "six",
    "sixes",
    "spin",
    "stadium",
    "stump",
    "stumping",
    "wicket",
    "wickets",
    "yorker",
}

CRICKET_MOMENT_TERMS = {
    "amazing",
    "best",
    "celebration",
    "crazy",
    "dramatic",
    "epic",
    "finish",
    "finishes",
    "impossible",
    "incredible",
    "insane",
    "last",
    "legendary",
    "moment",
    "moments",
    "over",
    "shocking",
    "super",
    "unbelievable",
    "unforgettable",
    "unreal",
    "unexpected",
    "viral",
}

CRICKET_EXCLUDED_TERMS = {
    "cartoon",
    "dream11",
    "edit",
    "edits",
    "fantasy",
    "game",
    "gameplay",
    "gaming",
    "highlights",
    "interview",
    "jersey",
    "lyrics",
    "minecraft",
    "news",
    "podcast",
    "prediction",
    "reaction",
    "roblox",
    "schedule",
    "score",
    "scores",
    "song",
    "talk",
    "talks",
    "trailer",
}

CRICKET_THEME_QUERIES: dict[str, list[str]] = {
    "catches": [
        "unreal cricket catches shorts",
        "best cricket catches shorts",
        "insane cricket fielding catches shorts",
        "impossible cricket catch shorts",
    ],
    "sixes": [
        "epic cricket sixes shorts",
        "biggest cricket sixes shorts",
        "unbelievable cricket sixes shorts",
        "insane cricket batting sixes shorts",
    ],
    "wickets": [
        "best cricket wickets shorts",
        "crazy cricket wickets shorts",
        "unbelievable cricket bowling wickets shorts",
        "cricket stump flying wickets shorts",
    ],
    "bowling": [
        "insane cricket bowling shorts",
        "best cricket yorkers shorts",
        "unplayable cricket bowling shorts",
        "cricket bouncer wickets shorts",
    ],
    "run_outs": [
        "impossible cricket run outs shorts",
        "crazy cricket runout shorts",
        "best cricket fielding run outs shorts",
        "last second cricket run out shorts",
    ],
    "stumpings": [
        "cricket stumpings shorts",
        "best cricket wicketkeeper stumpings shorts",
        "lightning cricket stumping shorts",
        "unbelievable cricket stumpings shorts",
    ],
    "finishes": [
        "cricket last over finishes shorts",
        "dramatic cricket finishes shorts",
        "cricket final over sixes shorts",
        "unbelievable cricket match finish shorts",
    ],
    "moments": [
        "unforgettable cricket moments shorts",
        "shocking cricket moments shorts",
        "cricket moments that shocked everyone shorts",
        "crazy cricket moments shorts",
    ],
}


class YouTubeApiError(RuntimeError):
    """Raised when a YouTube API call fails without exposing credentials."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


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
            status_code = (
                exc.response.status_code
                if isinstance(exc, requests.HTTPError) and exc.response is not None
                else None
            )
            raise YouTubeApiError(
                f"YouTube API request failed for {endpoint}: {_redact_api_key(str(exc))}",
                status_code=status_code,
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


def _ensure_football_query(query: str) -> str:
    if "football" in query.lower():
        return query
    return f"football {query}"


def _ensure_cricket_query(query: str) -> str:
    if "cricket" in query.lower():
        return query
    return f"cricket {query}"


def _domain_search_query(query: str, settings: Settings | None) -> str:
    if settings and settings.content_domain == "football":
        return _ensure_football_query(query)
    if settings and settings.content_domain == "cricket":
        return _ensure_cricket_query(query)
    return query


def _ensure_shorts_query(query: str) -> str:
    return query if "short" in query.lower() else f"{query} shorts"


def _football_theme(query: str) -> str:
    lowered = query.lower()
    if any(term in lowered for term in ("save", "goalkeeper", "keeper")):
        return "saves"
    if any(term in lowered for term in ("penalty", "penalties", "shootout")):
        return "penalties"
    if any(term in lowered for term in ("pass", "assist", "through ball", "no look")):
        return "passes"
    if any(term in lowered for term in ("free kick", "freekick")):
        return "free_kicks"
    if any(term in lowered for term in ("comeback", "last minute", "stoppage time")):
        return "comebacks"
    if any(term in lowered for term in ("skill", "dribble", "dribbling", "nutmeg")):
        return "skills"
    if any(term in lowered for term in ("volley", "bicycle kick")):
        return "volleys"
    if any(term in lowered for term in ("clearance", "clearances", "goal line")):
        return "clearances"
    if any(term in lowered for term in ("red card", "referee", "controversial", "drama")):
        return "cards"
    if any(term in lowered for term in ("goal", "goals", "finish", "finishes")):
        return "goals"
    return "moments"


def _football_theme_search_queries(query: str) -> list[str]:
    theme = _football_theme(query)
    return [query, *FOOTBALL_THEME_QUERIES[theme]]


def _cricket_theme(query: str) -> str:
    lowered = query.lower()
    if any(term in lowered for term in ("catch", "catches")):
        return "catches"
    if any(term in lowered for term in ("six", "sixes", "batting")):
        return "sixes"
    if any(term in lowered for term in ("wicket", "wickets", "stump flying")):
        return "wickets"
    if any(term in lowered for term in ("bowling", "bowler", "yorker", "bouncer")):
        return "bowling"
    if any(term in lowered for term in ("run out", "runout", "fielding")):
        return "run_outs"
    if any(term in lowered for term in ("stumping", "stumpings", "wicketkeeper")):
        return "stumpings"
    if any(term in lowered for term in ("finish", "finishes", "last over", "final over")):
        return "finishes"
    return "moments"


def _cricket_theme_search_queries(query: str) -> list[str]:
    theme = _cricket_theme(query)
    return [query, *CRICKET_THEME_QUERIES[theme]]


def _shorts_search_queries(
    query: str,
    language: str | None,
    settings: Settings | None,
) -> list[str]:
    query = _domain_search_query(query, settings)
    base_query = _ensure_shorts_query(query)
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
    if settings and settings.content_domain == "football":
        queries = [
            _append_language_to_query(theme_query, language)
            for theme_query in _football_theme_search_queries(query)
        ]
    if settings and settings.content_domain == "cricket":
        queries = [
            _append_language_to_query(theme_query, language)
            for theme_query in _cricket_theme_search_queries(query)
        ]

    deduped: list[str] = []
    for item in queries:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _contains_devanagari(text: str) -> bool:
    return any("\u0900" <= char <= "\u097f" for char in text)


def _contains_non_latin_script(text: str) -> bool:
    for char in text:
        if not char.isalpha():
            continue
        try:
            name = unicodedata.name(char)
        except ValueError:
            continue
        if name.startswith("LATIN"):
            continue
        return True
    return False


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
        return (
            not has_devanagari
            and not _contains_non_latin_script(text)
            and not bool(tokens & HINDI_ROMANIZED_HINTS)
        )
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


def _football_relevance_score(video: YouTubeVideo, query: str) -> float:
    text = _video_search_text(video)
    tokens = set(re.findall(r"[a-z0-9]+", text))
    query_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    query_tokens |= {token.rstrip("s") for token in query_tokens if len(token) > 3}
    comparable_tokens = tokens | {token.rstrip("s") for token in tokens if len(token) > 3}
    core_matches = tokens & FOOTBALL_CORE_TERMS
    moment_matches = tokens & FOOTBALL_MOMENT_TERMS
    query_matches = comparable_tokens & query_tokens
    excluded_matches = tokens & FOOTBALL_EXCLUDED_TERMS
    title_tokens = set(re.findall(r"[a-z0-9]+", video.title.lower()))
    title_core_matches = title_tokens & FOOTBALL_CORE_TERMS
    title_moment_matches = title_tokens & FOOTBALL_MOMENT_TERMS

    score = 0.0
    if core_matches:
        score += min(0.38, 0.2 + len(core_matches) * 0.035)
    if moment_matches:
        score += min(0.34, 0.14 + len(moment_matches) * 0.04)
    if query_matches:
        score += min(0.18, len(query_matches) * 0.035)
    if video.view_count:
        score += min(0.14, video.view_count / 1_500_000 * 0.14)
    if video.like_count:
        score += min(0.08, video.like_count / 150_000 * 0.08)
    if "short" in text or "#shorts" in text:
        score += 0.05

    if excluded_matches:
        score -= min(0.75, 0.4 + len(excluded_matches) * 0.08)
    if not core_matches:
        score -= 0.3
    if not moment_matches:
        score -= 0.12
    if excluded_matches & title_tokens:
        score -= 0.2
    if not title_core_matches:
        score -= 0.32
    if not title_moment_matches:
        score -= 0.08

    return round(max(0.0, min(1.0, score)), 4)


def _cricket_relevance_score(video: YouTubeVideo, query: str) -> float:
    text = _video_search_text(video)
    tokens = set(re.findall(r"[a-z0-9]+", text))
    query_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    query_tokens |= {token.rstrip("s") for token in query_tokens if len(token) > 3}
    comparable_tokens = tokens | {token.rstrip("s") for token in tokens if len(token) > 3}
    core_matches = tokens & CRICKET_CORE_TERMS
    moment_matches = tokens & CRICKET_MOMENT_TERMS
    query_matches = comparable_tokens & query_tokens
    excluded_matches = tokens & CRICKET_EXCLUDED_TERMS
    title_tokens = set(re.findall(r"[a-z0-9]+", video.title.lower()))
    title_core_matches = title_tokens & CRICKET_CORE_TERMS
    title_moment_matches = title_tokens & CRICKET_MOMENT_TERMS

    score = 0.0
    if core_matches:
        score += min(0.38, 0.2 + len(core_matches) * 0.035)
    if moment_matches:
        score += min(0.34, 0.14 + len(moment_matches) * 0.04)
    if query_matches:
        score += min(0.18, len(query_matches) * 0.035)
    if video.view_count:
        score += min(0.14, video.view_count / 1_500_000 * 0.14)
    if video.like_count:
        score += min(0.08, video.like_count / 150_000 * 0.08)
    if "short" in text or "#shorts" in text:
        score += 0.05

    if excluded_matches:
        score -= min(0.75, 0.4 + len(excluded_matches) * 0.08)
    if not core_matches:
        score -= 0.3
    if not moment_matches:
        score -= 0.12
    if excluded_matches & title_tokens:
        score -= 0.2
    if not title_core_matches:
        score -= 0.32
    if not title_moment_matches:
        score -= 0.08

    return round(max(0.0, min(1.0, score)), 4)


def _domain_relevance_score(
    settings: Settings | None,
    video: YouTubeVideo,
    query: str,
) -> float:
    if settings and settings.content_domain == "kids_funny":
        return _kids_funny_relevance_score(video, query)
    if settings and settings.content_domain == "football":
        return _football_relevance_score(video, query)
    if settings and settings.content_domain == "cricket":
        return _cricket_relevance_score(video, query)
    return 0.75


def _domain_relevance_threshold(settings: Settings | None) -> float | None:
    if settings and settings.content_domain in {"football", "cricket"}:
        return 0.55
    if settings and settings.content_domain == "kids_funny":
        return 0.45
    return None


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
        queries = _compilation_queries(self.settings)
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
        randomized_query_domains = {"kids_funny", "football", "cricket"}
        if self.settings.content_domain in randomized_query_domains:
            random.shuffle(candidates)
        candidates = sorted(
            candidates,
            key=lambda item: (
                int(self.history.query_stats(item[0], item[1]).get("run_count") or 0),
                str(self.history.query_stats(item[0], item[1]).get("last_used_at") or ""),
                queries.index(item[0])
                if self.settings.content_domain not in randomized_query_domains
                else 0,
                languages.index(item[1]),
            ),
        )
        trends: list[Trend] = []
        for index, (query, language) in enumerate(candidates[:limit]):
            title = _domain_search_query(query, self.settings)
            score = max(0.45, 1.0 - index * 0.06)
            trends.append(
                Trend(
                    title=title,
                    source="compilation_query",
                    velocity_score=score,
                    audience_fit_score=0.9,
                    metadata={
                        "domain": self.settings.content_domain,
                        "query_rank": index + 1,
                        "raw_query": query,
                        "source_language": language,
                        "source_language_label": _language_label(language),
                        "query_run_count": int(
                            self.history.query_stats(query, language).get("run_count") or 0
                        ),
                    },
                )
            )
        return trends


def _settings_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _football_query_combinations(settings: Settings) -> list[str]:
    adjectives = _settings_csv(settings.football_query_adjectives)
    types = _settings_csv(settings.football_query_types)
    return [
        _ensure_shorts_query(_ensure_football_query(f"{adjective} {query_type}"))
        for query_type in types
        for adjective in adjectives
    ]


def _cricket_query_combinations(settings: Settings) -> list[str]:
    adjectives = _settings_csv(settings.cricket_query_adjectives)
    types = _settings_csv(settings.cricket_query_types)
    return [
        _ensure_shorts_query(_ensure_cricket_query(f"{adjective} {query_type}"))
        for query_type in types
        for adjective in adjectives
    ]


def _compilation_queries(settings: Settings) -> list[str]:
    if settings.content_domain == "football":
        generated = _football_query_combinations(settings)
        configured = _settings_csv(settings.compilation_queries)
        queries = [*generated, *configured]
    elif settings.content_domain == "cricket":
        generated = _cricket_query_combinations(settings)
        configured = _settings_csv(settings.compilation_queries)
        queries = [*generated, *configured]
    else:
        queries = _settings_csv(settings.compilation_queries)

    deduped: list[str] = []
    for query in queries:
        normalized = _domain_search_query(query, settings)
        if normalized not in deduped:
            deduped.append(normalized)
    return deduped


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
        query_pool_size = (
            min(50, pool_size)
            if self.settings and self.settings.content_domain in {"football", "cricket"}
            else pool_size
        )
        videos: list[YouTubeVideo] = []
        seen_search_ids: set[str] = set()
        search_queries = _shorts_search_queries(trend.title, language, self.settings)
        focused_domain = (
            self.settings is not None
            and self.settings.content_domain in {"football", "cricket"}
        )
        if focused_domain:
            query_count = max(1, self.settings.youtube_focused_search_query_count)
            search_queries = search_queries[:query_count]
        quota_limited = False
        for search_query in search_queries:
            # Focused sports domains already rotate a concrete theme each run and only use
            # one expensive search.list call. Avoid constraining that single call to the
            # recent lookback window, which can leave us with too few downloadable Shorts.
            search_windows = (None,) if focused_domain else (published_after, None)
            for attempt_published_after in search_windows:
                try:
                    search_items = self.client.search_videos(
                        query=search_query,
                        max_results=query_pool_size,
                        order="relevance",
                        published_after=attempt_published_after,
                        region_code=self.settings.youtube_region_code if self.settings else None,
                        video_duration="short",
                        relevance_language=language,
                    )
                except YouTubeApiError as exc:
                    if exc.status_code in {403, 429}:
                        LOGGER.warning(
                            "YouTube API quota/rate limit while searching %r: %s",
                            search_query,
                            exc,
                        )
                        quota_limited = True
                        break
                    raise
                video_ids = [
                    video_id
                    for video_id in _video_ids_from_search_items(search_items)
                    if video_id not in seen_search_ids
                ]
                seen_search_ids.update(video_ids)
                try:
                    video_items = self.client.videos_by_id(video_ids)
                except YouTubeApiError as exc:
                    if exc.status_code in {403, 429}:
                        LOGGER.warning(
                            "YouTube API quota/rate limit while loading video details: %s",
                            exc,
                        )
                        quota_limited = True
                        break
                    raise
                for item in video_items:
                    video = _youtube_video_from_item(item, trend.id)
                    video.metadata["search_query"] = search_query
                    video.metadata["search_published_after"] = (
                        attempt_published_after.isoformat()
                        if attempt_published_after
                        else None
                    )
                    videos.append(video)
                if (
                    self.settings
                    and self.settings.content_domain not in {"football", "cricket"}
                    and len(videos) >= pool_size
                ):
                    break
            if quota_limited:
                break
            if (
                self.settings
                and self.settings.content_domain not in {"football", "cricket"}
                and len(videos) >= pool_size
            ):
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
            relevance_score = _domain_relevance_score(self.settings, updated, search_query)
            updated.metadata["primary_search_query"] = search_queries[0]
            updated.metadata["source_language"] = language
            updated.metadata["search_relevance_score"] = relevance_score
            if updated.id in seen_ids:
                updated.metadata["filtered_reason"] = "previously_seen_source_video"
                continue
            threshold = _domain_relevance_threshold(self.settings)
            if threshold is not None and relevance_score < threshold:
                updated.metadata["filtered_reason"] = (
                    f"low_{self.settings.content_domain}_relevance"
                )
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
        if self.settings.yt_dlp_extractor_args:
            for extractor_args in self.settings.yt_dlp_extractor_args.splitlines():
                extractor_args = extractor_args.strip()
                if extractor_args:
                    command.extend(["--extractor-args", extractor_args])
        if self.settings.yt_dlp_verbose:
            command.append("--verbose")
        command.append(video.url)
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.settings.yt_dlp_download_timeout_seconds,
            )
        except subprocess.CalledProcessError as exc:
            output = "\n".join(part for part in (exc.stdout, exc.stderr) if part)
            if output:
                LOGGER.warning(
                    "yt-dlp failed for %s:\n%s",
                    video.id,
                    output[-COMMAND_OUTPUT_SNIPPET_CHARS:],
                )
            raise
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


class ColabYtDlpVideoDownloadProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _failed_batch(
        self,
        videos: list[YouTubeVideo],
        *,
        error: str,
        kind: str = "download_error",
        stderr: str = "",
    ) -> tuple[list[YouTubeVideo], list[YouTubeVideo]]:
        failed: list[YouTubeVideo] = []
        for video in videos:
            failed_video = video.model_copy(deep=True)
            failed_video.metadata["download_failed"] = True
            failed_video.metadata["download_error"] = error
            failed_video.metadata["download_error_kind"] = kind
            if stderr:
                failed_video.metadata["download_stderr"] = stderr[-2000:]
            failed.append(failed_video)
        return [], failed

    def download_many(
        self,
        videos: list[YouTubeVideo],
        output_dir: Path,
        *,
        max_successes: int,
    ) -> tuple[list[YouTubeVideo], list[YouTubeVideo]]:
        output_dir.mkdir(parents=True, exist_ok=True)
        if not videos:
            return [], []
        session = f"{self.settings.colab_session_prefix}-batch-{uuid4().hex[:8]}"
        remote_dir = self.settings.colab_remote_dir.rstrip("/")
        job_path = output_dir / "colab_batch_job.json"
        result_zip = output_dir / "colab_batch_result.zip"
        worker_path = Path("scripts/colab_ytdlp_worker.py")
        extractor_args = [
            value.strip()
            for value in (self.settings.yt_dlp_extractor_args or "").splitlines()
            if value.strip()
        ]
        job_path.write_text(
            json.dumps(
                {
                    "videos": [{"id": video.id, "url": video.url} for video in videos],
                    "max_successes": max_successes,
                    "format": self.settings.yt_dlp_format,
                    "js_runtimes": self.settings.yt_dlp_js_runtimes,
                    "extractor_args": extractor_args,
                    "verbose": self.settings.yt_dlp_verbose,
                    "yt_dlp_requirement": self.settings.colab_yt_dlp_requirement,
                    "download_timeout_seconds": self.settings.yt_dlp_download_timeout_seconds,
                    "batch_timeout_seconds": self.settings.max_download_stage_seconds,
                    "enable_browser_po_token": self.settings.colab_enable_browser_po_token,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        try:
            try:
                self._run(["new", "-s", session])
                self._run(
                    ["exec", "-s", session],
                    input_text=(
                        "import pathlib\n"
                        f"pathlib.Path('{remote_dir}').mkdir(parents=True, exist_ok=True)\n"
                    ),
                )
                self._run(["upload", "-s", session, str(job_path), f"{remote_dir}/job.json"])
                cookies_path = self.settings.yt_dlp_cookies_path
                if (
                    self.settings.colab_upload_youtube_cookies
                    and cookies_path
                    and cookies_path.exists()
                ):
                    self._run(
                        ["upload", "-s", session, str(cookies_path), f"{remote_dir}/cookies.txt"]
                    )
                self._run(["upload", "-s", session, str(worker_path), f"{remote_dir}/worker.py"])
                self._start_remote_worker(session, remote_dir)
                result_ready = self._wait_for_remote_result(session, remote_dir)
                if result_ready:
                    self._run(
                        ["download", "-s", session, f"{remote_dir}/result.zip", str(result_zip)]
                    )
            finally:
                try:
                    self._run(["stop", "-s", session])
                except subprocess.CalledProcessError as exc:
                    LOGGER.warning("Failed to stop Colab session %s: %s", session, exc)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            output = _called_process_output(exc)
            return self._failed_batch(
                videos,
                error="colab_batch_command_failed",
                kind="download_infrastructure_error",
                stderr=output,
            )

        if not result_zip.exists():
            return self._failed_batch(
                videos,
                error="colab_batch_result_timeout",
                kind="download_infrastructure_error",
            )
        with zipfile.ZipFile(result_zip) as archive:
            archive.extractall(output_dir)

        result_path = output_dir / "result.json"
        result_payload = (
            json.loads(result_path.read_text(encoding="utf-8"))
            if result_path.exists()
            else {}
        )
        result_by_id = {
            str(item.get("video_id")): item
            for item in result_payload.get("results", [])
            if isinstance(item, dict)
        }
        downloaded: list[YouTubeVideo] = []
        failed: list[YouTubeVideo] = []
        for video in videos:
            item = result_by_id.get(video.id, {})
            if not item:
                continue
            if item.get("status") == "ok":
                try:
                    downloaded_path = self._find_download(video.id, output_dir)
                except FileNotFoundError:
                    item = {"status": "download_missing_file"}
                else:
                    updated = video.model_copy(deep=True)
                    updated.downloaded_path = downloaded_path
                    updated.metadata["download_provider"] = "colab-yt-dlp"
                    updated.metadata["downloaded_path"] = str(downloaded_path)
                    updated.metadata["colab_session"] = session
                    updated.metadata["download_backend"] = "colab_batch"
                    downloaded.append(updated)
                    continue
            failed_video = video.model_copy(deep=True)
            failed_video.metadata["download_failed"] = True
            failed_video.metadata["download_error"] = str(item.get("status") or "not_attempted")
            failed_video.metadata["download_stderr"] = str(item.get("stderr") or "")[-2000:]
            output_text = " ".join(str(item.get(key) or "") for key in ("stdout", "stderr"))
            if _is_youtube_bot_wall_text(output_text):
                error_kind = "youtube_bot_wall"
            elif _is_youtube_challenge_failure_text(output_text):
                error_kind = "youtube_challenge_failed"
            else:
                error_kind = "download_error"
            failed_video.metadata["download_error_kind"] = error_kind
            failed.append(failed_video)
        return downloaded, failed

    def _start_remote_worker(self, session: str, remote_dir: str) -> None:
        self._run(
            ["exec", "-s", session],
            input_text=(
                "import pathlib, subprocess, sys\n"
                f"remote_dir = pathlib.Path({remote_dir!r})\n"
                "log = open(remote_dir / 'worker.log', 'w', encoding='utf-8')\n"
                "subprocess.Popen(\n"
                "    [sys.executable, str(remote_dir / 'worker.py')],\n"
                "    stdout=log,\n"
                "    stderr=subprocess.STDOUT,\n"
                "    start_new_session=True,\n"
                ")\n"
                "print('worker_started')\n"
            ),
        )

    def _wait_for_remote_result(self, session: str, remote_dir: str) -> bool:
        timeout_seconds = self.settings.max_download_stage_seconds or (
            self.settings.yt_dlp_download_timeout_seconds * self.settings.max_download_attempts
        )
        timeout_seconds = max(60, timeout_seconds)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            time.sleep(20)
            result = self._run(
                ["exec", "-s", session],
                input_text=(
                    "from pathlib import Path\n"
                    f"print('RESULT_READY=' + str(Path({remote_dir!r}, 'result.zip').exists()))\n"
                ),
            )
            if "RESULT_READY=True" in result.stdout:
                return True
        LOGGER.warning(
            "Colab batch worker did not produce result.zip within %ss",
            timeout_seconds,
        )
        return False

    def download(self, video: YouTubeVideo, output_dir: Path) -> YouTubeVideo:
        output_dir.mkdir(parents=True, exist_ok=True)
        session = f"{self.settings.colab_session_prefix}-{video.id}-{uuid4().hex[:8]}"
        remote_dir = self.settings.colab_remote_dir.rstrip("/")
        job_path = output_dir / "colab_job.json"
        result_zip = output_dir / "colab_result.zip"
        worker_path = Path("scripts/colab_ytdlp_worker.py")
        extractor_args = [
            value.strip()
            for value in (self.settings.yt_dlp_extractor_args or "").splitlines()
            if value.strip()
        ]
        job_path.write_text(
            json.dumps(
                {
                    "video_id": video.id,
                    "url": video.url,
                    "format": self.settings.yt_dlp_format,
                    "js_runtimes": self.settings.yt_dlp_js_runtimes,
                    "extractor_args": extractor_args,
                    "verbose": self.settings.yt_dlp_verbose,
                    "yt_dlp_requirement": self.settings.colab_yt_dlp_requirement,
                    "download_timeout_seconds": self.settings.yt_dlp_download_timeout_seconds,
                    "enable_browser_po_token": self.settings.colab_enable_browser_po_token,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        try:
            self._run(["new", "-s", session])
            self._run(
                ["exec", "-s", session],
                input_text=(
                    "import pathlib\n"
                    f"pathlib.Path('{remote_dir}').mkdir(parents=True, exist_ok=True)\n"
                ),
            )
            self._run(["upload", "-s", session, str(job_path), f"{remote_dir}/job.json"])
            cookies_path = self.settings.yt_dlp_cookies_path
            if (
                self.settings.colab_upload_youtube_cookies
                and cookies_path
                and cookies_path.exists()
            ):
                self._run(["upload", "-s", session, str(cookies_path), f"{remote_dir}/cookies.txt"])
            self._run(["exec", "-s", session, "-f", str(worker_path)])
            self._run(["download", "-s", session, f"{remote_dir}/result.zip", str(result_zip)])
        finally:
            try:
                self._run(["stop", "-s", session])
            except subprocess.CalledProcessError as exc:
                LOGGER.warning("Failed to stop Colab session %s: %s", session, exc)

        if not result_zip.exists():
            raise FileNotFoundError(f"Colab did not return a result archive for {video.id}")
        with zipfile.ZipFile(result_zip) as archive:
            archive.extractall(output_dir)

        downloaded = self._find_download(video.id, output_dir)
        updated = video.model_copy(deep=True)
        updated.downloaded_path = downloaded
        updated.metadata["download_provider"] = "colab-yt-dlp"
        updated.metadata["downloaded_path"] = str(downloaded)
        updated.metadata["colab_session"] = session
        return updated

    def _run(
        self,
        args: list[str],
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = ["colab", f"--auth={self.settings.colab_cli_auth}"]
        if self.settings.colab_cli_config_path:
            command.extend(["--config", str(self.settings.colab_cli_config_path)])
        command.extend(args)
        try:
            return subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                input=input_text,
                timeout=self.settings.colab_command_timeout_seconds,
            )
        except subprocess.CalledProcessError as exc:
            output = "\n".join(part for part in (exc.stdout, exc.stderr) if part)
            if output:
                LOGGER.warning(
                    "Colab command failed (%s):\n%s",
                    " ".join(command),
                    output[-COMMAND_OUTPUT_SNIPPET_CHARS:],
                )
            raise
        except subprocess.TimeoutExpired as exc:
            output = "\n".join(
                str(part)
                for part in (exc.stdout, exc.stderr)
                if part
            )
            LOGGER.warning(
                "Colab command timed out after %ss (%s):\n%s",
                self.settings.colab_command_timeout_seconds,
                " ".join(command),
                output[-COMMAND_OUTPUT_SNIPPET_CHARS:],
            )
            raise

    def _find_download(self, video_id: str, output_dir: Path) -> Path:
        candidates = [
            path
            for path in output_dir.glob(f"{video_id}.*")
            if path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
        ]
        if not candidates:
            result_path = output_dir / "result.json"
            if result_path.exists():
                try:
                    result = json.loads(result_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    result = {"raw": result_path.read_text(encoding="utf-8")[-2000:]}
                detail = json.dumps(result, sort_keys=True)[-COMMAND_OUTPUT_SNIPPET_CHARS:]
                raise FileNotFoundError(
                    f"Colab yt-dlp did not produce a media file for {video_id}: {detail}"
                )
            raise FileNotFoundError(f"Colab yt-dlp did not produce a media file for {video_id}")
        return sorted(candidates, key=lambda path: path.stat().st_size, reverse=True)[0]


class KaggleYtDlpVideoDownloadProvider(ColabYtDlpVideoDownloadProvider):
    def download_many(
        self,
        videos: list[YouTubeVideo],
        output_dir: Path,
        *,
        max_successes: int,
    ) -> tuple[list[YouTubeVideo], list[YouTubeVideo]]:
        output_dir.mkdir(parents=True, exist_ok=True)
        if not videos:
            return [], []

        kernel_dir = output_dir / "kaggle_kernel"
        kernel_output_dir = output_dir / "kaggle_output"
        kernel_dir.mkdir(parents=True, exist_ok=True)
        kernel_output_dir.mkdir(parents=True, exist_ok=True)

        owner = self._kaggle_owner()
        slug = self._normalized_kernel_slug()
        kernel_ref = f"{owner}/{slug}"
        job = self._job_payload(videos, max_successes)
        metadata_path = kernel_dir / "kernel-metadata.json"
        metadata_path.write_text(
            json.dumps(
                {
                    "id": kernel_ref,
                    "title": self.settings.kaggle_kernel_title,
                    "code_file": "kernel.py",
                    "language": "python",
                    "kernel_type": "script",
                    "is_private": True,
                    "enable_gpu": False,
                    "enable_internet": True,
                    "dataset_sources": [],
                    "competition_sources": [],
                    "kernel_sources": [],
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        (kernel_dir / "kernel.py").write_text(
            self._kernel_source(job),
            encoding="utf-8",
        )

        try:
            self._run(["kernels", "push", "-p", str(kernel_dir)])
            if not self._wait_for_kernel(kernel_ref):
                return self._failed_batch(
                    videos,
                    error="kaggle_kernel_result_timeout",
                    kind="download_infrastructure_error",
                )
            self._run(["kernels", "output", kernel_ref, "-p", str(kernel_output_dir)])
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            output = _called_process_output(exc)
            return self._failed_batch(
                videos,
                error="kaggle_kernel_command_failed",
                kind="download_infrastructure_error",
                stderr=output,
            )

        result_zip = self._find_kaggle_output_file(kernel_output_dir, "result.zip")
        if result_zip:
            with zipfile.ZipFile(result_zip) as archive:
                archive.extractall(output_dir)
        else:
            for media_path in kernel_output_dir.rglob("*"):
                if media_path.is_file() and media_path.name in {"result.json"}:
                    (output_dir / media_path.name).write_bytes(media_path.read_bytes())
                elif media_path.is_file() and media_path.suffix.lower() in {
                    ".mp4",
                    ".mkv",
                    ".webm",
                    ".mov",
                    ".json",
                }:
                    target = output_dir / media_path.name
                    if not target.exists():
                        target.write_bytes(media_path.read_bytes())

        result_path = output_dir / "result.json"
        result_payload = (
            json.loads(result_path.read_text(encoding="utf-8"))
            if result_path.exists()
            else {}
        )
        result_by_id = {
            str(item.get("video_id")): item
            for item in result_payload.get("results", [])
            if isinstance(item, dict)
        }
        downloaded: list[YouTubeVideo] = []
        failed: list[YouTubeVideo] = []
        for video in videos:
            item = result_by_id.get(video.id, {})
            if not item:
                continue
            if item.get("status") == "ok":
                try:
                    downloaded_path = self._find_download(video.id, output_dir)
                except FileNotFoundError:
                    item = {"status": "download_missing_file"}
                else:
                    updated = video.model_copy(deep=True)
                    updated.downloaded_path = downloaded_path
                    updated.metadata["download_provider"] = "kaggle-yt-dlp"
                    updated.metadata["downloaded_path"] = str(downloaded_path)
                    updated.metadata["kaggle_kernel"] = kernel_ref
                    updated.metadata["download_backend"] = "kaggle_kernel"
                    downloaded.append(updated)
                    continue
            failed_video = video.model_copy(deep=True)
            failed_video.metadata["download_failed"] = True
            failed_video.metadata["download_error"] = str(item.get("status") or "not_attempted")
            failed_video.metadata["download_stderr"] = str(item.get("stderr") or "")[-2000:]
            output_text = " ".join(str(item.get(key) or "") for key in ("stdout", "stderr"))
            if _is_youtube_bot_wall_text(output_text):
                error_kind = "youtube_bot_wall"
            elif _is_youtube_challenge_failure_text(output_text):
                error_kind = "youtube_challenge_failed"
            else:
                error_kind = "download_error"
            failed_video.metadata["download_error_kind"] = error_kind
            failed.append(failed_video)
        return downloaded, failed

    def download(self, video: YouTubeVideo, output_dir: Path) -> YouTubeVideo:
        downloaded, failed = self.download_many([video], output_dir, max_successes=1)
        if downloaded:
            return downloaded[0]
        reason = failed[0].metadata.get("download_error") if failed else "not_attempted"
        raise FileNotFoundError(
            f"Kaggle yt-dlp did not produce a media file for {video.id}: {reason}"
        )

    def _job_payload(self, videos: list[YouTubeVideo], max_successes: int) -> dict[str, Any]:
        extractor_args = [
            value.strip()
            for value in (self.settings.yt_dlp_extractor_args or "").splitlines()
            if value.strip()
        ]
        return {
            "videos": [{"id": video.id, "url": video.url} for video in videos],
            "max_successes": max_successes,
            "format": self.settings.yt_dlp_format,
            "js_runtimes": self.settings.yt_dlp_js_runtimes,
            "extractor_args": extractor_args,
            "verbose": self.settings.yt_dlp_verbose,
            "yt_dlp_requirement": self.settings.kaggle_yt_dlp_requirement,
            "download_timeout_seconds": self.settings.yt_dlp_download_timeout_seconds,
            "batch_timeout_seconds": self.settings.max_download_stage_seconds,
            "enable_browser_po_token": self.settings.kaggle_enable_browser_po_token,
        }

    def _kernel_source(self, job: dict[str, Any]) -> str:
        worker_source = Path("scripts/colab_ytdlp_worker.py").read_text(encoding="utf-8")
        worker_source = worker_source.replace(
            'REMOTE_DIR = Path("/content/viral_pipeline_download")',
            f"REMOTE_DIR = Path({self.settings.kaggle_remote_dir!r})",
        )
        embedded_cookies = ""
        cookies_path = self.settings.yt_dlp_cookies_path
        if (
            self.settings.kaggle_upload_youtube_cookies
            and cookies_path
            and cookies_path.exists()
        ):
            embedded_cookies = cookies_path.read_text(encoding="utf-8")
        injected = (
            "\n\n"
            "# Generated by viral_pipeline.providers.KaggleYtDlpVideoDownloadProvider.\n"
            f"EMBEDDED_JOB_JSON = {json.dumps(json.dumps(job, sort_keys=True))}\n"
            f"EMBEDDED_COOKIES_TEXT = {json.dumps(embedded_cookies)}\n"
            "\n\n"
            "def _prepare_embedded_inputs() -> None:\n"
            "    REMOTE_DIR.mkdir(parents=True, exist_ok=True)\n"
            "    JOB_PATH.write_text(EMBEDDED_JOB_JSON, encoding='utf-8')\n"
            "    if EMBEDDED_COOKIES_TEXT:\n"
            "        (REMOTE_DIR / 'cookies.txt').write_text(EMBEDDED_COOKIES_TEXT, encoding='utf-8')\n"
        )
        worker_source = worker_source.replace(
            "RESULT_JSON = REMOTE_DIR / \"result.json\"\n",
            "RESULT_JSON = REMOTE_DIR / \"result.json\"\n" + injected + "\n",
            1,
        )
        worker_source = worker_source.replace(
            "def main() -> None:\n    job = json.loads(JOB_PATH.read_text(encoding=\"utf-8\"))",
            (
                "def main() -> None:\n"
                "    _prepare_embedded_inputs()\n"
                "    job = json.loads(JOB_PATH.read_text(encoding=\"utf-8\"))"
            ),
            1,
        )
        return worker_source

    def _kaggle_owner(self) -> str:
        env_username = os.environ.get("KAGGLE_USERNAME", "").strip()
        if env_username:
            return env_username
        result = self._run(["config", "view"])
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("username:"):
                username = stripped.split(":", 1)[1].strip()
                if username:
                    return username
        raise RuntimeError("Kaggle username was not available from `kaggle config view`")

    def _normalized_kernel_slug(self) -> str:
        slug = self.settings.kaggle_kernel_slug.strip().lower()
        slug = re.sub(r"[^a-z0-9-]+", "-", slug)
        slug = re.sub(r"-+", "-", slug).strip("-")
        if not slug:
            slug = f"viral-pipeline-ytdlp-{uuid4().hex[:8]}"
        return slug[:63]

    def _wait_for_kernel(self, kernel_ref: str) -> bool:
        deadline = time.monotonic() + max(60, self.settings.kaggle_command_timeout_seconds)
        while time.monotonic() < deadline:
            result = self._run(["kernels", "status", kernel_ref])
            status_text = (result.stdout or "").lower()
            if any(value in status_text for value in ("complete", "succeeded")):
                return True
            if any(value in status_text for value in ("error", "failed", "cancel")):
                LOGGER.warning("Kaggle kernel %s ended unsuccessfully:\n%s", kernel_ref, result.stdout)
                return True
            time.sleep(30)
        LOGGER.warning("Kaggle kernel %s did not finish within timeout", kernel_ref)
        return False

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        command = ["kaggle", *args]
        try:
            return subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.settings.kaggle_command_timeout_seconds,
            )
        except subprocess.CalledProcessError as exc:
            output = "\n".join(part for part in (exc.stdout, exc.stderr) if part)
            if output:
                LOGGER.warning(
                    "Kaggle command failed (%s):\n%s",
                    " ".join(command),
                    output[-COMMAND_OUTPUT_SNIPPET_CHARS:],
                )
            raise
        except subprocess.TimeoutExpired as exc:
            output = "\n".join(str(part) for part in (exc.stdout, exc.stderr) if part)
            LOGGER.warning(
                "Kaggle command timed out after %ss (%s):\n%s",
                self.settings.kaggle_command_timeout_seconds,
                " ".join(command),
                output[-COMMAND_OUTPUT_SNIPPET_CHARS:],
            )
            raise

    def _find_kaggle_output_file(self, output_dir: Path, name: str) -> Path | None:
        candidates = [path for path in output_dir.rglob(name) if path.is_file()]
        return candidates[0] if candidates else None


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
            "concise, and suitable for the configured compilation niche. Return valid JSON only."
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
    title = str(payload.get("title") or f"Top {len(clips)} Shorts").strip()
    title = title[:95].strip()
    description = str(payload.get("description") or "").strip()
    if not description:
        description = f"Top {len(clips)} clips selected from short-video sources."

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
        if settings.content_domain in {"kids_funny", "football", "cricket", "compilation"}
        else YouTubeTrendProvider(settings, youtube_client)
        if youtube_client
        else LocalTrendProvider()
    )
    youtube_provider: YouTubeProvider = (
        YouTubeDataProvider(settings.youtube_api_key, settings)
        if settings.youtube_api_key
        else LocalYouTubeProvider()
    )
    if settings.use_real_media and settings.download_backend == "colab":
        download_provider: VideoDownloadProvider = ColabYtDlpVideoDownloadProvider(settings)
    elif settings.use_real_media and settings.download_backend == "kaggle":
        download_provider = KaggleYtDlpVideoDownloadProvider(settings)
    elif settings.use_real_media:
        download_provider = YtDlpVideoDownloadProvider(settings)
    else:
        download_provider = LocalVideoDownloadProvider()
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
