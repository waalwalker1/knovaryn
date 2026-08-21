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
import re
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


_MATRIX_REF = re.compile(r"\$\{\{\s*matrix\.([A-Za-z0-9_]+)\s*\}\}")


def _matrix_combos(matrix_cfg: Any) -> list[dict[str, str]]:
    """Expand a workflow ``strategy.matrix`` into value combinations.

    Handles the shapes ci.yml uses — scalar product keys (``key: [v1, v2]``
    or a scalar), ``include:`` entries merged onto matching combos, and
    ``exclude:`` removals. Values are stringified the way GitHub interpolates
    them into a job's ``name:``.
    """
    if not isinstance(matrix_cfg, dict):
        return [{}]
    plain: dict[str, list[str]] = {}
    for key, values in matrix_cfg.items():
        if key in ("include", "exclude"):
            continue
        plain[str(key)] = [str(v) for v in values] if isinstance(values, list) else [str(values)]
    combos: list[dict[str, str]] = [{}]
    for key, values in plain.items():
        combos = [{**combo, key: value} for combo in combos for value in values]
    includes = matrix_cfg.get("include")
    if isinstance(includes, list):
        for entry in includes:
            if not isinstance(entry, dict):
                continue
            item = {str(k): str(v) for k, v in entry.items()}
            merged = False
            # Snapshot: appending during iteration would revisit the new
            # combos, which match their own keys forever.
            for combo in list(combos):
                if all(combo[k] == v for k, v in item.items() if k in combo):
                    combos.append({**combo, **item})
                    merged = True
            if not merged and not plain:
                combos.append(item)
    excludes = matrix_cfg.get("exclude")
    if isinstance(excludes, list):
        for entry in excludes:
            if isinstance(entry, dict):
                item = {str(k): str(v) for k, v in entry.items()}
                combos = [c for c in combos if not all(c.get(k) == v for k, v in item.items())]
    return combos or [{}]


def _job_check_names(job_id: str, job: dict[str, Any]) -> tuple[set[str], str]:
    """Return (exact check-run names, fallback prefix) for one CI job.

    GitHub names each matrix leg's check run after the job ``name:`` with
    ``${{ matrix.* }}`` interpolated — so comparing against the raw template
    string never matches ("Tests (offline) — py${{ matrix.python }}" vs the
    actual "Tests (offline) — py3.13"). The gate therefore expands the matrix
    itself. The accepted set is the union of the interpolated leg names, the
    raw display name, and the job id (non-matrix jobs are named after their
    display name or id; the literal template cannot occur on a real run, but
    accepting it keeps the historical contract honest). The prefix (literal
    text before the first expression) is the fallback matcher for legs the
    expansion could not predict; an empty prefix disables it.
    """
    name = str(job.get("name") or job_id)
    refs = set(_MATRIX_REF.findall(name))
    if not refs:
        return {name, job_id}, ""
    combos = _matrix_combos((job.get("strategy") or {}).get("matrix"))
    names: set[str] = {name, job_id}
    for combo in combos:
        resolved = name
        for token, value in combo.items():
            resolved = re.sub(rf"\$\{{\{{\s*matrix\.{re.escape(token)}\s*\}}\}}", value, resolved)
        if not _MATRIX_REF.search(resolved):
            names.add(resolved)
    prefix = _MATRIX_REF.split(name)[0]
    return names, prefix


def verify_release_sha(
    repo: str,
    sha: str,
    *,
    fetch_json: FetchJson | None = None,
    token: str | None = None,
    workflow_path: Path | str | None = None,
) -> dict[str, Any]:
    """Verify every CI job passed on ``sha``; raise ConfigurationError if not.

    Fails closed on: unknown commit, a required job (or any matrix leg of
    one) that failed, has no check run (CI never ran), or is still running.
    Check runs are matched by expanded job ``name:`` (matrix-aware), falling
    back to the literal prefix for unpredicted legs and to the job id when
    no ``name:`` is set.
    """
    import urllib.error

    fetch = fetch_json or _github_fetch_json
    required = ci_job_ids(workflow_path)

    path = Path(workflow_path) if workflow_path else DEFAULT_WORKFLOW
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    jobs_cfg = data.get("jobs") or {}

    url = f"https://api.github.com/repos/{repo}/commits/{sha}/check-runs"
    # Paginate (default page size is 30 — a SHA with several CI runs exceeds
    # it, which previously produced phantom "no check run" verdicts) and keep
    # the LATEST check run per leg name. A commit can carry many runs of the
    # same job (push + dispatch + re-runs); picking an arbitrary duplicate
    # let a stale `skipped` opt-in run mask a fresh `success`.
    all_runs: list[dict[str, Any]] = []
    page = 1
    while True:
        paged = f"{url}?per_page=100&page={page}"
        try:
            payload = fetch(paged, token=token) if token else fetch(paged)
        except FileNotFoundError as exc:
            raise ConfigurationError(
                f"release governance: commit {sha[:12]} not found on {repo} "
                f"({exc}); refusing to release an unknown SHA"
            ) from exc
        except urllib.error.HTTPError as exc:  # pragma: no cover - network
            raise ConfigurationError(
                f"release governance: GitHub API error {exc.code} for {url}"
            ) from exc
        batch = list(payload.get("check_runs", []))
        all_runs.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    def _recency(run: dict[str, Any]) -> tuple[int, str]:
        # Check-run ids are monotonic, so id order is creation order. Ranking
        # by completed_at instead would let an in-progress re-run (empty
        # completed_at) lose to an old success and hide behind it.
        return (int(run.get("id") or 0), str(run.get("completed_at") or ""))

    by_name: dict[str, dict[str, Any]] = {}
    for run in all_runs:
        name = str(run.get("name"))
        if name not in by_name or _recency(run) > _recency(by_name[name]):
            by_name[name] = run

    matchers: dict[str, tuple[set[str], str]] = {}
    for job_id in sorted(required):
        job = jobs_cfg.get(job_id)
        matchers[job_id] = _job_check_names(job_id, job if isinstance(job, dict) else {})

    verified: set[str] = set()
    violations: list[str] = []
    for job_id in sorted(required):
        exact, prefix = matchers[job_id]
        leg_names = sorted(n for n in by_name if n in exact)
        if not leg_names and prefix:
            # Prefix fallback only when unambiguous: another required job
            # whose exact names or longer prefix also claims these runs
            # voids the claim (fail closed rather than guess).
            contested = any(
                any(n.startswith(prefix) for n in other_exact)
                or bool(other_prefix and other_prefix.startswith(prefix))
                for other_id, (other_exact, other_prefix) in matchers.items()
                if other_id != job_id
            )
            if not contested:
                leg_names = sorted(n for n in by_name if n.startswith(prefix))
        if not leg_names:
            violations.append(f"'{job_id}' (no check run — CI did not run on this SHA)")
            continue
        bad = []
        for leg in leg_names:
            run = by_name[leg]
            if run.get("status") != "completed":
                bad.append(f"{leg}: still {run.get('status')}")
            elif run.get("conclusion") != "success":
                bad.append(f"{leg}: conclusion {run.get('conclusion')}")
        if bad:
            violations.append(f"'{job_id}' (" + "; ".join(bad) + ")")
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
