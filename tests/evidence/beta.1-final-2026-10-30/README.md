# Final beta.1 QA — 2026-10-30

The source includes durable private attachment copies, migration of accessible legacy attachments, retry on unavailable legacy sources, and launcher recovery. Originals are never removed by managed-copy deletion. Expired legacy portal grants cannot recover missing contents.

Local validation: 154 tests passed with GTK enabled under Xvfb, no skips. Command: `PATH=/tmp/xvfb-local/usr/bin:$PATH GSETTINGS_BACKEND=memory /tmp/xvfb-local/usr/bin/xvfb-run -a python3 -m unittest discover -s tests -v`. Transcript: `local-tests.log`.

Desktop-file validation, AppStream validation and `git diff --check` passed. Xvfb tests do not certify real compositor behavior or Thunderbird composition. Historical Ubuntu 24.04 interaction screenshots identify older bundles and remain separate.

Final CI, package and VM results will be appended after building this source commit.
