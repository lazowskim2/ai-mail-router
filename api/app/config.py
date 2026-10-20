import os


def _env(name: str, default: str, *legacy: str) -> str:
    """Read `name`, falling back to older variable names, then `default`."""
    for key in (name, *legacy):
        value = os.getenv(key)
        if value:
            return value
    return default


class Settings:
    """Runtime configuration, sourced from environment variables (see .env.example)."""

    # Any OpenAI-compatible endpoint (Ollama, OpenAI, Groq, OpenRouter, LM Studio...).
    # OLLAMA_* names are still accepted for backwards compatibility.
    llm_base_url: str = _env("LLM_BASE_URL", "http://ollama:11434/v1", "OLLAMA_BASE_URL")
    llm_model: str = _env("LLM_MODEL", "llama3.2", "OLLAMA_MODEL")
    llm_api_key: str = _env("LLM_API_KEY", "ollama")

    smtp_host: str = _env("SMTP_HOST", "mailhog")
    smtp_port: int = int(_env("SMTP_PORT", "1025"))
    smtp_from: str = _env("SMTP_FROM", "ai-router@example.com")
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_security: str = _env("SMTP_SECURITY", "none").lower()  # none | starttls | ssl

    # If set, every routing request must send the header `X-API-Key: <api_key>`.
    api_key: str = os.getenv("API_KEY", "")

    departments_file: str = _env("DEPARTMENTS_FILE", "/config/departments.yaml")


settings = Settings()
