# Public sources

| URL | Purpose | Retrieval attempts | Result | Accessible fields | Pagination | Limits |
|---|---|---|---|---|---|---|
| https://www.skool.com/ai-automation-society | External reference community (not Social Eagle, not administered by the owner) | 2026-10-20 16:09Z (curl), 16:42Z (app connector) from the cloud build sandbox | **Blocked by the sandbox egress proxy (HTTP 403 at CONNECT)**, so no Skool response was received. Recorded as a failed sync run. | Unknown (not observed) | Connector reads ≤3 pages (only the first page implemented) | ≥5 s between requests, 15 s timeout, robots.txt honoured, logged-out only |
| https://www.skool.com/robots.txt | Robots directives | same | blocked | — | — | — |
| help.skool.com articles 31, 103, 23, 144, 166, 56, 176, 179, 216 | Platform definitions | 2026-10-20 (WebFetch and curl) | **blocked / DNS failure** in the sandbox | — | — | Definitions currently taken from the spec author's 2026-10-20 review |

No snapshot of a real Skool page exists in this repository. The file `tests/fixtures/public_group_structure_SYNTHETIC.html` is hand-written and labelled synthetic.

**To verify on the owner's Mac:** run `uv run python -m app.cli public-sync`. A successful run stores the page under `data/public_cache/` (not committed). Then record here the date, the fields actually visible, whether posts were excerpts, and how many posts appeared on the first page. Do not mass-harvest profiles.
