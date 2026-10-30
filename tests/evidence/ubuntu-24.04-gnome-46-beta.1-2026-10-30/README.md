# Ubuntu 24.04 / GNOME 46 — beta.1 Sticky Code resize evidence

| Field | Value |
| --- | --- |
| Date | 2026-10-30 |
| App | `io.orbitz.Postits` |
| OS | Ubuntu 24.04.4 LTS x86_64 |
| Desktop | GNOME Shell 46.0 |
| Flatpak runtime | GNOME 49 |
| App commit | `2870dfb5473fb51ecef7eb0d620953758ea465583ecd37b22e61d5d970779cbb` |
| CI commit | `19a7e338108e907e61fb8a694d2497d8830b3f95` |
| Bundle SHA-256 | `5f6c7160e02578e5a01e6c520ad409ca10633c48dcfb5a19727b958fa3bb3416` |
| Display | 1024×768 |

The same Flatpak bundle produced by CI was installed in this disposable VM after the previous release. The note contained 200 synthetic code lines. Its own bottom-right resize handle was dragged to make the code window smaller and then larger; the editor content remained intact. The images are direct VM screenshots. They include the disposable VM's terminal in the background; no real note or attachment data is present.

- `sticky-code-before-resize.png` — initial large Sticky Code window; status shows line 200.
- `sticky-code-after-shrink.png` — reduced Sticky Code window.
- `sticky-code-after-expand.png` — expanded again after shrinking.

This evidence covers the custom Sticky Code resize handle only. It does not certify other desktops or display servers.
