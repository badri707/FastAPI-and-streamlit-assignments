"""Logged-out public Skool read connector.

Safety properties (each covered by tests/test_connectors.py):
* Only https URLs on an explicit host allowlist; every redirect hop is re-validated.
* No cookies, no Authorization header, no credentials — even if SKOOL_* env vars exist.
* robots.txt is honoured; a minimum interval between requests; bounded retries with
  backoff on 429/5xx; timeouts; at most ``public_max_pages`` pages per sync.
* Login walls, denials and unparseable pages become a *failed* sync with a reason —
  never an empty community.
* There is no write method that does anything: posting/replying/reacting raises.

STATUS: the parser targets the Next.js ``__NEXT_DATA__`` JSON that Skool public pages
are believed to embed. This could NOT be verified from the build environment
(www.skool.com was blocked by the sandbox network policy on 2026-10-20). The parser
is therefore "implemented, not verified against live pages"; see docs/CAPABILITIES.md.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from app.config import PARSER_VERSION, ExternalWriteDisabled, Settings
from app.timeutil import iso, parse_ts

ALLOWED_HOSTS = frozenset({"www.skool.com", "skool.com"})
USER_AGENT = "SocialEagleCommunityManager/0.1 (logged-out public read; contact: owner via local install)"
_SLUG = re.compile(r"^/[a-z0-9][a-z0-9\-]{0,99}(/[A-Za-z0-9\-_/]*)?$")


class UnsafeURL(ValueError):
    pass


class AccessDenied(RuntimeError):
    pass


class ParseFailed(RuntimeError):
    pass


def validate_url(url: str) -> str:
    u = urlparse(url)
    if u.scheme != "https":
        raise UnsafeURL(f"only https is allowed: {url}")
    if u.hostname not in ALLOWED_HOSTS or u.port not in (None, 443):
        raise UnsafeURL(f"host not in allowlist: {u.hostname}")
    if u.username or u.password:
        raise UnsafeURL("credentials in URL are not allowed")
    if not _SLUG.match(u.path or "/x"):
        raise UnsafeURL(f"unexpected path: {u.path}")
    if re.search(r"/(login|signup|settings|chat|api)(/|$)", u.path):
        raise UnsafeURL(f"path is not a public read target: {u.path}")
    return url


@dataclass(frozen=True)
class PublicSource:
    slug: str
    url: str
    label: str
    note: str = "External reference community — not Social Eagle and not administered by the owner."


DEFAULT_SOURCES = [PublicSource("ai-automation-society", "https://www.skool.com/ai-automation-society",
                                "AI Automation Society (external reference)")]


class PublicFetcher:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None, sleep=time.sleep):
        self.settings = settings
        self.cache_dir = settings.data_dir / "public_cache"
        self._transport = transport
        self._sleep = sleep
        self._last_request = 0.0
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self.request_log: list[str] = []

    def _client(self) -> httpx.Client:
        # Fresh client per request: no cookie persistence, no auth, no env proxies credentials leakage.
        return httpx.Client(transport=self._transport, follow_redirects=False, timeout=self.settings.public_timeout_s,
                            headers={"User-Agent": USER_AGENT, "Accept": "text/html"}, cookies=None)

    def _throttle(self) -> None:
        wait = self.settings.public_min_request_interval_s - (time.monotonic() - self._last_request)
        if wait > 0:
            self._sleep(wait)
        self._last_request = time.monotonic()

    def _raw_get(self, url: str) -> httpx.Response:
        u = urlparse(url)
        if u.path == "/robots.txt":
            if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS:
                raise UnsafeURL(url)
        else:
            validate_url(url)
        self._throttle()
        self.request_log.append(url)
        with self._client() as c:
            req = c.build_request("GET", url)
            assert "authorization" not in {k.lower() for k in req.headers}
            assert "cookie" not in {k.lower() for k in req.headers}
            return c.send(req)

    def robots_allows(self, url: str) -> bool:
        host = urlparse(url).hostname or ""
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            r = self._raw_get(f"https://{host}/robots.txt")
            if r.status_code >= 400 and r.status_code != 404:
                raise AccessDenied(f"robots.txt unavailable (HTTP {r.status_code}); not fetching")
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            self._robots[host] = rp
        return self._robots[host].can_fetch(USER_AGENT, url)

    def get(self, url: str) -> tuple[str, str]:
        """Return (final_url, html). Follows at most 3 validated redirects."""
        validate_url(url)
        if not self.robots_allows(url):
            raise AccessDenied(f"robots.txt disallows {url}")
        current = url
        for _hop in range(4):
            for attempt in range(3):
                r = self._raw_get(current)
                if r.status_code in (429, 502, 503, 504) and attempt < 2:
                    retry_after = r.headers.get("Retry-After", "")
                    self._sleep(min(float(retry_after) if retry_after.isdigit() else 10 * 2 ** attempt, 120))
                    continue
                break
            if r.status_code in (301, 302, 303, 307, 308):
                nxt = urljoin(current, r.headers.get("Location", ""))
                if "/login" in urlparse(nxt).path or "/signup" in urlparse(nxt).path:
                    raise AccessDenied(f"redirected to a login wall: {nxt}")
                try:
                    current = validate_url(nxt)
                except UnsafeURL as exc:
                    raise AccessDenied(f"redirect rejected: {exc}") from exc
                continue
            if r.status_code in (401, 403):
                raise AccessDenied(f"HTTP {r.status_code}: access denied for logged-out reads")
            if r.status_code != 200:
                raise AccessDenied(f"HTTP {r.status_code}")
            self._cache(current, r.text)
            return current, r.text
        raise AccessDenied("too many redirects")

    def _cache(self, url: str, body: str) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(url.encode()).hexdigest()[:24]
        (self.cache_dir / f"{key}.html").write_text(body, encoding="utf-8")
        (self.cache_dir / f"{key}.json").write_text(json.dumps({"url": url, "fetched_at": time.time()}), encoding="utf-8")


# ---------------------------------------------------------------- parsing

_NEXT = re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def _walk(obj, pred):
    if isinstance(obj, dict):
        if pred(obj):
            yield obj
        for v in obj.values():
            yield from _walk(v, pred)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, pred)


def _display(n) -> str | None:
    if n is None:
        return None
    if isinstance(n, (int, float)):
        return str(int(n))
    return str(n)


def parse_group_page(html: str, url: str) -> dict:
    """Extract community identity, displayed totals and visible feed posts.

    Returns {"community": {...}, "posts": [...], "authors": {...}, "warnings": [...]}.
    Raises AccessDenied for login walls and ParseFailed for unrecognised structure.
    """
    m = _NEXT.search(html)
    if not m:
        if re.search(r"log\s*in", html, re.I) and not re.search(r"postTrees|\"posts\"", html):
            raise AccessDenied("page shows a login prompt and no public data")
        raise ParseFailed("no __NEXT_DATA__ payload found (page structure changed or not a group page)")
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise ParseFailed(f"__NEXT_DATA__ is not valid JSON: {exc}") from exc
    props = data.get("props", {}).get("pageProps", {})
    warnings = []
    group = props.get("currentGroup") or props.get("group")
    if not isinstance(group, dict):
        raise ParseFailed("no group object in pageProps")
    gmeta = group.get("metadata", {}) if isinstance(group.get("metadata"), dict) else {}
    community = {
        "source_group_id": group.get("id"), "slug": group.get("name") or urlparse(url).path.strip("/").split("/")[0],
        "name": gmeta.get("displayName") or group.get("displayName") or group.get("name"),
        "displayed_member_total": _display(gmeta.get("totalMembers")),
        "displayed_online": _display(gmeta.get("totalOnlineMembers")),
    }
    trees = props.get("postTrees")
    if trees is None:
        trees = list(_walk(props, lambda d: "post" in d and isinstance(d["post"], dict) and "metadata" in d["post"]))
        if trees:
            warnings.append("postTrees key missing; used structural search")
    posts, authors = [], {}
    for t in trees or []:
        p = t.get("post", t)
        meta = p.get("metadata", {}) or {}
        user = p.get("user", {}) or {}
        uid = user.get("id") or p.get("userId")
        name = " ".join(x for x in (user.get("firstName"), user.get("lastName")) if x) or user.get("name")
        if uid:
            authors[uid] = name or f"(unnamed {uid})"
        created = p.get("createdAt")
        try:
            created_ts = parse_ts(created) if created else None
            precision = "second" if created_ts else "unknown"
        except ValueError:
            created_ts, precision = None, "unknown"
            warnings.append(f"unparseable createdAt {created!r}")
        slug = p.get("name")
        posts.append({
            "id": p.get("id"), "author": uid, "title": meta.get("title"),
            "body": (meta.get("content") or "")[:500], "is_excerpt": True,
            "created_at": iso(created_ts) if created_ts else None, "timestamp_precision": precision,
            "displayed_time": created, "like_count": meta.get("upvotes"), "comment_count": meta.get("comments"),
            "category": meta.get("labels") or p.get("labelId"),
            "url": f"https://www.skool.com/{community['slug']}/{slug}" if slug else url,
        })
    posts = [p for p in posts if p["id"]]
    if not posts:
        # A public feed with zero recognisable posts almost always means the page structure differs
        # from what this parser expects. Report it as a failure rather than a successful empty read.
        raise ParseFailed("group found but no posts recognised (page structure differs from parser "
                          "expectations; run `python -m app.cli public-inspect`)")
    return {"community": community, "posts": posts, "authors": authors, "warnings": warnings}


def to_bundle(parsed: dict, source: PublicSource, observed_at: datetime, pages: list[str]) -> dict:
    c = parsed["community"]
    return {
        "format": "social-eagle-import/1",
        "community": {"slug": f"public-{source.slug}", "name": c["name"] or source.label, "source_url": source.url,
                      "is_synthetic": False, "is_company_community": False, "expected_sources": None,
                      "displayed_member_total": c["displayed_member_total"], "displayed_online": c["displayed_online"]},
        "source_name": "public_feed", "source_ref": source.url, "method": "public_read",
        "observed_at": iso(observed_at), "parser_version": PARSER_VERSION,
        "coverage": {"status": "partial", "pages": pages,
                     "gaps": ["feed first page(s) only", "post bodies are excerpts", "comments/likes not enumerated"]},
        "members": [{"id": uid, "name": name} for uid, name in parsed["authors"].items()],
        "posts": [{k: v for k, v in p.items() if k != "category" or isinstance(v, str)} for p in parsed["posts"]],
    }


def failed_bundle(source: PublicSource, observed_at: datetime, error: str) -> dict:
    return {"format": "social-eagle-import/1",
            "community": {"slug": f"public-{source.slug}", "name": source.label, "source_url": source.url,
                          "is_synthetic": False, "is_company_community": False},
            "source_name": "public_feed", "source_ref": source.url, "method": "public_read",
            "observed_at": iso(observed_at), "status": "failed", "error": error, "parser_version": PARSER_VERSION,
            "failed_sources": [source.url]}


class PublicReadConnector:
    mode = "public"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None, sleep=time.sleep):
        self.fetcher = PublicFetcher(settings, transport, sleep)

    def fetch_bundle(self, source: PublicSource, now: datetime) -> dict:
        try:
            final_url, html = self.fetcher.get(source.url)
            parsed = parse_group_page(html, final_url)
        except (AccessDenied, ParseFailed, UnsafeURL, httpx.HTTPError) as exc:
            return failed_bundle(source, now, f"{type(exc).__name__}: {exc}")
        return to_bundle(parsed, source, now, [final_url])

    # ---- writes: permanently disabled in this phase
    def post(self, *a, **k):
        raise ExternalWriteDisabled("External Skool writes are disabled in public mode.")

    reply = react = message = join_group = post


def load_snapshot(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def structure_skeleton(obj, depth: int = 0, max_depth: int = 6, key: str = "") -> list[str]:
    """Describe JSON shape only (keys, types, lengths) — no values, so no member content is printed."""
    pad = "  " * depth
    if depth > max_depth:
        return [f"{pad}{key}…"]
    if isinstance(obj, dict):
        out = [f"{pad}{key}{{}} {len(obj)} keys"]
        for k, v in list(obj.items())[:40]:
            out += structure_skeleton(v, depth + 1, max_depth, f"{k}: ")
        return out
    if isinstance(obj, list):
        out = [f"{pad}{key}[] len={len(obj)}"]
        if obj:
            out += structure_skeleton(obj[0], depth + 1, max_depth, "[0]: ")
        return out
    return [f"{pad}{key}{type(obj).__name__}"]


def inspect_cached_page(cache_dir: Path) -> str:
    files = sorted(cache_dir.glob("*.html"), key=lambda p: p.stat().st_mtime)
    if not files:
        return "No cached public page. Run public-sync first."
    html = files[-1].read_text(encoding="utf-8")
    lines = [f"file: {files[-1].name}  size: {len(html)} chars"]
    m = _NEXT.search(html)
    if not m:
        lines.append("no __NEXT_DATA__ script found")
        scripts = re.findall(r"<script[^>]*>", html)[:30]
        lines.append(f"script tags ({len(scripts)} shown): " + " | ".join(s[:80] for s in scripts))
        return "\n".join(lines)
    data = json.loads(m.group(1))
    props = data.get("props", {}).get("pageProps", {})
    lines += structure_skeleton(props, max_depth=5, key="pageProps: ")
    return "\n".join(lines)
