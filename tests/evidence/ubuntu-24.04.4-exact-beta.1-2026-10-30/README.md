# Exact beta.1 upgrade and interactive QA — Ubuntu 24.04.4

| Field | Result |
| --- | --- |
| Date | 2026-10-30 |
| OS | Ubuntu 24.04.4 LTS, x86_64 |
| Desktop | GNOME Shell 46.0, 1024×768 |
| App | `io.orbitz.Postits`, x86_64 |
| Installed commit | `04ba23195c46b67d37ff39ce293ff0c6dff2c80c3f7c0744bae6497426bf3488` |
| Runtime | `org.gnome.Platform/x86_64/49` |
| Source commit | `b02144d27eb8289a059875fc12cc571cbb896b46` |
| Bundle SHA-256 | `9e98800a4da7452ffbe12cf8e4488c0fd59f877255131ea177a173fb6bc4ea24` |

The candidate bundle was copied to the guest and its SHA-256 matched the local release bundle. Flatpak updated an existing installation; the app was then launched in the guest's live GNOME session. No application was installed on the host.

## Upgrade data comparison

A consistent SQLite backup was made before the update. Immediately after installation and before interactive changes, the four synthetic notes and their text, title, mode, positions, dimensions, and metadata matched the backup. The single attachment metadata row also matched. The fixture included a long Sticky Code note at `(66, 32)` with 200 synthetic lines.

The attachment row's path was a Flatpak document-portal path (`/run/flatpak/doc/...`). That source file was no longer present after the VM/session restart. Thus, the database record survived the upgrade, but access to the original attachment content did not. A newly selected synthetic attachment was included in the generated QA email MIME draft during the live session; this does not resolve persistence across restart and is a release limitation.

Interactive QA added only synthetic notes and text. The VM now retains those QA changes; it was not reset after testing.

## Interactive results

| Flow | Result |
| --- | --- |
| Sticky Code custom resize | Passed visually: reduced with its own handle, then expanded; long content remained available. See `sticky-code-shrunk.png` and `sticky-code-expanded.png`. This was a visual functional check, not a frame-time benchmark. |
| Note/Sticky Code template toggle | Passed: the note and code view swapped without simultaneous duplicate windows, and text remained available after toggling back. |
| Opacity | Passed visually for note and code views; reduced opacity exposed the desktop behind each window. The initial state was restored after the check. |
| Settings and shortcuts | Both dialogs opened and were inspected. No PIN was configured. |
| Archive / restore | Passed: the synthetic fixture was archived, listed by title, and restored. |
| Hide / restore from the note menu | Passed in the app menu. The launcher `Open hidden notes` command was also exercised, but this run did not conclusively show it restoring the hidden fixture; treat that launcher path as unverified. |
| Launcher `New note` | Passed: the launcher command created a synthetic note. The test database contains overlapping blank fixtures at default coordinates. |
| Launcher `Close notes` | Passed: all note windows disappeared from the visible desktop. |
| Email draft | The dialog accepted `qa@example.invalid`; Enter launched Thunderbird. The generated `.eml` contained the synthetic note body and a MIME attachment and was marked `X-Unsent: 1`. Thunderbird displayed its first-run account setup, so the compose window itself could not be visually inspected. No account was configured and no message was sent. |
| Attachment chooser | Opened the GTK file picker and selected a synthetic text file. The attachment icon appeared in the note, and the draft MIME contained its payload. Persistence after a later restart remains unverified; the prior portal grant had expired. |

Screenshots show only the disposable VM and synthetic data. `email-dialog-with-test-recipient.png` uses the reserved `.invalid` domain; the Thunderbird first-run screen is intentionally excluded because it displayed profile information.

## Remaining compatibility and release limits

- The exact beta.1 bundle was not run on Ubuntu 22.04. This evidence cannot substantiate Ubuntu 22.04 support.
- The original attachment file path stored through the document portal did not resolve after the VM/session restart. Attachment persistence across upgrades/restarts needs a durable design or explicit documentation and validation.
- Thunderbird's first-run flow prevented visual confirmation of the compose window, even though the app generated a complete unsent MIME draft with body and attachment.
- The launcher `Open hidden notes` route was not conclusively validated in this run.
- No email was sent; no account, real recipient, or personal data was used.

The PNGs in this directory are direct screenshots from the guest. `SHA256SUMS` covers every evidence file in this directory except the checksum file itself.
