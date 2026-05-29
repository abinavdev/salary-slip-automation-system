"""
Gunicorn configuration optimized for Render free tier.

Recommended start command:
  gunicorn -c gunicorn.conf.py app:app
"""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"

workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "2"))

# One PDF + SendGrid call per request; keep under Render's kill window.
timeout = min(int(os.environ.get("GUNICORN_TIMEOUT", "120")), 180)
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = 5

max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "150"))
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", "25"))

preload_app = workers == 1

loglevel = os.environ.get("LOG_LEVEL", "info").lower()
accesslog = "-"
errorlog = "-"
capture_output = True


def on_starting(server):
    server.log.info(
        "Gunicorn starting | workers=%s class=%s threads=%s timeout=%ss",
        workers,
        worker_class,
        threads,
        timeout,
    )


def when_ready(server):
    server.log.info("Gunicorn ready | bind=%s", bind)
