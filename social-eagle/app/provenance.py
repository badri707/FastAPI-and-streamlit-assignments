from __future__ import annotations

import hashlib
import json
from typing import Any


def record_hash(obj: Any) -> str:
    """Stable SHA-256 over canonical JSON. Detects changes to stored evidence;
    it does not prove source authenticity."""
    data = json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
