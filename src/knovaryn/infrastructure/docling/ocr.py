"""OCR policy (spec §9.2).

Modes: off (native text only), auto (detect pages with insufficient/suspicious
native text), on (OCR all eligible pages), force_engine. Engines discovered via
capability detection (RapidOCR/Tesseract/EasyOCR/OS-native); none is claimed to
be universally best.
"""

from __future__ import annotations

from dataclasses import dataclass


class OCRMode:
    OFF = "off"
    AUTO = "auto"
    ON = "on"
    FORCE_ENGINE = "force_engine"


@dataclass
class OCRProfile:
    mode: str = OCRMode.AUTO
    engine: str | None = None
    min_native_chars_per_page: int = 40
    suspicious_ratio: float = 0.05  # fraction of pages that look empty before forcing

    def effective_mode(self) -> str:
        return self.mode


def detect_available_ocr_engines() -> list[str]:
    """Return engines importable in this environment (best-effort)."""
    engines: list[str] = []
    if _importable("rapidocr_onnxruntime"):
        engines.append("rapidocr")
    if _importable("pytesseract"):
        engines.append("tesseract")
    if _importable("easyocr"):
        engines.append("easyocr")
    return engines


def needs_ocr(mode: str, *, native_chars: int, page_index: int, engine_engines: list[str]) -> bool:
    if mode == OCRMode.OFF:
        return False
    if mode == OCRMode.ON or mode == OCRMode.FORCE_ENGINE:
        return bool(engine_engines)
    if mode == OCRMode.AUTO:
        if not engine_engines:
            return False
        return native_chars < 40  # configurable minimum
    return False


def _importable(module: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(module) is not None
