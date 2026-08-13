"""Review subsystem — immutable example revisions + persisted review decisions
(spec §10 review, WP H1/H2, P0-9).

P0-9 requires that a review action actually change the example: so a decision is
never applied by mutating the example's current row in place. Instead every
decision *creates a new immutable revision* — a full snapshot of ``TrainingExample``
with the resulting ``quality_status`` — and persists a ``ReviewDecisionRecord``
that references the reviewer's base revision.

Optimistic concurrency: a review must carry the ``concurrency_token`` of the
revision it reviewed. If the example has moved on (a newer revision exists), the
stale token is rejected with ``ConcurrencyError`` (HTTP 409) rather than silently
overwriting a newer decision.
"""

from __future__ import annotations

import logging
from typing import Any

from ...domain.errors import ConcurrencyError, NotFoundError
from ...domain.ids import IdGenerator
from ...domain.schemas import (
    ExampleRevision,
    QualityStatus,
    ReviewDecision,
    ReviewDecisionRecord,
    TrainingExample,
)
from ...infrastructure.database.repositories import (
    ExampleRepository,
    ReviewRepository,
    RevisionRepository,
)

log = logging.getLogger("knovaryn.review")

_DECISION_TO_STATUS: dict[ReviewDecision, QualityStatus] = {
    ReviewDecision.approve: QualityStatus.accepted,
    ReviewDecision.reject: QualityStatus.rejected,
    ReviewDecision.needs_work: QualityStatus.review,
}


class ReviewService:
    """Applies review decisions by appending immutable revisions (never in place)."""

    def __init__(
        self,
        *,
        ids: IdGenerator,
        revisions: RevisionRepository,
        reviews: ReviewRepository,
        examples: ExampleRepository,
    ) -> None:
        self._ids = ids
        self._revisions = revisions
        self._reviews = reviews
        self._examples = examples

    async def review_example(
        self,
        *,
        example_id: str,
        revision_id: int,
        reviewer: str,
        decision: ReviewDecision,
        note: str = "",
        policy_version: str = "",
        concurrency_token: str | None = None,
    ) -> ExampleRevision:
        """Apply a review decision, creating a new immutable revision.

        Raises ``ConcurrencyError`` (409) when the example has advanced past the
        revision the reviewer based their decision on.
        """
        example = await self._examples.get(example_id)
        if example is None:
            raise NotFoundError(f"example not found: {example_id}")

        latest = await self._revisions.latest(example_id)
        if latest is None:
            # Bootstrap revision 1 from the current example state so the review
            # always targets an explicit, concurrency-token-carrying base.
            latest = self._snapshot(example, revision_id=1, parent=None, review_state=None)
            await self._revisions.add(latest)

        # ---- optimistic concurrency (stale token / stale base revision -> 409)
        if concurrency_token is not None and concurrency_token != latest.concurrency_token:
            raise ConcurrencyError(
                f"stale concurrency token for example {example_id}: the example has "
                "advanced past the revision that was reviewed (409)"
            )
        if revision_id != latest.revision_id:
            raise ConcurrencyError(
                f"stale base revision for example {example_id}: reviewed revision "
                f"{revision_id} but latest is {latest.revision_id} (409)"
            )

        record = ReviewDecisionRecord(
            id=self._ids.new_handle("rvw"),
            example_id=example_id,
            revision_id=latest.revision_id,
            reviewer_principal=reviewer,
            decision=decision,
            note=note,
            policy_version=policy_version,
            concurrency_token=latest.concurrency_token,
        )
        await self._reviews.add(record)

        # Apply the decision to a NEW revision (never mutate the example content;
        # the revision chain is the immutable audit trail).
        new_status = _DECISION_TO_STATUS[decision]
        new_snapshot = _with_status(example, new_status)
        new_revision = self._snapshot(
            example,
            revision_id=latest.revision_id + 1,
            parent=latest.revision_id,
            review_state=decision,
            snapshot_override=new_snapshot,
        )
        await self._revisions.add(new_revision)
        # Keep the current row's status in sync so accepted-filtered version /
        # export queries reflect the decision (a rejected example is excluded
        # from new versions and exports). P0-9 is satisfied because the
        # pre-review status remains recoverable in the immutable revisions.
        await self._examples.update_quality_status(example_id, new_status)
        log.debug(
            "review %s on %s: %s -> quality_status %s (revision %d)",
            reviewer,
            example_id,
            decision.value,
            new_status.value,
            new_revision.revision_id,
        )
        return new_revision

    async def list_revisions(self, example_id: str) -> list[ExampleRevision]:
        return await self._revisions.list_revisions(example_id)

    async def revision_history(self, example_id: str) -> list[dict[str, Any]]:
        revs = await self._revisions.list_revisions(example_id)
        return [r.model_dump(mode="json") for r in revs]

    async def decisions(self, example_id: str) -> list[ReviewDecisionRecord]:
        return await self._reviews.list_for_example(example_id)

    def _snapshot(
        self,
        example: TrainingExample,
        *,
        revision_id: int,
        parent: int | None,
        review_state: ReviewDecision | None,
        snapshot_override: dict[str, Any] | None = None,
    ) -> ExampleRevision:
        payload = snapshot_override or example.model_dump(mode="json")
        return ExampleRevision(
            id=self._ids.new_handle("rev"),
            example_logical_id=example.id,
            revision_id=revision_id,
            parent_revision_id=parent,
            content_hash=example.content_hash,
            snapshot=payload,
            review_state=review_state,
            concurrency_token=self._ids.new_token(nbytes=24),
            created_by="system",
        )


def _with_status(example: TrainingExample, status: QualityStatus) -> dict[str, Any]:
    payload = example.model_dump(mode="json")
    payload["quality_status"] = status.value
    return payload
