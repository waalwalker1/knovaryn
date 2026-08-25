"""Typed REST request/response models (spec §17.3, WP J1).

Pydantic request bodies give the OpenAPI schema a concrete, validated surface
and turn malformed payloads into HTTP ``422`` automatically (J2). Review
decisions reuse the canonical ``ReviewDecision`` values (approve / reject /
needs_work) so the REST interface shares the exact same policy surface as the
CLI, MCP, and SDK — no interface reimplements its own review semantics
(contract rule for a single shared application-service path).
"""

from __future__ import annotations

import base64
import binascii
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Decision = Literal["approve", "reject", "needs_work"]

MAX_NAME = 200
MAX_NOTE = 4000


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")]
    display_name: Annotated[str, Field(min_length=1, max_length=MAX_NAME)]
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class SourceAdd(BaseModel):
    """Add a text/binary source through the secure intake funnel.

    Binary uploads are carried as ``raw`` (base64/octet bytes); text callers
    pass ``content``. ``declared_license`` and ``privacy`` are the operator's
    required declarations (J6); the intake pipeline still independently detects
    and gates both (defense in depth, rule 6 — never accept a declaration as
    truth without an authoritative check).
    """

    model_config = ConfigDict(extra="forbid")

    original_name: Annotated[str, Field(min_length=1, max_length=MAX_NAME)]
    media_type: str | None = None
    content: str | None = None
    raw: bytes | None = None
    declared_license: str | None = None

    @field_validator("raw", mode="before")
    @classmethod
    def _decode_raw_b64(cls, v: object) -> object:
        """Decode the JSON carrier into the true bytes.

        Over HTTP ``raw`` always arrives as a base64 string; neither pydantic
        lax coercion (str → UTF-8 bytes) nor JSON-mode validation decodes it,
        so without this validator intake would hash and store the base64
        *text* while the caller meant the binary — corrupting sha256,
        byte_size, media sniffing, and the stored original artifact.
        """
        if v is None or isinstance(v, (bytes, bytearray, memoryview)):
            return v
        if isinstance(v, str):
            try:
                return base64.b64decode(v.encode("ascii"), validate=True)
            except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
                raise ValueError("raw must be standard base64-encoded bytes") from exc
        return v

    declared_license: str | None = None
    privacy: str | None = Field(
        default=None,
        description="operator declaration, e.g. 'public' / 'internal'; advisory only",
    )


class PipelineStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_family_proportions: dict[str, float] | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)
    profile: str | None = None
    budget_max_usd: float | None = None
    target_examples: int | None = Field(default=None, ge=1)


class ReviewRequest(BaseModel):
    """Review an example by appending an immutable revision (H1/H2/P0-9).

    Mirrors the canonical ``ReviewService`` contract: ``decision`` is
    approve/reject/needs_work and the caller may supply a ``concurrency_token``
    from the base revision for optimistic concurrency (409 on a stale token).
    """

    model_config = ConfigDict(extra="forbid")

    decision: Decision
    note: Annotated[str, Field(max_length=MAX_NOTE)] = ""
    revision_id: int | None = Field(default=None, ge=1, description="base revision to review")
    concurrency_token: str | None = None
    policy_version: str = ""


class VersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantic_version: str | None = Field(
        default=None, max_length=64, pattern=r"^\d+\.\d+(\.\d+)?([-+][A-Za-z0-9.]+)?$"
    )


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: str | None = None


class PublishRequest(BaseModel):
    """Publication request. Dry-run is the default; a live publish requires an
    explicit ``confirm=True`` (never publish without the owner's explicit
    authorization — contract rule 22)."""

    model_config = ConfigDict(extra="forbid")

    repo_id: Annotated[str, Field(min_length=1, max_length=256)]
    dry_run: bool = True
    confirm: bool = False
