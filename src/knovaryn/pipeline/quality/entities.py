"""Entity validation utilities (WP A2).

Functions for checking entity-role consistency and detecting
subject/object reversals between claims and evidence.
"""

from .claims import (
    check_entity_role_reversal,
    check_unsupported_entities,
    detect_causal_direction,
)

__all__ = [
    "check_entity_role_reversal",
    "check_unsupported_entities",
    "detect_causal_direction",
]
