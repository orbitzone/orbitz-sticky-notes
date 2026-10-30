# Ubuntu 24.04 / GNOME 46 manual QA evidence

| Field | Value |
| --- | --- |
| Date | 2026-10-30 |
| Application | `io.orbitz.Postits` |
| Flatpak runtime | GNOME 49 |
| Test bundle SHA-256 | `8528a315cb5c352eaaf78e840db7a8241b2bab464247eec90c029aa37215f4c8` |
| Environment | Disposable Ubuntu 24.04.4 LTS x86_64 VM, GNOME Shell 46.0, 1024×768 |

All note text and attachments in these screenshots were synthetic QA data. The Thunderbird first-run screenshot has the profile-name field redacted. SSH, sudo, package-installation, and intermediate account-setup captures were not included because they are infrastructure details and do not add product behavior evidence.

## Screenshots

| File | What it records | Result / limitation |
| --- | --- | --- |
| `orbitz-qa-realclick-menu.png` | Main note menu | Opened; the screenshot shows the available commands. It does not mean every command was activated individually. |
| `orbitz-qa-settings.png` | Settings dialog | Opened. Destructive PIN reset was not run. |
| `orbitz-qa-shortcuts.png` | Shortcuts dialog | Opened. |
| `orbitz-qa-color-blue-conv.png` | Note color | Synthetic note changed to blue. |
| `orbitz-qa-always-above-conv.png` | Always above menu state | The option appeared selected. |
| `orbitz-qa-opacity-note.png` | Reduced opacity | Desktop was visible through the note. Exact percentage and Sticky Code opacity were not compared. |
| `orbitz-qa-filechooser.png` | Native attachment chooser | Opened. |
| `orbitz-qa-pdf-attached.png`, `orbitz-qa-png-attached2.png` | PDF and PNG attached | Synthetic files appeared as note attachments. |
| `orbitz-qa-pdf-preview.png`, `orbitz-qa-image-preview2.png` | PDF and image previews | Both opened; the PDF page rendered white in the dark preview surface. |
| `orbitz-qa-resize-large.png`, `orbitz-qa-resize-small.png` | Regular note resize | The note was enlarged and reduced. |
| `orbitz-qa-stickycode.png` | Sticky Code view | Code window shown without a second note behind it. |
| `orbitz-qa-stickycode-resized.png` | Sticky Code after window resize | Resized using GNOME/WM keyboard resize; this does not validate the custom resize handle. |
| `orbitz-qa-return-note.png` | Switch back from Sticky Code | Note title, body, and attachments remained present. |
| `orbitz-qa-secret-lock.png` | Secret note locked | Content was hidden. |
| `orbitz-qa-pin-wrong.png`, `orbitz-qa-pin-correct2.png` | PIN validation | Wrong PIN rejected; synthetic correct PIN unlocked the note. |
| `orbitz-qa-pin-esc.png` | Escape while unlocked | Note returned to the locked view. |
| `orbitz-qa-open-hidden2.png` | Restore hidden secret note | Hidden note reopened and remained locked. |
| `orbitz-qa-archived-dropdown.png`, `orbitz-qa-archive-restored.png` | Archive and restore | Untitled note appeared as `undefined-3` and was restored. |
| `orbitz-qa-delete-confirmation.png` | State after Delete note | Synthetic note was removed; no confirmation dialog appeared in this build. |
| `orbitz-qa-unlocked-screen.png`, `orbitz-qa-email-enter.png` | Email draft dialog | Form opened, then closed after Enter. The default client launch is separately limited by the Thunderbird first-run screen. |
| `thunderbird-first-run-redacted.png` | Default email client launch | Thunderbird opened to first-run setup, before the compose editor. No email was sent; attachment delivery to the composer was not verified. |

## Scope

This is manual visual evidence for one Ubuntu/GNOME combination, not cross-distribution certification. The Sticky Code custom resize handle, fully configured Thunderbird compose flow with attachments, some menu commands, accessibility with a screen reader, and other desktop sessions remain unverified. The project validation notes are in [`docs/validation.md`](../../../docs/validation.md). The evidence limitations are also recorded above; these screenshots alone do not establish production readiness.
