"""Regression tests: logical provider calls must not be duplicated after a crash
(spec §11.5, §12/E5).

The gateway caches provider responses by request fingerprint, but the default
cache is in-memory: after a crash the new process's cache is cold, and the
durable ``model_calls`` ledger — which recorded the call and its cost — is never
consulted. The provider is re-invoked for an already-paid logical call and a
duplicate cost event is written.

The durable contract: on a cache miss, the ``model_calls`` ledger (keyed by
``(job_id, request_fingerprint)``) is the source of truth. A call whose
fingerprint already has a successful ledger row with a stored result payload is
served from the ledger — no provider invocation, no second ledger row.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from knovaryn.application.workspace import Workspace
from knovaryn.domain.ids import IdGenerator
from knovaryn.infrastructure.database.repositories import ModelCallRepository
from knovaryn.infrastructure.models.fake_provider import FakeProvider
from knovaryn.infrastructure.models.gateway import ModelGateway


class CountingFake(FakeProvider):
    """FakeProvider that records every real provider invocation."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.calls: list[dict[str, Any]] = []

    async def complete(self, **kw: Any) -> dict[str, Any]:  # type: ignore[override]
        self.calls.append(dict(kw))
        return await super().complete(**kw)


class LedgerAdapter:
    """Per-op session adapter so the gateway can use ModelCallRepository
    outside a request transaction (same pattern as WorkerRepository)."""

    def __init__(self, db: Any, ids: IdGenerator) -> None:
        self._db = db
        self._ids = ids

    async def _op(self, method: str, *args: Any, **kwargs: Any) -> Any:
        async with self._db.session() as session, session.begin():
            repo = ModelCallRepository(session, self._ids)
            return await getattr(repo, method)(*args, **kwargs)

    async def record(self, call: dict[str, Any]) -> None:
        await self._op("record", call)

    async def get_by_fingerprint(self, job_id: str, fingerprint: str) -> Any:
        return await self._op("get_by_fingerprint", job_id, fingerprint)


_MESSAGES = [{"role": "user", "content": "Explain how a widget valve works."}]
_SAMPLING = {"temperature": 0.0, "max_output_tokens": 512}


def _generate_kwargs() -> dict[str, Any]:
    return {
        "prompt_template_version": "tpl-v1",
        "sampling": dict(_SAMPLING),
        "schema_hash": None,
        "source_hashes": ["sha:source-1"],
        "messages": [dict(m) for m in _MESSAGES],
        "source_text": "A widget valve regulates pressure.",
        "chunk_id": "ch1",
        "task_family": "factual_explanation",
        "difficulty": "intermediate",
        "seed": 7,
    }


@pytest.fixture
async def workspace(tmp_path: Path) -> Workspace:
    db = tmp_path / "knovaryn-dedup.db"
    ws = Workspace(database_url=f"sqlite+aiosqlite:///{db}", principal="test")
    await ws.open()
    yield ws
    await ws.close()


async def _ledger_rows(ws: Workspace, job_id: str, fp: str) -> list[Any]:
    async with ws._db.session() as session:
        from sqlalchemy import select

        from knovaryn.infrastructure.database.models import ModelCallDB

        rows = (
            (
                await session.execute(
                    select(ModelCallDB).where(
                        ModelCallDB.job_id == job_id,
                        ModelCallDB.request_fingerprint == fp,
                    )
                )
            )
            .scalars()
            .all()
        )
        return list(rows)


class TestNoDuplicateLogicalCall:
    """A crash between the provider call and any checkpoint must not re-invoke
    the provider for the same fingerprint on resume."""

    async def test_resume_serves_from_durable_ledger(self, workspace: Workspace) -> None:
        ids = IdGenerator()
        job_id = "job_dedup_1"

        # -- pass A: the original run --------------------------------------
        fake_a = CountingFake()
        gateway_a = ModelGateway(
            generator_model="fake",
            fake=fake_a,
            job_id=job_id,
            project_id="p1",
            stage="generate",
            model_call_repo=LedgerAdapter(workspace._db, ids),
            # default in-memory cache: exactly the post-crash-cold state for B
        )
        result_a = await gateway_a.generate(**_generate_kwargs())

        assert len(fake_a.calls) == 1, "first pass must call the provider exactly once"
        fp = result_a["_fingerprint"]

        rows = await _ledger_rows(workspace, job_id, fp)
        assert len(rows) == 1, "pass A must record exactly one ledger row"
        assert rows[0].result_payload, "ledger row must carry the result payload for resume"

        # -- crash: new process, cold in-memory cache, fresh gateway -------
        fake_b = CountingFake()
        gateway_b = ModelGateway(
            generator_model="fake",
            fake=fake_b,
            job_id=job_id,
            project_id="p1",
            stage="generate",
            model_call_repo=LedgerAdapter(workspace._db, ids),
        )
        result_b = await gateway_b.generate(**_generate_kwargs())

        assert len(fake_b.calls) == 0, (
            "the provider was re-invoked for an already-paid logical call after "
            "the crash — the durable ledger must serve the cached result"
        )
        assert result_b["content"] == result_a["content"], (
            "restored result must match the original provider response"
        )

    async def test_different_fingerprint_still_calls_provider(self, workspace: Workspace) -> None:
        """Dedup is keyed on the fingerprint: a genuinely new call still executes."""
        ids = IdGenerator()
        job_id = "job_dedup_2"
        fake = CountingFake()
        gateway = ModelGateway(
            generator_model="fake",
            fake=fake,
            job_id=job_id,
            project_id="p1",
            stage="generate",
            model_call_repo=LedgerAdapter(workspace._db, ids),
        )
        await gateway.generate(**_generate_kwargs())
        kw = _generate_kwargs()
        kw["messages"] = [{"role": "user", "content": "A different question entirely?"}]
        await gateway.generate(**kw)
        assert len(fake.calls) == 2, "distinct logical calls must each hit the provider"


class TestNoDuplicateCostEvent:
    """At most one model_calls ledger row (cost event) per (job_id, fingerprint)."""

    async def test_no_second_ledger_row_after_resume(self, workspace: Workspace) -> None:
        ids = IdGenerator()
        job_id = "job_cost_1"

        fake_a = CountingFake()
        gateway_a = ModelGateway(
            generator_model="fake",
            fake=fake_a,
            job_id=job_id,
            project_id="p1",
            stage="generate",
            model_call_repo=LedgerAdapter(workspace._db, ids),
        )
        result_a = await gateway_a.generate(**_generate_kwargs())
        fp = result_a["_fingerprint"]

        # crash + resume with a cold cache
        fake_b = CountingFake()
        gateway_b = ModelGateway(
            generator_model="fake",
            fake=fake_b,
            job_id=job_id,
            project_id="p1",
            stage="generate",
            model_call_repo=LedgerAdapter(workspace._db, ids),
        )
        await gateway_b.generate(**_generate_kwargs())

        rows = await _ledger_rows(workspace, job_id, fp)
        assert len(rows) == 1, (
            f"duplicate cost event: {len(rows)} ledger rows for fingerprint {fp[:12]} — "
            "the resumed job re-recorded an already-recorded call"
        )
        # and the restored result is the recorded one
        assert rows[0].result_payload.get("content") == result_a["content"]

    async def test_ledger_cost_sum_unchanged_by_resume(self, workspace: Workspace) -> None:
        """sum of estimated_cost for the job must not grow across a resume."""
        ids = IdGenerator()
        job_id = "job_cost_2"
        adapter = LedgerAdapter(workspace._db, ids)

        fake_a = CountingFake()
        gateway_a = ModelGateway(
            generator_model="fake",
            fake=fake_a,
            job_id=job_id,
            project_id="p1",
            stage="generate",
            model_call_repo=adapter,
        )
        await gateway_a.generate(**_generate_kwargs())

        from sqlalchemy import func, select

        from knovaryn.infrastructure.database.models import ModelCallDB

        async with workspace._db.session() as session:
            total_before = float(
                (
                    await session.execute(
                        select(func.coalesce(func.sum(ModelCallDB.estimated_cost), 0.0)).where(
                            ModelCallDB.job_id == job_id
                        )
                    )
                ).scalar_one()
            )

        fake_b = CountingFake()
        gateway_b = ModelGateway(
            generator_model="fake",
            fake=fake_b,
            job_id=job_id,
            project_id="p1",
            stage="generate",
            model_call_repo=adapter,
        )
        await gateway_b.generate(**_generate_kwargs())

        async with workspace._db.session() as session:
            total_after = float(
                (
                    await session.execute(
                        select(func.coalesce(func.sum(ModelCallDB.estimated_cost), 0.0)).where(
                            ModelCallDB.job_id == job_id
                        )
                    )
                ).scalar_one()
            )

        assert total_after == pytest.approx(total_before), (
            f"resume grew the job's recorded cost {total_before} → {total_after}"
        )
