"""Dependency-automation governance (§3.12, v0.2.1).

* Every label named in ``.github/dependabot.yml`` must be DECLARED in
  ``.github/labels.json`` with a color + description (the owner creates them
  in the repo via ``scripts/ensure_labels.py``; CI can't reach the live label
  list from a fork, so the declaration file is the testable contract).
* No auto-merge of MAJOR dependency bumps: nothing in the repository may
  enable automatic merging of dependency PRs without a compatibility gate —
  encoded here so an automerge workflow can't sneak in later unnoticed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit]

_REPO = Path(__file__).resolve().parents[1]


def _labels_declared() -> dict[str, dict[str, str]]:
    import json

    raw = json.loads((_REPO / ".github" / "labels.json").read_text(encoding="utf-8"))
    return {entry["name"]: entry for entry in raw}


def test_dependabot_labels_are_declared() -> None:
    cfg = yaml.safe_load((_REPO / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    declared = _labels_declared()
    problems: list[str] = []
    for update in cfg.get("updates", []):
        for label in update.get("labels", []):
            entry = declared.get(label)
            if entry is None:
                problems.append(f"label {label!r} used in dependabot.yml is not declared "
                                f"in .github/labels.json")
            elif not entry.get("color"):
                problems.append(f"label {label!r} has no color in labels.json")
            elif not entry.get("description"):
                problems.append(f"label {label!r} has no description in labels.json")
    assert not problems, "\n".join(problems)


def test_breaking_major_label_is_declared() -> None:
    """The review gate for major bumps needs its label to exist."""
    assert "breaking-major" in _labels_declared()


def test_no_dependency_automerge_exists() -> None:
    """No workflow may auto-merge dependency PRs (major bumps especially).

    Dependabot PRs merge through protected-branch human review. If a future
    automerge is introduced deliberately, this test must be updated alongside
    a major-version guard — it fails precisely so that decision is visible.
    """
    wf_dir = _REPO / ".github" / "workflows"
    offenders: list[str] = []
    for path in sorted(wf_dir.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        if "automerge" in lowered or "auto-merge" in lowered:
            offenders.append(path.name)
        if "gh pr merge" in lowered and "--auto" in lowered:
            offenders.append(path.name)
        if "dependabot" in lowered and ("merge" in lowered) and "enable" not in lowered:
            # heuristic: dependabot + merge mentioned together needs eyes
            offenders.append(f"{path.name} (mentions dependabot+merge)")
    assert not offenders, (
        f"possible dependency auto-merge surface in {offenders}; §3.12 forbids "
        "auto-merging major dependency bumps"
    )


def test_dependabot_open_pr_limit_is_bounded() -> None:
    cfg = yaml.safe_load((_REPO / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    for update in cfg.get("updates", []):
        limit = int(update.get("open-pull-requests-limit", 5))
        assert 0 < limit <= 20, f"unreviewable PR flood: limit={limit}"
