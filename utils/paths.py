"""Filesystem paths for uploads and PDFs (Render-safe).

When using PostgreSQL on Render, set INSTANCE_PATH (e.g. /tmp) so uploads and
generated PDFs are written to a writable directory.
"""

import os
from pathlib import Path

from sqlalchemy.engine.url import make_url

BASE_DIR = Path(__file__).resolve().parent.parent


def _sqlite_data_dir(app_root=None):
    """
    If DATABASE_URL/SQLALCHEMY_DATABASE_URI is SQLite, use the DB file's directory.

    Render often sets DATABASE_URL=sqlite:////tmp/salary_system.db — uploads/PDFs
    must live on the same writable volume (/tmp), not the app source directory.
    """
    for env_key in ("DATABASE_URL", "SQLALCHEMY_DATABASE_URI"):
        uri = os.getenv(env_key, "").strip()
        if not uri.startswith("sqlite"):
            continue
        try:
            db_path = make_url(uri).database
        except Exception:
            continue
        if not db_path or db_path == ":memory:":
            continue
        path = Path(db_path)
        if not path.is_absolute() and app_root:
            path = Path(app_root) / path
        return path.parent
    return None


def get_data_root(app_root=None) -> Path:
    """
    Root directory for mutable data (uploads, generated PDFs).

    Priority: INSTANCE_PATH > SQLite DATABASE_URL parent > app root.

    With PostgreSQL, INSTANCE_PATH should be set on Render (see render.yaml).
    """
    instance = os.getenv("INSTANCE_PATH", "").strip()
    if instance:
        root = Path(instance)
    else:
        sqlite_dir = _sqlite_data_dir(app_root)
        if sqlite_dir is not None:
            root = sqlite_dir
        elif app_root:
            root = Path(app_root)
        else:
            root = BASE_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_upload_folder(app_root: str) -> Path:
    folder = get_data_root(app_root) / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def get_pdf_folder(app_root: str) -> Path:
    folder = get_data_root(app_root) / "generated_pdfs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def verify_writable_directory(folder: Path) -> bool:
    """Return True if the directory exists and is writable (used by /health)."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False
