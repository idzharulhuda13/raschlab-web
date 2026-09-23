from dataclasses import dataclass
import os


@dataclass
class Settings:
    database_url: str | None
    port: int
    app_env: str
    gate_open: bool
    app_version: str

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
        return cls(
            database_url=database_url,
            port=port,
            app_env=app_env,
            gate_open=gate_open,
            app_version=app_version,
        )


settings = Settings.from_env()
