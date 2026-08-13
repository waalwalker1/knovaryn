# Architecture — at a Glance (Diagrams)

This page collects the diagrams that used to live in the README, so the README
stays concise and these stay editable in one place. Each is available as a
rendered PNG (`assets/*.png`) and as raw Mermaid source
(`assets/diagrams/*.mmd`).

## 1. System architecture — one core, four interfaces

Everything sits on a single **application-services core** (domain + application)
behind a durable pipeline engine. Four interfaces — CLI, the 23-tool MCP server,
REST + web console, and the Python SDK — all drive the *same* services, so a job
started from the CLI is visible everywhere.

<p align="center">
  <img src="../assets/system-architecture.png" alt="Knovaryn system architecture" width="100%"/>
</p>

```mermaid
flowchart LR
    subgraph AGENTS["Host agents"]
        MCPAG["Claude · Cursor · etc."]
    end

    subgraph INTERFACES["Four interfaces — same services"]
        C["CLI<br/>(knovaryn)"]
        M["MCP server<br/>(knovaryn_mcp — 23 tools)"]
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
        PA["Parse (Docling)"]
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
        ART["Artifact store<br/>local / S3"]
        MG["Model gateway<br/>fake offline · LiteLLM"]
        AUTH["Auth / bearer + scopes"]
        SEC["Secrets: env-only, redacted"]
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
        S2 --> S3["Heading paths · spans · source_span_ids · sha256"]
    end

    subgraph GEN["4 · Generate examples"]
        direction TB
        G1["Planner: task + difficulty map"] --> G2["Prompt library"]
        G2 --> G3["SFT · Preference · KTO · Eval"]
        G3 --> G4["Model gateway — fake offline or LiteLLM"]
    end

    subgraph VAL["5 · Validate — gates quarantine failures"]
        direction TB
        V1["Schema / Grounding / Completeness"]
        V2["Format / Refusal / Dedupe"]
        V3["Contamination / Privacy / License"]
        V1 --> V4{"All gates pass?"}
        V2 --> V4
        V3 --> V4
        V4 -- fail --> V5["Quarantine"]
        V4 -- pass --> V6["Review state"]
    end

    subgraph OUT["6 · Version + export + publish"]
        direction TB
        O1["Dataset version"] --> O2["Release bundle: card · manifest · reports · checksums"]
        O2 --> O3["Exporters — JSONL + variations"]
        O2 --> O4["Publish to Hugging Face — dry-run by default"]
    end

    A5 --> P1
    P3 --> S1
    S3 --> G1
    G4 --> V1
    V6 --> O1
```

## 3. Durable jobs — nothing is lost on a crash

Every stage of the pipeline runs as a **durable job** with leases, heartbeats,
idempotency keys, checkpoints, and budget caps. A crash, kill, or timeout just
expires the lease and **resumes from the last checkpoint** — no re-generation of
paid work.

<p align="center">
  <img src="../assets/durable-jobs.png" alt="Knovaryn durable job lifecycle" width="100%"/>
</p>

```mermaid
flowchart LR
    A["Create job<br/>(idempotency key)"] --> B["Enqueue"]
    B --> C["Lease acquired<br/>(worker holds lease)"]
    C --> D["Stage 1 … Stage N"]
    D --> E{"Checkpoint<br/>per stage"}

    E -->|"normal"| F["Stage complete → persist + heartbeats"]
    F --> G["All stages done"]
    G --> H["Record cost events + result"]
    H --> I["Idempotent done state"]

    E -->|"crash / kill / timeout"| J["Lease expires → re-lease"]
    J --> K["Resume from last checkpoint<br/>(no re-gen of paid work)"]
    K --> D

    E -->|"budget cap hit"| L["Cancel with cost audit"]
    L --> M["Partial state preserved"]
```

## 4. A typical MCP agent session

From an empty workspace to a published dataset version using the 23-tool MCP
suite — exactly what a Claude/Cursor-style agent sees.

<p align="center">
  <img src="../assets/mcp-session.png" alt="Typical MCP agent session" width="100%"/>
</p>

```mermaid
flowchart LR
    A["knovaryn_create_project"] --> B["knovaryn_add_source"]
    B --> C["knovaryn_inspect_source"]
    C --> D["knovaryn_license_report"]
    D --> E["knovaryn_estimate_run"]
    E --> F{"budget OK?"}
    F -->|"yes"| G["knovaryn_start_pipeline"]
    F -->|"no / tune"| E
    G --> H["knovaryn_get_job / run_job<br/>(poll progress)"]
    H --> I["knovaryn_preview_examples"]
    I --> J["knovaryn_review_example"]
    J --> K["knovaryn_validate_dataset"]
    K --> L["knovaryn_compare_runs"]
    L --> M["knovaryn_create_dataset_version"]
    M --> N["knovaryn_export_dataset"]
    N --> O["knovaryn_publish_dataset<br/>(dry-run → confirm)"]
    O --> P["knovaryn_doctor (health check)"]
```

## 5. Security & privacy flow

Offline-first, secrets from the environment only, and nothing published unless
explicitly approved.

<p align="center">
  <img src="../assets/security.png" alt="Knovaryn security and privacy flow" width="100%"/>
</p>

```mermaid
flowchart TD
    subgraph TRUST["Untrusted input boundary"]
        T1["Local file / archive / URL"]
        T2["Path-traversal + symlink checks"]
        T3["Verified archives · SSRF defense · URL ingest OFF by default"]
        T1 --> T2 --> T3
        T3 --> T4["Preflight: SHA-256 · size · license · privacy class"]
    end

    subgraph SECRETS["Secrets handling"]
        S1["API keys from environment only (never committed)"]
        S2["Redacted at display boundary"]
        S3["Never logged · never in cost ledger · never in audit"]
        S1 --> S2 --> S3
    end

    subgraph LOCAL["Offline-first by default"]
        L1["Deterministic fake provider — no keys, no network"]
        L2["Loopback HTTP binding · Host/Origin checks"]
        L3["Bearer token + scopes when KNOVARYN_API_TOKEN set"]
        L1 --> L2 --> L3
    end

    subgraph GATE["Publication gate"]
        G1["License approval required"]
        G2["Privacy report must pass"]
        G3["Confirmation token required"]
        G4["Dry-run by default — nothing pushed unasked"]
        G1 --> G2 --> G3 --> G4
    end

    T4 --> LOCAL
    LOCAL --> GATE
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
        V1["Every example traced to doc · page · sentence (provenance)"]
        V2["10 quality gates that quarantine failures"]
        V3["Durable jobs — leases, heartbeats, resume from checkpoint"]
        V4["License registry + publication gate · dry-run by default"]
        V5["ModelGateway + trainer-native exporters — BYO model"]
        V6["Cost ledger + budget caps (incl. deepseek_flash_budget)"]
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
```
