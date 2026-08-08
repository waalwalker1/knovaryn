"""Resource / accelerator policy (spec §9.3).

Deterministic, environment-aware selection of an accelerator profile for
parsing and inference. Pure capability detection; never guesses hardware that
is absent. The doctor command surfaces the effective profile.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ResourceProfile:
    accelerator: str = "cpu"  # cpu | mps | cuda
    device_count: int = 0
    note: str = ""
    ocr_thread_pool: int = 2
    warmup_models: bool = False


def detect_resource_profile(*, prefer_cuda: bool = True) -> ResourceProfile:
    """Detect the best available accelerator (no network)."""
    if prefer_cuda and _cuda_available():
        return ResourceProfile(accelerator="cuda", device_count=_cuda_count(), note="CUDA detected", warmup_models=True, ocr_thread_pool=4)
    if _mps_available():
        return ResourceProfile(accelerator="mps", device_count=1, note="Apple Silicon MPS detected", ocr_thread_pool=3)
    return ResourceProfile(accelerator="cpu", device_count=0, note="CPU-only profile; heavy extras optional", ocr_thread_pool=2)


def _cuda_available() -> bool:
    if os.environ.get("KNOVARYN_FORCE_CPU"):
        return False
    try:
        import torch  # noqa: F401

        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        return False


def _cuda_count() -> int:
    try:
        import torch  # noqa: F401

        return int(torch.cuda.device_count())
    except Exception:  # noqa: BLE001
        return 0


def _mps_available() -> bool:
    if os.environ.get("KNOVARYN_FORCE_CPU"):
        return False
    if not (sys_platform() == "darwin"):
        return False
    try:
        import torch  # noqa: F401

        return bool(torch.backends.mps.is_available())
    except Exception:  # noqa: BLE001
        return False


def sys_platform() -> str:
    import sys

    return sys.platform
