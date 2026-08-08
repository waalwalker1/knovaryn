"""Canonical identity enforcement (spec §3.5, exec rule).

The display name is ``Knovaryn``; package ``knovaryn``; MCP server id
``knovaryn_mcp``. The legacy ``OmniTrain`` / ``omnitrain`` / ``OMNITRAIN``
identifiers MUST be rejected as non-canonical.
"""

from __future__ import annotations


def test_legacy_identifiers_are_flagged() -> None:
    import knovaryn.identity as ident

    for spelling in ("OmniTrain", "omnitrain", "OMNITRAIN"):
        assert spelling in ident.LEGACY_IDENTIFIERS


def test_mcp_server_id_is_canonical() -> None:
    from knovaryn.interfaces.mcp.server import SERVER_ID

    assert SERVER_ID == "knovaryn_mcp"
    assert all(lg not in SERVER_ID for lg in ("OmniTrain", "omnitrain", "OMNITRAIN"))


def test_package_name_is_canonical() -> None:
    import importlib.metadata as md

    assert md.version("knovaryn")
    name = md.metadata("knovaryn").get("Name", "")
    assert name.lower() == "knovaryn"
    assert "omnitrain" not in name.lower()
