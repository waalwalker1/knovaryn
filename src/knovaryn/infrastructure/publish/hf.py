"""Hugging Face publication (spec §16.3).

Publishes a release bundle to a Hugging Face Hub dataset repository. This is an
outward-facing action: publication requires the ``knovaryn[hub]`` extra, a
``HF_TOKEN`` (or explicit repo credentials), AND an explicit ``authorized=True``
flag — Knovaryn never publishes autonomously. Without the extra or token it
raises a typed ConfigurationError rather than pretending success.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from typing import Any

from ...domain.errors import ConfigurationError, PolicyBlockError


def hub_available() -> bool:
    return importlib.util.find_spec("huggingface_hub") is not None


@dataclass
class PublicationRecord:
    repo_id: str
    version: str
    revision: str = ""
    url: str = ""


class HFPublisher:
    name = "huggingface"
    version = "1"

    def __init__(self, *, repo_id: str, token: str | None = None, authorized: bool = False) -> None:
        self.repo_id = repo_id
        self.token = token or os.environ.get("HF_TOKEN")
        self.authorized = authorized
        if not hub_available():
            raise ConfigurationError(
                "Hugging Face publication requires the 'knovaryn[hub]' extra "
                "(huggingface_hub). Install the extra to enable publication."
            )

    def _require_authorization(self, *, action: str) -> None:
        if not self.authorized:
            raise PolicyBlockError(
                f"Refusing to publish to Hugging Face ({action}). Explicit authorization "
                "is required before any external publication. Pass authorized=True and "
                "confirm the target repo."
            )
        if not self.token:
            raise ConfigurationError(
                "No Hugging Face token configured. Set HF_TOKEN or pass token= to publish."
            )

    def publish_bundle(self, bundle: Any, *, message: str = "") -> PublicationRecord:
        """Upload a release bundle to the configured repository.

        The bundle is materialized to a temp dir and uploaded with huggingface_hub.
        This method is synchronous to match the simple hub client.
        """
        self._require_authorization(action=self.repo_id)
        from huggingface_hub import HfApi, create_repo

        api = HfApi(token=self.token, endpoint="https://huggingface.co")
        try:
            create_repo(self.repo_id, repo_type="dataset", token=self.token, exist_ok=True)
        except Exception as exc:  # noqa: BLE001 - surface as typed error
            raise ConfigurationError(f"could not create/access repo {self.repo_id}: {exc}") from exc

        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "release.zip").write_bytes(bundle.to_zip())
            for logical, data in bundle.files.items():
                safe_path = root / logical
                safe_path.parent.mkdir(parents=True, exist_ok=True)
                safe_path.write_bytes(data)
            api.upload_folder(
                folder_path=str(root),
                repo_id=self.repo_id,
                repo_type="dataset",
                token=self.token,
                commit_message=message or f"Knovaryn release {bundle.version}",
            )

        revision = api.model_info(self.repo_id, repo_type="dataset", token=self.token).sha
        url = f"https://huggingface.co/datasets/{self.repo_id}"
        return PublicationRecord(repo_id=self.repo_id, version=bundle.version, revision=revision, url=url)
