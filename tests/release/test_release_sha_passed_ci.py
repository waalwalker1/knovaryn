"""Release governance (defect 4.12): a release SHA must have passed CI *and*
Security.

v0.1 published releases with no binding between the released commit and a
green CI run — a maintainer could publish a Release for a SHA where CI
failed (or never ran) and the publish workflow would build and upload it
anyway. Corrected contract:

* the canonical required-check set is derived from the push-required job ids
  across ALL governance workflows (``ci.yml`` AND ``security.yml``, §3.11) —
  the gate can never drift from the workflows' own definitions;
* jobs gated to schedule/dispatch events are excluded from that set because
  they cannot have a check run on an ordinary push SHA; the deployment E2E
  (compose-e2e) is instead enforced release-time by publish.yml, which runs
  the reusable deploy-e2e workflow on the exact tag SHA and needs it before
  anything is built or uploaded (§3.10);
* ``verify_release_sha`` resolves a commit's check runs via the GitHub API
  (injectable fetcher — these tests run fully offline) and FAILS CLOSED:
  any required job that is not ``SUCCESS`` — failed, missing, or still
  pending — is a governance violation naming the job;
* the publish workflow runs this gate BEFORE building/uploading anything.
"""

from __future__ import annotations

import pytest
import yaml
from scripts.release_governance import (
    ci_job_ids,
    governance_workflows,
    verify_release_sha,
)

from knovaryn.domain.errors import ConfigurationError

pytestmark = pytest.mark.release

REPO = "waalwalker1/knovaryn"
SHA = "a" * 40


def _all_required_jobs() -> list[str]:
    """The exact demand-set production enforces: push-required jobs from every
    governance workflow. Mocks MUST mirror this union — building check runs
    from ci.yml alone would misrepresent verify_release_sha as satisfied when
    the Security workflow never ran."""
    jobs: list[str] = []
    for wf in governance_workflows():
        jobs.extend(sorted(ci_job_ids(wf)))
    return jobs


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
    """The required set comes from the workflows themselves, no hand-copy."""

    def test_parses_real_ci_workflow(self):
        ids = ci_job_ids()  # default path = .github/workflows/ci.yml in-repo
        assert "lint-type" in ids
        assert "test" in ids
        assert "test-tiers" in ids
        assert "coverage" in ids

    def test_compose_e2e_is_event_gated_not_push_required(self):
        """§3.10: the Compose E2E cannot be demanded of an ordinary push SHA
        (schedule/dispatch jobs produce no check runs there), so it is excluded
        from the push-required set — and publish.yml must compensate by running
        the reusable exact-SHA E2E itself and needing it before any artifact
        job. Both halves are asserted so neither can rot silently."""
        ids = ci_job_ids()  # default path = .github/workflows/ci.yml in-repo
        assert "compose-e2e" not in ids
        ci_path = next(wf for wf in governance_workflows() if wf.name == "ci.yml")
        raw = yaml.safe_load(ci_path.read_text(encoding="utf-8"))
        assert "compose-e2e" in raw["jobs"], "E2E job vanished from ci.yml"
        publish = (ci_path.parent / "publish.yml").read_text(encoding="utf-8")
        assert "uses: ./.github/workflows/deploy-e2e.yml" in publish
        # nothing may build until the E2E succeeded on this SHA
        build_needs = yaml.safe_load(publish)["jobs"]["build"]["needs"]
        assert "deploy-e2e" in build_needs

    def test_security_workflow_jobs_are_required_too(self):
        """§3.11: the demand-set spans BOTH governance workflows."""
        security = next(wf for wf in governance_workflows() if wf.name == "security.yml")
        sec_ids = ci_job_ids(security)
        assert sec_ids, "security.yml contributes no push-required jobs"
        assert "secrets" in sec_ids

    def test_missing_workflow_is_an_error(self, tmp_path):
        with pytest.raises(ConfigurationError, match="ci.yml"):
            ci_job_ids(workflow_path=tmp_path / "nope.yml")


class TestVerifyReleaseSha:
    def test_all_checks_pass(self):
        jobs = dict.fromkeys(_all_required_jobs(), "success")
        report = verify_release_sha(REPO, SHA, fetch_json=lambda url, **kw: _api_response(jobs))
        assert report["sha"] == SHA
        assert report["verified_jobs"] == set(_all_required_jobs())

    def test_failed_check_is_rejected_and_named(self):
        jobs = dict.fromkeys(_all_required_jobs(), "success")
        jobs["test"] = "failure"
        with pytest.raises(ConfigurationError, match=r"'test'"):
            verify_release_sha(REPO, SHA, fetch_json=lambda url, **kw: _api_response(jobs))

    def test_missing_check_never_ran_is_rejected(self):
        jobs = {j: "success" for j in _all_required_jobs() if j != "coverage"}
        with pytest.raises(ConfigurationError, match="coverage"):
            verify_release_sha(REPO, SHA, fetch_json=lambda url, **kw: _api_response(jobs))

    def test_missing_security_check_is_rejected_too(self):
        """A Security-workflow job absent from the commit's check runs fails
        the gate exactly like a CI job would (§3.11)."""
        jobs = {j: "success" for j in _all_required_jobs() if j != "secrets"}
        with pytest.raises(ConfigurationError, match="'secrets'"):
            verify_release_sha(REPO, SHA, fetch_json=lambda url, **kw: _api_response(jobs))

    def test_pending_check_is_rejected(self):
        resp = _api_response(dict.fromkeys(_all_required_jobs(), "success"))
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
        resp = _api_response(dict.fromkeys(_all_required_jobs(), "success"))
        for run in resp["check_runs"]:
            if run["name"] == "lint-type":
                run["name"] = "Lint, format & type (L4)"  # its display name
        resp["check_runs"].append(
            {"name": "nonessential", "status": "completed", "conclusion": "failure"}
        )  # not a CI job
        report = verify_release_sha(REPO, SHA, fetch_json=lambda url, **kw: resp)
        assert "lint-type" in report["verified_jobs"]
