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
    "babies and kids funny shorts,kids try not to laugh shorts,"
    "hilarious toddler moments shorts,wholesome kids funny moments shorts,"
    "funny family kids moments shorts,silly toddler moments shorts,"
    "cute baby funny moments shorts,kids silly reactions shorts"
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
    "best football goals shorts,impossible football free kicks shorts"
)

FOOTBALL_QUERY_ADJECTIVES = (
    "unreal,epic,unforgettable,insane,best,impossible,crazy,legendary,"
    "dramatic,unbelievable,incredible,shocking"
)

FOOTBALL_QUERY_TYPES = (
    "football saves,football penalties,football moments,football passes,"
    "football goals,football free kicks,football goalkeeper saves,"
    "football comebacks,football last minute goals,football nutmeg skills,"
    "football volley goals,football red card drama,football goal line clearances,"
    "football skills"
)

FOOTBALL_EVENT_KEYWORDS = (
    "football,soccer,goal,goals,skill,skills,save,saves,goalkeeper,"
    "keeper,penalty,free kick,freekick,header,volley,dribble,dribbling,"
    "nutmeg,tackle,red card,yellow card,referee,var,celebration,"
    "comeback,last minute,stoppage time,injury time,match,league,cup,"
    "final,club,crowd,stadium,fans,fails,funny,crazy,unbelievable,"
    "incredible,impossible"
)

CRICKET_ACTIVITY_SEED_QUERIES = (
    "viral cricket moments,cricket shorts,cricket challenge,"
    "cricket compilation,viral cricket trend,cricket trick shots,"
    "cricket catches,cricket wickets"
)

CRICKET_COMPILATION_QUERIES = (
    "unreal cricket catches shorts,epic cricket sixes shorts,"
    "unforgettable cricket moments shorts,insane cricket bowling shorts,"
    "best cricket wickets shorts,impossible cricket run outs shorts"
)

CRICKET_QUERY_ADJECTIVES = (
    "unreal,epic,unforgettable,insane,best,impossible,crazy,legendary,"
    "dramatic,unbelievable,incredible,shocking"
)

CRICKET_QUERY_TYPES = (
    "cricket catches,cricket sixes,cricket wickets,cricket bowling,"
    "cricket batting,cricket run outs,cricket fielding,cricket yorkers,"
    "cricket bouncers,cricket stumpings,cricket finishes,cricket moments,"
    "cricket celebrations,cricket last over finishes"
)

CRICKET_EVENT_KEYWORDS = (
    "cricket,batsman,batter,batting,bowler,bowling,wicket,wickets,"
    "six,sixes,four,boundary,catch,catches,fielding,run out,runout,"
    "stumping,yorker,bouncer,googly,spin,fast bowling,innings,over,"
    "last over,super over,finish,finishes,celebration,stadium,crowd,"
    "fans,crazy,unbelievable,incredible,impossible"
)

BASKETBALL_ACTIVITY_SEED_QUERIES = (
    "viral basketball moments,basketball shorts,basketball challenge,"
    "basketball compilation,viral basketball trend,basketball trick shots,"
    "basketball dunks,basketball blocks"
)

BASKETBALL_COMPILATION_QUERIES = (
    "unreal basketball dunks shorts,epic basketball blocks shorts,"
    "unforgettable basketball moments shorts,insane basketball crossovers shorts,"
    "best basketball buzzer beaters shorts,impossible basketball passes shorts"
)

BASKETBALL_QUERY_ADJECTIVES = (
    "unreal,epic,unforgettable,insane,best,impossible,crazy,legendary,"
    "dramatic,unbelievable,incredible,shocking"
)

BASKETBALL_QUERY_TYPES = (
    "basketball dunks,basketball blocks,basketball moments,basketball crossovers,"
    "basketball assists,basketball buzzer beaters,basketball game winners,"
    "basketball steals,basketball ankle breakers,basketball three pointers,"
    "basketball clutch shots,basketball fast breaks,basketball alley oops"
)

BASKETBALL_EVENT_KEYWORDS = (
    "basketball,nba,wnba,hoops,hoop,dunk,dunks,slam,slams,block,blocks,"
    "crossover,crossovers,assist,assists,pass,passes,buzzer beater,game winner,"
    "three pointer,three pointers,three point,steal,steals,ankle breaker,"
    "alley oop,fast break,layup,layups,shot,shots,clutch,comeback,"
    "overtime,quarter,arena,crowd,fans,crazy,unbelievable,incredible,impossible"
)

TENNIS_ACTIVITY_SEED_QUERIES = (
    "viral tennis moments,tennis shorts,tennis challenge,tennis compilation,"
    "viral tennis trend,tennis trick shots,tennis rallies,tennis winners"
)

TENNIS_COMPILATION_QUERIES = (
    "unreal tennis rallies shorts,epic tennis winners shorts,"
    "unforgettable tennis moments shorts,insane tennis shots shorts,"
    "best tennis aces shorts,impossible tennis saves shorts"
)

TENNIS_QUERY_ADJECTIVES = (
    "unreal,epic,unforgettable,insane,best,impossible,crazy,legendary,"
    "dramatic,unbelievable,incredible,shocking"
)

TENNIS_QUERY_TYPES = (
    "tennis rallies,tennis winners,tennis shots,tennis aces,tennis saves,"
    "tennis volleys,tennis passing shots,tennis match points,tennis drop shots,"
    "tennis lobs,tennis comebacks,tennis forehands,tennis backhands"
)

TENNIS_EVENT_KEYWORDS = (
    "tennis,atp,wta,grand slam,rally,rallies,winner,winners,ace,aces,serve,serves,"
    "forehand,backhand,volley,volleys,smash,smashes,drop shot,passing shot,lob,lobs,"
    "return,returns,baseline,court,net,match,point,match point,comeback,tiebreak,"
    "set,sets,game,games,crowd,fans,crazy,unbelievable,incredible,impossible"
)

FORMULA1_ACTIVITY_SEED_QUERIES = (
    "viral formula 1 moments,formula 1 shorts,formula 1 challenge,"
    "formula 1 compilation,viral formula 1 trend,formula 1 overtakes,"
    "formula 1 pit stops,formula 1 last lap"
)

FORMULA1_COMPILATION_QUERIES = (
    "unreal formula 1 overtakes shorts,epic formula 1 pit stops shorts,"
    "unforgettable formula 1 moments shorts,insane formula 1 saves shorts,"
    "best formula 1 starts shorts,impossible formula 1 wet weather shorts"
)

FORMULA1_QUERY_ADJECTIVES = (
    "unreal,epic,unforgettable,insane,best,impossible,crazy,legendary,"
    "dramatic,unbelievable,incredible,shocking"
)

FORMULA1_QUERY_TYPES = (
    "formula 1 overtakes,formula 1 pit stops,formula 1 moments,formula 1 saves,"
    "formula 1 starts,formula 1 last lap finishes,formula 1 wet weather drives,"
    "formula 1 wheel to wheel battles,formula 1 fastest laps,formula 1 comebacks,"
    "formula 1 race battles,formula 1 qualifying laps"
)

FORMULA1_EVENT_KEYWORDS = (
    "formula 1,formula1,f1,grand prix,race,races,racing,driver,drivers,car,cars,"
    "overtake,overtakes,passing,pit stop,pit stops,pitlane,lap,laps,last lap,"
    "fastest lap,qualifying,grid,start,starts,wet weather,rain,drift,save,saves,"
    "recovery,recoveries,wheel to wheel,comeback,finish,finishes,checkered flag,"
    "podium,crowd,fans,crazy,unbelievable,incredible,impossible"
)

UNEXPECTED_ACTIVITY_SEED_QUERIES = (
    "unexpected moments,close calls caught on camera,perfect timing moments,"
    "impossible saves caught on camera,unexpected reactions,complete chaos moments,"
    "impossible luck,nobody saw that coming"
)

UNEXPECTED_COMPILATION_QUERIES = (
    "too close moments shorts,perfect timing moments shorts,"
    "impossible saves caught on camera shorts,unexpected outcomes shorts,"
    "unexpected reactions shorts,complete chaos moments shorts,"
    "impossible luck moments shorts,nobody saw that coming shorts"
)

UNEXPECTED_QUERY_PILLARS = (
    "too close,perfect timing,impossible saves,unexpected outcomes,"
    "unexpected reactions,complete chaos,impossible luck,nobody saw that coming"
)

UNEXPECTED_EVENT_KEYWORDS = (
    "close call,near miss,perfect timing,impossible save,last second save,"
    "unexpected,outcome,reaction,chaos,luck,nobody saw,what happened,"
    "caught on camera,fail,fails,surprise,shocked,unbelievable,incredible,"
    "insane,viral,accident,rescue,save,saves"
)

SATISFYING_ACTIVITY_SEED_QUERIES = (
    "oddly satisfying moments,cleaning transformations,perfect precision work,"
    "restoration process,mesmerizing machines,satisfying art process,"
    "before and after transformations,perfect fit moments,kinetic sand crushing"
)

SATISFYING_COMPILATION_QUERIES = (
    "oddly satisfying moments shorts,cleaning transformations shorts,"
    "perfectly cut things shorts,restoration process shorts,"
    "machines working perfectly shorts,satisfying art process shorts,"
    "before and after transformations shorts,perfect precision fits shorts,"
    "kinetic sand slime crushing shorts,try not to feel satisfied shorts"
)

SATISFYING_QUERY_PILLARS = (
    "oddly satisfying moments,cleaning transformations,perfectly cut things,"
    "restoration videos,perfect machines and processes,smooth art and craft,"
    "before and after transformations,perfect fits and precision,"
    "sand slime and crushing,try not to feel satisfied"
)

SATISFYING_EVENT_KEYWORDS = (
    "satisfying,oddly satisfying,cleaning,clean,pressure washing,carpet cleaning,"
    "restoration,restore,precision,perfect fit,align,organize,cutting,slicing,"
    "crushing,machine,manufacturing,process,packaging,painting,woodworking,"
    "pottery,resin,carving,sculpting,before and after,transformation,"
    "kinetic sand,slime,mesmerizing,smooth"
)

MAGIC_ACTIVITY_SEED_QUERIES = (
    "card magic tricks,street magic reactions,mind reading magic,impossible illusions,"
    "coin magic,everyday object magic,magic reveals,funny magic fails,sleight of hand"
)

MAGIC_COMPILATION_QUERIES = (
    "impossible card magic shorts,street magic reactions shorts,mind reading magic shorts,"
    "impossible illusions shorts,coin magic tricks shorts,best magic reveals shorts,"
    "funny magic fails shorts,sleight of hand shorts"
)

MAGIC_QUERY_PILLARS = (
    "card magic,street magic reactions,mind reading and predictions,"
    "impossible illusions,coin and everyday object magic,best magic reveals,"
    "funny magic moments,sleight of hand"
)

MAGIC_EVENT_KEYWORDS = (
    "magic,magician,card trick,card magic,street magic,mind reading,mentalism,"
    "prediction,illusion,disappear,appearing,levitation,floating,coin magic,"
    "ring magic,money magic,reveal,reaction,sleight of hand,close up magic,"
    "magic fail,magic prank,impossible trick"
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
    min_download_videos_for_upload: int = 1
    fail_on_no_source_downloads: bool = True
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
    youtube_focused_search_query_count: int = 3
    youtube_activity_seed_queries: str = ""
    compilation_queries: str = ""
    football_query_adjectives: str = FOOTBALL_QUERY_ADJECTIVES
    football_query_types: str = FOOTBALL_QUERY_TYPES
    cricket_query_adjectives: str = CRICKET_QUERY_ADJECTIVES
    cricket_query_types: str = CRICKET_QUERY_TYPES
    basketball_query_adjectives: str = BASKETBALL_QUERY_ADJECTIVES
    basketball_query_types: str = BASKETBALL_QUERY_TYPES
    tennis_query_adjectives: str = TENNIS_QUERY_ADJECTIVES
    tennis_query_types: str = TENNIS_QUERY_TYPES
    formula1_query_adjectives: str = FORMULA1_QUERY_ADJECTIVES
    formula1_query_types: str = FORMULA1_QUERY_TYPES
    unexpected_query_pillars: str = UNEXPECTED_QUERY_PILLARS
    satisfying_query_pillars: str = SATISFYING_QUERY_PILLARS
    magic_query_pillars: str = MAGIC_QUERY_PILLARS
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
    yt_dlp_download_timeout_seconds: int = 240
    yt_dlp_network_timeout_seconds: int = 180
    colab_cli_auth: str = "adc"
    colab_cli_config_path: Path | None = None
    colab_session_prefix: str = "viral-pipeline"
    colab_remote_dir: str = "/content/viral_pipeline_download"
    colab_command_timeout_seconds: int = 900
    colab_yt_dlp_requirement: str = "yt-dlp[default]>=2025.9.26"
    colab_upload_youtube_cookies: bool = False
    colab_enable_browser_po_token: bool = False
    render_width: int = 1080
    render_height: int = 1920
    render_fps: int = 30
    render_mode: str = "plain_compilation"
    render_command_timeout_seconds: int = 300
    apply_provenance_transform: bool = True
    provenance_transform_timeout_seconds: int = 600
    provenance_transform_fail_open: bool = True
    provenance_transform_level: int | None = None
    provenance_transform_script: Path = Field(
        default=Path("provenance_robustness_tool/transform.py")
    )
    render_intro_seconds: float = 2.5
    render_outro_seconds: float = 2.5
    enable_voiceover: bool = False
    local_tts_voice: str = "Samantha"
    max_download_stage_seconds: int = 0

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
        elif self.content_domain == "cricket":
            if not self.content_label:
                self.content_label = "Cricket Moments"
            if not self.source_languages:
                self.source_languages = "en"
            if not self.youtube_activity_seed_queries:
                self.youtube_activity_seed_queries = CRICKET_ACTIVITY_SEED_QUERIES
            if not self.compilation_queries:
                self.compilation_queries = CRICKET_COMPILATION_QUERIES
            if not self.event_keywords:
                self.event_keywords = CRICKET_EVENT_KEYWORDS
        elif self.content_domain == "basketball":
            if not self.content_label:
                self.content_label = "Basketball Moments"
            if not self.source_languages:
                self.source_languages = "en"
            if not self.youtube_activity_seed_queries:
                self.youtube_activity_seed_queries = BASKETBALL_ACTIVITY_SEED_QUERIES
            if not self.compilation_queries:
                self.compilation_queries = BASKETBALL_COMPILATION_QUERIES
            if not self.event_keywords:
                self.event_keywords = BASKETBALL_EVENT_KEYWORDS
        elif self.content_domain == "tennis":
            if not self.content_label:
                self.content_label = "Tennis Moments"
            if not self.source_languages:
                self.source_languages = "en"
            if not self.youtube_activity_seed_queries:
                self.youtube_activity_seed_queries = TENNIS_ACTIVITY_SEED_QUERIES
            if not self.compilation_queries:
                self.compilation_queries = TENNIS_COMPILATION_QUERIES
            if not self.event_keywords:
                self.event_keywords = TENNIS_EVENT_KEYWORDS
        elif self.content_domain == "formula1":
            if not self.content_label:
                self.content_label = "Formula 1 Moments"
            if not self.source_languages:
                self.source_languages = "en"
            if not self.youtube_activity_seed_queries:
                self.youtube_activity_seed_queries = FORMULA1_ACTIVITY_SEED_QUERIES
            if not self.compilation_queries:
                self.compilation_queries = FORMULA1_COMPILATION_QUERIES
            if not self.event_keywords:
                self.event_keywords = FORMULA1_EVENT_KEYWORDS
        elif self.content_domain == "unexpected":
            if not self.content_label:
                self.content_label = "Unexpected Moments"
            if not self.source_languages:
                self.source_languages = "en"
            if not self.youtube_activity_seed_queries:
                self.youtube_activity_seed_queries = UNEXPECTED_ACTIVITY_SEED_QUERIES
            if not self.compilation_queries:
                self.compilation_queries = UNEXPECTED_COMPILATION_QUERIES
            if not self.event_keywords:
                self.event_keywords = UNEXPECTED_EVENT_KEYWORDS
        elif self.content_domain == "satisfying":
            if not self.content_label:
                self.content_label = "Satisfying Moments"
            if not self.source_languages:
                self.source_languages = "en"
            if not self.youtube_activity_seed_queries:
                self.youtube_activity_seed_queries = SATISFYING_ACTIVITY_SEED_QUERIES
            if not self.compilation_queries:
                self.compilation_queries = SATISFYING_COMPILATION_QUERIES
            if not self.event_keywords:
                self.event_keywords = SATISFYING_EVENT_KEYWORDS
        elif self.content_domain == "magic":
            if not self.content_label:
                self.content_label = "Magic Moments"
            if not self.source_languages:
                self.source_languages = "en"
            if not self.youtube_activity_seed_queries:
                self.youtube_activity_seed_queries = MAGIC_ACTIVITY_SEED_QUERIES
            if not self.compilation_queries:
                self.compilation_queries = MAGIC_COMPILATION_QUERIES
            if not self.event_keywords:
                self.event_keywords = MAGIC_EVENT_KEYWORDS
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
