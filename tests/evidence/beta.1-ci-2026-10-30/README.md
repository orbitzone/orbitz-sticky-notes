# Beta 1 release candidate — CI and local test evidence

| Field | Value |
| --- | --- |
| Date | 2026-10-30 |
| Release candidate | `v0.2.0-beta.1` |
| Source commit | `b02144d27eb8289a059875fc12cc571cbb896b46` |
| GitHub Actions | [Run #12 — Linux tests and Flatpak](https://github.com/orbitzone/orbitz-sticky-notes/actions/runs/41121236944) |
| CI result | Success; 8m 41s |
| Bundle | `orbitz-sticky-notes-x86_64.flatpak` |
| Bundle SHA-256 | `9e98800a4da7452ffbe12cf8e4488c0fd59f877255131ea177a173fb6bc4ea24` |
| Artifact ZIP SHA-256 | `c4bc866c3f01bcfa5dc66f69a9bdfc32d96132674013967660d8c2ee814e9eb5` |

## Local test run

`make test` completed successfully with 146 tests and 2 display-dependent GTK skips. The captured output is in [`local-tests.log`](local-tests.log). The skips are expected without an accessible GTK display; interactive GUI checks are documented separately in the VM evidence directories.

`git diff --check` passed. The release bundle checksum was independently checked against the local Flatpak with `sha256sum -c`; the result was `OK`.

## VM validation

The exact bundle above was subsequently installed as an upgrade in the Ubuntu 24.04.4 QA VM and exercised in its visible GNOME 46 session. The package hash matched before transfer and after install. See the [exact beta.1 VM report](../ubuntu-24.04.4-exact-beta.1-2026-10-30/README.md) for the update comparison, interactive results, screenshots, and limits.

This confirms the exact bundle on Ubuntu 24.04.4 only. The earlier Ubuntu 22.04 and Ubuntu 24.04 evidence used prior CI candidates and remains separate in the [production-readiness report](../../../docs/production-readiness-report.md) and the [previous GNOME 46 manual QA](../ubuntu-24.04-gnome-46-2026-10-30/README.md).

