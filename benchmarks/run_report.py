"""Canonical Knovaryn benchmark runner (methodology v2).

Produces ``benchmarks/results/<version>/`` per
``docs/reference/benchmark-methodology.md`` §18:

    environment.json   machine/software record (§3)
    run-1..N.json      one metric dict per repetition (§4)
    aggregate.json     medians + Wilson intervals + digest-equality verdict
    checksums.txt      SHA-256 of every other file in the directory
    README.md          how these files were produced

Everything measured here is OFFLINE and DETERMINISTIC (fake provider).
Live-provider cost/quality is explicitly reported as *not measured* by this
runner; deployment E2E and the MCP dual-SDK matrix are executed separately and
cited by the narrative report, never synthesized here.

Usage:
    uv run python benchmarks/run_report.py --version 0.2.1 --runs 3
    uv run python benchmarks/run_report.py --check benchmarks/results/0.2.1
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import math
import platform
import subprocess
import sys
import tempfile
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

Z95 = 1.96
EXPECTED_RUNS = 3  # methodology §4: three-run reproducibility requirement


def _r(value, digits: int = 4):
    return round(value, digits) if isinstance(value, float) else value


def wilson(p: float, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (methodology §14)."""
    if n == 0:
        return (0.0, 1.0)
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _rate_with_ci(numerator: int, denominator: int) -> dict:
    p = numerator / denominator if denominator else 0.0
    lo, hi = wilson(p, denominator)
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": _r(p),
        "ci95_low": _r(lo),
        "ci95_high": _r(hi),
    }


# --------------------------------------------------------------------------
# 1. offline pipeline suite (parse/chunk/span/provenance/quality/export)
# --------------------------------------------------------------------------


def _corpus() -> dict[str, bytes]:
    names = ("numbered-headings.md", "multilingual.txt", "sample.csv", "sample.json")
    out: dict[str, bytes] = {}
    for name in names:
        p = REPO_ROOT / "tests" / "fixtures" / "intake" / name
        if p.exists():
            out[name] = p.read_bytes()
    return out


async def pipeline_metrics() -> dict[str, object]:
    from knovaryn.application.service import ProjectService
    from knovaryn.domain.ids import IdGenerator
    from knovaryn.domain.schemas import DatasetPlan, Project, SourceDocument, SourceKind
    from knovaryn.pipeline.export.formats import SUPPORTED_FORMATS, export_format

    corpus = _corpus()
    # reproducible mode (methodology §5): seeded handles so the release-bundle
    # digest depends on inputs only, never wall-clock UUIDv7 timestamps.
    ids = IdGenerator(seed="knovaryn-benchmark/0.2.1")
    project = Project(
        id=ids.new_handle("proj"),
        slug="bench",
        display_name="Knovaryn Benchmark",
        owner_principal="bench",
    )
    plan = DatasetPlan(
        task_family_proportions={"factual_explanation": 0.5, "procedure": 0.3, "comparison": 0.2},
        difficulty_distribution={"basic": 0.3, "intermediate": 0.5, "advanced": 0.2},
        maximum_dataset_size=2000,
    )
    sources: list[SourceDocument] = []
    raw: list[bytes] = []
    for name, blob in corpus.items():
        sources.append(
            SourceDocument(
                id=ids.new_handle("src"),
                project_id=project.id,
                original_name=name,
                media_type="text/markdown" if name.endswith(".md") else "text/plain",
                byte_size=len(blob),
                sha256=hashlib.sha256(blob).hexdigest(),
                source_kind=SourceKind.local_path,
                group_key=name,
            )
        )
        raw.append(blob)

    m: dict[str, object] = {
        "corpus_sha256": {n: hashlib.sha256(b).hexdigest() for n, b in sorted(corpus.items())},
        "provider": "fake (deterministic)",
    }

    tracemalloc.start()
    t0 = time.monotonic()
    svc = ProjectService(ids=ids)
    result = await svc.run_pipeline(project=project, sources=sources, raw_contents=raw, plan=plan)
    elapsed = time.monotonic() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # parse fidelity / yields
    m["sources"] = len(sources)
    m["parsed"] = len(result.parsed)
    m["chunks"] = len(result.chunks)
    m["spans"] = len(result.spans)
    m["candidates"] = len(result.candidates)
    m["examples"] = len(result.examples)
    m["parse_success_rate"] = _r(len(result.parsed) / len(sources)) if sources else 0.0
    heading_chunks = sum(1 for c in result.chunks if getattr(c, "heading_path", None))
    m["chunk_heading_coverage"] = _r(heading_chunks / len(result.chunks)) if result.chunks else 0.0

    # provenance resolution + precision distribution
    doc_ids = {d.id for d in result.parsed} | {s.id for s in sources}
    span_ids = {s.id for s in result.spans}
    resolved = sum(
        1
        for e in result.examples
        if bool(e.source_document_ids)
        and all(x in doc_ids for x in e.source_document_ids)
        and (not e.source_span_ids or all(x in span_ids for x in e.source_span_ids))
        and bool(e.content_hash)
        and bool(e.generation_candidate_ids)
    )
    m["lineage_resolution"] = _rate_with_ci(resolved, len(result.examples))
    precision_dist: dict[str, int] = {}
    for span in result.spans:
        key = str(getattr(span, "precision", "unknown")).rsplit(".", 1)[-1]
        precision_dist[key] = precision_dist.get(key, 0) + 1
    m["precision_distribution"] = dict(sorted(precision_dist.items()))

    # quality outcomes
    statuses: dict[str, int] = {}
    for e in result.examples:
        key = str(e.quality_status).rsplit(".", 1)[-1]
        statuses[key] = statuses.get(key, 0) + 1
    m["quality_status_counts"] = dict(sorted(statuses.items()))
    q = result.quality if isinstance(result.quality, dict) else {}
    rc = q.get("reason_codes") if isinstance(q.get("reason_codes"), list) else []
    m["quality_duplicate_rejects"] = rc.count("duplicate")
    m["quality_contamination_rejects"] = rc.count("contamination")
    m["quality_grounding_rejects"] = rc.count("grounding")

    # framework overhead + memory
    m["elapsed_s"] = _r(elapsed)
    m["examples_per_second"] = _r(len(result.examples) / elapsed if elapsed else 0.0)
    m["peak_allocated_bytes"] = peak

    # release bundle
    m["release_bundle_bytes"] = len(result.release_bundle_bytes)
    m["release_bundle_sha256"] = hashlib.sha256(result.release_bundle_bytes).hexdigest()
    m["release_sha256_present"] = bool(result.release_sha256)

    # export round-trip
    export_status: dict[str, str] = {}
    for fmt in sorted(SUPPORTED_FORMATS):
        try:
            res = export_format(result.examples, fmt)
            n_rows = getattr(res, "rows", None)
            ok = (
                isinstance(n_rows, int)
                and n_rows > 0
                and bool(getattr(res, "bytes", b""))
                and bool(getattr(res, "sha256", ""))
            )
            export_status[fmt] = "ok" if ok else "empty"
        except Exception as exc:  # noqa: BLE001
            export_status[fmt] = f"err:{type(exc).__name__}"
    m["export_round_trip"] = export_status
    return m


# --------------------------------------------------------------------------
# 2. semantic adversarial benchmark (deterministic layer, methodology §8)
# --------------------------------------------------------------------------


def semantic_adversarial() -> dict[str, object]:
    """Reuse the exact case corpus CI asserts on — zero divergence by design."""
    tp = REPO_ROOT / "tests" / "semantic" / "test_semantic_benchmark.py"
    spec = importlib.util.spec_from_file_location("_semantic_benchmark_cases", tp)
    assert spec and spec.loader, f"cannot load {tp}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    from knovaryn.pipeline.quality.claims import ClaimVerdict
    from knovaryn.pipeline.quality.semantic import (
        DeterministicSemanticVerifier,
        extract_atomic_claims,
    )

    verifier = DeterministicSemanticVerifier()
    loop = asyncio.new_event_loop()
    results: list[dict[str, str]] = []
    try:
        for category, evidence, answer, expected in mod.CASES:
            claims = extract_atomic_claims(answer)
            assessments = loop.run_until_complete(verifier.assess_claims(claims, evidence))
            got = [a.verdict for a in assessments]
            if ClaimVerdict.contradicted in got:
                observed = "contradicted"
            elif got and all(v is ClaimVerdict.entailed for v in got):
                observed = "entailed"
            else:
                observed = "unverified"
            results.append({"category": category, "expected": expected, "observed": observed})
    finally:
        loop.close()

    n = len(results)
    contradicted_n = sum(1 for r in results if r["expected"] == "contradicted")
    entailed_n = sum(1 for r in results if r["expected"] == "entailed")
    fa = sum(1 for r in results if r["expected"] == "contradicted" and r["observed"] == "entailed")
    fr = sum(1 for r in results if r["expected"] == "entailed" and r["observed"] == "contradicted")
    unverified_entailment = sum(
        1 for r in results if r["expected"] == "entailed" and r["observed"] == "unverified"
    )
    return {
        "layer": "deterministic (offline-fast); certified judge requires live provider",
        "cases": n,
        "false_accept": _rate_with_ci(fa, contradicted_n),
        "false_reject": _rate_with_ci(fr, entailed_n),
        "unverified_on_entailment": _rate_with_ci(unverified_entailment, entailed_n),
        "per_case": results,
    }


# --------------------------------------------------------------------------
# 3. preference quality (methodology §9)
# --------------------------------------------------------------------------


class _ScriptedPairwiseGateway:
    """Canned two-call judge: one payload per presentation order."""

    verifier_model = "bench-judge/deterministic"

    def __init__(self, payloads: list[str]):
        self.payloads = list(payloads)
        self.calls = 0

    async def judge(
        self,
        *,
        system,
        user,
        prompt_template_version,
        schema_hash,
        stage="judge",
        max_output_tokens=None,
        model=None,
    ):
        self.calls += 1
        return {"content": self.payloads.pop(0)}


def _payload(
    first_q: float, second_q: float, defect_side: str | None, confidence: float = 0.92
) -> str:
    return json.dumps(
        {
            "first_quality": first_q,
            "second_quality": second_q,
            "preferred": "first" if first_q > second_q else "second",
            "defects_first": ["factually_incorrect_number_or_unit"]
            if defect_side == "first"
            else [],
            "defects_second": ["factually_incorrect_number_or_unit"]
            if defect_side == "second"
            else [],
            "confidence": confidence,
        }
    )


def preference_metrics() -> dict[str, object]:
    from knovaryn.pipeline.quality.information_gain import assess_information_gain
    from knovaryn.pipeline.quality.preference_judge import CertifiedPairwiseJudge

    evidence = (
        "The XR-9 sensor is calibrated at the factory before shipping. "
        "Calibration takes 40 minutes per unit and must be repeated annually."
    )
    prompt = "How long does calibration take and how often is it repeated?"
    chosen = "Calibration takes 40 minutes per unit and must be repeated annually."
    rejected_bad_number = "Calibration takes 15 minutes per unit and must be repeated monthly."

    def run_pair(payloads: list[str], swap: bool) -> object:
        gw = _ScriptedPairwiseGateway(payloads)
        judge = CertifiedPairwiseJudge(gw, model="bench-judge/deterministic")
        kw = {
            "prompt": prompt,
            "chosen_text": rejected_bad_number if swap else chosen,
            "rejected_text": chosen if swap else rejected_bad_number,
            "evidence_text": evidence,
        }
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(judge.judge_pair(**kw))
        finally:
            loop.close()

    # --- order consistency: N margin levels, judged in both orders ---------
    # Rejected sides are clearly defective (quality <= 3.5) so the
    # both-answers-good fail-closed gate never fires inside THIS measurement;
    # that gate gets its own metric below.
    n_pairs = 10
    consistent = 0
    for i in range(n_pairs):
        bad = 3.5 - (i % 3) * 0.5  # margins 1.5 / 2.0 / 2.5
        # order A: chosen presented first → (good first, bad second)
        a = run_pair([_payload(5.0, bad, "second"), _payload(bad, 5.0, "first")], swap=False)
        # order B: rejected presented first → (bad first, good second)
        b = run_pair([_payload(bad, 5.0, "first"), _payload(5.0, bad, "second")], swap=True)
        if (
            getattr(a, "verdict", "") == "valid"
            and getattr(a, "order_consistent", False)
            and getattr(b, "order_consistent", False)
        ):
            consistent += 1

    # --- both-good pairs must route to review, never pass ------------------
    both_good_reviewed = 0
    for _ in range(3):
        out = run_pair([_payload(5.0, 4.0, None), _payload(4.0, 5.0, None)], swap=False)
        if getattr(out, "verdict", "") != "valid":
            both_good_reviewed += 1

    # --- identical-pair rejection ------------------------------------------
    ident_rejected = 0
    for _ in range(3):
        out = run_pair([_payload(5.0, 5.0, None), _payload(5.0, 5.0, None)], swap=False)
        if getattr(out, "verdict", "") != "valid":
            ident_rejected += 1

    # --- near-duplicate rejection (cosmetic edit, equal scores) ------------
    nd_rejected = 0
    for _ in range(3):
        gw = _ScriptedPairwiseGateway([_payload(5.0, 5.0, None), _payload(5.0, 5.0, None)])
        judge = CertifiedPairwiseJudge(gw, model="bench-judge/deterministic")
        loop = asyncio.new_event_loop()
        try:
            out = loop.run_until_complete(
                judge.judge_pair(
                    prompt=prompt,
                    chosen_text=chosen,
                    rejected_text=chosen + " Indeed.",
                    evidence_text=evidence,
                )
            )
        finally:
            loop.close()
        if getattr(out, "verdict", "") != "valid":
            nd_rejected += 1

    # --- information-gain gate ---------------------------------------------
    no_signal = [
        ("", "What is calibration?", "Calibration"),
        ("I cannot answer that question.", "What is calibration?", "Calibration"),
        ("Calibration is important.", "Why does calibration matter?", "Calibration"),
    ]
    ig_rejected = sum(
        1
        for ans, pr, hd in no_signal
        if assess_information_gain(ans, prompt=pr, heading=hd).score <= 0.35
    )
    substantive = [
        (
            "Calibration takes 40 minutes per unit and must be repeated annually.",
            "How long does calibration take?",
            "Calibration",
        ),
        (
            "Factory calibration verifies gauge accuracy against a reference standard.",
            "What does factory calibration do?",
            "Calibration",
        ),
    ]
    ig_kept = sum(
        1
        for ans, pr, hd in substantive
        if assess_information_gain(ans, prompt=pr, heading=hd).score > 0.35
    )

    return {
        "judge": "CertifiedPairwiseJudge over deterministic scripted scores "
        "(live-judge certification not measured here)",
        "order_consistency": _rate_with_ci(consistent, n_pairs),
        "both_good_routed_to_review": _rate_with_ci(both_good_reviewed, 3),
        "identical_pair_rejection": _rate_with_ci(ident_rejected, 3),
        "near_duplicate_rejection": _rate_with_ci(nd_rejected, 3),
        "information_gain_no_signal_rejection": _rate_with_ci(ig_rejected, len(no_signal)),
        "information_gain_substantive_retention": _rate_with_ci(ig_kept, len(substantive)),
    }


# --------------------------------------------------------------------------
# 4. crash-recovery scenario (methodology §12)
# --------------------------------------------------------------------------

_CRASH_SECTIONS = [
    ("# Widget handbook", "A widget converts pressure into rotation. The valve regulates intake."),
    (
        "## Maintenance",
        "Inspect the valve monthly. Replace the gasket when pressure drops below 2 bar.",
    ),
    ("## Assembly", "Seat the rotor, torque the housing to 12 Nm, then calibrate the governor."),
    ("## Comparison", "Compared with rotor-X, the rotor-Y runs cooler but delivers less torque."),
    (
        "## Troubleshooting",
        "If the governor oscillates, check the spring tension and the intake screen.",
    ),
    ("## Lubrication", "Apply synthetic grease to the bearing race every 500 operating hours."),
    ("## Storage", "Store widgets in a dry room below 30 C. Keep the valve open during storage."),
]
_CRASH_SOURCE = "\n\n".join(f"{h}\n\n{b}" for h, b in _CRASH_SECTIONS)


def crash_recovery_metrics() -> dict[str, object]:
    """Kill a worker mid-pipeline (hard provider failure), reclaim via lease
    expiry, resume — then verify no double payment and no duplicate cost
    events (the chaos-tier guarantee, exercised as a measured scenario)."""
    from datetime import timedelta

    from knovaryn.application.service import ProjectService
    from knovaryn.application.workspace import Workspace
    from knovaryn.domain.errors import KnovarynError
    from knovaryn.domain.ids import IdGenerator
    from knovaryn.domain.schemas import DatasetPlan, JobState
    from knovaryn.infrastructure.artifacts.local import LocalArtifactStore
    from knovaryn.infrastructure.database.repositories import (
        JobRepository,
        ModelCallRepository,
        ProjectRepository,
        SourceRepository,
    )
    from knovaryn.infrastructure.models.call_cache import CallCache
    from knovaryn.infrastructure.models.fake_provider import FakeProvider
    from knovaryn.infrastructure.models.gateway import ModelGateway
    from knovaryn.pipeline.jobs.engine import JobEngine
    from knovaryn.pipeline.jobs.retry import RetryPolicy
    from knovaryn.pipeline.jobs.worker import WorkerRepository

    class WorkerDied(KnovarynError):
        code = "worker_died"

        def __init__(self) -> None:
            super().__init__("worker process killed mid-pipeline")

    class CrashingFake(FakeProvider):
        def __init__(self, crash_after: int, **kw):
            super().__init__(**kw)
            self.calls: list[dict] = []
            self.crash_after = crash_after

        async def complete(self, **kw):
            if len(self.calls) >= self.crash_after:
                raise WorkerDied()
            self.calls.append(dict(kw))
            return await super().complete(**kw)

    class CountingFake(FakeProvider):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.calls: list[dict] = []

        async def complete(self, **kw):
            self.calls.append(dict(kw))
            return await super().complete(**kw)

    class LedgerAdapter:
        def __init__(self, db, ids):
            self._db, self._ids = db, ids

        async def _op(self, method, *args):
            async with self._db.session() as session, session.begin():
                return await getattr(ModelCallRepository(session, self._ids), method)(*args)

        async def record(self, call):
            await self._op("record", call)

        async def get_by_fingerprint(self, job_id, fingerprint):
            return await self._op("get_by_fingerprint", job_id, fingerprint)

    async def scenario(root: Path) -> dict[str, object]:
        ids = IdGenerator()
        ws = Workspace(database_url=f"sqlite+aiosqlite:///{root / 'crash.db'}", principal="bench")
        await ws.open()
        try:
            proj = await ws.create_project(slug="crash", display_name="Crash Resume")
            await ws.add_source(
                project_id=proj.id,
                original_name="handbook.md",
                media_type="text/markdown",
                content=_CRASH_SOURCE,
            )
            job = await ws.start_pipeline(project_id=proj.id, task_family_proportions={})
            repo = WorkerRepository(ws._db, ids)

            async def stage(ctx):
                async with ws._db.session() as session, session.begin():
                    project = await ProjectRepository(session, ids).get(ctx.job.project_id)
                    sources, contents = [], []
                    for sid in (ctx.job.input or {}).get("source_ids") or []:
                        src = await SourceRepository(session).get(sid)
                        if src is not None:
                            sources.append(src)
                            contents.append((src.metadata or {}).get("content", "") or "")
                plan = DatasetPlan(
                    task_family_proportions={
                        "factual_explanation": 0.5,
                        "procedure": 0.3,
                        "comparison": 0.2,
                    }
                )
                gateway = ModelGateway(
                    generator_model="fake",
                    critic_model="fake",
                    verifier_model="fake",
                    fake=provider_box["fake"],
                    call_cache=CallCache(store=LocalArtifactStore(root / "artifacts")),
                    model_call_repo=LedgerAdapter(ws._db, ids),
                    project_id=ctx.job.project_id,
                    job_id=ctx.job.id,
                    stage="generate",
                )
                svc = ProjectService(ids=ids, gateway=gateway)
                result = await svc.run_pipeline(
                    project=project, sources=sources, contents=contents, plan=plan
                )
                await ctx.checkpoint("pipeline", step=1, key="result", value=result.to_dict())
                return result.to_dict()

            # pass A: claim, start, die hard mid-pipeline
            provider_box = {"fake": CrashingFake(crash_after=2)}
            claimed = await repo.claim_eligible(worker="worker-a", lease_seconds=300)
            assert claimed is not None and claimed.id == job.id
            claimed.state = JobState.running
            await repo.save(claimed)

            class Ctx:
                job = claimed
                checkpoint_sequence = 0

                async def checkpoint(self, *a, **k):
                    raise AssertionError("pass A must die before any checkpoint commits")

            died = False
            try:
                await stage(Ctx())
            except WorkerDied:
                died = True
            crash_calls = len(provider_box["fake"].calls)

            # nothing cleans up; expire the lease like wall-clock would
            async with ws._db.session() as session, session.begin():
                jrepo = JobRepository(session, ids)
                orphan = await jrepo.get(job.id)
                assert orphan is not None and orphan.state == JobState.running
                orphan.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                await jrepo.save(orphan)

            # pass B: replacement worker reclaims + resumes to success
            reclaimed = await repo.claim_eligible(worker="worker-b", lease_seconds=300)
            resumed_ok = reclaimed is not None and reclaimed.id == job.id
            out: dict[str, object] = {"crashed_mid_pipeline": died}
            if not resumed_ok:
                out.update(
                    {
                        "crash_resume_success": 0,
                        "duplicate_provider_calls": None,
                        "duplicate_cost_events": None,
                    }
                )
                return out

            provider_box["fake"] = CountingFake()
            engine = JobEngine(ids=ids, repo=repo, retry_policy=RetryPolicy())
            result = await engine.run(
                reclaimed, [("pipeline", stage)], services={"job.input": reclaimed.input}
            )
            resumed_ok = result.state == JobState.succeeded

            from sqlalchemy import select

            from knovaryn.infrastructure.database.models import ModelCallDB

            async with ws._db.session() as session:
                fps = list(
                    (
                        await session.execute(
                            select(ModelCallDB.request_fingerprint).where(
                                ModelCallDB.job_id == job.id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            total_invocations = crash_calls + len(provider_box["fake"].calls)
            unique_fps = set(fps)
            out.update(
                {
                    "crash_resume_success": 1 if resumed_ok else 0,
                    "provider_invocations_total": total_invocations,
                    "unique_request_fingerprints": len(unique_fps),
                    "duplicate_provider_calls": max(0, total_invocations - len(unique_fps)),
                    "duplicate_cost_events": max(0, len(fps) - len(unique_fps)),
                }
            )
            return out
        finally:
            await ws.close()

    with tempfile.TemporaryDirectory(prefix="knv-bench-crash-") as td:
        return asyncio.new_event_loop().run_until_complete(scenario(Path(td)))


# --------------------------------------------------------------------------
# 5. environment record (methodology §3)
# --------------------------------------------------------------------------


def _commit_sha() -> str | None:
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=15,
        )
        return out.stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def environment_record(version: str) -> dict[str, object]:
    uname = platform.uname()
    return {
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "os": f"{uname.system} {uname.release}",
        "os_version_build": uname.version,
        "machine": uname.machine,
        "python": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "cpu_count": __import__("os").cpu_count(),
        "knovaryn_version": version,
        "commit_sha": _commit_sha(),
        "provider": "FakeProvider (deterministic, zero-cost)",
        "optional_extras_detected": {
            name: _module_available(name)
            for name in ("docling", "docetl", "litellm", "boto3", "psycopg", "mcp")
        },
        "notes": [
            "offline deterministic run; no network, no API keys",
            "live-provider cost/quality NOT measured",
        ],
    }


# --------------------------------------------------------------------------
# 6. repetition driver, aggregate, checksums, verification
# --------------------------------------------------------------------------

_DIGEST_SENSITIVE_KEYS = ("release_bundle_sha256",)


def build_run(run_index: int) -> dict[str, object]:
    m: dict[str, object] = {}
    m.update(asyncio.new_event_loop().run_until_complete(pipeline_metrics()))
    m["semantic_adversarial"] = semantic_adversarial()
    m["preference_quality"] = preference_metrics()
    m["crash_recovery"] = crash_recovery_metrics()
    m["run"] = run_index
    return m


def aggregate(runs: list[dict[str, object]]) -> dict[str, object]:
    med_keys = ("elapsed_s", "examples_per_second", "peak_allocated_bytes")
    agg: dict[str, object] = {"runs": len(runs)}
    for key in med_keys:
        vals = sorted(float(r[key]) for r in runs)  # type: ignore[arg-type]
        mid = len(vals) // 2
        median = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
        agg[key] = {"median": _r(median), "per_run": [_r(v) for v in vals]}

    digests = {r["release_bundle_sha256"] for r in runs}  # type: ignore[arg-type]
    agg["release_bundle_sha256_values"] = sorted(str(d) for d in digests)
    agg["digest_equality_H_R1_eq_H_R2_eq_H_R3"] = len(digests) == 1
    agg["release_bundle_bytes"] = runs[0]["release_bundle_bytes"]
    agg["reproducible_mode"] = "deterministic fake provider; fixed seeds; committed corpus"
    agg["not_measured"] = {
        "live_provider_cost": "no live provider invoked by this runner",
        "live_provider_quality": "no live provider invoked by this runner",
        "docling_layout_ocr": "docling extra availability recorded in environment.json; "
        "layout/OCR corpus requires the extra",
        "postgres_minio_e2e": "executed separately by deploy-e2e workflow / compose E2E; "
        "cited by the narrative report when run",
        "mcp_dual_sdk_lifecycle": "executed separately by scripts/mcp_acceptance_matrix.py; "
        "cited by the narrative report",
    }
    return agg


def write_results(out_dir: Path, version: str, runs: list[dict[str, object]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = environment_record(version)
    (out_dir / "environment.json").write_text(json.dumps(env, indent=2) + "\n")
    for i, r in enumerate(runs, 1):
        (out_dir / f"run-{i}.json").write_text(json.dumps(r, indent=2) + "\n")
    agg = aggregate(runs)
    (out_dir / "aggregate.json").write_text(json.dumps(agg, indent=2) + "\n")

    names = [
        "environment.json",
        *[f"run-{i}.json" for i in range(1, len(runs) + 1)],
        "aggregate.json",
    ]
    lines = [f"{hashlib.sha256((out_dir / n).read_bytes()).hexdigest()}  {n}" for n in names]
    (out_dir / "checksums.txt").write_text("\n".join(lines) + "\n")

    readme = f"""# Benchmark results — knovaryn {version}

Produced on {env["generated_at_utc"]} by `benchmarks/run_report.py`
(methodology v2: `docs/reference/benchmark-methodology.md`) on commit
`{env["commit_sha"]}`.

- `environment.json` — machine/software record
- `run-1..{len(runs)}.json` — per-repetition metrics (deterministic inputs;
  only timing/memory vary between repetitions)
- `aggregate.json` — medians, release-digest equality verdict, explicit
  *not measured* items
- `checksums.txt` — SHA-256 of every file above

Offline deterministic framework benchmark. Not live-model generation
throughput. Reproduce with:

```bash
uv run python benchmarks/run_report.py --version {version} --runs {len(runs)}
```

then compare `release_bundle_sha256_values` (must be length 1) and spot-check
counts against the committed files.
"""
    (out_dir / "README.md").write_text(readme)


def check_results(dir_: Path) -> int:
    """Verify a committed results directory: checksums + digest equality.

    Also (§25 hostile-audit hardening) enforces the methodology's run count
    and recomputes every aggregate median from the per-run files, so a
    trimmed or hand-edited directory cannot pass.
    """
    ok = True
    for line in (dir_ / "checksums.txt").read_text().splitlines():
        digest, name = line.split("  ", 1)
        actual = hashlib.sha256((dir_ / name).read_bytes()).hexdigest()
        if actual != digest:
            print(f"CHECKSUM MISMATCH: {name}")
            ok = False
    agg = json.loads((dir_ / "aggregate.json").read_text())
    if not agg.get("digest_equality_H_R1_eq_H_R2_eq_H_R3"):
        print("DIGEST EQUALITY FAILED:", agg.get("release_bundle_sha256_values"))
        ok = False
    run_files = sorted(dir_.glob("run-*.json"))
    for rf in run_files:
        r = json.loads(rf.read_text())
        if r.get("release_bundle_sha256") != agg["release_bundle_sha256_values"][0]:
            print(f"DIGEST DRIFT in {rf.name}")
            ok = False

    expected_runs = agg.get("runs")
    if expected_runs is None or len(run_files) != expected_runs:
        print(f"RUN COUNT: aggregate says {expected_runs!r}, found {len(run_files)} run files")
        ok = False
    elif expected_runs != EXPECTED_RUNS:
        print(f"RUN COUNT: {expected_runs} below the methodology's {EXPECTED_RUNS}-run minimum")
        ok = False

    # recompute medians of every scalar metric from the run files and compare
    # against the aggregate's stored medians
    metrics: dict[str, list] = {}
    for rf in run_files:
        r = json.loads(rf.read_text())
        for k, v in r.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                metrics.setdefault(k, []).append(v)
    for key, values in sorted(metrics.items()):
        if len(values) != expected_runs:
            continue
        stored = agg.get(key, {})
        if not isinstance(stored, dict) or "median" not in stored:
            continue
        recomputed = _r(
            sorted(values)[len(values) // 2]
            if len(values) % 2
            else _r((sorted(values)[len(values) // 2 - 1] + sorted(values)[len(values) // 2]) / 2)
        )
        if recomputed != stored["median"]:
            print(f"MEDIAN MISMATCH: {key}: recomputed {recomputed} != stored {stored['median']}")
            ok = False

    print("results directory VERIFIED" if ok else "results directory FAILED")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=None, help="knovaryn version label")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--out", default=None, help="output dir (default benchmarks/results/<v>)")
    parser.add_argument(
        "--check", metavar="DIR", default=None, help="verify an existing results directory and exit"
    )
    args = parser.parse_args()

    if args.check:
        return check_results(Path(args.check))

    sys.path.insert(0, str(REPO_ROOT / "src"))
    from knovaryn import __version__

    version = args.version or __version__
    out_dir = Path(args.out) if args.out else REPO_ROOT / "benchmarks" / "results" / version

    print(
        f"Knovaryn benchmark runner (methodology v2) — knovaryn {version}, {args.runs} repetitions"
    )
    warmup = asyncio.new_event_loop().run_until_complete(pipeline_metrics())
    print(f"  warmup done ({warmup['examples']} examples; discarded)")

    runs = []
    for i in range(1, args.runs + 1):
        t0 = time.monotonic()
        runs.append(build_run(i))
        print(
            f"  run-{i}: {time.monotonic() - t0:.1f}s "
            f"bundle={runs[-1]['release_bundle_bytes']}B "
            f"sha={str(runs[-1]['release_bundle_sha256'])[:12]}…"
        )

    write_results(out_dir, version, runs)
    agg = aggregate(runs)
    print(f"wrote {out_dir}")
    print(f"  digest equality H(R1)=H(R2)=H(R3): {agg['digest_equality_H_R1_eq_H_R2_eq_H_R3']}")
    return 0 if agg["digest_equality_H_R1_eq_H_R2_eq_H_R3"] else 1


if __name__ == "__main__":
    sys.exit(main())
