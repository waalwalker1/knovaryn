"""Numeric validation utilities (WP A2).

Functions for normalizing and comparing numbers, units, and dates
across evidence and candidate answers.
"""

from .claims import (
    NormalizedDate,
    NormalizedNumber,
    NormalizedUnit,
    normalize_date,
    normalize_number_text,
    normalize_unit,
)

__all__ = [
    "NormalizedNumber",
    "NormalizedDate",
    "NormalizedUnit",
    "normalize_number_text",
    "normalize_unit",
    "normalize_date",
]
