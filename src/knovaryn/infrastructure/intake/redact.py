"""Safe locator redaction (spec §8 / WP G3).

Turns a source locator (usually a URL) into a redacted, non-secret form for
persistence on a :class:`SourceDocument`. Strips credentials, query strings and
fragments so a stored locator never leaks auth material or tracking params.
"""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse


def redact_locator(locator: str) -> str:
    """Return a redacted form of ``locator`` safe to persist.

    Non-URL locators (local paths, plain names) are returned as the default
    ``"-"`` when empty, otherwise passed through unchanged. For URLs, the
    scheme + host + port + path are kept and credentials / query / fragment are
    dropped.
    """
    if not locator:
        return "-"
    if "://" not in locator:
        return locator
    parsed = urlparse(locator)
    if not parsed.scheme or not parsed.netloc:
        return locator
    # strip any user:pass credentials embedded in the host, then rebuild with
    # credentials / params / query / fragment removed (typeshed disallows the
    # ``_replace`` kwargs, so we reconstruct from a tuple).
    host = parsed.netloc
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    redacted = (parsed.scheme, host, parsed.path, "", "", "")
    return urlunparse(redacted)
