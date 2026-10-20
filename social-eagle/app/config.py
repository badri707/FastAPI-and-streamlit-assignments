"""Runtime configuration and the three operating modes.

public  – default; real logged-out Skool reads + offline drafts only.
test    – isolated synthetic workspace; no Skool network access at all.
private – disabled until the owner explicitly authorizes it later.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_TZ = ZoneInfo("Asia/Kolkata")
CALC_VERSION = "metrics-2026.10.20-1"
PARSER_VERSION = "skool-public-0.1.0"


class Mode(StrEnum):
    PUBLIC = "public"
    TEST = "test"
    PRIVATE = "private"


class PrivateModeDisabled(RuntimeError):
    """Raised whenever private (authenticated) mode is requested before authorization."""


class ExternalWriteDisabled(RuntimeError):
    """Raised for any attempted external write (post/reply/message/react) to Skool."""


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("SE_DATA_DIR", PROJECT_ROOT / "data")))
    host: str = os.environ.get("SE_HOST", "127.0.0.1")
    port: int = int(os.environ.get("SE_PORT", "8765"))
    report_hour_local: int = int(os.environ.get("SE_REPORT_HOUR", "9"))
    report_minute_local: int = int(os.environ.get("SE_REPORT_MINUTE", "0"))
    # Demonstration values only — not Social Eagle commitments.
    support_first_response_target_hours: float = float(os.environ.get("SE_SUPPORT_TARGET_HOURS", "24"))
    support_target_basis: str = os.environ.get("SE_SUPPORT_TARGET_BASIS", "calendar")  # calendar | working
    working_hours_start: int = 10
    working_hours_end: int = 19
    new_member_grace_days: int = int(os.environ.get("SE_GRACE_DAYS", "7"))
    catchup_max_days: int = int(os.environ.get("SE_CATCHUP_MAX_DAYS", "7"))
    outreach_quiet_days: int = 14
    public_min_request_interval_s: float = float(os.environ.get("SE_PUBLIC_MIN_INTERVAL", "5"))
    public_timeout_s: float = 15.0
    public_max_pages: int = 3
    private_mode_authorized: bool = False  # deliberately not configurable from env in this phase

    def db_path(self, mode: Mode) -> Path:
        if mode is Mode.PRIVATE:
            raise PrivateModeDisabled("Private mode is deferred until explicit owner authorization.")
        return self.data_dir / f"{mode.value}.db"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"


def get_settings() -> Settings:
    return Settings()
