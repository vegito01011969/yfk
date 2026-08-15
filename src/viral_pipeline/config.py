from __future__ import annotations

from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

KIDS_FUNNY_ACTIVITY_SEED_QUERIES = (
    "viral challenge,tiktok challenge,youtube shorts challenge,"
    "dance challenge,people trying trend,challenge compilation,"
    "viral trend everyone is doing,friends challenge,couples challenge"
)

KIDS_FUNNY_COMPILATION_QUERIES = (
    "funny toddler fails shorts,kids funny fails shorts,"
    "funny toddler pranks shorts,kids pranks shorts,"
    "funny baby reactions shorts,funny toddler reactions shorts,"
    "kids bloopers shorts,toddler bloopers shorts,"
    "funny sibling moments shorts,kids laughing shorts,"
    "funny kids mispronounce words shorts,cute funny toddler shorts,"
    "babies and kids funny shorts,kids try not to laugh shorts"
)

KIDS_FUNNY_EVENT_KEYWORDS = (
    "laugh,laughing,funny,cute,toddler,baby,kid,kids,child,children,"
    "reaction,reacts,fail,fails,blooper,bloopers,prank,pranks,silly,"
    "surprise,crying,giggling,playing,family,sibling,brother,sister,"
    "mispronounce,mispronounces"
)

FOOTBALL_ACTIVITY_SEED_QUERIES = (
    "viral football moments,football challenge,football shorts challenge,"
    "football skills challenge,football compilation,"
    "viral football trend,football fans challenge,football trick shots"
)

FOOTBALL_COMPILATION_QUERIES = (
    "unreal football saves shorts,epic football penalties shorts,"
    "unforgettable football moments shorts,insane football passes shorts,"
    "best football goals shorts,impossible football free kicks shorts,"
    "crazy football goalkeeper saves shorts,legendary football comebacks shorts,"
    "football last minute goals shorts,football nutmeg skills shorts,"
    "football volley goals shorts,football red card drama shorts,"
    "football goal line clearances shorts,football skills that shocked everyone shorts"
)

FOOTBALL_EVENT_KEYWORDS = (
    "football,soccer,goal,goals,skill,skills,save,saves,goalkeeper,"
    "keeper,penalty,free kick,freekick,header,volley,dribble,dribbling,"
    "nutmeg,tackle,red card,yellow card,referee,var,celebration,"
    "comeback,last minute,stoppage time,injury time,match,league,cup,"
    "final,club,crowd,stadium,fans,fails,funny,crazy,unbelievable,"
    "incredible,impossible"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    pipeline_db_path: Path = Field(default=Path("data/pipeline.sqlite3"))
    pipeline_workdir: Path = Field(default=Path("workdir"))
    source_history_path: Path = Field(default=Path("data/source_video_history.json"))
    content_domain: str = "kids_funny"
    content_label: str = ""
    source_language_mode: str = "cycle"
    source_languages: str = ""
    max_trends: int = 5
    selected_trend_count: int = 1
    max_videos_per_trend: int = 20
    max_download_videos: int = 10
    max_download_attempts: int = 0
    youtube_search_pool_size: int = 50
    max_clips_per_video: int = 8
    max_clips: int = 5
    source_video_mode: str = "shorts"
    max_source_video_seconds: int = 30
    min_clip_seconds: float = 4.0
    max_clip_seconds: float = 30.0
    min_clip_quality_score: float = 0.45
    duplicate_hash_distance: int = 0
    clip_scene_threshold: float = 0.35
    clip_scene_scan_interval: float = 0.5
    youtube_api_key: str | None = None
    youtube_oauth_client_secrets: Path | None = None
    youtube_oauth_token_path: Path = Field(default=Path("data/youtube_oauth_token.json"))
    enable_youtube_upload: bool = False
    youtube_upload_allow_duplicate: bool = False
    youtube_upload_privacy_status: str = "public"
    youtube_upload_notify_subscribers: bool = False
    youtube_upload_category_id: str = "22"
    youtube_upload_expected_channel_id: str | None = None
    youtube_video_made_for_kids: bool = False
    youtube_video_self_declared_made_for_kids: bool = False
    youtube_region_code: str = "US"
    youtube_trend_category_id: str | None = None
    youtube_trend_source_video_count: int = 50
    youtube_trend_probe_results: int = 5
    youtube_trend_min_topic_videos: int = 3
    youtube_trend_min_compilation_videos: int = 2
    youtube_trend_lookback_hours: int = 168
    youtube_activity_seed_queries: str = ""
    compilation_queries: str = ""
    event_keywords: str = ""
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    openai_voice: str = "alloy"
    groqcloud_api_key: str | None = None
    groq_api_key: str | None = None
    groqcloud_model: str = "openai/gpt-oss-20b"
    groqcloud_base_url: str = "https://api.groq.com/openai/v1"
    use_real_media: bool = False
    download_backend: str = "local"
    yt_dlp_format: str = "bv*[height<=720]+ba/b[height<=720]/best[height<=720]/best"
    yt_dlp_cookies_path: Path | None = None
    yt_dlp_js_runtimes: str | None = None
    yt_dlp_extractor_args: str | None = None
    yt_dlp_verbose: bool = False
    colab_cli_auth: str = "adc"
    colab_cli_config_path: Path | None = None
    colab_session_prefix: str = "viral-pipeline"
    colab_remote_dir: str = "/content/viral_pipeline_download"
    colab_command_timeout_seconds: int = 900
    colab_yt_dlp_requirement: str = "yt-dlp>=2025.9.26"
    colab_upload_youtube_cookies: bool = False
    render_width: int = 1080
    render_height: int = 1920
    render_fps: int = 30
    render_mode: str = "plain_compilation"
    apply_provenance_transform: bool = True
    provenance_transform_script: Path = Field(
        default=Path("provenance_robustness_tool/transform.py")
    )
    render_intro_seconds: float = 2.5
    render_outro_seconds: float = 2.5
    enable_voiceover: bool = False
    local_tts_voice: str = "Samantha"

    @model_validator(mode="after")
    def apply_domain_defaults(self) -> Settings:
        if self.content_domain == "football":
            if not self.content_label:
                self.content_label = "Football Moments"
            if not self.source_languages:
                self.source_languages = "en"
            if not self.youtube_activity_seed_queries:
                self.youtube_activity_seed_queries = FOOTBALL_ACTIVITY_SEED_QUERIES
            if not self.compilation_queries:
                self.compilation_queries = FOOTBALL_COMPILATION_QUERIES
            if not self.event_keywords:
                self.event_keywords = FOOTBALL_EVENT_KEYWORDS
        elif self.content_domain == "kids_funny":
            if not self.content_label:
                self.content_label = "Funny Kid Clips"
            if not self.source_languages:
                self.source_languages = "en,hi"
            if not self.youtube_activity_seed_queries:
                self.youtube_activity_seed_queries = KIDS_FUNNY_ACTIVITY_SEED_QUERIES
            if not self.compilation_queries:
                self.compilation_queries = KIDS_FUNNY_COMPILATION_QUERIES
            if not self.event_keywords:
                self.event_keywords = KIDS_FUNNY_EVENT_KEYWORDS
        return self

    @property
    def runs_dir(self) -> Path:
        return self.pipeline_workdir / "runs"

    @property
    def llm_api_key(self) -> str | None:
        return self.groqcloud_api_key or self.groq_api_key or self.openai_api_key
