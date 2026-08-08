# Privacy & Licensing

Knovaryn is a training-data foundry: it ingests documents, cleans and labels
them, and exports datasets for model training. Privacy and licensing are
design concerns from intake through export. This page describes the built-in
controls and the responsibilities that remain with the operator. See
[hardening.md](./hardening.md) for the operational checklist and
[architecture/security.md](../architecture/security.md) for the threat model.

> The built-in controls reduce risk; they are not a certification. Whether a
> given corpus may be used for training is a legal determination you must make
> for your jurisdiction, your contract terms, and the provenance of each
> document.

## General design principles

- **Untrusted-in, controlled-out.** Every source document is treated as
  untrusted at intake (spec §8.6). Nothing in a source is allowed to drive
  code execution, path traversal, or prompt injection against the operator.
- **Local by default.** The control plane and pipeline run on the operator's
  machine (loopback `127.0.0.1:8765` by default). Data stays on the machine
  unless the operator explicitly configures external storage or ingestion.
- **Source and provenance.** Every document entering the pipeline is tracked
  with provenance metadata (origin, source path, ingest time, hash) so an
  operator can audit where a training row came from.

## Privacy controls

### Intake

- Restrict the source surface with `sources.allowed_roots`, disable symlink
  following, and bound `max_file_mb` / `max_pages` so the pipeline cannot be
  coerced into reading more than the operator intended.
- Treat all docs as untrusted: parsing, chunking, and extraction never trust
  content as instructions.
- URL ingestion is off by default; enabling it extends the intake surface and
  requires SSRF hardening (see `hardening.md`).

### Storage & secrets

- Secrets (API keys, tokens, service credentials) are never committed and
  never stored in document text fields. `.gitignore` excludes secret material;
  secret handling is documented with the configured secrets backend.
- Embedded stores are encrypted at rest by the OS when the machine disk is
  encrypted; treat `*.db` files as sensitive and control access to them.

### Data minimization

- Only the fields required for the configured use case are carried through the
  pipeline; the schema is explicit (spec schema) rather than "load everything."
- Operators should review any dataset that may contain personal data and apply
  redaction/anonymization as required before export.

## Licensing controls

- Knovaryn tracks a `license` field and provenance on each ingested document
  and surfaces it in the dataset manifest, so downstream consumers can see what
  terms applied to the source material.
- The export manifest (`manifest.json`) records source provenance, hashes, and
  per-source license metadata so a training corpus can be traced back to its
  inputs.
- Knovaryn does **not** make licensing judgments for you. Decide whether each
  source corpus permits the intended use (training, redistribution, commercial)
  under its own terms, and record that decision in the manifest or an operator
  policy.

## Operator responsibilities

1. Confirm you have the right to ingest and train on each source corpus.
2. Review datasets for personal data and apply redaction before export where
   required.
3. Record a licensing decision per source and keep the audit trail.
4. Apply the operational controls in `hardening.md` before any deployment that
   is not a throwaway local demo.

## Related

- [Hardening checklist](./hardening.md)
- [Architecture: security](../architecture/security.md)
- Provenance & manifest schema in the pipeline documentation (`docs/pipeline/`)
