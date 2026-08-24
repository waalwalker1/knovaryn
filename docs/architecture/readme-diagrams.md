# Architecture — at a Glance (Diagrams)

This page collects the diagrams that used to live in the README, so the README
stays concise and these stay editable in one place. Each is available as a
rendered PNG (`assets/*.png`) and as raw Mermaid source
(`assets/diagrams/*.mmd`); the inline blocks below mirror those sources.
Diagram text is count-free by policy — surfaces say what they are, never how
many; the generated reference pages carry live numbers.

## 1. System architecture — one core, four interfaces

Everything sits on a single **application-services core** (domain + application)
behind a durable pipeline engine. Four interfaces — CLI, MCP server, REST + web
console, and the Python SDK — all drive the *same* services, so a job started
from the CLI is visible everywhere.

<p align="center">
  <img src="../assets/system-architecture.png" alt="Knovaryn system architecture" width="100%"/>
</p>

```mermaid
flowchart LR
    subgraph AGENTS["Host agents"]
        MCPAG["MCP-capable agents"]
    end

    subgraph INTERFACES["Four interfaces — same services"]
        C["CLI<br/>(knovaryn)"]
        M["MCP server<br/>(registered tool catalogue,<br/>generated reference page)"]
        R["REST + web console<br/>(knovaryn server)"]
        S["Python SDK"]
    end

    subgraph CORE["Application-services core (domain + application)"]
        WS["Workspace control plane"]
        SRV["Services: projects · sources · jobs · datasets"]
        POL["Domain policies & config"]
    end

    subgraph PIPELINE["Durable pipeline engine"]
        IN["Intake & preflight"]
        PA["Parse (Docling / fallbacks)"]
        SP["Split & chunk"]
        PL["Plan (dry-run cost)"]
        GE["Generate (ModelGateway)"]
        VA["Validate & quality gates"]
        VE["Version & export"]
        PU["Publish (dry-run)"]
        IN --> PA --> SP --> PL --> GE --> VA --> VE --> PU
    end

    subgraph INFRA["Infrastructure"]
        DB[("SQLite / Postgres")]
        ART["Artifact store<br/>content-addressed, local / S3"]
        MG["Model gateway<br/>fake offline · LiteLLM"]
        AUTH["Auth / bearer + scopes + tenancy"]
        SEC["Secrets: env-only, redacted"]
    end

    subgraph DEPLOY["Deployment profiles"]
        D1["Local — single process"]
        D2["Compose — api · worker · pg · minio · proxy"]
        D3["Kubernetes — kustomize base"]
    end

    AGENTS --> MCPAG --> M
    C --> WS
    M --> WS
    R --> WS
    S --> WS
    WS --> SRV --> POL
    SRV --> PIPELINE
    PIPELINE --> DB
    PIPELINE --> ART
    GE --> MG
    WS --> AUTH
    R --> AUTH
    MG --> SEC
    DB -.-> D2
    ART -.-> D2
    D2 -.-> D3

    style CORE fill:#e8f0fe,stroke:#1a73e8
    style PIPELINE fill:#e6f4ea,stroke:#188038
    style INFRA fill:#fef7e0,stroke:#b06000
    style MG fill:#fce8e6,stroke:#c5221f
    style DEPLOY fill:#f3e8fd,stroke:#8e24aa
```

## 2. End-to-end pipeline flow — every example traced to its source

<p align="center">
  <img src="../assets/pipeline-flow.png" alt="Knovaryn pipeline flow" width="100%"/>
</p>

```mermaid
flowchart LR
    subgraph INPUT["1 · Intake — permitted documents"]
        direction TB
        A1["Local files"] --> A2["Path + symlink checks"]
        A3["Archives zip / tar"] --> A2
        A4["URLs — opt-in"] --> A2
        A2 --> A5["Preflight: SHA-256 · size · pages · license"]
    end

    subgraph PARSE["2 · Parse → canonical representation"]
        direction TB
        P1["Docling canonical JSON"] --> P2["Diagnostics + quality summary"]
        P2 --> P3["Markdown — derivative output"]
    end

    subgraph SPLIT["3 · Split + chunk with provenance"]
        direction TB
        S1["Split at source group"] --> S2["Structure-aware chunking"]
        S2 --> S3["Heading paths · spans · source_span_ids · sha256<br/>location precision recorded per span"]
    end

    subgraph GEN["4 · Generate examples (durable stage)"]
        direction TB
        G1["Planner: task + difficulty map<br/>budget · profile · target-size constraints"] --> G2["Prompt library"]
        G2 --> G3["SFT · Preference · KTO · Eval"]
        G3 --> G4["Model gateway — fake offline or LiteLLM"]
        G4 --> G5["Provider-call cache<br/>(idempotent retries, no double cost)"]
    end

    subgraph VAL["5 · Validate — gates quarantine failures"]
        direction TB
        V1["Schema / Grounding / Completeness"]
        V2["Format / Refusal / Dedupe"]
        V3["Contamination / Privacy / License"]
        V4a["Semantic consistency<br/>offline-fast deterministic · certified-semantic judge"]
        V4b["Preference signal (pairs)<br/>+ information gain"]
        V1 --> V5{"All gates pass?"}
        V2 --> V5
        V3 --> V5
        V4a --> V5
        V4b --> V5
        V5 -- fail --> V6["Quarantine / review routing"]
        V5 -- pass --> V7["Review state"]
    end

    subgraph OUT["6 · Version + export + publish"]
        direction TB
        O1["Dataset version (immutable)"] --> O2["Release bundle: card · manifest · reports · checksums"]
        O2 --> O3["Exporters — provenance gate re-resolves every citation"]
        O2 --> O4["Publish to Hugging Face — dry-run by default"]
    end

    A5 --> P1
    P3 --> S1
    S3 --> G1
    G5 --> V1
    V7 --> O1

    style V6 fill:#fbe3e3,stroke:#b3261e
    style A5 fill:#e8f0fe,stroke:#1a73e8
    style O4 fill:#e8f0fe,stroke:#1a73e8
    style V4a fill:#fef7e0,stroke:#b06000
    style V4b fill:#fef7e0,stroke:#b06000
    style G5 fill:#e6f4ea,stroke:#188038
```

## 3. Durable jobs — nothing is lost on a crash

Every stage of the pipeline runs as a **durable job** with atomic claims,
heartbeats, idempotency keys, checkpoint artifacts, and budget caps. A crash,
kill, or timeout just expires the lease and **resumes from the last checkpoint**
— no re-generation of paid work.

<p align="center">
  <img src="../assets/durable-jobs.png" alt="Knovaryn durable job lifecycle" width="100%"/>
</p>

```mermaid
flowchart LR
    A["Create job<br/>(idempotency key)"] --> B["Enqueue<br/>(queued state)"]
    B --> C{"Atomic claim<br/>SELECT … FOR UPDATE SKIP LOCKED<br/>(one winner among N workers)"}

    C -->|"won lease"| D["Run stage"]
    D --> E["Persist checkpoint artifact<br/>(stage inputs/outputs, resumable)"]
    E --> F["Heartbeat renews lease<br/>while work continues"]

    F -->|"more stages"| D
    F -->|"stages done"| G["Record cost events + result<br/>→ idempotent done state"]

    E -->|"provider call"| H["Provider-call dedup cache<br/>(same prompt+model+seed = cached)"]
    H --> D

    subgraph CANCEL["Cancellation (polled, never mid-write)"]
        X1["cancel requested"] --> X2{"safe point?<br/>between stages"}
        X2 -- "yes" --> X3["Cancel with cost audit<br/>partial state preserved"]
        X2 -- "no" --> X4["finish current stage,<br/>then cancel"]
        X4 --> X3
    end
    F -.->|"poll cancel flag"| X1

    subgraph CRASH["Crash / kill / timeout"]
        K1["lease expires unrenewed"] --> K2["re-lease to any worker"]
        K2 --> K3["resume from last<br/>checkpoint artifact"]
        K3 --> D
    end

    style C fill:#e8f0fe,stroke:#1a73e8
    style E fill:#fef7e0,stroke:#b06000
    style K1 fill:#fce8e6,stroke:#c5221f
    style K3 fill:#e6f4ea,stroke:#188038
    style X3 fill:#fce8e6,stroke:#c5221f
    style H fill:#e6f4ea,stroke:#188038
```

## 4. A typical MCP agent session

From an empty workspace to an exported dataset version over the MCP tools —
exactly what a Claude/Cursor-style agent sees.

<p align="center">
  <img src="../assets/mcp-session.png" alt="Typical MCP agent session" width="100%"/>
</p>

```mermaid
flowchart TD
    subgraph PHASE1["Phase 1 · Set up"]
        direction TB
        A["knovaryn_create_project"] --> B["knovaryn_add_source"]
        B --> C["knovaryn_inspect_source · knovaryn_license_report"]
    end

    subgraph PHASE2["Phase 2 · Estimate & run"]
        direction TB
        E["knovaryn_estimate_run (dry-run cost)"] --> F{"budget OK?"}
        F -- "yes" --> G["knovaryn_start_pipeline"]
        F -- "no / tune" --> E
        G --> H["knovaryn_get_job / run_job — poll progress"]
    end

    subgraph PHASE3["Phase 3 · Inspect & review"]
        direction TB
        I["knovaryn_preview_examples"] --> J["knovaryn_review_example<br/>(immutable revisions)"]
        J --> K["knovaryn_validate_dataset · knovaryn_compare_runs"]
    end

    subgraph PHASE4["Phase 4 · Ship"]
        direction TB
        L["knovaryn_create_dataset_version"] --> M["knovaryn_export_dataset"]
        M --> N["knovaryn_publish_dataset<br/>(dry-run → confirm)"]
    end

    P["knovaryn_doctor — health check, anytime"]

    PHASE1 --> PHASE2 --> PHASE3 --> PHASE4
    P -.-> PHASE1

    style E fill:#fef7e0,stroke:#b06000
    style N fill:#e6f4ea,stroke:#188038
    style P fill:#f3e8fd,stroke:#8e24aa
```

## 5. Security & privacy flow

Offline-first, secrets from the environment only, tenant-scoped remote access,
and nothing published unless explicitly approved.

<p align="center">
  <img src="../assets/security.png" alt="Knovaryn security and privacy flow" width="100%"/>
</p>

```mermaid
flowchart TD
    subgraph INTAKE["Untrusted input boundary"]
        T1["Local file / archive / URL"]
        T2["Path-traversal + symlink checks"]
        T3["Verified archives · SSRF defense · URL ingest OFF by default"]
        T1 --> T2 --> T3
        T4["Preflight: SHA-256 · size · license · privacy class"]
        T3 --> T4
    end

    subgraph LOCAL["Local trust (default)"]
        L1["Deterministic fake provider — no keys, no network"]
        L2["Loopback HTTP binding · Host/Origin checks"]
    end

    subgraph REMOTE["Remote access (opt-in)"]
        R1["MCP streamable-http / REST behind bearer token"]
        R2["Least-privilege scopes per principal<br/>(read · write · review · publish)"]
        R3["Tenant isolation — principals only see their own projects"]
        R1 --> R2 --> R3
    end

    subgraph SECRETS["Secrets handling"]
        S1["API keys from environment only (never committed)"]
        S2["Redacted at display boundary"]
        S3["Never logged · never in cost ledger · never in audit"]
        S1 --> S2 --> S3
    end

    subgraph ARTIFACTS["Artifact integrity"]
        A1["Content-addressed artifact store (SHA-256)"]
        A2["Export re-resolves every citation + recomputes hashes"]
        A3["Release bundle: detached checksums + per-file manifest<br/>verified by knovaryn verify-release"]
        A1 --> A2 --> A3
    end

    subgraph PUBLISH["Publication authorization"]
        G1["License approval required"]
        G2["Privacy report must pass"]
        G3["Confirmation token required"]
        G4["Dry-run by default — nothing pushed unasked"]
        G1 --> G2 --> G3 --> G4
    end

    subgraph RELEASE["Release attestation (supply chain)"]
        N1["PyPI Sigstore provenance from OIDC trusted publishing"]
        N2["CycloneDX SBOM + SHA256SUMS attached to the GitHub Release"]
        N1 --- N2
    end

    T4 --> LOCAL
    LOCAL --> REMOTE
    REMOTE --> SECRETS
    T4 --> ARTIFACTS
    ARTIFACTS --> PUBLISH
    PUBLISH --> RELEASE

    style INTAKE fill:#fbe3e3,stroke:#b3261e
    style REMOTE fill:#fef7e0,stroke:#b06000
    style SECRETS fill:#fef7e0,stroke:#b06000
    style LOCAL fill:#e6f4ea,stroke:#188038
    style ARTIFACTS fill:#e8f0fe,stroke:#1a73e8
    style PUBLISH fill:#e8f0fe,stroke:#1a73e8
    style RELEASE fill:#f3e8fd,stroke:#8e24aa
```

## 6. Why it's useful — problem → value

<p align="center">
  <img src="../assets/value-proposition.png" alt="Knovaryn value proposition" width="100%"/>
</p>

```mermaid
flowchart TD
    subgraph PAIN["Why teams struggle today"]
        P1["Opaque pipelines — can't trace an example to its source"]
        P2["No quality gates — weak rows ship silently"]
        P3["Expensive work lost on a crash — no resume"]
        P4["Licensing & privacy risk — no knowledge of rights"]
        P5["Provider/trainer lock-in — can't switch"]
        P6["No cost control — token bills run away"]
    end

    subgraph VALUE["What Knovaryn delivers"]
        V1["Every example traced to source spans with<br/>machine-checkable location precision (provenance)"]
        V2["Fail-closed quality gates that quarantine failures —<br/>deterministic checks, honest semantic modes"]
        V3["Durable jobs — atomic claims, heartbeats,<br/>resume from checkpoint, no double cost"]
        V4["License registry + publication gate · dry-run by default"]
        V5["ModelGateway + trainer-native exporters — BYO model"]
        V6["Cost ledger + budget caps"]
    end

    P1 --> V1
    P2 --> V2
    P3 --> V3
    P4 --> V4
    P5 --> V5
    P6 --> V6

    V1 --> OUT["Trustworthy SFT, preference, KTO & eval datasets"]
    V2 --> OUT
    V3 --> OUT
    V4 --> OUT
    V5 --> OUT
    V6 --> OUT

    style PAIN fill:#fbe3e3,stroke:#b3261e
    style VALUE fill:#e6f4ea,stroke:#188038
    style OUT fill:#e8f0fe,stroke:#1a73e8,stroke-width:2px
```
