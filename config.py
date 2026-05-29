import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from dotenv import load_dotenv


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


def _normalize_database_url(url: str) -> str:
    """Render may supply postgres://; SQLAlchemy requires postgresql://."""
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


def _sqlite_uri() -> str:
    """SQLite path; use INSTANCE_PATH on Render persistent disk if configured."""
    instance = os.getenv("INSTANCE_PATH", "").strip()
    if instance:
        db_path = Path(instance) / "salary_system.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db_path.as_posix()}"
    return f"sqlite:///{(BASE_DIR / 'salary_system.db').as_posix()}"


def _database_uri() -> str:
    """
    Resolve database URL.

    Priority: SQLALCHEMY_DATABASE_URI > DATABASE_URL > local SQLite fallback.
    """
    explicit = os.getenv("SQLALCHEMY_DATABASE_URI", "").strip()
    if explicit:
        return _normalize_database_url(explicit)

    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return _normalize_database_url(database_url)

    return _sqlite_uri()


def _engine_options(uri: str) -> dict:
    if uri.startswith("sqlite"):
        return {
            "pool_pre_ping": True,
            "connect_args": {"check_same_thread": False},
        }
    return {"pool_pre_ping": True}


def mask_database_uri(uri: str) -> str:
    """Return a log-safe database URI with credentials redacted."""
    try:
        parsed = urlparse(uri)
        if parsed.password:
            netloc = parsed.hostname or ""
            if parsed.username:
                netloc = f"{parsed.username}:****@{netloc}"
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            return urlunparse(
                (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
            )
    except Exception:
        pass
    return uri


_DB_URI = _database_uri()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = _DB_URI
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = _engine_options(_DB_URI)
    UPLOAD_FOLDER = "uploads"
    PDF_FOLDER = "generated_pdfs"
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_MB", "8")) * 1024 * 1024
    ALLOWED_EXTENSIONS = {"csv", "xlsx"}
    MAX_SLIPS_PER_REQUEST = int(os.getenv("MAX_SLIPS_PER_REQUEST", "1"))
    GUNICORN_TIMEOUT = int(os.getenv("GUNICORN_TIMEOUT", "120"))
    SENDGRID_TIMEOUT = int(os.getenv("SENDGRID_TIMEOUT", "30"))
    SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
    FROM_EMAIL = os.getenv("FROM_EMAIL", "")
    COMPANY_NAME = os.getenv("COMPANY_NAME", "Nippon Toyota")
    COMPANY_EMAIL = os.getenv("COMPANY_EMAIL", "")
    COMPANY_PHONE = os.getenv("COMPANY_PHONE", "")
    COMPANY_ADDRESS = os.getenv("COMPANY_ADDRESS", "")
    COMPANY_LOGO_URL = os.getenv("COMPANY_LOGO_URL", "")
    SENDER_NAME = os.getenv("SENDER_NAME", "")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")


class ProductionConfig(Config):
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True
    MAX_SLIPS_PER_REQUEST = int(os.getenv("MAX_SLIPS_PER_REQUEST", "1"))


class DevelopmentConfig(Config):
    DEBUG = True
    MAX_SLIPS_PER_REQUEST = int(os.getenv("MAX_SLIPS_PER_REQUEST", "50"))
    SESSION_COOKIE_SECURE = False


def get_config():
    env = os.getenv("FLASK_ENV", "development").lower()
    if env == "production":
        return ProductionConfig
    return DevelopmentConfig
