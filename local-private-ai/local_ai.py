"""Shared settings and a privacy guard for the local-AI scripts.

Everything here is about one promise: requests go to a model on THIS machine.
"""

import os
from urllib.parse import urlparse

# Where Ollama listens. It binds to 127.0.0.1:11434 by default.
BASE_URL = os.environ.get("LOCAL_AI_URL", "http://localhost:11434").rstrip("/")

# Chat model and embedding model. Override with env vars, e.g. LOCAL_MODEL=gemma4:e4b
CHAT_MODEL = os.environ.get("LOCAL_MODEL", "qwen3.5:9b")
EMBED_MODEL = os.environ.get("LOCAL_EMBED_MODEL", "nomic-embed-text")

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class NotLocalError(RuntimeError):
    """Raised when a request would leave this machine."""


def check_local(base_url: str = BASE_URL, *models: str) -> None:
    """Refuse to run unless the endpoint is on this machine and no model is a cloud model.

    Ollama can also run cloud models (names like 'gemma4:cloud' or tags ending
    in '-cloud') when you are signed in. Those prompts go to ollama.com, so we
    block them here. Set ALLOW_REMOTE=1 only if you really mean it.
    """
    if os.environ.get("ALLOW_REMOTE") == "1":
        return
    host = urlparse(base_url).hostname
    if host not in LOCAL_HOSTS:
        raise NotLocalError(
            f"{base_url} is not on this machine. Set ALLOW_REMOTE=1 to override."
        )
    for m in models:
        tag = m.split(":", 1)[1] if ":" in m else ""
        if "cloud" in tag:
            raise NotLocalError(
                f"'{m}' is an Ollama cloud model; prompts would leave this machine."
            )
