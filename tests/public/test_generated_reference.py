"""§5.1 — generated reference documentation cannot drift from the code.

Each public reference surface is rendered from its real registration point by
``scripts/generate_reference_docs.py``; these tests fail when committed
documentation differs from what the code actually exposes. Regenerate with:

    python scripts/generate_reference_docs.py
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

fastapi = pytest.importorskip("fastapi", reason="REST reference needs fastapi")
mcp_pkg = pytest.importorskip("mcp", reason="MCP catalogue needs mcp")

sys_path_scripts = str(Path(__file__).resolve().parents[2] / "scripts")
if sys_path_scripts not in __import__("sys").path:
    __import__("sys").path.insert(0, sys_path_scripts)

import generate_reference_docs as gen  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
REF = REPO_ROOT / "docs" / "reference"


def _block(path: Path, tag: str) -> str:
    """The committed marked block INCLUDING its begin/end markers.

    The render functions return the full marked block, so the comparison
    side must include the markers too — extracting only the inner content
    could never be equal to what the renderer emits.
    """
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(gen._begin(tag)) + r"(.*?)" + re.escape(gen._end(tag)), re.S)
    m = pattern.search(text)
    assert m, f"missing {tag} markers in {path}"
    return m.group(0).strip()


def _full_page(renderer_name: str, filename: str) -> None:
    """Full-file page = renderer body + the §17 front matter wrapper.

    build_all() wraps render_*() output with _with_front_matter() before
    writing, so the committed page equals the *wrapped* content; compare
    against exactly that (the script's own wrapper — drift in either the
    body or the description still fails).
    """
    import io
    from contextlib import redirect_stdout

    committed = (REF / filename).read_text(encoding="utf-8")
    render = getattr(gen, renderer_name)
    # importing the REST/MCP apps prints banner noise; keep stdout clean
    buf = io.StringIO()
    with redirect_stdout(buf):
        rendered = render()
    expected = gen._with_front_matter(gen._PAGE_DESCRIPTIONS[filename], rendered)
    assert expected == committed


def test_rest_api_reference_matches_openapi() -> None:
    _full_page("render_rest_api", "rest-api.md")


def test_mcp_catalogue_matches_registration() -> None:
    _full_page("render_mcp_catalogue", "mcp-tools.md")


def test_quality_gates_match_validators() -> None:
    _full_page("render_quality_gates", "quality-gates.md")


def test_profiles_reference_matches_registry() -> None:
    _full_page("render_profiles", "profiles.md")


def test_claim_matrix_matches_registry() -> None:
    """§10: the claim-to-evidence page is generated, not hand-maintained."""
    _full_page("render_claim_matrix", "claim-matrix.md")


def test_export_formats_block_matches_registry() -> None:
    assert gen.render_export_formats().strip() == _block(REF / "exporters.md", "EXPORT FORMATS")


def test_config_defaults_block_matches_settings() -> None:
    assert gen.render_config_defaults().strip() == _block(REF / "config.md", "CONFIG DEFAULTS")


def test_no_phantom_format_names_survive_in_exporters() -> None:
    """The old hand-written table advertised hyphenated formats that never existed."""
    text = (REF / "exporters.md").read_text(encoding="utf-8")
    for phantom in (
        "canonical-jsonl",
        "trl-conversational",
        "llamafactory-sharegpt",
        "openai-chat",
    ):
        assert f"`{phantom}`" not in text, f"phantom export format {phantom!r} is back"


def test_no_phantom_cli_commands_survive_in_config_reference() -> None:
    """`knovaryn config validate` does not exist on the real Typer app."""
    text = (REF / "config.md").read_text(encoding="utf-8")
    assert "config validate" not in text
