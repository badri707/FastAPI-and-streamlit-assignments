"""Application settings. RUN_MODE=evaluation is the default and is enforced in the backend."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    run_mode: Literal["evaluation", "live"] = "evaluation"
    # Live connection requires BOTH run_mode=live and this explicit flag, and is not implemented
    # in this phase. Evaluation mode ignores any Skool credentials present on the machine.
    live_connection_authorized: bool = False

    data_dir: Path = PROJECT_ROOT / "data"
    host: str = "127.0.0.1"
    port: int = 8787
    display_tz: str = "Asia/Kolkata"

    # Clock: "wall" (real time + optional offset) or "frozen" (tests).
    clock_mode: Literal["wall", "frozen"] = "wall"

    ai_provider: Literal["ollama", "none"] = "ollama"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "se-qwen3-4b"
    # Optional local embedding model for hybrid retrieval; keyword-only (FTS5) retrieval is used if it is unavailable.
    ollama_embed_model: str = "nomic-embed-text"
    ai_timeout_s: float = 180.0
    ai_num_ctx: int = 4096
    ai_max_retries: int = 1
    ai_breaker_threshold: int = 3
    ai_breaker_cooldown_s: float = 60.0

    session_ttl_hours: int = 12
    backup_dir: Path | None = None
    external_ssd_path: Path | None = None
    min_free_disk_mb: int = 500

    worker_poll_s: float = 1.0
    worker_lease_s: int = 120
    sync_interval_s: int = 60
    log_max_bytes: int = 2_000_000

    allowed_hosts: list[str] = Field(default_factory=lambda: ["127.0.0.1", "localhost"])

    @property
    def app_db_path(self) -> Path:
        return self.data_dir / ("app.db" if self.run_mode == "evaluation" else "live-app.db")

    @property
    def sim_db_path(self) -> Path:
        return self.data_dir / "simulator.db"

    @property
    def effective_backup_dir(self) -> Path:
        return self.backup_dir or (self.data_dir / "backups")


@lru_cache
def get_settings() -> Settings:
    return Settings()
