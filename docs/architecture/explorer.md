---
description: >-
  Interactive explorer of Knovaryn's layered architecture — click
  through ports, adapters, and the domain core; keyboard-navigable
  and screen-reader labeled.
---

# Architecture — Interactive Explorer

Eight views of the same system, no contradictions allowed. Each tab embeds
the deterministic render of a canonical Mermaid source; the source files are
the single source of truth (this page never restates them inline), and every
panel links to its source and to the docs that explain the subsystem.

The tabs are plain radio buttons: use <kbd>Tab</kbd> to reach the tab row and
<kbd>←</kbd>/<kbd>→</kbd> to switch views — no JavaScript required. Every
panel also carries a text summary, so the content reads correctly with images
off, with JavaScript off, and in dark mode (diagrams render on a light card
by design; the palette is documented in the
[design system](../design-system/color.md)).

<div class="kn-tabs">
  <input type="radio" name="kn-explorer" id="kn-exp-0" checked>
  <label for="kn-exp-0">Architecture</label>
  <input type="radio" name="kn-explorer" id="kn-exp-1">
  <label for="kn-exp-1">Pipeline flow</label>
  <input type="radio" name="kn-explorer" id="kn-exp-2">
  <label for="kn-exp-2">Durable jobs</label>
  <input type="radio" name="kn-explorer" id="kn-exp-3">
  <label for="kn-exp-3">Provenance chain</label>
  <input type="radio" name="kn-explorer" id="kn-exp-4">
  <label for="kn-exp-4">MCP session</label>
  <input type="radio" name="kn-explorer" id="kn-exp-5">
  <label for="kn-exp-5">Security boundaries</label>
  <input type="radio" name="kn-explorer" id="kn-exp-6">
  <label for="kn-exp-6">Deployment topology</label>
  <input type="radio" name="kn-explorer" id="kn-exp-7">
  <label for="kn-exp-7">Release chain</label>

  <div class="kn-tabpanels">

    <section class="kn-panel">
      <h3>System architecture</h3>
      <p>Six layers: users and agents → four interfaces → application-services
      core → the eight-stage durable pipeline engine → infrastructure → three
      deployment profiles. Every interface drives the same core.</p>
      <figure class="kn-figure">
        <a href="../../assets/system-architecture.png"><img src="../../assets/system-architecture.png" alt="System architecture: users and agents, interfaces (CLI, MCP, REST and web console, SDK), application core, pipeline stages, infrastructure, deployment profiles" loading="lazy"></a>
        <figcaption>Open the image in a new tab for full-size reading; the render is deterministic from the Mermaid source.</figcaption>
      </figure>
      <ul>
        <li>Interfaces: <code>knovaryn</code> CLI, MCP server, <code>knovaryn server</code> REST + web console, Python SDK.</li>
        <li>Pipeline stages are checkpointed — validate is the fail-closed gate.</li>
        <li>Infrastructure: SQLite/PostgreSQL metadata, content-addressed artifacts, model gateway.</li>
      </ul>
      <p><a href="https://github.com/waalwalker1/knovaryn/blob/main/docs/assets/diagrams/system-architecture.mmd">Canonical Mermaid source</a> · <a href="../overview/">Architecture overview</a></p>
    </section>

    <section class="kn-panel">
      <h3>Pipeline flow</h3>
      <p>Two rows: <strong>prepare</strong> (intake → parse → split &amp; chunk →
      plan) and <strong>produce</strong> (generate → validate → review → version
      &amp; export). Validation failures quarantine with reason codes and are
      never exported.</p>
      <figure class="kn-figure">
        <a href="../../assets/pipeline-flow.png"><img src="../../assets/pipeline-flow.png" alt="Pipeline flow: prepare row from intake to plan, produce row from generation through validation, review, versioning and export" loading="lazy"></a>
        <figcaption>The plan stage is a dry run — cost is priced before any model call.</figcaption>
      </figure>
      <ul>
        <li>Intake preflights hash, size, license, and privacy class on untrusted documents.</li>
        <li>Chunks carry <code>source_span_ids</code> and recorded location precision.</li>
        <li>Exporters re-resolve every citation; publish is dry-run by default.</li>
      </ul>
      <p><a href="https://github.com/waalwalker1/knovaryn/blob/main/docs/assets/pipeline-flow.mmd">Canonical Mermaid source</a> · <a href="../diagram/">Stage-by-stage notes</a></p>
    </section>

    <section class="kn-panel">
      <h3>Durable jobs</h3>
      <p>Three lanes: normal execution (atomic claim, checkpoint, heartbeat),
      crash and recovery (lease expiry → re-lease → resume from checkpoint),
      and cancellation or budget stop (polled between stages, never mid-write,
      with a cost audit).</p>
      <figure class="kn-figure">
        <a href="../../assets/durable-jobs.png"><img src="../../assets/durable-jobs.png" alt="Durable job lifecycle: normal lane with claim, checkpoint and heartbeat; crash lane with lease expiry and resume; cancellation lane with safe points" loading="lazy"></a>
        <figcaption>Provider-call and cost-event dedup mean a replayed stage never bills twice.</figcaption>
      </figure>
      <ul>
        <li>Atomic claim via <code>SKIP LOCKED</code> — one winner among N workers.</li>
        <li>Resume continues from the last checkpoint artifact; paid work is not repeated.</li>
        <li>Budget caps pause the job before the limit is crossed.</li>
      </ul>
      <p><a href="https://github.com/waalwalker1/knovaryn/blob/main/docs/assets/diagrams/durable-jobs.mmd">Canonical Mermaid source</a> · <a href="../jobs/">Job engine reference</a></p>
    </section>

    <section class="kn-panel">
      <h3>Provenance chain</h3>
      <p>Every exported example chains back to source bytes: candidate → chunk →
      source span (page, section path, offsets, bounding box, quoted text with
      its own SHA-256) → parsed document → source document (file hash, license,
      privacy class). A provenance minimum is enforced.</p>
      <figure class="kn-figure">
        <a href="../../assets/provenance-lineage.png"><img src="../../assets/provenance-lineage.png" alt="Provenance lineage: exported example, generation candidate, chunk, source span, parsed document, source document, with hashes and location precision" loading="lazy"></a>
        <figcaption><code>knovaryn_lineage</code> walks this chain for any example.</figcaption>
      </figure>
      <ul>
        <li>Spans quote their text and hash it — grounding is checkable, not asserted.</li>
        <li>Parser configuration is hashed, so re-parses are comparable.</li>
        <li>License and privacy classification happen at intake, before parsing.</li>
      </ul>
      <p><a href="https://github.com/waalwalker1/knovaryn/blob/main/docs/assets/provenance-lineage.mmd">Canonical Mermaid source</a> · <a href="../../concepts/provenance/">Provenance concepts</a></p>
    </section>

    <section class="kn-panel">
      <h3>MCP session</h3>
      <p>Four phases — setup, estimate &amp; generate, inspect &amp; review,
      version &amp; release — using the real tool names. The estimate step loops
      against the budget before <code>start_pipeline</code>;
      <code>knovaryn_doctor</code> is usable at any time.</p>
      <figure class="kn-figure">
        <a href="../../assets/mcp-session.png"><img src="../../assets/mcp-session.png" alt="MCP agent session: setup, estimate and generate with a budget check, inspect and review, version and release" loading="lazy"></a>
        <figcaption>Tool catalogue with schemas lives on the MCP tools reference page.</figcaption>
      </figure>
      <ul>
        <li>Dry-run cost estimate precedes every real generation run.</li>
        <li>Review uses immutable revisions with evidence.</li>
        <li>Publish is dry-run first, then confirmed.</li>
      </ul>
      <p><a href="https://github.com/waalwalker1/knovaryn/blob/main/docs/assets/diagrams/mcp-session.mmd">Canonical Mermaid source</a> · <a href="../../reference/mcp-tools/">MCP tools reference</a></p>
    </section>

    <section class="kn-panel">
      <h3>Security boundaries</h3>
      <p>Regions colored by trust: untrusted input boundary, local trust
      default, opt-in remote access, secrets handling, artifact integrity,
      publication authorization, and the release attestation chain.</p>
      <figure class="kn-figure">
        <a href="../../assets/security.png"><img src="../../assets/security.png" alt="Security and privacy boundaries: untrusted input, local trust, remote access, secrets, artifact integrity, publication authorization, release attestation" loading="lazy"></a>
        <figcaption>Red is untrusted input; green is the offline local default.</figcaption>
      </figure>
      <ul>
        <li>URL ingest is off by default; archives are verified before extraction.</li>
        <li>Scopes are least-privilege per principal; tenants see only their projects.</li>
        <li>Secrets come from the environment and are redacted at the display boundary.</li>
      </ul>
      <p><a href="https://github.com/waalwalker1/knovaryn/blob/main/docs/assets/diagrams/security.mmd">Canonical Mermaid source</a> · <a href="../security/">Security architecture</a></p>
    </section>

    <section class="kn-panel">
      <h3>Deployment topology</h3>
      <p>One running system — access layer, core, worker pool, state — plus the
      external model providers (worker outbound calls only) and the scale
      decision: local, compose, or Kubernetes. Configuration, not a fork.</p>
      <figure class="kn-figure">
        <a href="../../assets/deployment-topology.png"><img src="../../assets/deployment-topology.png" alt="Deployment topology: clients, access layer, core, workers, state stores, external providers, and the three scale profiles" loading="lazy"></a>
        <figcaption>The same core runs at all three scales; only configuration differs.</figcaption>
      </figure>
      <ul>
        <li>Compose ships api, workers, PostgreSQL, MinIO, and a proxy.</li>
        <li>Kubernetes base includes a migration Job, NetworkPolicies, and PDBs.</li>
        <li>Providers are reached only by worker outbound calls.</li>
      </ul>
      <p><a href="https://github.com/waalwalker1/knovaryn/blob/main/docs/assets/deployment-topology.mmd">Canonical Mermaid source</a> · <a href="../../deployment/profiles/">Deployment profiles</a></p>
    </section>

    <section class="kn-panel">
      <h3>Release supply chain</h3>
      <p>Tag push → four gates on the exact release SHA → build → artifacts
      (detached checksums, CycloneDX SBOM, notes, prerelease enforcement) →
      OIDC publish to PyPI → clean-environment verification → your own
      <code>knovaryn verify-release</code>.</p>
      <figure class="kn-figure">
        <a href="../../assets/release-supply-chain.png"><img src="../../assets/release-supply-chain.png" alt="Release supply chain: gates on the release SHA, build, release artifacts, PyPI publish via OIDC, post-publish verification, local bundle verification" loading="lazy"></a>
        <figcaption>Verification ends on your machine, not in CI.</figcaption>
      </figure>
      <ul>
        <li>Deployment E2E runs the published tag through the compose stack.</li>
        <li>Publishing uses OIDC trusted publishing — no long-lived tokens.</li>
        <li>0.x tags are enforced as pre-releases.</li>
      </ul>
      <p><a href="https://github.com/waalwalker1/knovaryn/blob/main/docs/assets/release-supply-chain.mmd">Canonical Mermaid source</a> · <a href="../../security/governance-and-ci/">Governance and CI</a></p>
    </section>

  </div>
</div>

## Where these renders come from

```bash
python scripts/render_diagrams.py   # sources in docs/assets/diagrams/ → PNG
```

The gallery page lists all renders with commentary; the
[diagram sources](https://github.com/waalwalker1/knovaryn/tree/main/docs/assets/diagrams)
are plain Mermaid text you can diff and reuse.
