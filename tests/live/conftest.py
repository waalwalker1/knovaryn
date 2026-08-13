"""D8 opt-in live-provider contract tests.

These are skipped by default. They exercise the live ``LiteLLMProvider``
against a real provider ONLY when the operator sets ``KNOVARYN_LIVE_PROVIDER=1``,
and they enforce hard spending caps so an accidental run cannot run up cost.
Set ``KNOVARYN_LIVE_PROVIDER_CAP_USD`` (default 0.10) to bound spend.
"""

from __future__ import annotations

import os

import pytest

from knovaryn.identity import ENV_PREFIX


def _live_enabled() -> bool:
    return os.environ.get(f"{ENV_PREFIX}LIVE_PROVIDER", "0") == "1"


def pytest_collection_modifyitems(config, items):
    # skip live-provider marked tests unless explicitly enabled
    if _live_enabled():
        return
    skip = pytest.mark.skip(reason=f"set {ENV_PREFIX}LIVE_PROVIDER=1 to run live-provider tests")
    for item in items:
        if "live_provider" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def spend_cap_usd() -> float:
    raw = os.environ.get(f"{ENV_PREFIX}LIVE_PROVIDER_CAP_USD", "0.10")
    try:
        cap = float(raw)
    except ValueError:
        cap = 0.10
    if cap <= 0 or cap > 5.0:
        raise pytest.fail("spend cap must be in (0, 5.0] USD")
    return cap
