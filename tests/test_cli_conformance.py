"""Defect 3.4 (v0.2.1) — public CLI documentation must match reality.

Three layers of enforcement:

1. **--help conformance**: every command in the real Typer tree exits 0 on
   ``--help`` (via CliRunner, no subprocess).
2. **Docs example validation**: every ``knovaryn ...`` invocation in a
   fenced code block under ``docs/`` must name an existing command path, use
   only flags that exist on that command, and use the correct executable
   name — no phantom commands.
3. **Command-tree snapshot**: the canonical tree is snapshotted; any change
   to the CLI surface fails here until the snapshot AND
   ``docs/reference/cli.md`` are regenerated deliberately
   (``scripts/generate_cli_reference.py``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from click.testing import CliRunner
from typer.main import get_command

pytestmark = [pytest.mark.unit]

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SNAPSHOT = Path(__file__).resolve().parent / "cli" / "command_tree_snapshot.json"

# Docs scanned for `knovaryn ...` examples. Changelogs/ADRs may describe
# historical surfaces and are exempt.
_SCAN_FILES = [
    "docs/index.md",
    "docs/reference/cli.md",
    "README.md",
]


def _context_class() -> type:
    """Context class from the same click universe the commands belong to.

    Typer >= 0.26 vendors its own adapted click (``typer._click``) and builds
    the whole command tree on it — introspecting those objects with a real
    ``click.Context`` mixes incompatible universes. Older typer builds on
    plain ``click``. See scripts/generate_cli_reference.py (same logic).
    """
    try:
        from typer._click import Context as vendored_context

        return vendored_context
    except ImportError:
        import click

        return click.Context


def _subcommands(cmd) -> dict | None:
    """Group-like children mapping (duck-typed), else ``None`` for leaves.

    Works for classic ``click.Group`` and typer >= 0.26 ``TyperGroup`` — the
    latter subclasses a vendored ``click.Command``, so an ``isinstance``
    check against ``click.Group`` silently degrades the tree to a single
    root "leaf" and every downstream gate with it.
    """
    sub = getattr(cmd, "commands", None)
    if isinstance(sub, dict) and sub:
        return sub
    return None


def _root_command():
    return get_command(__import__("knovaryn.interfaces.cli.main", fromlist=["app"]).app)


def _tree() -> dict[str, list[str]]:
    """{command path -> sorted option long-flags} from the real app."""
    ctx_cls = _context_class()
    out: dict[str, list[str]] = {}

    def visit(cmd, path: list[str]) -> None:
        sub = _subcommands(cmd)
        if sub is not None:
            for name in sorted(sub):
                visit(sub[name], [*path, name])
            return
        ctx = ctx_cls(cmd, info_name="knovaryn")
        opts: set[str] = set()
        for p in cmd.get_params(ctx):
            for o in getattr(p, "opts", []) or []:
                if o.startswith("--"):
                    opts.add(o)
        out[" ".join(path)] = sorted(opts)

    visit(_root_command(), [])
    return out


def test_every_real_command_help_exits_zero() -> None:
    runner = CliRunner()
    ctx_cls = _context_class()
    root = _root_command()

    # every group-like node must carry a --help option
    def visit_groups(cmd, path: list[str]) -> None:
        sub = _subcommands(cmd)
        if sub is None:
            return
        assert "--help" in {
            o for p in cmd.get_params(ctx_cls(cmd)) for o in p.opts
        }, path
        for name in sub:
            visit_groups(sub[name], [*path, name])

    visit_groups(root, [])
    # flat invocation check for each leaf through its parent group chain
    leaves = _tree()
    assert leaves, "CLI command tree must not be empty"
    for path_str in leaves:
        argv = [*path_str.split()]
        result = runner.invoke(root, [*argv, "--help"], catch_exceptions=False)
        assert result.exit_code == 0, f"`knovaryn {path_str} --help` failed:\n{result.output}"


def _fenced_blocks(text: str) -> list[str]:
    return re.findall(r"```(?:bash|sh|shell|console|zsh)?\n(.*?)```", text, re.S)


_KNOWN_PREFIXES = ("knovaryn",)


def _iter_documented_invocations() -> list[tuple[str, str]]:
    """(file, command line) pairs actually invoking the knovaryn executable."""
    found: list[tuple[str, str]] = []
    for rel in _SCAN_FILES:
        path = _REPO_ROOT / rel
        if not path.exists():
            continue
        for block in _fenced_blocks(path.read_text(encoding="utf-8")):
            for line in block.splitlines():
                stripped = line.strip().lstrip("$ ").lstrip("> ")
                tokens = stripped.split()
                if not tokens or tokens[0] not in _KNOWN_PREFIXES:
                    continue
                # skip pure help/version output lines
                if stripped.startswith("#"):
                    continue
                found.append((rel, stripped))
    return found


def test_no_phantom_commands_or_flags_in_public_docs() -> None:
    tree = _tree()
    problems: list[str] = []
    for rel, cmdline in _iter_documented_invocations():
        tokens = cmdline.split()
        # resolve longest matching command path
        best: tuple[str, int] | None = None
        for n in range(min(len(tokens) - 1, 4), 0, -1):
            candidate = " ".join(tokens[1 : 1 + n])
            if candidate in tree:
                best = (candidate, n)
                break
        if best is None:
            sub = " ".join(tokens[: min(5, len(tokens))])
            problems.append(f"{rel}: `{sub}` — first token(s) after 'knovaryn' do not form "
                            f"a real command (known: {sorted(tree)})")
            continue
        cmd_path, consumed = best
        known_opts = tree[cmd_path]
        for tok in tokens[1 + consumed :]:
            if tok.startswith("--") and "=" in tok:
                tok = tok.split("=", 1)[0]
            if tok.startswith("--") and tok != "--" and tok not in known_opts:
                problems.append(f"{rel}: `{tok}` is not a flag of `knovaryn {cmd_path}` "
                                f"(has: {known_opts})")
    assert not problems, "public docs reference nonexistent CLI surface:\n- " + "\n- ".join(problems)


def test_command_tree_snapshot_is_deliberate() -> None:
    tree = _tree()
    assert _SNAPSHOT.exists(), (
        f"missing snapshot {_SNAPSHOT}; generate it when you change the CLI:\n"
        f"  python -c \"import json,pathlib;"
        f"print(json.dumps(_tree()))\" > tests/cli/command_tree_snapshot.json"
    )
    recorded = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    if recorded == tree:
        return
    added = sorted(set(tree) - set(recorded))
    removed = sorted(set(recorded) - set(tree))
    changed = sorted(k for k in set(tree) & set(recorded) if tree[k] != recorded[k])
    pytest.fail(
        "CLI surface changed without a deliberate documentation update.\n"
        f"  added: {added}\n  removed: {removed}\n  flags changed: {changed}\n"
        "Regenerate the snapshot AND docs/reference/cli.md:\n"
        "  python scripts/generate_cli_reference.py\n"
        "then refresh tests/cli/command_tree_snapshot.json.",
    )
