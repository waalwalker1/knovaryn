---
name: Security
about: Redirect to the private security reporting path
title: "[SECURITY] Do not use this template for vulnerabilities"
labels: []
assignees: ""
---

## This issue template is not for reporting vulnerabilities

**Thank you** for wanting to report a security issue. Please do **not** open a
public issue with vulnerability details — that exposes the issue to the community
before a fix can ship, which is exactly what we want to avoid.

## Report privately instead

Report security vulnerabilities privately to the Knovaryn security maintainers:

- **Private report:** GitHub Security tab → "Report a vulnerability" (see SECURITY.md)
- **GitHub private vulnerability reporting:** use the repository's private
  security-advisory path once it is enabled (repository → Security → Report a
  vulnerability).

Please do not include security details in this issue. If you open a public issue,
a maintainer will ask you to report privately and may close or redact the issue.

## What to include in the private report

- The Knovaryn version(s) and commit hash affected, if known.
- A minimal reproduction (without leaking secrets).
- Impact assessment on confidentiality / integrity / availability.
- Any suggested mitigation.

We aim to acknowledge reports within **3 business days** and to coordinate a fix
before public disclosure. See [SECURITY.md](../../SECURITY.md) for the full policy.

---

**If you are here for a non-security bug**, please close this issue and use the
[bug report template](./bug_report.md) instead.
