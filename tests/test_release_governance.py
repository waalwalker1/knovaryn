"""Unit tests for the release-governance gate (scripts/release_governance.py).

The gate blocks PyPI publishing, so its matching logic is proven here against
stubbed GitHub API payloads rather than trusted live: matrix-leg expansion
(a job ``name:`` template never matches its interpolated check-run names),
latest-run-wins among duplicate runs, pagination past the default 30-item
page, and fail-closed behavior for failed / missing / running jobs.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "release_governance", _REPO_ROOT / "scripts" / "release_governance.py"
)
rg = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(rg)


def _run(name: str, conclusion: str, *, completed: str = "", run_id: int = 0) -> dict[str, Any]:
    return {
        "name": name,
        "status": "completed",
        "conclusion": conclusion,
        "completed_at": completed,
        "id": run_id,
    }


def _payload(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {"total_count": len(runs), "check_runs": runs}


def _ok_payload() -> dict[str, Any]:
    """Mirror the real f170afa shape: duplicate runs per leg, one stale
    `skipped` compose-e2e masked by a later `success`, matrix legs expanded."""
    legs: list[dict[str, Any]] = [
        _run("Lint, format & type (L4)", "success", completed="2026-08-21T13:19:32Z", run_id=1),
        _run("Coverage gate (L3)", "success", completed="2026-08-21T13:20:25Z", run_id=2),
        _run("Docs build & link check (L6)", "success", completed="2026-08-21T13:19:26Z", run_id=3),
        _run("Secret scan (gitleaks)", "success", completed="2026-08-21T13:19:20Z", run_id=4),
        _run("Dependency + static scan", "success", completed="2026-08-21T13:19:35Z", run_id=5),
        _run("Build mkdocs site", "success", completed="2026-08-21T13:19:29Z", run_id=6),
        _run("Deploy to GitHub Pages", "success", completed="2026-08-21T13:19:44Z", run_id=7),
        _run("Package CI (L7 — build + verify release candidate)", "success", run_id=8),
        _run("Release tag matches package version (L9)", "success", run_id=9),
        _run("Dependabot", "success", run_id=10),
        _run("Build container", "success", run_id=11),
        _run("SBOM (cycloneDX)", "success", run_id=12),
    ]
    for py in ("3.11", "3.12", "3.13"):
        legs.append(_run(f"Tests (offline) — py{py}", "success", run_id=len(legs)))
    for tier in ("unit", "integration", "mcp", "chaos", "release", "rest"):
        legs.append(_run(f"Tier {tier}", "success", run_id=len(legs)))
    for os_name in ("windows-latest", "macos-latest"):
        legs.append(_run(f"Smoke — {os_name} (L1)", "success", run_id=len(legs)))
    # compose-e2e: stale skipped run from the push, fresh success from dispatch
    legs.append(
        _run(
            "Compose E2E (deployed topology)",
            "skipped",
            completed="2026-08-21T13:19:10Z",
            run_id=100,
        )
    )
    legs.append(
        _run(
            "Compose E2E (deployed topology)",
            "success",
            completed="2026-08-21T13:25:43Z",
            run_id=200,
        )
    )
    # duplicates of everything (push run + dispatch run) with older
    # timestamps and lower ids — latest-wins must ignore them all
    older = [
        _run(str(leg["name"]), "success", completed="2026-08-21T13:00:00Z", run_id=leg["id"] - 1000)
        for leg in legs
    ]
    return _payload(legs + older)


def test_matrix_legs_expanded_from_real_ci_yml() -> None:
    """Exact-name sets must contain the interpolated leg names GitHub uses."""
    test_names, _ = rg._job_check_names(
        "test",
        {
            "name": "Tests (offline) — py${{ matrix.python }}",
            "strategy": {"matrix": {"python": ["3.11", "3.12", "3.13"]}},
        },
    )
    assert {f"Tests (offline) — py{v}" for v in ("3.11", "3.12", "3.13")} <= test_names
    # The raw template and the job id stay accepted (historical contract).
    assert "Tests (offline) — py${{ matrix.python }}" in test_names
    assert "test" in test_names

    tier_names, _ = rg._job_check_names(
        "test-tiers",
        {"name": "Tier ${{ matrix.tier }}", "strategy": {"matrix": {"tier": ["unit", "rest"]}}},
    )
    assert {"Tier unit", "Tier rest"} <= tier_names

    smoke_names, prefix = rg._job_check_names(
        "platform-smoke",
        {
            "name": "Smoke — ${{ matrix.os }} (L1)",
            "strategy": {"matrix": {"os": ["windows-latest", "macos-latest"]}},
        },
    )
    assert {"Smoke — windows-latest (L1)", "Smoke — macos-latest (L1)"} <= smoke_names
    assert prefix == "Smoke — "

    # A job without name: is named after its id; no-matrix names are exact.
    assert rg._job_check_names("lint-type", {}) == ({"lint-type"}, "")


def test_matrix_include_and_exclude_shapes() -> None:
    combos = rg._matrix_combos(
        {"os": ["linux"], "include": [{"os": "linux", "experimental": "yes"}]}
    )
    assert {"os": "linux", "experimental": "yes"} in combos
    combos = rg._matrix_combos({"py": ["3.11", "3.12"], "exclude": [{"py": "3.11"}]})
    assert combos == [{"py": "3.12"}]


def test_verify_passes_on_realistic_payload() -> None:
    report = rg.verify_release_sha(
        "waalwalker1/knovaryn",
        "f" * 40,
        fetch_json=lambda url, **kw: _ok_payload(),
    )
    assert report["verified_jobs"] >= rg.ci_job_ids()


def test_stale_skipped_run_does_not_mask_fresh_success() -> None:
    """Regression: arbitrary duplicate selection refused a releasable SHA.

    With two runs of one job, latest-wins must decide: an earlier `skipped`
    masked by a later `success` passes; the reverse refuses.
    """
    base = _ok_payload()
    base["check_runs"] = [r for r in base["check_runs"] if r["name"] != "Lint, format & type (L4)"]

    def with_lint(later: dict[str, Any], earlier: dict[str, Any]) -> Any:
        return lambda url, **kw: _payload(
            base["check_runs"] + [earlier, later]  # earlier listed first…
        )

    # …but the LATER timestamp/run_id wins regardless of list order.
    good = _run("Lint, format & type (L4)", "success", completed="2026-08-21T13:00:00Z", run_id=2)
    stale = _run("Lint, format & type (L4)", "skipped", completed="2026-08-21T10:00:00Z", run_id=1)
    report = rg.verify_release_sha(
        "waalwalker1/knovaryn", "f" * 40, fetch_json=with_lint(good, stale)
    )
    assert "lint-type" in report["verified_jobs"]

    bad = _run("Lint, format & type (L4)", "failure", completed="2026-08-21T13:00:00Z", run_id=2)
    fresh_ok = _run(
        "Lint, format & type (L4)", "success", completed="2026-08-21T10:00:00Z", run_id=1
    )
    with pytest.raises(Exception, match="Lint.*failure"):
        rg.verify_release_sha("waalwalker1/knovaryn", "f" * 40, fetch_json=with_lint(bad, fresh_ok))


def test_failed_matrix_leg_fails_the_job() -> None:
    base = _ok_payload()
    for r in base["check_runs"]:
        if r["name"] == "Tier chaos":
            r["conclusion"] = "failure"
    with pytest.raises(Exception, match="Tier chaos"):
        rg.verify_release_sha("waalwalker1/knovaryn", "f" * 40, fetch_json=lambda url, **kw: base)


def test_missing_job_fails_closed() -> None:
    base = _ok_payload()
    base["check_runs"] = [r for r in base["check_runs"] if r["name"] != "Build container"]
    with pytest.raises(Exception, match=r"'container' \(no check run"):
        rg.verify_release_sha("waalwalker1/knovaryn", "f" * 40, fetch_json=lambda url, **kw: base)


def test_running_job_fails_closed() -> None:
    base = _ok_payload()
    base["check_runs"].append(
        {
            "name": "Coverage gate (L3)",
            "status": "in_progress",
            "conclusion": None,
            "completed_at": "",
            "id": 999,
        }
    )
    with pytest.raises(Exception, match="still in_progress"):
        rg.verify_release_sha("waalwalker1/knovaryn", "f" * 40, fetch_json=lambda url, **kw: base)


def test_pagination_collects_all_pages() -> None:
    """>100 runs must paginate; a single-page reader loses page-2 legs."""
    calls: list[str] = []
    page_two = _ok_payload()["check_runs"]

    def fetch(url: str, **kw: Any) -> dict[str, Any]:
        calls.append(url)
        page = int(url.rsplit("page=", 1)[1])
        if page == 1:
            return _payload([_run(f"filler-{i}", "success", run_id=i) for i in range(100)])
        assert page == 2
        return _payload(page_two)

    report = rg.verify_release_sha("waalwalker1/knovaryn", "f" * 40, fetch_json=fetch)
    # All required jobs verified from page 2 alone — page 1 was all filler.
    assert report["verified_jobs"] >= rg.ci_job_ids()
    assert len(calls) == 2


def test_unknown_sha_raises_configuration_error() -> None:
    def fetch(url: str, **kw: Any) -> dict[str, Any]:
        raise FileNotFoundError(url)

    with pytest.raises(rg.ConfigurationError, match="not found"):
        rg.verify_release_sha(
            "waalwalker1/knovaryn",
            "f" * 40,
            fetch_json=fetch,  # type: ignore[arg-type]
        )
