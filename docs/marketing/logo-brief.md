# Knovaryn — Logo Brief

**Document status:** DRAFT brief for designers. **This is NOT a finalized or trademarked logo.** It describes the visual direction, constraints, and deliverables. Legal/trademark clearance for any final mark is required before commercial use (see `release-gate.md` and `launch-checklist.md`).

---

## 1. About the brand (context for the designer)

Knovaryn is a training-data **foundry** — a place where raw permitted documents are refined into traceable, quality-gated datasets. Core values and their visual echoes:

- **Trace / provenance** → connected nodes, a chain, a lineage path, an arrow from source to example.
- **Quality gate / refine** → a threshold, a filter, a mark that passes or rejects, a chisel, a sieve.
- **Foundry / forge** → heat, metal, cast parts — but keep it calm and technical, not industrial-cluttered.
- **MCP-native / agent-driven** → a connector, a plug, a point-to-point link between an agent and tools.
- **Open source** → Apache-2.0; avoid lock-in imagery; keep it approachable.

The tagline to keep in mind while designing: *From documents to defensible training data.*

---

## 2. Design direction

A single mark that works at favicon size (16 px) and on a landing page. Explore:

- **Primary concept:** a compact chain/gate glyph — several small source nodes converging into one refined node behind a subtle threshold/door. Reads as "many documents → one gated, traceable example."
- **Alternative A:** a three-span "evidenceline" — three short, connected segments (doc → chunk → example) with a small check that lives in the gap.
- **Alternative B:** a stylized "K" whose right stroke is a chisel/gate leaving a clean mark.

Do **not** over-literally combine data + fire. Keep one clear idea.

---

## 3. Color

Provide a light and dark variant from day one (the docs use mkdocs-material; the CLI uses `rich`). A small, system-neutral, brand-neutral palette is preferred (the project is provider-neutral — avoid implying a specific model vendor's colors). Recommend:

- A single primary (calm blue/teal family is a safe starting point; final pick is the maintainers' call),
- A single accent for "accepted / quality," and
- A warning accent for "rejected / quarantine," used sparingly.

Deliver hex, RGB, and a dark-theme adjustment. Test contrast on both light and dark backgrounds.

---

## 4. Typography

- Recommend a readable geometric or humanist sans for wordmark and docs.
- Provide the exact font, license, and fallback stack. Prefer open/hosted fonts for the open-source project.

---

## 5. Usage rules

- Minimum clear-space at least the height of the "1" counter or one node-diameter.
- Minimum sizes: 16 px icon, 24 px inline wordmark in context.
- Don't place on busy photography; provide a tinted-plate version.
- Don't stretch, recolor, or rotate the mark.
- Never place the mark next to any vendor logo in a way implying partnership (provider-neutral).

---

## 6. Deliverables

- [ ] Primary SVG (light + dark) and 512 px PNG (light + dark)
- [ ] Wordmark lockup (mark + "knovaryn" lowercase wordmark)
- [ ] Favicon / app-icon set (16, 32, 180, 192, 512)
- [ ] Monochrome version for emboss/stamp and CLI
- [ ] Short brand-usage page (rules above) or drop-in section for docs
- [ ] `docs/marketing/logo-brief.md` updated with the final palette values

---

## 7. Trademark / clearance note

**A final logo is a legal asset.** Before any public or commercial use:
- Search the mark for conflicts (see `launch-checklist.md` for clearance steps).
- If intended as a protected mark, run trademark clearance / registration review with counsel.
- Do **not** ship a logo asserting trademark protection until that review is done. This brief produces art direction, not a cleared mark.
