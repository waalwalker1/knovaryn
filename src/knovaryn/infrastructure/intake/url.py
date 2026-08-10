"""URL ingestion policy and SSRF protection (spec §8.4).

URL ingestion is disabled by default. When enabled: HTTPS required (unless a
narrow admin exception), DNS resolved and loopback/private/link-local/metadata
addresses blocked, every redirect revalidated, redirects/bytes/time capped,
no user-auth-header forwarding across origins, and the final URL + ETag +
Last-Modified + retrieval time + content hash recorded.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from ...domain.errors import IntakeError, SSRFError
from ...domain.hashing import ContentHasher


@dataclass
class URLPolicy:
    enabled: bool = False
    allow_http: bool = False
    max_redirects: int = 5
    max_bytes: int = 200 * 1024 * 1024
    timeout_s: float = 30.0
    allowlist: list[str] = field(default_factory=list)  # exact hostnames (enterprise)
    block_metadata: bool = True


def _is_private(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True
    if isinstance(ip, ipaddress.IPv4Address):
        # carrier-grade NAT 100.64.0.0/10 and metadata-style ranges
        if ip in ipaddress.ip_network("100.64.0.0/10"):
            return True
        if ip in ipaddress.ip_network("169.254.0.0/16"):
            return True
    return False


def resolve_all(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise IntakeError(f"DNS resolution failed for {host!r}") from exc
    addrs: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        try:
            addrs.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    return addrs


def _validate_url(url: str, policy: URLPolicy) -> httpx.URL:
    if not policy.enabled:
        raise SSRFError("URL ingestion is disabled")
    parsed = urlparse(url)
    if parsed.scheme != "https" and not (policy.allow_http and parsed.scheme == "http"):
        raise SSRFError("only HTTPS URLs are allowed")
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"unsupported scheme {parsed.scheme!r}")
    if not parsed.hostname:
        raise SSRFError("URL has no host")
    host = parsed.hostname

    if (
        policy.allowlist
        and host not in policy.allowlist
        and not any(host.endswith("." + h) for h in policy.allowlist if h.startswith("*."))
    ):
        raise SSRFError(f"host {host!r} not in allowlist")

    # block metadata/cloud-credential hosts early
    metadata_hostnames = ("metadata.google.internal", "169.254.169.254")
    if policy.block_metadata and host in metadata_hostnames:
        raise SSRFError("metadata service host blocked")

    # resolve and validate every address (DNS rebinding defense)
    for ip in resolve_all(host):
        if _is_private(ip):
            raise SSRFError(f"address {ip} resolves to a private/blocked network")

    # forbid credentials and fragments
    if parsed.username or parsed.password:
        raise SSRFError("URL credentials are not allowed")
    return httpx.URL(urlunparse(parsed))


async def safe_fetch(
    url: str, policy: URLPolicy, *, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    """Fetch a URL through validated redirects, returning metadata + content."""
    origin = _validate_url(url, policy)  # raises if disabled
    current = origin
    results: dict[str, Any] = {}

    async with httpx.AsyncClient(follow_redirects=False, timeout=policy.timeout_s) as client:
        for hop in range(policy.max_redirects + 1):
            hop_headers = dict(headers or {})
            if hop > 0:
                # never forward user authorization to another origin
                hop_headers.pop("Authorization", None)
                hop_headers.pop("Cookie", None)
            resp = await client.get(str(current), headers=hop_headers)
            if resp.is_redirect:
                next_url = resp.headers.get("location")
                if not next_url:
                    raise IntakeError("redirect without Location")
                next_url = str(httpx.URL(next_url).join(str(current)))
                # revalidate the redirect target completely
                current = _validate_url(next_url, policy)
                continue
            results["final_url"] = str(resp.url)
            results["status"] = resp.status_code
            results["etag"] = resp.headers.get("etag")
            results["last_modified"] = resp.headers.get("last-modified")
            if resp.status_code >= 400:
                raise IntakeError(f"HTTP {resp.status_code} from {str(resp.url)}")
            body = resp.content
            if len(body) > policy.max_bytes:
                raise IntakeError("response exceeds max_bytes")
            results["content_type"] = resp.headers.get("content-type", "")
            results["sha256"] = ContentHasher.sha256_bytes(body)
            results["bytes"] = body
            return results
    raise IntakeError("too many redirects")
