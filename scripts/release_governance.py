#!/usr/bin/env python3
"""Release governance gate (defect 4.12): a release SHA must have passed CI.

v0.1 allowed publishing a Release for any commit regardless of whether CI
passed on it — the publish workflow built and uploaded whatever SHA the tag
pointed at. This module closes that hole:

* the canonical required-check set is parsed from
  ``.github/workflows/ci.yml`` job ids, so the gate can never silently drift
  from CI's own definition;
* ``verify_release_sha`` resolves the commit's check runs through the GitHub
  API and fails closed: every required job must be present and concluded
  ``SUCCESS`` — failed, missing, or still-running are all violations;
* the publish workflow (``publish.yml``) runs this gate before building or
  uploading anything.

CLI (used by publish.yml; also usable locally with a token):

    python scripts/release_governance.py <sha> [--repo owner/name]

Exit codes: 0 = the SHA passed all required CI jobs; 1 = governance violation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from knovaryn.domain.errors import ConfigurationError  # noqa: E402

DEFAULT_REPO = "waalwalker1/knovaryn"
DEFAULT_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"

# Injected in publish.yml so the API call is observable and testable.
FetchJson = Callable[..., dict[str, Any]]


def ci_job_ids(workflow_path: Path | str | None = None) -> frozenset[str]:
    """The CI job ids this repo treats as required checks for a release.

    Parsed from the workflow's own ``jobs:`` mapping — adding or renaming a
    CI job automatically changes what the release gate demands.
    """
    path = Path(workflow_path) if workflow_path else DEFAULT_WORKFLOW
    if not path.is_file():
        raise ConfigurationError(f"CI workflow not found: {path} (expected ci.yml in-repo)")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    jobs = data.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        raise ConfigurationError(f"CI workflow {path} defines no jobs")
    return frozenset(str(j) for j in jobs)


def _github_fetch_json(url: str, *, token: str | None = None) -> dict[str, Any]:
    """Fetch a GitHub API URL, returning the parsed JSON body."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    tok = token or os.environ.get("GITHUB_TOKEN") or ""
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return dict(json.loads(resp.read().decode("utf-8")))


def verify_release_sha(
    repo: str,
    sha: str,
    *,
    fetch_json: FetchJson | None = None,
    token: str | None = None,
    workflow_path: Path | str | None = None,
) -> dict[str, Any]:
    """Verify every CI job passed on ``sha``; raise ConfigurationError if not.

    Fails closed on: unknown commit, a required job that failed, a required
    job with no check run (CI never ran), and a job still in progress.
    Check runs are matched against job ids OR the job's display ``name:``
    (GitHub names Actions check runs after the display name when set).
    """
    import urllib.error

    fetch = fetch_json or _github_fetch_json
    required = ci_job_ids(workflow_path)

    # job id -> display name (either may name the check run)
    path = Path(workflow_path) if workflow_path else DEFAULT_WORKFLOW
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    display: dict[str, str] = {}
    for job_id, job in (data.get("jobs") or {}).items():
        name = (job or {}).get("name") if isinstance(job, dict) else None
        if name:
            display[str(job_id)] = str(name)

    url = f"https://api.github.com/repos/{repo}/commits/{sha}/check-runs"
    try:
        payload = fetch(url, token=token) if token else fetch(url)
    except FileNotFoundError as exc:
        raise ConfigurationError(
            f"release governance: commit {sha[:12]} not found on {repo} "
            f"({exc}); refusing to release an unknown SHA"
        ) from exc
    except urllib.error.HTTPError as exc:  # pragma: no cover - network
        raise ConfigurationError(
            f"release governance: GitHub API error {exc.code} for {url}"
        ) from exc

    by_name: dict[str, dict[str, Any]] = {
        str(run.get("name")): run for run in payload.get("check_runs", [])
    }
    verified: set[str] = set()
    violations: list[str] = []
    for job_id in sorted(required):
        run = by_name.get(job_id) or by_name.get(display.get(job_id, ""))
        if run is None:
            violations.append(f"'{job_id}' (no check run — CI did not run on this SHA)")
            continue
        if run.get("status") != "completed":
            violations.append(f"'{job_id}' (still {run.get('status')})")
            continue
        if run.get("conclusion") != "success":
            violations.append(f"'{job_id}' (conclusion: {run.get('conclusion')})")
            continue
        verified.add(job_id)

    if violations:
        raise ConfigurationError(
            "release governance: refusing to release "
            f"{sha[:12]} on {repo} — required CI checks did not pass: " + "; ".join(violations)
        )
    return {"sha": sha, "repo": repo, "verified_jobs": verified}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify a release SHA passed all required CI jobs.")
    ap.add_argument("sha", help="commit SHA the release tag points at")
    ap.add_argument("--repo", default=DEFAULT_REPO, help="owner/name (default: knovaryn origin)")
    args = ap.parse_args(argv)
    try:
        report = verify_release_sha(args.repo, args.sha)
    except ConfigurationError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        f"OK: {args.sha[:12]} passed all {len(report['verified_jobs'])} "
        f"required CI jobs on {args.repo}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
