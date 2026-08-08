# Third-Party Licenses

Knovaryn is distributed under the **Apache License, Version 2.0** (see the root
[LICENSE](LICENSE)). This project depends on third-party libraries and tools whose
licenses we are required to preserve and, in some cases, redistribute.

## How third-party notices are handled

- **Dependency licenses.** The Apache-2.0 license requires that redistributions
  preserve applicable notices. Where a dependency's license or notice file must be
  included in a distribution (wheel, container image, or source archive), that
  notice is preserved verbatim and is bundled with the artifacts Knovaryn ships.
- **Where notices live.** The Knovaryn build and packaging tooling recreates a
  third-party notices artifact at release time from the locked dependency set, so a
  release accurately reflects exactly what it bundled. Dependency-addition reviews
  (via the dependency baseline, ADR `0001`) record each dependency's license.
- **Because licenses and dependency sets change over time**, this file intentionally
  does **not** attempt to enumerate every upstream license inline — doing so would
  drift out of date. Instead:

> **The authoritative third-party notices for any given Knovaryn release are
> generated from the `uv.lock` / dependency set at build time** and shipped with the
> corresponding distribution artifact. If you receive a Knovaryn artifact, the
> notices included with *that artifact* are the source of truth.

## What we ask of consumers

- Redistributions of Knovaryn (source or binary) must retain the Apache-2.0 license
  and any included third-party notices, per the terms of the Apache-2.0 license.
- If you repackage Knovaryn, please also preserve and redistribute the third-party
  notices so downstream users retain the legal attributions they are owed.

## Project license

Knovaryn itself is licensed under the Apache License, Version 2.0:

- [LICENSE](LICENSE)

## Reporting a licensing problem

If you believe a dependency or bundled artifact is missing its required notice, or
that Knovaryn includes material under an incompatible license, please open an issue
(or, for urgent legal matters, contact the maintainers via `maintainers@knovaryn.dev`).
We will address license compliance promptly.
