"""Typed domain errors.

Every error carries a stable machine code and a sanitized public message.
No secrets or raw document content in messages.
"""

from __future__ import annotations

from typing import Any


class KnovarynError(Exception):
    """Base error with a stable code."""

    code = "knovaryn_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def as_public_dict(self) -> dict[str, Any]:
        """Sanitized, serializable representation (safe for MCP/REST)."""
        return {"code": self.code, "message": self.message}


class ConfigurationError(KnovarynError):
    code = "configuration_error"


class NotFoundError(KnovarynError):
    code = "not_found"


class AlreadyExistsError(KnovarynError):
    code = "already_exists"


class ValidationError(KnovarynError):
    code = "validation_error"


class PolicyBlockError(KnovarynError):
    """A source or example was blocked by a policy (license/privacy/quality)."""

    code = "policy_block"

    def __init__(
        self,
        reason_codes: list[str],
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        if message is None:
            message = "Blocked by policy: " + ", ".join(reason_codes)
        self.reason_codes = reason_codes
        super().__init__(message, details=details)


class IntakeError(KnovarynError):
    """Unsafe or malformed source."""

    code = "intake_error"


class PathTraversalError(IntakeError):
    code = "path_traversal"


class ArchiveBombError(IntakeError):
    code = "archive_bomb"


class SSRFError(IntakeError):
    code = "ssrf_block"


class MalwareScanError(IntakeError):
    """A configured malware scanner reported a positive on a source."""

    code = "malware_scan"


class ProviderError(KnovarynError):
    """Model provider failure, possibly retryable."""

    code = "provider_error"

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.retryable = retryable
        super().__init__(message, details=details)


class BudgetExceededError(KnovarynError):
    """Hard budget would be exceeded; job must pause."""

    code = "budget_exhausted"


class ConcurrencyError(KnovarynError):
    """Optimistic-concurrency conflict on review/edits."""

    code = "concurrency_conflict"


class AuthorizationError(KnovarynError):
    code = "authorization_error"


class UnsupportedOperationError(KnovarynError):
    code = "unsupported_operation"


class JobStateError(KnovarynError):
    code = "job_state_error"


class ExportError(KnovarynError):
    code = "export_error"


class CorruptedArtifactError(KnovarynError):
    code = "corrupted_artifact"


class RateLimitError(KnovarynError):
    """A configured abuse-control budget was exceeded (HTTP 429).

    Raised when a per-principal request budget, concurrent-job cap, provider-call
    cap, or publication-attempt cap is exhausted (spec §17.4, WP J7).
    """

    code = "rate_limited"
