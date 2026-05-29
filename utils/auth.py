"""Admin authentication helpers."""

import os
from functools import wraps

from flask import flash, redirect, request, session, url_for

PUBLIC_ENDPOINTS = frozenset({"login", "logout", "health", "static"})


def verify_admin_credentials(username: str, password: str) -> bool:
    """Validate admin username/password from environment variables."""
    expected_username = os.getenv("ADMIN_USERNAME", "admin").strip()
    expected_password = os.getenv("ADMIN_PASSWORD", "").strip()
    if not expected_password:
        return False
    return username.strip() == expected_username and password == expected_password


def login_required(view):
    """Decorator: require admin session before accessing a view."""

    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("admin_logged_in"):
            flash("Please log in to access the admin portal.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def register_auth_middleware(app):
    """Redirect unauthenticated users to login for all non-public routes."""

    @app.before_request
    def require_admin_login():
        if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
            return None
        if not session.get("admin_logged_in"):
            flash("Please log in to access the admin portal.", "warning")
            return redirect(url_for("login"))
        return None
