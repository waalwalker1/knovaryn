"""Core ports (spec §5.4).

Typed Protocols the application/pipeline depend on. Infrastructure provides
implementations. No external framework types leak through these.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Protocol, runtime_checkable


class Clock(Protocol):
    def utc_now(self) -> Any: ...  # datetime


class IdGenerator(Protocol):
    def new(self) -> str: ...
    def new_handle(self, prefix: str) -> str: ...
    def new_token(self, *, nbytes: int = 32) -> str: ...


class EventSink(Protocol):
    """Append-only structured event log (jobs, audit)."""

    async def emit(
        self,
        *,
        scope: str,
        key: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None: ...


class ArtifactStore(Protocol):
    """Content-addressed immutable artifact storage."""

    async def put(
        self,
        data: bytes,
        *,
        media_type: str,
        producer: dict[str, Any],
        parents: list[str] | None = None,
        privacy: str = "restricted",
    ) -> dict[str, Any]: ...
    async def get(self, artifact_id: str) -> bytes: ...
    async def get_meta(self, artifact_id: str) -> dict[str, Any]: ...
    async def put_stream(self, producer: dict[str, Any], *, media_type: str, parent: str | None = None):
        """Return an async writer for large artifacts."""
        ...
    async def exists(self, artifact_id: str) -> bool: ...


class ProjectRepository(Protocol):
    async def create(self, project: Any) -> Any: ...
    async def get(self, project_id: str) -> Any | None: ...
    async def get_by_slug(self, slug: str) -> Any | None: ...
    async def list_(self, *, limit: int, cursor: str | None) -> tuple[list[Any], str | None]: ...
    async def save(self, project: Any) -> None: ...


class JobRepository(Protocol):
    async def create(self, job: Any) -> Any: ...
    async def get(self, job_id: str) -> Any | None: ...
    async def save(self, job: Any) -> None: ...
    async def claim_eligible(self, *, worker: str) -> Any | None: ...
    async def list_(self, *, project_id: str | None, limit: int, cursor: str | None) -> tuple[list[Any], str | None]: ...
    async def append_event(self, job_id: str, event: Any) -> None: ...
    async def get_events(self, job_id: str, *, cursor: int | None, limit: int) -> tuple[list[Any], int | None]: ...


class DocumentParser(Protocol):
    async def parse(self, source: Any, *, config: dict[str, Any]) -> Any: ...


class Chunker(Protocol):
    async def chunk(self, parsed: Any, *, config: dict[str, Any]) -> Any: ...


class ModelGateway(Protocol):
    """Normalized LLM completion, capability-aware."""

    async def complete(self, request: Any, *, cache_key: str | None = None) -> Any: ...
    async def supports(self, capability: str) -> bool: ...


class EmbeddingGateway(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class Validator(Protocol):
    name: str
    version: str
    async def validate(self, example: Any, *, context: dict[str, Any]) -> Any: ...


class Judge(Protocol):
    """Model-assisted or heuristic judge returning a scored assessment."""

    async def assess(self, *, prompt: Any, evidence: Any, responses: dict[str, Any]) -> Any: ...


class PIIScanner(Protocol):
    async def scan(self, text: str) -> Any: ...


class LicensePolicy(Protocol):
    async def evaluate(self, source: Any, *, declared: str | None) -> Any: ...


class DatasetExporter(Protocol):
    name: str
    async def export(self, version: Any, *, writer: Any, options: dict[str, Any]) -> Any: ...


class Publisher(Protocol):
    async def dry_run(self, version: Any, *, options: dict[str, Any]) -> Any: ...
    async def publish(self, version: Any, *, confirmation: str, options: dict[str, Any]) -> Any: ...


class CostEstimator(Protocol):
    def estimate(self, *, plan: Any, profile: Any) -> Any: ...
