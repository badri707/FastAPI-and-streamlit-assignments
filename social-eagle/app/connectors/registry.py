"""Connector selection per mode. The backend and worker both go through here."""
from __future__ import annotations

from app.config import ExternalWriteDisabled, Mode, PrivateModeDisabled, Settings


class LocalTestConnector:
    """Test mode: synthetic data only. Has no network client at all."""
    mode = "test"

    def fetch_bundle(self, *a, **k):
        raise RuntimeError("test mode never reads Skool; use the import adapter with synthetic bundles")

    def post(self, *a, **k):
        raise ExternalWriteDisabled("test mode actions are local only")

    reply = react = message = join_group = post


class PrivateConnector:
    """Placeholder boundary for future authenticated access. Disabled until explicit authorization."""

    def __init__(self, *a, **k):
        raise PrivateModeDisabled("Private Skool access is deferred until the owner authorizes it.")


def get_connector(mode: Mode, settings: Settings, **kw):
    if mode is Mode.PUBLIC:
        from app.connectors.public_skool import PublicReadConnector
        return PublicReadConnector(settings, **kw)
    if mode is Mode.TEST:
        return LocalTestConnector()
    return PrivateConnector()
