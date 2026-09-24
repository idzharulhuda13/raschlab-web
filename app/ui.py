"""Shared presentation helpers for the RaschLab templates.

Every helper is registered as a Jinja global on the template environments built in
app.main and app.auth, so a template can call it directly (for example
``{{ initials_for(user.email) }}``).
"""

import re

_PART_SEPARATORS = re.compile(r"[.\-_]")
_LETTER = re.compile(r"[A-Za-z]")


def initials_for(account: str | None) -> str:
    """Up to two upper-case initials for an account string (usually an e-mail).

    The local part is split on dot, dash and underscore and the first letter of the
    first two parts wins. When the local part has no letter, the first letter of the
    domain is used instead; a string with no letter at all yields an empty string,
    and the templates then render no disc.
    """
    text = account.strip() if isinstance(account, str) else ""
    if not text:
        return ""
    local, _, domain = text.partition("@")
    parts = [part for part in _PART_SEPARATORS.split(local) if part]
    letters = ""
    if len(parts) >= 2:
        letters = _letter_for(parts[0]) + _letter_for(parts[1])
    elif parts:
        letters = "".join(_LETTER.findall(parts[0])[:2])
    if not letters:
        letters = _letter_for(domain)
    return letters[:2].upper()


def _letter_for(text: str) -> str:
    """The first letter of text, or an empty string when it holds no letter."""
    match = _LETTER.search(text)
    return match.group(0) if match else ""
