"""Data anonymization for sensitive content before Cloud API submission.

Scans decompiled code, sandbox reports, and hardcoded strings for
sensitive patterns (internal IPs, user paths, API keys, credentials)
and replaces them with stable placeholder tokens.  The mapping is
stored per-session and can be reversed for post-analysis reporting.

This module is the **replacement for Local LLM integration** (Gap #4):
instead of running a local model to avoid cloud exposure, we scrub
the data before sending it.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Configurable blocklists
# ---------------------------------------------------------------------------

#: Domain suffixes considered "internal" — traffic to these should never
#: appear in cloud-sent prompts.
DEFAULT_INTERNAL_DOMAIN_SUFFIXES: tuple[str, ...] = (
    ".corp",
    ".internal",
    ".lan",
    ".local",
    ".intra",
    ".home",
    ".localdomain",
    ".ad",
)

#: Common prefixes for API keys / tokens that must be redacted.
_API_KEY_PREFIXES = (
    "sk-",        # OpenAI / Stripe
    "AKIA",       # AWS Access Key
    "ghp_",       # GitHub PAT
    "glpat-",     # GitLab PAT
    "xoxb-",      # Slack Bot
    "xoxp-",      # Slack User
    "Bearer ",    # Generic bearer token header value
)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# RFC 1918 private IPv4
_RE_PRIVATE_IPV4 = re.compile(
    r"\b("
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|127\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r")\b"
)

# Windows user path: C:\Users\<name>\ or C:\Users\<name>
_RE_WIN_USER_PATH = re.compile(
    r"[A-Za-z]:\\Users\\([^\s\\\"']+)",
    re.IGNORECASE,
)

# Linux home path: /home/<name>/ or /home/<name>
_RE_LINUX_USER_PATH = re.compile(
    r"/home/([^\s/\"']+)",
)

# Credential assignments: password=, passwd=, pwd=
_RE_CREDENTIAL = re.compile(
    r"""(?:password|passwd|pwd|secret|token)\s*[=:]\s*["']?([^\s"']{4,})["']?""",
    re.IGNORECASE,
)

# Email-like patterns (may contain analyst/victim identifiers)
_RE_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class AnonymizationSummary:
    """Counts per category for telemetry."""
    internal_ips: int = 0
    user_paths: int = 0
    api_keys: int = 0
    credentials: int = 0
    internal_domains: int = 0
    emails: int = 0

    def total(self) -> int:
        return (
            self.internal_ips
            + self.user_paths
            + self.api_keys
            + self.credentials
            + self.internal_domains
            + self.emails
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "internal_ips": self.internal_ips,
            "user_paths": self.user_paths,
            "api_keys": self.api_keys,
            "credentials": self.credentials,
            "internal_domains": self.internal_domains,
            "emails": self.emails,
            "total": self.total(),
        }


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DataAnonymizer:
    """Scans text for sensitive patterns and replaces with stable tokens.

    Parameters
    ----------
    internal_domain_suffixes:
        Tuple of domain suffixes considered internal.  Defaults to
        ``DEFAULT_INTERNAL_DOMAIN_SUFFIXES``.
    extra_api_key_prefixes:
        Additional prefixes to treat as API keys on top of built-ins.
    """

    def __init__(
        self,
        internal_domain_suffixes: tuple[str, ...] | None = None,
        extra_api_key_prefixes: tuple[str, ...] = (),
    ) -> None:
        self._domain_suffixes = (
            internal_domain_suffixes
            if internal_domain_suffixes is not None
            else DEFAULT_INTERNAL_DOMAIN_SUFFIXES
        )
        self._api_key_prefixes = _API_KEY_PREFIXES + extra_api_key_prefixes

        # Build a regex for internal FQDNs from the suffix list.
        escaped = "|".join(re.escape(s) for s in self._domain_suffixes)
        self._re_internal_domain = re.compile(
            rf"\b([a-zA-Z0-9](?:[a-zA-Z0-9\-]{{0,61}}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]{{0,61}}[a-zA-Z0-9])?)*)({escaped})\b",
            re.IGNORECASE,
        )

        # Per-session mapping: original_value -> token
        self._token_map: dict[str, str] = {}
        self._reverse_map: dict[str, str] = {}
        self._counters: dict[str, int] = defaultdict(int)

    # -- Public API ----------------------------------------------------------

    def anonymize(self, text: str) -> tuple[str, dict[str, str]]:
        """Replace sensitive patterns in *text* with placeholder tokens.

        Returns ``(anonymized_text, token_map)`` where *token_map* maps
        ``placeholder -> original_value``.
        """
        result = text

        # Order matters — do longer/more-specific patterns first to avoid
        # partial replacements (e.g., a credential containing an IP).
        result = self._replace_credentials(result)
        result = self._replace_api_keys(result)
        result = self._replace_emails(result)
        result = self._replace_user_paths(result)
        result = self._replace_internal_domains(result)
        result = self._replace_private_ips(result)

        # Return a snapshot of the reverse map (token -> original)
        return result, dict(self._reverse_map)

    def restore(self, text: str, token_map: dict[str, str] | None = None) -> str:
        """Reverse anonymization using the provided or internal token map."""
        rmap = token_map if token_map is not None else self._reverse_map
        result = text
        # Replace longest tokens first to avoid partial matches
        for token in sorted(rmap, key=len, reverse=True):
            result = result.replace(token, rmap[token])
        return result

    def get_summary(self) -> AnonymizationSummary:
        """Return counts of each replaced category."""
        return AnonymizationSummary(
            internal_ips=self._counters["INTERNAL_IP"],
            user_paths=self._counters["USER_PATH"],
            api_keys=self._counters["API_KEY"],
            credentials=self._counters["CREDENTIAL"],
            internal_domains=self._counters["INTERNAL_DOMAIN"],
            emails=self._counters["EMAIL"],
        )

    def reset(self) -> None:
        """Clear all state for a new session."""
        self._token_map.clear()
        self._reverse_map.clear()
        self._counters.clear()

    # -- Internal replacement helpers ----------------------------------------

    def _get_or_create_token(self, category: str, original: str) -> str:
        """Return a stable token for *original*, creating one if first seen."""
        if original in self._token_map:
            return self._token_map[original]

        self._counters[category] += 1
        index = self._counters[category]
        token = f"[{category}_{index}]"

        self._token_map[original] = token
        self._reverse_map[token] = original
        return token

    def _replace_private_ips(self, text: str) -> str:
        def _replacer(match: re.Match) -> str:
            return self._get_or_create_token("INTERNAL_IP", match.group(0))
        return _RE_PRIVATE_IPV4.sub(_replacer, text)

    def _replace_user_paths(self, text: str) -> str:
        def _win_replacer(match: re.Match) -> str:
            username = match.group(1)
            token = self._get_or_create_token("USER_PATH", username)
            # Replace just the username part, keep the rest of the path structure
            return match.group(0).replace(username, token, 1)
        text = _RE_WIN_USER_PATH.sub(_win_replacer, text)

        def _linux_replacer(match: re.Match) -> str:
            username = match.group(1)
            token = self._get_or_create_token("USER_PATH", username)
            return match.group(0).replace(username, token, 1)
        text = _RE_LINUX_USER_PATH.sub(_linux_replacer, text)

        return text

    def _replace_internal_domains(self, text: str) -> str:
        def _replacer(match: re.Match) -> str:
            full_domain = match.group(0)
            return self._get_or_create_token("INTERNAL_DOMAIN", full_domain)
        return self._re_internal_domain.sub(_replacer, text)

    def _replace_api_keys(self, text: str) -> str:
        for prefix in self._api_key_prefixes:
            # Find each occurrence of prefix followed by key-like characters
            pattern = re.compile(
                re.escape(prefix) + r"[A-Za-z0-9_\-]{8,}",
            )
            def _replacer(match: re.Match) -> str:
                return self._get_or_create_token("API_KEY", match.group(0))
            text = pattern.sub(_replacer, text)
        return text

    def _replace_credentials(self, text: str) -> str:
        def _replacer(match: re.Match) -> str:
            value = match.group(1)
            token = self._get_or_create_token("CREDENTIAL", value)
            return match.group(0).replace(value, token, 1)
        return _RE_CREDENTIAL.sub(_replacer, text)

    def _replace_emails(self, text: str) -> str:
        def _replacer(match: re.Match) -> str:
            return self._get_or_create_token("EMAIL", match.group(0))
        return _RE_EMAIL.sub(_replacer, text)
