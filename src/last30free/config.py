from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer, got: {raw}") from exc


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class AppSettings(BaseModel):
    output_dir: Path = Field(default=Path("outputs"))
    cache_dir: Path = Field(default=Path("cache"))
    db_path: Path = Field(default=Path("cache/last30free.sqlite"))
    request_timeout_seconds: int = 20
    default_days: int = 30
    max_items_per_source: int = 25
    user_agent: str = "last30free/0.1.0"
    jina_api_key: str = ""  # Optional — set JINA_API_KEY for higher Jina Reader rate limits

    def ensure_directories(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


class RedditSettings(BaseModel):
    base_url: str = "https://www.reddit.com"
    search_limit: int = 25
    comment_limit: int = 5


class HNSettings(BaseModel):
    base_url: str = "https://hn.algolia.com/api/v1"
    search_limit: int = 25
    comment_limit: int = 10


class YouTubeSettings(BaseModel):
    search_limit: int = 20
    sub_langs: str = "en.*,en"
    write_auto_subs: bool = True
    write_subs: bool = True


class XSettings(BaseModel):
    auth_token: str = ""
    ct0: str = ""
    search_limit: int = 20
    enable: bool = True

    @property
    def configured(self) -> bool:
        return bool(self.auth_token.strip() and self.ct0.strip())


class InstagramSettings(BaseModel):
    search_limit: int = 20
    enable: bool = True
    session_id: str = ""  # Set INSTAGRAM_SESSION_ID to enable scraping

    @property
    def authenticated(self) -> bool:
        return bool(self.session_id.strip())

    @property
    def active(self) -> bool:
        """True only when explicitly enabled AND a session token is present."""
        return self.enable and self.authenticated


class TikTokSettings(BaseModel):
    search_limit: int = 20
    enable: bool = True


class FacebookSettings(BaseModel):
    search_limit: int = 20
    enable: bool = True
    c_user: str = ""  # Set FACEBOOK_C_USER to enable (get from browser DevTools → Cookies → facebook.com → c_user)
    xs: str = ""      # Set FACEBOOK_XS (browser DevTools → Cookies → facebook.com → xs)
    datr: str = ""    # Optional — FACEBOOK_DATR. Warning: ties scraping to your real browser; if flagged may affect your normal account session
    sb: str = ""      # Optional — FACEBOOK_SB. Same warning as datr — avoid if using the same account/browser normally

    @property
    def configured(self) -> bool:
        return bool(self.c_user.strip() and self.xs.strip())

    @property
    def active(self) -> bool:
        return self.enable and self.configured


class Settings(BaseModel):
    app: AppSettings
    reddit: RedditSettings
    hn: HNSettings
    youtube: YouTubeSettings
    x: XSettings
    instagram: InstagramSettings
    tiktok: TikTokSettings
    facebook: FacebookSettings

    def ensure_directories(self) -> None:
        self.app.ensure_directories()


def load_settings() -> Settings:
    settings = Settings(
        app=AppSettings(
            output_dir=Path(os.getenv("LAST30_OUTPUT_DIR", "outputs")),
            cache_dir=Path(os.getenv("LAST30_CACHE_DIR", "cache")),
            db_path=Path(os.getenv("LAST30_DB_PATH", "cache/last30free.sqlite")),
            request_timeout_seconds=_get_int("LAST30_REQUEST_TIMEOUT_SECONDS", 20),
            default_days=_get_int("LAST30_DEFAULT_DAYS", 30),
            max_items_per_source=_get_int("LAST30_MAX_ITEMS_PER_SOURCE", 25),
            user_agent=os.getenv("LAST30_USER_AGENT", "last30free/0.1.0"),
            jina_api_key=os.getenv("JINA_API_KEY", ""),
        ),
        reddit=RedditSettings(
            base_url=os.getenv("REDDIT_BASE_URL", "https://www.reddit.com"),
            search_limit=_get_int("REDDIT_SEARCH_LIMIT", 25),
            comment_limit=_get_int("REDDIT_COMMENT_LIMIT", 5),
        ),
        hn=HNSettings(
            base_url=os.getenv("HN_ALGOLIA_BASE_URL", "https://hn.algolia.com/api/v1"),
            search_limit=_get_int("HN_SEARCH_LIMIT", 25),
            comment_limit=_get_int("HN_COMMENT_LIMIT", 10),
        ),
        youtube=YouTubeSettings(
            search_limit=_get_int("YOUTUBE_SEARCH_LIMIT", 20),
            sub_langs=os.getenv("YOUTUBE_SUB_LANGS", "en.*,en"),
            write_auto_subs=_get_bool("YOUTUBE_WRITE_AUTO_SUBS", True),
            write_subs=_get_bool("YOUTUBE_WRITE_SUBS", True),
        ),
        x=XSettings(
            auth_token=os.getenv("AUTH_TOKEN", ""),
            ct0=os.getenv("CT0", ""),
            search_limit=_get_int("X_SEARCH_LIMIT", 20),
            enable=_get_bool("X_ENABLE", True),
        ),
        instagram=InstagramSettings(
            search_limit=_get_int("INSTAGRAM_SEARCH_LIMIT", 20),
            enable=_get_bool("INSTAGRAM_ENABLE", True),
            session_id=os.getenv("INSTAGRAM_SESSION_ID", ""),
        ),
        tiktok=TikTokSettings(
            search_limit=_get_int("TIKTOK_SEARCH_LIMIT", 20),
            enable=_get_bool("TIKTOK_ENABLE", True),
        ),
        facebook=FacebookSettings(
            search_limit=_get_int("FACEBOOK_SEARCH_LIMIT", 20),
            enable=_get_bool("FACEBOOK_ENABLE", True),
            c_user=os.getenv("FACEBOOK_C_USER", ""),
            xs=os.getenv("FACEBOOK_XS", ""),
            datr=os.getenv("FACEBOOK_DATR", ""),
            sb=os.getenv("FACEBOOK_SB", ""),
        ),
    )
    return settings
