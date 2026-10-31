# Test evidence index

This directory contains the retained CI, automated-test, and manual VM evidence for the beta release. Each evidence set identifies its tested commit or bundle and records limits; results from different bundle hashes must not be treated as interchangeable.

| Evidence set | Contents |
| --- | --- |
| [`beta.1-final-2026-10-30/`](beta.1-final-2026-10-30/README.md) | Final durable-attachment and launcher regression validation; CI/package results. |
| [`beta.1-ci-2026-10-30/`](beta.1-ci-2026-10-30/README.md) | CI run #12 for `b02144d`, exact bundle SHA-256, captured local test output, and link to the subsequent exact-bundle VM run. |
| [`ubuntu-24.04.4-exact-beta.1-2026-10-30/`](ubuntu-24.04.4-exact-beta.1-2026-10-30/README.md) | Exact beta.1 bundle upgrade and interactive evidence on Ubuntu 24.04.4/GNOME 46, including Sticky Code resize, menus, opacity, attachment and email draft limits. |
| [`ubuntu-24.04-gnome-46-beta.1-2026-10-30/`](ubuntu-24.04-gnome-46-beta.1-2026-10-30/README.md) | Screenshots of the custom Sticky Code resize handle using the prior beta candidate `5f6c7160…`. |
| [`ubuntu-24.04-gnome-46-2026-10-30/`](ubuntu-24.04-gnome-46-2026-10-30/README.md) | Manual functional screenshots from Ubuntu 24.04/GNOME 46 using the earlier candidate `8528a315…`, including note, PIN, attachments, menu, opacity, and email-handler checks. |
| [`docs/production-readiness-report.md`](../../docs/production-readiness-report.md) | Combined Ubuntu 22.04/24.04 upgrade evidence, validation summary, risk assessment, and unresolved compatibility gates. |

## Evidence handling

- The Ubuntu 24.04 screenshots use synthetic QA note content; the Thunderbird first-run image is redacted.
- The Ubuntu 22.04 validation recorded in the production-readiness report was headless and has no interactive desktop screenshots.
- The exact `b02144d` artifact has CI, local test, and Ubuntu 24.04.4 VM evidence. It has not been tested on Ubuntu 22.04.
- SHA-256 manifests inside each evidence directory detect accidental changes to their screenshots/logs.

