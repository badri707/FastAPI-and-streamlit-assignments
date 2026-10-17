# Future Skool adapter — plan and open questions (DEFERRED until owner approval)

Nothing here is implemented. No Skool endpoint, account, URL, cookie or login was accessed in this phase.

## Documentation status
The Skool help pages listed in the build spec (Zapier integration, platform policy, analytics definitions, points/levels) could **not**
be fetched from this build environment (network policy blocked `help.skool.com`, checked 2026-10-17). Their contents are therefore
**not** relied on here. They must be read during the authorized connection phase.

## Desired data (to verify against what Skool actually exposes for the owner's role and plan)
members (stable ID, join date, membership/tier, role, status), posts/comments/replies with stable IDs and timestamps, reactions,
course/lesson structure and completion, events and attendance, leaderboard points/levels, membership/billing (read-only, if permitted).

## Desired actions (each needs explicit owner authorization and verification)
publish a reply in a thread, send a member message, (consequential) remove/ban — only if a supported interface exists.

## Approach for the connection phase
1. Ask the owner for community URL, actual role, group plan and permitted connection method; secrets entered only via secure local
   setup or the provider's own login, never in chat.
2. Record which operations are supported by documented interfaces (e.g. Zapier triggers/actions) with evidence; mark everything else
   unsupported (`UnsupportedOperation`) rather than inventing endpoints.
3. If an essential operation lacks a supported interface, assess browser automation only within authorized access and platform rules
   (no CAPTCHA/paywall/rate-limit bypass), with a dedicated protected profile, conservative rates and session-expiry handling.
4. Use a separate live database; carry over no synthetic identities, jobs, approvals or simulated messages; outward actions disabled
   at first; validate a small read, reconcile with the source, then one specifically authorized write and verify it.
5. Re-evaluate idempotency: the simulator honours idempotency keys; a real platform may not. Reconciliation would then match by
   author + body signature in the thread (already implemented in `_verify`), and unknown outcomes would be held for review.
6. Report unavailable fields honestly (e.g. exact time spent is very likely unavailable).
