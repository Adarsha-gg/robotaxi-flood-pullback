"""Shared Gemini API client and environment loader for Lane G."""
from pathlib import Path
from dotenv import load_dotenv
from google import genai

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = Path("/Users/adarsha/new proj/.env")


def ensure_env() -> None:
    """Load GEMINI_API_KEY explicitly (bare load_dotenv() fails on Python 3.15)."""
    if ENV_PATH.exists():
        load_dotenv(str(ENV_PATH))
    else:
        local_env = REPO_ROOT / ".env"
        if local_env.exists():
            load_dotenv(str(local_env))


def get_client() -> genai.Client:
    ensure_env()
    return genai.Client()


def get_beta_client() -> genai.Client:
    ensure_env()
    return genai.Client(http_options={"api_version": "v1beta"})
