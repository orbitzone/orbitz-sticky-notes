# Final beta.1 QA — 2026-10-30

The source includes durable private attachment copies, migration of accessible legacy attachments, retry on unavailable legacy sources, and launcher recovery. Originals are never removed by managed-copy deletion. Expired legacy portal grants cannot recover missing contents.

Local validation: 154 tests passed with GTK enabled under Xvfb, no skips. Command: `PATH=/tmp/xvfb-local/usr/bin:$PATH GSETTINGS_BACKEND=memory /tmp/xvfb-local/usr/bin/xvfb-run -a python3 -m unittest discover -s tests -v`. Transcript: `local-tests.log`.

Desktop-file validation, AppStream validation and `git diff --check` passed. Xvfb tests do not certify real compositor behavior or Thunderbird composition. Historical Ubuntu 24.04 interaction screenshots identify older bundles and remain separate.

## Official artifact

Source commit: `ba29f50367eb3e76a53ee8c64312185c42e7991b`.
CI: https://github.com/orbitzone/orbitz-sticky-notes/actions/runs/41153532222 — successful tests and Flatpak build.
Bundle: 19,626,784 bytes; SHA-256 `11b1d7bcaa27911cde14d3947128e3d64256f5896167bb2014ef7a9cfe58a9ac`.
The downloaded CI artifact was transferred to both VMs; each guest printed the same SHA-256 before installation.

## Exact-package VM checks

`package-smoke.py` ran with Python and GTK from the installed Flatpak, a private D-Bus session and a temporary synthetic Store. Ubuntu 22.04.5 used Xvfb; Ubuntu 24.04.4 used the real GNOME 46 XWayland session. Both checks passed: attachment content after deleting the original and reopening Store, SQLite integrity, note mapping, hiding and restoration through the production command-line handler. Installation upgraded the prior candidate in each VM. The crop `ubuntu-24.04-final-note.png` shows the final package's synthetic note after restoration.

These are targeted package checks, not full desktop-menu automation or a reboot test. The launcher handler was exercised directly in the installed runtime; the GNOME icon menu itself was not clicked. Earlier resize, opacity and menu screenshots remain historical evidence. Thunderbird compose contents, Orca, native Wayland and other architectures remain unverified. Portal services emitted warnings on the headless VM; those checks do not certify portals. Session helper shutdown can report a closed D-Bus connection after the successful assertions.
