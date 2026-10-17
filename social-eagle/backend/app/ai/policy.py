"""Deterministic answer policy (defence in depth around the model).

Community content (questions, comments, documents) is untrusted. Nothing in it can change policy, reveal
configuration, grant permissions or trigger admin tools. A claim to be an administrator is never authorization.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

POLICY_VERSION = "answer-policy-2026.10.1"

INJECTION_PATTERNS = [
    r"\bignore (all |any |the )?(previous|prior|above|earlier|your) (instructions|rules|prompts?)",
    r"\bdisregard (all |any |the |your )?(previous|prior|above|earlier)?\s*(instructions|rules|guidelines|what you were told)",
    r"\b(system|hidden|developer|initial) (prompt|instructions|message|configuration|config)\b",
    r"\breveal (your|the) (prompt|instructions|rules|configuration|config|secrets?)",
    r"\b(i am|i'm|im) (the |an |a )?(admin|administrator|owner|moderator|developer)\b",
    r"\b(act|behave) as (an? )?(admin|administrator|developer|system)",
    r"\b(developer|god|dan|jailbreak) mode\b",
    r"\b(list|give|show|send|export|dump) (me )?(all |every |each )?(the )?(members?'?s?|users?'?s?) ?(emails?|e-mail|phone|contact|addresses|data|details)",
    r"\b(every|all) members?'?s? (emails?|e-mail|phone|contact|addresses)",
    r"\bgrant (me )?(admin|moderator|access)\b",
    r"\b(api key|password|token|cookie)s?\b.*\b(show|give|reveal|send)\b",
    r"\b(show|give|reveal|send)\b.*\b(api key|password|credentials)\b",
]
STAFF_ONLY_PATTERNS = [
    r"\brefund", r"\bchargeback", r"\bbilling\b", r"\bcharged? (me )?(twice|again|wrong)", r"\bcancel (my )?(plan|subscription|membership)",
    r"\bpayment\b", r"\binvoice\b", r"\bban (him|her|them|this|that)\b", r"\bdelete (my )?account\b", r"\bupgrade (my )?(plan|tier)\b",
    r"\bdowngrade\b",
]
SUPPORT_PATTERNS = [
    r"\bcan'?t (access|log ?in|open|see|play)", r"\bcannot (access|log ?in|open|see|play)", r"\bnot (working|loading|playing)\b",
    r"\b(error|bug|broken|locked out)\b", r"\bpassword reset\b",
]
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(\+?\d[\d\s-]{8,}\d)(?!\d)")
SYSTEM_PROMPT_MARKERS = ["UNTRUSTED", "You are Eagle Assistant", "Rules you must follow"]


@dataclass
class PreCheck:
    blocked: bool = False
    route: str | None = None  # injection | staff_only | support
    reasons: list[str] = field(default_factory=list)


def _matches(patterns: list[str], text: str) -> list[str]:
    return [p for p in patterns if re.search(p, text, re.I)]


def precheck(question: str) -> PreCheck:
    q = question or ""
    inj = _matches(INJECTION_PATTERNS, q)
    if inj:
        return PreCheck(blocked=True, route="injection", reasons=["Possible prompt-injection or privilege-escalation request"])
    staff = _matches(STAFF_ONLY_PATTERNS, q)
    if staff:
        return PreCheck(blocked=True, route="staff_only", reasons=["Billing/refund/account/permission topics are staff-only"])
    sup = _matches(SUPPORT_PATTERNS, q)
    if sup:
        return PreCheck(blocked=False, route="support", reasons=["Looks like an access/technical problem needing staff follow-up"])
    return PreCheck()


def numbers_in(text: str) -> set[str]:
    out = set()
    for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text or ""):
        out.add(m.replace(",", "").rstrip(".").lstrip("0") or "0")
    return out


WORD_NUMBERS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
                "nine": "9", "ten": "10", "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50", "seventy": "70",
                "half": ".5", "quarter": ".25"}


def normalized_numbers(text: str) -> set[str]:
    nums = numbers_in(text)
    for w, n in WORD_NUMBERS.items():
        if re.search(rf"\b{w}\b", text or "", re.I):
            nums.add(n)
    return nums


def ungrounded_numbers(answer: str, sources: list[str], extra_allowed: set[str] | None = None) -> set[str]:
    allowed = set().union(*(normalized_numbers(s) for s in sources)) if sources else set()
    allowed |= extra_allowed or set()
    return {n for n in numbers_in(answer) if n not in allowed}


DATE_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def contains_pii(text: str) -> bool:
    if EMAIL_RE.search(text or ""):
        return True
    for m in PHONE_RE.finditer(text or ""):
        cand = m.group(1).strip()
        if DATE_LIKE.match(cand):  # ISO dates are not phone numbers
            continue
        if sum(ch.isdigit() for ch in cand) >= 10:
            return True
    return False


def leaks_system_prompt(text: str) -> bool:
    return any(m.lower() in (text or "").lower() for m in SYSTEM_PROMPT_MARKERS)


SAFE_REPLIES = {
    "injection": "I can't help with that request. Requests about permissions, private member data or how this assistant "
                 "is configured are handled by staff only. A team member has been notified.",
    "staff_only": "Billing, refunds, cancellations, plan changes and account permissions are handled only by our staff. "
                  "I've flagged your post so a team member can follow up with you directly.",
    "abstain": "I couldn't find a clear answer to this in the approved course material, so I won't guess. "
               "I've flagged it for the team to answer.",
}
