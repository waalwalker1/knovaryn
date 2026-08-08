# Knovaryn — Launch Checklist

**Document status:** DRAFT checklist. Drive this to completion before the public announcement. Some items (legal) require counsel sign-off. Anything checked here that isn't actually true must be un-checked.

---

## A. Pre-launch (4–8 weeks out)

### A.1 Name & identity clearance
- [ ] **GitHub:** repo `knovaryn` available / owned, not squatting a confusingly similar name.
- [ ] **PyPI:** `knovaryn` name available on PyPI. (Our local project name is `knovaryn`; verify no prior occupant.)
- [ ] **Domains:** check `knovaryn.com` / `.dev` / `.io` / `.org` / `.ai` availability or ownership; decide what to register.
- [ ] **Trademarks:** search USPTO/EUIPO + a broader web search for existing "Knovaryn" or phonetically similar marks (e.g., anything like "Kno-vary-n", "Novaryn", "Knovar"). Record results with dates.
- [ ] **Phonetic similarity:** test how customers hear it in noisy/voice contexts ("Knovaryn" ← "Know-varyn", "Knowledge," "Knox", "Novarin", "Novar"). Document near-misses and decide whether the name is safe.
- [ ] **Legacy identifiers:** confirm no `OmniTrain`/`omnitrain`/`OMNITRAIN` strings leak into public product surfaces (the repo's identity test enforces this). Resolve any stragglers in URL slugs, migrated docs, or old domains.
- [ ] **Social handles:** check `@knovaryn` on X, LinkedIn, GitHub org, npm-style ecosystems if relevant.
- [ ] **Record the clearance evidence** in `BUILD_LEDGER.md` / DECISION_LOG so it's auditable.

### A.2 Engineering readiness
- [ ] Version bump to `0.1.0` and release notes written (`release-notes-0-1-0.md`).
- [ ] The 1.0 gate is documented (`release-gate.md`) even though 0.1.0 is alpha.
- [ ] `README.md` expanded from the current stub to a real quickstart.
- [ ] Docs build cleanly with mkdocs (no broken links).
- [ ] CI green on the release commit; pytest + coverage ≥ 70% (as configured).
- [ ] Offline demo verified end-to-end with **no API keys** (`knovaryn mcp --profile offline-demo`).
- [ ] Live-provider smoke test passed against one OpenAI-compatible and one Anthropic-compatible endpoint under the spending cap (opt-in live tests).
- [ ] Security policy (`SECURITY.md`) present and linked; coordinated-disclosure channel open.

### A.3 Content (these marketing docs)
- [ ] One-pager, demo script, blog post, HN/Reddit post, LinkedIn, X thread finalized and fact-checked.
- [ ] Peer comparison refreshed against live repos (it goes stale fast) and dated.
- [ ] Benchmark methodology finalized; first reproducible report produced (or explicitly deferred with a date).
- [ ] Logo produced from `logo-brief.md`; trademark clearance done or explicitly deferred.
- [ ] Sample-dataset proposal (`sample-dataset.md`) reviewed; a redistributable corpus selected and rights confirmed.

### A.4 Legal review (counsel)
- [ ] License: Apache-2.0 correct and headers present.
- [ ] Attribution/notice requirements for any bundled/derived content.
- [ ] Foreign/regulated-use disclaimers reviewed.
- [ ] Logo/trademark clearance or documented deferral.
- [ ] If shipping a sample public dataset: source redistribution rights verified and documented.

---

## B. Launch week

- [ ] Tag release on GitHub; push to PyPI; verify `pip install knovaryn` works in a clean env.
- [ ] Publish docs site and link the quickstart.
- [ ] Post blog post; link from README top.
- [ ] Publish LinkedIn announcement and X thread (compress thread to strongest posts).
- [ ] Post Show HN / Reddit self-post; be present in comments for 48h, answering honestly.
- [ ] Announce on relevant communities (r/LocalLLaMA, r/MachineLearning, MCP-focused channels) without spammy repetition.
- [ ] Publish the first benchmark report (`benchmarks/`) or state a date it will land.
- [ ] Verify every external link in the marketing docs resolves.
- [ ] Standing up a monitoring watchplan? Use a background monitor for reply/issue volume during the day.

---

## C. First 90 days

### C.1 Responsiveness & trust
- [ ] Triage every GitHub issue/PR within 3 business days.
- [ ] Publish a "known limitations" update if real-world usage exposes gaps.
- [ ] Confirm the honest-values posture holds — never overclaim bias-free/improvement.

### C.2 Roadmap execution
- [ ] Stabilize APIs toward 1.0 (release-gate checklist drives this).
- [ ] Add/tested provider adapters, exporters, validators per roadmap.
- [ ] Publish the reproducible benchmark report on the public corpus.
- [ ] Release the sample public dataset (from `sample-dataset.md`) with full dataset cards + license + provenance.

### C.3 Community
- [ ] Document contributor onboarding (setup, first PR, tests).
- [ ] Publish at least one "lessons learned / limitations" engineering post (honest, no hype).
- [ ] Refresh peer comparison and benchmark reports before any "1.0" or "stable" claim.

### C.4 Governance
- [ ] Enforce CODE_OF_CONDUCT.md; appoint maintainers if not single-maintainer.
- [ ] Re-run security review before every tag; keep `pip-audit` clean.
- [ ] Keep the 1.0 release gate current; treat it as the definition of stable.
