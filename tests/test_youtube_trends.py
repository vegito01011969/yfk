from __future__ import annotations

from typing import Any

from viral_pipeline.config import Settings
from viral_pipeline.domain import Trend, YouTubeVideo
from viral_pipeline.providers import (
    CompilationQueryProvider,
    YouTubeApiError,
    YouTubeDataProvider,
    YouTubeTrendProvider,
    _shorts_search_queries,
)
from viral_pipeline.source_history import SourceHistory


class FakeYouTubeClient:
    def __init__(
        self,
        topic_hits: list[dict[str, Any]] | None = None,
        compilation_hits: list[dict[str, Any]] | None = None,
    ) -> None:
        self.topic_hits = topic_hits or []
        self.compilation_hits = compilation_hits or []
        self.search_queries: list[str] = []

    def most_popular_videos(
        self,
        *,
        region_code: str,
        max_results: int,
        category_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            {
                "id": "popular-1",
                "snippet": {
                    "title": "Tiny desk setup transformations are everywhere",
                    "tags": ["tiny desk setup", "desk transformation", "workspace"],
                },
                "statistics": {"viewCount": "2500000"},
            },
            {
                "id": "popular-2",
                "snippet": {
                    "title": "Creator reacts to tiny desk setup trend",
                    "tags": ["tiny desk setup", "setup tour"],
                },
                "statistics": {"viewCount": "900000"},
            },
        ][:max_results]

    def search_videos(
        self,
        *,
        query: str,
        max_results: int,
        order: str = "relevance",
        published_after: object | None = None,
        region_code: str | None = None,
        video_duration: str | None = None,
        relevance_language: str | None = None,
    ) -> list[dict[str, Any]]:
        self.search_queries.append(query)
        if query == "tiny desk setup":
            return self.topic_hits[:max_results]
        if query == "tiny desk setup compilation":
            return self.compilation_hits[:max_results]
        return []


class FakeShortsClient:
    def search_videos(
        self,
        *,
        query: str,
        max_results: int,
        order: str = "relevance",
        published_after: object | None = None,
        region_code: str | None = None,
        video_duration: str | None = None,
        relevance_language: str | None = None,
    ) -> list[dict[str, Any]]:
        assert video_duration == "short"
        assert relevance_language == "en"
        return [
            {"id": {"videoId": "seen-1"}},
            {"id": {"videoId": "fresh-1"}},
            {"id": {"videoId": "hindi-1"}},
        ][:max_results]

    def videos_by_id(self, video_ids: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "id": video_id,
                "snippet": {
                    "title": (
                        "यह मजेदार बच्चा है"
                        if video_id == "hindi-1"
                        else f"{video_id} funny kids shorts"
                    ),
                    "channelTitle": "Fixture Channel",
                    "publishedAt": "2026-08-08T00:00:00Z",
                },
                "contentDetails": {"duration": "PT12S"},
                "statistics": {"viewCount": "1000", "likeCount": "50", "commentCount": "5"},
            }
            for video_id in video_ids
        ]


class FakeKidsQualityClient:
    def search_videos(
        self,
        *,
        query: str,
        max_results: int,
        order: str = "relevance",
        published_after: object | None = None,
        region_code: str | None = None,
        video_duration: str | None = None,
        relevance_language: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            {"id": {"videoId": "generic-funny"}},
            {"id": {"videoId": "toddler-prank"}},
            {"id": {"videoId": "cartoon-kids"}},
            {"id": {"videoId": "baby-reaction"}},
        ][:max_results]

    def videos_by_id(self, video_ids: list[str]) -> list[dict[str, Any]]:
        fixtures = {
            "generic-funny": {
                "title": "Best funny viral shorts",
                "description": "Random meme comedy clip",
                "tags": ["funny", "viral"],
                "viewCount": "2000000",
                "likeCount": "200000",
            },
            "toddler-prank": {
                "title": "Funny toddler prank reaction #shorts",
                "description": "Little kid reacts to a harmless family prank",
                "tags": ["toddler", "prank", "reaction", "funny kids"],
                "viewCount": "500000",
                "likeCount": "50000",
            },
            "cartoon-kids": {
                "title": "Funny kids cartoon song #shorts",
                "description": "Animated nursery rhyme",
                "tags": ["kids", "cartoon", "song"],
                "viewCount": "900000",
                "likeCount": "30000",
            },
            "baby-reaction": {
                "title": "Hilarious baby reaction to lemon #shorts",
                "description": "Cute baby laughing with family",
                "tags": ["baby", "reaction", "laughing", "cute"],
                "viewCount": "700000",
                "likeCount": "70000",
            },
        }
        return [
            {
                "id": video_id,
                "snippet": {
                    "title": fixtures[video_id]["title"],
                    "description": fixtures[video_id]["description"],
                    "tags": fixtures[video_id]["tags"],
                    "channelTitle": "Fixture Channel",
                    "publishedAt": "2026-08-08T00:00:00Z",
                },
                "contentDetails": {"duration": "PT12S"},
                "statistics": {
                    "viewCount": fixtures[video_id]["viewCount"],
                    "likeCount": fixtures[video_id]["likeCount"],
                    "commentCount": "5",
                },
            }
            for video_id in video_ids
        ]


class FakeFootballQualityClient:
    def __init__(self) -> None:
        self.search_queries: list[str] = []
        self.max_results: list[int] = []
        self.published_after_values: list[object | None] = []

    def search_videos(
        self,
        *,
        query: str,
        max_results: int,
        order: str = "relevance",
        published_after: object | None = None,
        region_code: str | None = None,
        video_duration: str | None = None,
        relevance_language: str | None = None,
    ) -> list[dict[str, Any]]:
        self.search_queries.append(query)
        self.max_results.append(max_results)
        self.published_after_values.append(published_after)
        return [
            {"id": {"videoId": "gameplay"}},
            {"id": {"videoId": "goal"}},
            {"id": {"videoId": "transfer-news"}},
            {"id": {"videoId": "arabic-title"}},
            {"id": {"videoId": "football-talk"}},
            {"id": {"videoId": "asmr-title"}},
            {"id": {"videoId": "save"}},
        ][:max_results]

    def videos_by_id(self, video_ids: list[str]) -> list[dict[str, Any]]:
        fixtures = {
            "gameplay": {
                "title": "EAFC gameplay impossible goal #shorts",
                "description": "Football game highlights",
                "tags": ["eafc", "gameplay", "fifa"],
                "viewCount": "3000000",
                "likeCount": "250000",
            },
            "goal": {
                "title": "Unbelievable last minute football goal #shorts",
                "description": "The stadium crowd explodes after an impossible volley.",
                "tags": ["football", "goal", "last minute", "volley", "soccer"],
                "viewCount": "900000",
                "likeCount": "90000",
            },
            "transfer-news": {
                "title": "Football transfer news today #shorts",
                "description": "Latest transfer rumors and podcast reaction",
                "tags": ["football", "transfer", "news", "podcast"],
                "viewCount": "2000000",
                "likeCount": "100000",
            },
            "arabic-title": {
                "title": "جنون خطة ارسنال 🥶🔥",
                "description": "Football moments and Arsenal goals",
                "tags": ["football", "goal", "soccer"],
                "viewCount": "1200000",
                "likeCount": "80000",
            },
            "football-talk": {
                "title": "IShowSpeed football talk gets wild #shorts",
                "description": "Reaction stream talking about football",
                "tags": ["football", "talk", "reaction", "ishowspeed"],
                "viewCount": "1500000",
                "likeCount": "100000",
            },
            "asmr-title": {
                "title": "#asmr",
                "description": "Football goal sounds and viral football moments",
                "tags": ["asmr", "football", "goal", "soccer"],
                "viewCount": "2000000",
                "likeCount": "100000",
            },
            "save": {
                "title": "Crazy goalkeeper penalty save #shorts",
                "description": "Goalkeeper save in a cup match with fans going wild.",
                "tags": ["football", "goalkeeper", "penalty", "save", "soccer"],
                "viewCount": "600000",
                "likeCount": "70000",
            },
        }
        return [
            {
                "id": video_id,
                "snippet": {
                    "title": fixtures[video_id]["title"],
                    "description": fixtures[video_id]["description"],
                    "tags": fixtures[video_id]["tags"],
                    "channelTitle": "Fixture Channel",
                    "publishedAt": "2026-08-08T00:00:00Z",
                },
                "contentDetails": {"duration": "PT14S"},
                "statistics": {
                    "viewCount": fixtures[video_id]["viewCount"],
                    "likeCount": fixtures[video_id]["likeCount"],
                    "commentCount": "5",
                },
            }
            for video_id in video_ids
        ]


class FakeCricketQualityClient:
    def __init__(self) -> None:
        self.search_queries: list[str] = []
        self.published_after_values: list[object | None] = []

    def search_videos(
        self,
        *,
        query: str,
        max_results: int,
        order: str = "relevance",
        published_after: object | None = None,
        region_code: str | None = None,
        video_duration: str | None = None,
        relevance_language: str | None = None,
    ) -> list[dict[str, Any]]:
        self.search_queries.append(query)
        self.published_after_values.append(published_after)
        return [
            {"id": {"videoId": "gameplay"}},
            {"id": {"videoId": "catch"}},
            {"id": {"videoId": "fantasy-news"}},
            {"id": {"videoId": "six"}},
        ][:max_results]

    def videos_by_id(self, video_ids: list[str]) -> list[dict[str, Any]]:
        fixtures = {
            "gameplay": {
                "title": "Cricket 24 gameplay impossible catch #shorts",
                "description": "Cricket game highlights",
                "tags": ["cricket", "gameplay", "gaming"],
                "viewCount": "3000000",
                "likeCount": "250000",
            },
            "catch": {
                "title": "Unreal cricket catch at the boundary #shorts",
                "description": "The fielder takes an impossible catch in a packed stadium.",
                "tags": ["cricket", "catch", "fielding", "unreal"],
                "viewCount": "900000",
                "likeCount": "90000",
            },
            "fantasy-news": {
                "title": "Cricket fantasy team prediction today #shorts",
                "description": "Dream11 prediction and score update",
                "tags": ["cricket", "fantasy", "prediction", "news"],
                "viewCount": "2000000",
                "likeCount": "100000",
            },
            "six": {
                "title": "Insane cricket six in the last over #shorts",
                "description": "A batter hits a huge six to finish the match.",
                "tags": ["cricket", "six", "batting", "last over", "finish"],
                "viewCount": "800000",
                "likeCount": "70000",
            },
        }
        return [
            {
                "id": video_id,
                "snippet": {
                    "title": fixtures[video_id]["title"],
                    "description": fixtures[video_id]["description"],
                    "tags": fixtures[video_id]["tags"],
                    "channelTitle": "Fixture Channel",
                    "publishedAt": "2026-08-08T00:00:00Z",
                },
                "contentDetails": {"duration": "PT14S"},
                "statistics": {
                    "viewCount": fixtures[video_id]["viewCount"],
                    "likeCount": fixtures[video_id]["likeCount"],
                    "commentCount": "5",
                },
            }
            for video_id in video_ids
        ]


class FakeQuotaLimitedClient:
    def search_videos(
        self,
        *,
        query: str,
        max_results: int,
        order: str = "relevance",
        published_after: object | None = None,
        region_code: str | None = None,
        video_duration: str | None = None,
        relevance_language: str | None = None,
    ) -> list[dict[str, Any]]:
        raise YouTubeApiError("quota exceeded", status_code=429)

    def videos_by_id(self, video_ids: list[str]) -> list[dict[str, Any]]:
        return []


def test_youtube_trend_provider_selects_compilation_backed_topic() -> None:
    client = FakeYouTubeClient(
        topic_hits=[
            {
                "id": {"videoId": "topic-1"},
                "snippet": {"title": "Trying tiny desk setup challenge"},
            },
            {"id": {"videoId": "topic-2"}, "snippet": {"title": "Tiny desk setup trend attempt"}},
            {"id": {"videoId": "topic-3"}, "snippet": {"title": "Friends doing tiny desk setup"}},
        ],
        compilation_hits=[
            {
                "id": {"videoId": "compilation-1"},
                "snippet": {"title": "Tiny desk setup challenge compilation"},
            },
            {
                "id": {"videoId": "compilation-2"},
                "snippet": {"title": "Best tiny desk setup trend moments"},
            },
        ],
    )
    provider = YouTubeTrendProvider(
        Settings(_env_file=None, max_trends=3),
        client,  # type: ignore[arg-type]
    )

    trends = provider.discover(limit=1)

    assert len(trends) == 1
    assert trends[0].title == "tiny desk setup"
    assert trends[0].source == "youtube_most_popular_with_topic_and_compilation_probes"
    assert trends[0].metadata["topic_probe_count"] == 3
    assert trends[0].metadata["compilation_probe_count"] == 2
    assert "tiny desk setup" in client.search_queries
    assert any(query.endswith(" compilation") for query in client.search_queries)


def test_youtube_trend_provider_requires_recent_compilation_hits() -> None:
    provider = YouTubeTrendProvider(
        Settings(_env_file=None, max_trends=3),
        FakeYouTubeClient(
            topic_hits=[
                {"id": {"videoId": "topic-1"}, "snippet": {"title": "Trying tiny desk setup"}},
                {"id": {"videoId": "topic-2"}, "snippet": {"title": "Tiny desk setup trend"}},
                {"id": {"videoId": "topic-3"}, "snippet": {"title": "Doing tiny desk setup"}},
            ],
            compilation_hits=[],
        ),  # type: ignore[arg-type]
    )

    assert provider.discover(limit=1) == []


def test_youtube_trend_provider_requires_recent_topic_hits() -> None:
    provider = YouTubeTrendProvider(
        Settings(_env_file=None, max_trends=3),
        FakeYouTubeClient(
            topic_hits=[],
            compilation_hits=[
                {
                    "id": {"videoId": "compilation-1"},
                    "snippet": {"title": "Tiny desk setup challenge compilation"},
                },
                {
                    "id": {"videoId": "compilation-2"},
                    "snippet": {"title": "Tiny desk setup trend compilation"},
                },
            ],
        ),  # type: ignore[arg-type]
    )

    assert provider.discover(limit=1) == []


def test_youtube_trend_provider_rejects_entities_without_activity_evidence() -> None:
    client = FakeYouTubeClient(
        topic_hits=[
            {"id": {"videoId": "topic-1"}, "snippet": {"title": "Tiny desk setup official"}},
            {"id": {"videoId": "topic-2"}, "snippet": {"title": "Tiny desk setup interview"}},
            {"id": {"videoId": "topic-3"}, "snippet": {"title": "Tiny desk setup performance"}},
        ],
        compilation_hits=[
            {"id": {"videoId": "compilation-1"}, "snippet": {"title": "Tiny desk setup clips"}},
            {"id": {"videoId": "compilation-2"}, "snippet": {"title": "Tiny desk setup videos"}},
        ],
    )
    provider = YouTubeTrendProvider(
        Settings(_env_file=None, max_trends=3),
        client,  # type: ignore[arg-type]
    )

    assert provider.discover(limit=1) == []


def test_compilation_query_provider_prefers_unused_query_bucket(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        content_domain="kids_funny",
        source_history_path=tmp_path / "source_video_history.json",
        source_languages="en",
        compilation_queries="funny kids shorts,toddler reaction shorts,kids bloopers shorts",
    )
    SourceHistory(settings.source_history_path).mark_query_used(
        "funny kids shorts",
        "previous-run",
        language="en",
    )

    trends = CompilationQueryProvider(settings).discover(limit=2)

    assert trends[0].title in {"toddler reaction shorts", "kids bloopers shorts"}
    assert "funny kids shorts" not in {trend.title for trend in trends}


def test_compilation_query_provider_rotates_query_language_bucket(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        content_domain="kids_funny",
        source_history_path=tmp_path / "source_video_history.json",
        source_languages="en,hi",
        compilation_queries="funny kids shorts",
    )
    SourceHistory(settings.source_history_path).mark_query_used(
        "funny kids shorts",
        "previous-run",
        language="en",
    )

    trends = CompilationQueryProvider(settings).discover(limit=1)

    assert trends[0].title == "funny kids shorts"
    assert trends[0].metadata["source_language"] == "hi"


def test_settings_apply_domain_specific_defaults() -> None:
    kids = Settings(_env_file=None, content_domain="kids_funny")
    football = Settings(_env_file=None, content_domain="football")
    cricket = Settings(_env_file=None, content_domain="cricket")

    assert kids.content_label == "Funny Kid Clips"
    assert kids.source_languages == "en,hi"
    assert kids.compilation_queries.split(",")[0] == "funny toddler fails shorts"

    assert football.content_label == "Football Moments"
    assert football.source_languages == "en"
    assert football.football_query_adjectives.split(",")[0] == "unreal"
    assert football.football_query_types.split(",")[0] == "football saves"

    assert cricket.content_label == "Cricket Moments"
    assert cricket.source_languages == "en"
    assert cricket.cricket_query_adjectives.split(",")[0] == "unreal"
    assert cricket.cricket_query_types.split(",")[0] == "cricket catches"


def test_football_compilation_query_provider_enforces_football_keyword(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        content_domain="football",
        source_history_path=tmp_path / "football_source_video_history.json",
        source_languages="en",
        compilation_queries="crazy goals shorts,penalty saves shorts",
        football_query_adjectives="",
        football_query_types="",
    )

    trends = CompilationQueryProvider(settings).discover(limit=2)

    assert {trend.title for trend in trends} == {
        "football crazy goals shorts",
        "football penalty saves shorts",
    }
    assert {trend.metadata["raw_query"] for trend in trends} == {
        "football crazy goals shorts",
        "football penalty saves shorts",
    }


def test_football_compilation_query_provider_generates_adjective_type_combinations(
    tmp_path,
) -> None:
    settings = Settings(
        _env_file=None,
        content_domain="football",
        source_history_path=tmp_path / "football_source_video_history.json",
        source_languages="en",
        compilation_queries=(
            "unreal football saves shorts,epic football saves shorts,"
            "unreal football penalties shorts,epic football penalties shorts"
        ),
        football_query_adjectives="unreal,epic",
        football_query_types="football saves,football penalties",
    )
    SourceHistory(settings.source_history_path).mark_query_used(
        "unreal football saves shorts",
        "previous-run",
        language="en",
    )

    trends = CompilationQueryProvider(settings).discover(limit=3)

    titles = {trend.title for trend in trends}
    assert "unreal football saves shorts" not in titles
    assert titles <= {
        "epic football saves shorts",
        "unreal football penalties shorts",
        "epic football penalties shorts",
    }
    assert len(titles) == 3
    assert all(trend.title.endswith(" shorts") for trend in trends)


def test_football_short_queries_stay_inside_selected_theme() -> None:
    settings = Settings(_env_file=None, content_domain="football")

    queries = _shorts_search_queries("unreal football saves shorts", "en", settings)

    assert queries
    assert all("football" in query.lower() for query in queries)
    assert all(
        any(term in query.lower() for term in ("save", "saves", "goalkeeper", "keeper"))
        for query in queries
    )
    assert not any("viral football moments" in query.lower() for query in queries)
    assert not any(
        "football goals shorts" == query.lower().replace(" english", "")
        for query in queries
    )


def test_cricket_compilation_query_provider_generates_adjective_type_combinations(
    tmp_path,
) -> None:
    settings = Settings(
        _env_file=None,
        content_domain="cricket",
        source_history_path=tmp_path / "cricket_source_video_history.json",
        source_languages="en",
        compilation_queries=(
            "unreal cricket catches shorts,epic cricket catches shorts,"
            "unreal cricket wickets shorts,epic cricket wickets shorts"
        ),
        cricket_query_adjectives="unreal,epic",
        cricket_query_types="cricket catches,cricket wickets",
    )
    SourceHistory(settings.source_history_path).mark_query_used(
        "unreal cricket catches shorts",
        "previous-run",
        language="en",
    )

    trends = CompilationQueryProvider(settings).discover(limit=3)

    titles = {trend.title for trend in trends}
    assert "unreal cricket catches shorts" not in titles
    assert titles <= {
        "epic cricket catches shorts",
        "unreal cricket wickets shorts",
        "epic cricket wickets shorts",
    }
    assert len(titles) == 3
    assert all(trend.title.endswith(" shorts") for trend in trends)


def test_cricket_short_queries_stay_inside_selected_theme() -> None:
    settings = Settings(_env_file=None, content_domain="cricket")

    queries = _shorts_search_queries("unreal cricket catches shorts", "en", settings)

    assert queries
    assert all("cricket" in query.lower() for query in queries)
    assert all(
        any(term in query.lower() for term in ("catch", "catches", "fielding"))
        for query in queries
    )
    assert not any("viral cricket moments" in query.lower() for query in queries)


def test_youtube_short_search_filters_seen_video_ids(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        content_domain="kids_funny",
        source_history_path=tmp_path / "source_video_history.json",
        youtube_api_key="test-key",
        max_source_video_seconds=30,
        source_languages="en",
    )
    SourceHistory(settings.source_history_path).mark_videos_seen(
        [
            YouTubeVideo(
                id="seen-1",
                trend_id="trend-1",
                title="previously used short",
                url="https://www.youtube.com/watch?v=seen-1",
            )
        ],
        run_id="previous-run",
        query="funny kids shorts",
    )
    provider = YouTubeDataProvider(settings.youtube_api_key, settings)
    provider.client = FakeShortsClient()  # type: ignore[assignment]

    videos = provider.search_compilations(
        trend=Trend(
            id="trend-1",
            title="funny kids shorts",
            source="test",
            metadata={"source_language": "en"},
        ),
        limit=2,
    )

    assert [video.id for video in videos] == ["fresh-1"]
    assert videos[0].metadata["search_query"] == "funny kids shorts english"
    assert videos[0].metadata["source_language"] == "en"


def test_youtube_short_search_prefers_concrete_kids_funny_formats(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        content_domain="kids_funny",
        source_history_path=tmp_path / "source_video_history.json",
        youtube_api_key="test-key",
        max_source_video_seconds=30,
        source_languages="en",
    )
    provider = YouTubeDataProvider(settings.youtube_api_key, settings)
    provider.client = FakeKidsQualityClient()  # type: ignore[assignment]

    videos = provider.search_compilations(
        trend=Trend(
            id="trend-1",
            title="funny toddler pranks shorts",
            source="test",
            metadata={"source_language": "en"},
        ),
        limit=3,
    )

    assert [video.id for video in videos] == ["toddler-prank", "baby-reaction"]
    assert all(video.metadata["search_relevance_score"] >= 0.45 for video in videos)


def test_youtube_short_search_prefers_real_football_moments(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        content_domain="football",
        source_history_path=tmp_path / "football_source_video_history.json",
        youtube_api_key="test-key",
        max_source_video_seconds=30,
        source_languages="en",
    )
    provider = YouTubeDataProvider(settings.youtube_api_key, settings)
    fake_client = FakeFootballQualityClient()
    provider.client = fake_client  # type: ignore[assignment]

    videos = provider.search_compilations(
        trend=Trend(
            id="trend-1",
            title="crazy moments shorts",
            source="test",
            metadata={"source_language": "en"},
        ),
        limit=6,
    )

    assert [video.id for video in videos] == ["goal", "save"]
    assert all(video.metadata["search_relevance_score"] >= 0.45 for video in videos)
    assert fake_client.search_queries
    assert len(fake_client.search_queries) == 3
    assert fake_client.max_results == [36, 36, 36]
    assert fake_client.published_after_values == [None, None, None]
    assert all("football" in query.lower() for query in fake_client.search_queries)
    assert not any(
        "viral football moments" in query.lower()
        for query in fake_client.search_queries
    )


def test_youtube_short_search_prefers_real_cricket_moments(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        content_domain="cricket",
        source_history_path=tmp_path / "cricket_source_video_history.json",
        youtube_api_key="test-key",
        max_source_video_seconds=30,
        source_languages="en",
    )
    provider = YouTubeDataProvider(settings.youtube_api_key, settings)
    fake_client = FakeCricketQualityClient()
    provider.client = fake_client  # type: ignore[assignment]

    videos = provider.search_compilations(
        trend=Trend(
            id="trend-1",
            title="unreal catches shorts",
            source="test",
            metadata={"source_language": "en"},
        ),
        limit=6,
    )

    assert {video.id for video in videos} == {"catch", "six"}
    assert all(video.metadata["search_relevance_score"] >= 0.55 for video in videos)
    assert fake_client.search_queries
    assert len(fake_client.search_queries) == 3
    assert fake_client.published_after_values == [None, None, None]
    assert all("cricket" in query.lower() for query in fake_client.search_queries)
    assert not any(
        "viral cricket moments" in query.lower()
        for query in fake_client.search_queries
    )


def test_youtube_short_search_returns_empty_on_quota_limited_focused_domain(
    tmp_path,
) -> None:
    settings = Settings(
        _env_file=None,
        content_domain="football",
        source_history_path=tmp_path / "football_source_video_history.json",
        youtube_api_key="test-key",
        source_languages="en",
    )
    provider = YouTubeDataProvider(settings.youtube_api_key, settings)
    provider.client = FakeQuotaLimitedClient()  # type: ignore[assignment]

    videos = provider.search_compilations(
        trend=Trend(
            id="trend-1",
            title="best football volleys shorts",
            source="test",
            metadata={"source_language": "en"},
        ),
        limit=6,
    )

    assert videos == []


def test_youtube_trend_provider_filters_generic_media_terms() -> None:
    provider = YouTubeTrendProvider(
        Settings(_env_file=None, max_trends=3),
        FakeYouTubeClient(compilation_hits=[{"id": {"videoId": "hit"}}]),  # type: ignore[arg-type]
    )

    ranked = provider._rank_candidates(
        [
            {
                "id": "popular-1",
                "snippet": {
                    "title": "Best upcoming movie trailer compilation funny moments",
                    "tags": ["trailer", "funny", "movie compilation"],
                },
                "statistics": {"viewCount": "5000000"},
            }
        ]
    )

    assert ranked == []
