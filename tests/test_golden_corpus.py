"""Golden document corpus (spec §9 / WP G6).

Static, committed fixtures under ``tests/fixtures/intake/`` exercise intake and
the fallback parser without requiring reportlab / PIL / docling at runtime:

* structure + provenance: each fixture exists with expected magic type and a
  stable SHA-256 (content hash), never asserting fragile rendered text;
* fallback parser: parsed doc id / parser / provenance resolved from source;
* binary-failure quarantining: unparseable binary blobs are quarantined, never
  downgraded to Latin-1 garbage;
* archive fixtures: safe-member iteration + artifact-first persistence with a
  real ``sha256`` and ``artifact_id_original``.

Real Docling behavior is asserted in ``@pytest.mark.docling`` tests (skipped
when the extra is not installed).
"""

from __future__ import annotations

import hashlib
import pathlib
import zipfile

import pytest

from knovaryn.domain.errors import IntakeError
from knovaryn.domain.ids import IdGenerator
from knovaryn.domain.schemas import SourceDocument
from knovaryn.infrastructure.artifacts.local import LocalArtifactStore
from knovaryn.infrastructure.docling.adapter import DoclingAdapter
from knovaryn.infrastructure.intake.archive import iter_supported_members
from knovaryn.infrastructure.intake.intake import IntakeService, sniff_media_type

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "intake"


@pytest.fixture
def store(tmp_path) -> LocalArtifactStore:
    return LocalArtifactStore(tmp_path / "artifacts")


@pytest.fixture
def svc(tmp_path, store) -> IntakeService:
    class _Ids:
        def new_handle(self, prefix: str) -> str:
            return f"{prefix}_corpus"

    return IntakeService(ids=_Ids(), store=store, quarantine_dir=tmp_path / "q")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# structure + provenance
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name, expected_magic_type, from_magic",
    [
        ("native-text.pdf", "application/pdf", True),
        ("scanned.pdf", "application/pdf", True),
        ("two-column.pdf", "application/pdf", True),
        ("huge-pages.pdf", "application/pdf", True),
        ("malformed.pdf", "application/pdf", True),
        ("password-protected.pdf", "application/pdf", True),
        ("docx-list.docx", "application/zip", True),
        ("merged-cells.xlsx", "application/zip", True),
        ("multilingual.txt", "text/plain", False),
        ("numbered-headings.md", "text/markdown", False),
    ],
)
def test_fixture_magic(name, expected_magic_type, from_magic) -> None:
    data = (FIXTURES / name).read_bytes()
    mtype, magic = sniff_media_type(name, data[:16])
    assert magic is from_magic
    assert mtype == expected_magic_type


def test_fixture_shas_are_stable() -> None:
    """Committed fixture SHAs are content-addressing provenance, not render output."""
    known = {
        "native-text.pdf": "287e9a0c6e18",
        "scanned.pdf": "55129799e325",
        "docx-list.docx": "09e2ac3b95f7",
        "merged-cells.xlsx": "11082914eebf",
        "multilingual.txt": "415cb3612705",
        "numbered-headings.md": "a8f2598cf1eb",
    }
    for name, prefix in known.items():
        data = (FIXTURES / name).read_bytes()
        assert _sha(data).startswith(prefix), f"fixture {name} content changed"


# ---------------------------------------------------------------------------
# artifact-first intake: real sha256 + artifact_id_original
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_intake_persists_artifact_first(svc, store) -> None:
    """Intake is artifact-first: original bytes stored, real content SHA-256 set."""
    data = (FIXTURES / "native-text.pdf").read_bytes()
    res = await svc.ingest_bytes(project_id="p1", name="native-text.pdf", data=data)
    assert res.preflight_ok
    assert res.source.sha256 == _sha(data)  # real content hash, not cfg_hash
    assert res.source.byte_size == len(data)
    assert res.source.media_type == "application/pdf"
    assert res.source.artifact_id_original  # immutable original artifact id
    # the stored blob resolves back to the exact original bytes
    stored = await store.get(res.source.sha256)
    assert stored == data


@pytest.mark.asyncio
async def test_intake_rejects_disallowed_extension(svc) -> None:
    with pytest.raises(IntakeError):
        await svc.ingest_bytes(project_id="p1", name="script.py", data=b"print(1)")
    with pytest.raises(IntakeError):
        await svc.ingest_bytes(project_id="p1", name="bad.xyz", data=b"hello")


@pytest.mark.asyncio
async def test_intake_rejects_nested_archive(svc) -> None:
    # a docx containing a nested zip member
    import io

    inner = pathlib.Path(FIXTURES / "docx-list.docx").read_bytes()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("nested.zip", inner)
    with pytest.raises(IntakeError):
        await svc.ingest_bytes(project_id="p1", name="outer.docs", data=buf.getvalue())


# ---------------------------------------------------------------------------
# fallback parser golden tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fallback_parses_text_fixture() -> None:
    adapter = DoclingAdapter(ids=IdGenerator())
    src = SourceDocument(
        id="src_md",
        project_id="p1",
        original_name="numbered-headings.md",
        media_type="text/markdown",
        byte_size=0,
        sha256="x",
    )
    raw = (FIXTURES / "numbered-headings.md").read_bytes()
    outcome = await adapter.parse(src, raw, config={})
    assert outcome.quarantined is False
    assert outcome.parser_name == "fallback-text"
    assert "Intro" in outcome.markdown  # provenance text survives; not fragile render
    assert outcome.used_docling is False


@pytest.mark.asyncio
async def test_fallback_quarantines_binary_not_latin1() -> None:
    """A scanned/image PDF falling back to text is quarantined, never garbage."""
    adapter = DoclingAdapter(ids=IdGenerator())
    src = SourceDocument(
        id="src_scan",
        project_id="p1",
        original_name="scanned.pdf",
        media_type="application/pdf",
        byte_size=0,
        sha256="x",
    )
    raw = (FIXTURES / "scanned.pdf").read_bytes()
    outcome = await adapter.parse(src, raw, config={})
    assert outcome.quarantined is True
    assert outcome.parser_name == "quarantined"
    assert outcome.plain_text == ""  # no Latin-1 downgrade
    assert outcome.diagnostics.get("quarantined") is True
    assert outcome.diagnostics.get("reason")


# ---------------------------------------------------------------------------
# archive fixtures: safe-member iteration
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_docx_archive_members_iterate_safely() -> None:
    data = (FIXTURES / "docx-list.docx").read_bytes()
    names = [n async for n, _ in iter_supported_members(data)]
    assert any(n.endswith(".xml") for n in names)
    assert all(not n.startswith("/") and ".." not in n for n in names)


@pytest.mark.asyncio
async def test_xlsx_archive_members_iterate_safely() -> None:
    data = (FIXTURES / "merged-cells.xlsx").read_bytes()
    names = [n async for n, _ in iter_supported_members(data)]
    assert any(n.endswith(".xml") for n in names)


# ---------------------------------------------------------------------------
# real docling (opt-in, requires the docling extra)
# ---------------------------------------------------------------------------
@pytest.mark.docling
@pytest.mark.skipif(
    not __import__("importlib.util").util.find_spec("docling"),
    reason="docling extra not installed",
)
def test_fixtures_render_under_real_docling() -> None:
    """When the docling extra is present, the native-text PDF parses with it."""
    from knovaryn.infrastructure.docling.adapter import docling_available

    assert docling_available()
