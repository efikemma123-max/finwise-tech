import os
from urllib.parse import urlparse


_PRODUCTION_ENVIRONMENTS = {"prod", "production", "live"}


def env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


def deployment_environment() -> str:
    for key in ("FINWISE_ENV", "APP_ENV", "ENVIRONMENT"):
        value = str(os.getenv(key, "")).strip().lower()
        if value:
            return value
    return "development"


def is_production_environment() -> bool:
    return env_flag("FINWISE_PRODUCTION_MODE", False) or deployment_environment() in _PRODUCTION_ENVIRONMENTS


def allow_insecure_oauth_transport() -> bool:
    return env_flag(
        "FINWISE_ALLOW_INSECURE_OAUTH_TRANSPORT",
        default=not is_production_environment(),
    )


def broker_secret_persistence_enabled() -> bool:
    return env_flag(
        "FINWISE_PERSIST_BROKER_SECRETS",
        default=not is_production_environment(),
    )


def resolve_redirect_uri(explicit_uri: str, default_port: int = 8501, service_name: str = "OAuth") -> str:
    explicit = str(explicit_uri or "").strip()
    localhost_uri = f"http://localhost:{default_port}"
    production = is_production_environment()

    if not explicit:
        if production:
            raise RuntimeError(
                f"{service_name} redirect URI is missing. Configure a public HTTPS callback URL before deploying."
            )
        return localhost_uri

    parsed = urlparse(explicit)
    if not parsed.scheme or not parsed.netloc:
        if production:
            raise RuntimeError(
                f"{service_name} redirect URI is invalid. Configure a public HTTPS callback URL before deploying."
            )
        return localhost_uri

    hostname = (parsed.hostname or "").lower()
    if hostname in {"localhost", "127.0.0.1"}:
        if production:
            raise RuntimeError(
                f"{service_name} redirect URI cannot use localhost in production. Configure a public HTTPS callback URL."
            )
        port = parsed.port or default_port
        scheme = parsed.scheme or "http"
        return f"{scheme}://{hostname}:{port}{parsed.path or ''}"

    if parsed.scheme.lower() != "https":
        raise RuntimeError(f"{service_name} redirect URI must use HTTPS.")

    return explicit
