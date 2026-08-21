"""Release governance (defect 4.12): a release SHA must have passed CI.

v0.1 published releases with no binding between the released commit and a
green CI run — a maintainer could publish a Release for a SHA where CI
failed (or never ran) and the publish workflow would build and upload it
anyway. Corrected contract:

* the canonical "CI passed" set is derived from the job ids in
  ``.github/workflows/ci.yml`` (the gate can never drift from CI's own
  definition);
* ``verify_release_sha`` resolves a commit's check runs via the GitHub API
  (injectable fetcher — these tests run fully offline) and FAILS CLOSED:
  any required job that is not ``SUCCESS`` — failed, missing, or still
  pending — is a governance violation naming the job;
* the publish workflow runs this gate BEFORE building/uploading anything.
"""

from __future__ import annotations

import pytest
from scripts.release_governance import (
    ci_job_ids,
    verify_release_sha,
)

from knovaryn.domain.errors import ConfigurationError

pytestmark = pytest.mark.release

REPO = "waalwalker1/knovaryn"
SHA = "a" * 40


def _api_response(jobs: dict[str, str]) -> dict:
    """Shape of GET /repos/{repo}/commits/{sha}/check-runs."""
    return {
        "total_count": len(jobs),
        "check_runs": [
            {"name": name, "status": "completed", "conclusion": conclusion}
            for name, conclusion in jobs.items()
        ],
    }


class TestCiJobIdsDerivedFromWorkflow:
    """The required set comes from ci.yml itself, not a hand-copied list."""

    def test_parses_real_ci_workflow(self):
        ids = ci_job_ids()  # default path = .github/workflows/ci.yml in-repo
        assert "lint-type" in ids
        assert "test" in ids
        assert "test-tiers" in ids
        assert "coverage" in ids
        # the compose E2E gate (defect 4.11) must itself be part of CI
        assert "compose-e2e" in ids

    def test_missing_workflow_is_an_error(self, tmp_path):
        with pytest.raises(ConfigurationError, match="ci.yml"):
            ci_job_ids(workflow_path=tmp_path / "nope.yml")


class TestVerifyReleaseSha:
    def test_all_checks_pass(self):
        jobs = dict.fromkeys(ci_job_ids(), "success")
        report = verify_release_sha(REPO, SHA, fetch_json=lambda url, **kw: _api_response(jobs))
        assert report["sha"] == SHA
        assert report["verified_jobs"] == set(ci_job_ids())

    def test_failed_check_is_rejected_and_named(self):
        jobs = dict.fromkeys(ci_job_ids(), "success")
        jobs["test"] = "failure"
        with pytest.raises(ConfigurationError, match=r"'test'"):
            verify_release_sha(REPO, SHA, fetch_json=lambda url, **kw: _api_response(jobs))

    def test_missing_check_never_ran_is_rejected(self):
        jobs = {j: "success" for j in ci_job_ids() if j != "coverage"}
        with pytest.raises(ConfigurationError, match="coverage"):
            verify_release_sha(REPO, SHA, fetch_json=lambda url, **kw: _api_response(jobs))

    def test_pending_check_is_rejected(self):
        resp = _api_response(dict.fromkeys(ci_job_ids(), "success"))
        resp["check_runs"][0]["status"] = "in_progress"
        pending_name = resp["check_runs"][0]["name"]
        with pytest.raises(ConfigurationError, match=pending_name):
            verify_release_sha(REPO, SHA, fetch_json=lambda url, **kw: resp)

    def test_unknown_sha_is_rejected(self):
        def fetch_404(url: str, **kw):
            raise FileNotFoundError(url)

        with pytest.raises(ConfigurationError, match="not found|unknown commit"):
            verify_release_sha(REPO, SHA, fetch_json=fetch_404)

    def test_job_display_name_satisfies_gate(self):
        """A check run named by the job's display `name:` also counts (GitHub
        names Actions check runs after the display name when one is set)."""
        resp = _api_response(dict.fromkeys(ci_job_ids(), "success"))
        for run in resp["check_runs"]:
            if run["name"] == "lint-type":
                run["name"] = "Lint, format & type (L4)"  # its display name
        resp["check_runs"].append(
            {"name": "nonessential", "status": "completed", "conclusion": "failure"}
        )  # not a CI job
        report = verify_release_sha(REPO, SHA, fetch_json=lambda url, **kw: resp)
        assert "lint-type" in report["verified_jobs"]
