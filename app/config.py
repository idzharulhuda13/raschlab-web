from dataclasses import dataclass
import os


@dataclass
class Settings:
    database_url: str | None
    port: int
    app_env: str
    gate_open: bool
    app_version: str
    resend_api_key: str | None
    resend_from: str
    app_base_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        database_url = os.getenv("DATABASE_URL") or None
        port_raw = os.getenv("PORT", "7860")
        try:
            port = int(port_raw)
        except ValueError:
            port = 7860
        app_env = os.getenv("APP_ENV", "prod")
        gate_val = os.getenv("GATE_OPEN")
        gate_open = gate_val.lower() == "true" if gate_val is not None else False
        app_version = os.getenv("APP_VERSION", "0.1.0")
        resend_api_key = os.getenv("RESEND_API_KEY") or None
        resend_from = os.getenv("RESEND_FROM", "RaschLab <onboarding@resend.dev>")
        app_base_url = os.getenv("APP_BASE_URL", "http://127.0.0.1:7860").rstrip("/")
        return cls(
            database_url=database_url,
            port=port,
            app_env=app_env,
            gate_open=gate_open,
            app_version=app_version,
            resend_api_key=resend_api_key,
            resend_from=resend_from,
            app_base_url=app_base_url,
        )


settings = Settings.from_env()
