"""Intake security guards (spec §8.3, §8.4) — local-path and URL/SSRF policy.

Owns the branch coverage for path-traversal rejection and the URL
ingestion/SSRF guard. Network fetch (safe_fetch) is unit-tested only for the
validation pre-checks; redirect/HTTP behavior requires the opt-in httpx mocks.
"""

from __future__ import annotations

import ipaddress
import socket
from pathlib import Path

import pytest

from knovaryn.domain.errors import PathTraversalError, SSRFError
from knovaryn.infrastructure.intake.paths import (
    is_within,
    resolve_allowed_roots,
    validate_local_path,
)
from knovaryn.infrastructure.intake.url import (
    URLPolicy,
    _is_private,
    _validate_url,
    resolve_all,
)


# ---------------------------------------------------------------------------
# §8.3 — local path policy
# ---------------------------------------------------------------------------


def test_resolve_allowed_roots_creates_and_returns(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    resolved = resolve_allowed_roots([str(root)])
    assert resolved[0] == root.resolve()
    assert root.exists()


def test_is_within_true_for_child(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    child = root / "a" / "b.md"
    assert is_within(child, [root.resolve()]) is True


def test_is_within_false_outside(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    other = tmp_path / "other" / "b.md"
    assert is_within(other, [root.resolve()]) is False


def test_validate_local_path_ok_within_root(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "data"
    root.mkdir()
    target = root / "hello.md"
    target.write_text("x")
    monkeypatch.chdir(tmp_path)
    result = validate_local_path(str(target), allowed_roots=[str(root)])
    assert result == target.resolve()


def test_validate_local_path_relative_to_cwd(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "data"
    root.mkdir()
    (root / "ok.txt").write_text("x")
    monkeypatch.chdir(root)
    result = validate_local_path("ok.txt", allowed_roots=[str(root)])
    assert result.name == "ok.txt"


def test_validate_local_path_rejects_shell_syntax(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    with pytest.raises(PathTraversalError):
        validate_local_path("a; b", allowed_roots=[str(root)])


def test_validate_local_path_rejects_dollar(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    with pytest.raises(PathTraversalError):
        validate_local_path("$HOME/secret", allowed_roots=[str(root)])


def test_validate_local_path_rejects_escape(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "data"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.txt").write_text("x")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(PathTraversalError):
        validate_local_path("../outside/x.txt", allowed_roots=[str(root)])


def test_validate_local_path_rejects_missing(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    with pytest.raises(PathTraversalError):
        validate_local_path(str(root / "nope.md"), allowed_roots=[str(root)])


def test_validate_local_path_rejects_symlink_component(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(root)
    except OSError:
        pytest.skip("symlinks not supported")
    with pytest.raises(PathTraversalError):
        validate_local_path(str(link / "x.md"), allowed_roots=[str(root)], follow_symlinks=False)


# ---------------------------------------------------------------------------
# §8.4 — URL / SSRF guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ip, expected",
    [
        ("127.0.0.1", True),
        ("10.0.0.1", True),
        ("192.168.1.1", True),
        ("100.64.0.1", True),
        ("169.254.169.254", True),
        ("8.8.8.8", False),
        ("1.1.1.1", False),
    ],
)
def test_is_private(ip, expected) -> None:
    assert _is_private(ipaddress.ip_address(ip)) is expected


def test_is_private_ipv6_loopback() -> None:
    assert _is_private(ipaddress.ip_address("::1")) is True


def test_validate_url_disabled_raises() -> None:
    with pytest.raises(SSRFError):
        _validate_url("https://example.com/a", URLPolicy(enabled=False))


def test_validate_url_http_blocked_by_default() -> None:
    with pytest.raises(SSRFError):
        _validate_url("http://example.com/a", URLPolicy(enabled=True))


def test_validate_url_missing_host_raises() -> None:
    with pytest.raises(SSRFError):
        _validate_url("https:///path", URLPolicy(enabled=True))


def test_validate_url_metadata_host_blocked(monkeypatch) -> None:
    monkeypatch.setattr("knovaryn.infrastructure.intake.url.resolve_all", lambda h: [])
    with pytest.raises(SSRFError):
        _validate_url(
            "https://metadata.google.internal/x", URLPolicy(enabled=True, block_metadata=True)
        )


def test_validate_url_private_resolution_blocked(monkeypatch) -> None:
    monkeypatch.setattr(
        "knovaryn.infrastructure.intake.url.resolve_all", lambda h: [ipaddress.ip_address("10.0.0.5")]
    )
    with pytest.raises(SSRFError):
        _validate_url("https://example.com/x", URLPolicy(enabled=True))


def test_validate_url_allowlist_rejects_other_host(monkeypatch) -> None:
    monkeypatch.setattr("knovaryn.infrastructure.intake.url.resolve_all", lambda h: [ipaddress.ip_address("8.8.8.8")])
    policy = URLPolicy(enabled=True, allowlist=["trusted.example"])
    with pytest.raises(SSRFError):
        _validate_url("https://evil.example/x", policy)


def test_validate_url_allowlist_exact_match_ok(monkeypatch) -> None:
    monkeypatch.setattr(
        "knovaryn.infrastructure.intake.url.resolve_all", lambda h: [ipaddress.ip_address("8.8.8.8")]
    )
    policy = URLPolicy(enabled=True, allowlist=["example.com"])
    url = _validate_url("https://example.com/x", policy)
    assert str(url).startswith("https://example.com")


def test_validate_url_credentials_rejected(monkeypatch) -> None:
    monkeypatch.setattr("knovaryn.infrastructure.intake.url.resolve_all", lambda h: [ipaddress.ip_address("8.8.8.8")])
    with pytest.raises(SSRFError):
        _validate_url("https://user:pass@example.com/x", URLPolicy(enabled=True))


def test_validate_url_http_allowed_when_configured(monkeypatch) -> None:
    monkeypatch.setattr("knovaryn.infrastructure.intake.url.resolve_all", lambda h: [ipaddress.ip_address("8.8.8.8")])
    url = _validate_url("http://example.com/x", URLPolicy(enabled=True, allow_http=True))
    assert str(url).startswith("http://example.com")


def test_resolve_all_valid(monkeypatch) -> None:
    def fake(*a, **k):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    addrs = resolve_all("example.com")
    assert any(str(a) == "8.8.8.8" for a in addrs)


def test_resolve_all_dns_failure(monkeypatch) -> None:
    def fail(*a, **k):
        raise socket.gaierror("fail")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    from knovaryn.domain.errors import IntakeError

    with pytest.raises(IntakeError):
        resolve_all("nonexistent.invalid")


def test_resolve_all_skips_bad_entries(monkeypatch) -> None:
    def fake(*a, **k):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("not-an-ip", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    addrs = resolve_all("example.com")
    assert len(addrs) == 1
    assert str(addrs[0]) == "8.8.8.8"
