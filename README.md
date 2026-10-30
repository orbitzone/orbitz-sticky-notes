# Orbitz Sticky Notes

**Keep useful notes right on your Linux desktop.** Orbitz Sticky Notes brings colorful, always-with-you notes and a focused code snippet workspace into one lightweight desktop app—so the details that matter stay close while you work.

Create a note in seconds, give it a title, choose a color, and place it where it helps your workflow. Switch the same note to **Sticky Code** when you want a clean dark editor for a snippet. With great features and details that matter, it is an awesome, productive companion for daily tasks, planning, quick references, and development work—useful tools that make your workflow feel amazing without getting in the way.

> **Preview release:** Orbitz Sticky Notes is currently distributed as an x86_64 Flatpak preview. Please review the compatibility and privacy notes below before installing. There is no Flathub listing or automatic update channel yet.

## Useful features

- **Colorful desktop notes** with editable titles, rich-text shortcuts, emoji picker, links, move and resize controls.
- **Sticky Code** transforms a note into a dark code editor while keeping its title and content in the same note. It includes syntax highlighting, line numbers, indentation, language selection, and one-click code copying. The app does not execute code.
- **A smoother workflow** with hidden and archived notes, keyboard shortcuts, per-note opacity, and desktop launcher actions.
- **Private-by-default local storage:** notes and daily backups stay on your computer. Optional PIN locking hides secret notes from view.
- **Attachments and previews** for common image and PDF files, plus a handoff to your default email application with the note and selected attachments.
- **English and Brazilian Portuguese** interface options.

Details that matter: closing a note hides it; it does not delete it. Permanent deletion is a separate menu action. Resizing changes the available text area while the font stays the same. Long content scrolls within the note or code editor.

## Install the Linux preview

The current preview package targets **x86_64** and the GNOME 49 Flatpak runtime. It uses GTK 3 with the X11 socket; a Wayland session therefore needs XWayland. Window management, portal, and accessibility workflows still need desktop-specific testing. The app does not depend on a particular GNOME Shell extension version, but window placement and “always on top” behavior vary by desktop environment and window manager.

1. Install Flatpak for your distribution using the [Flatpak setup guide](https://flatpak.org/setup/).
2. Download `orbitz-sticky-notes-x86_64.flatpak` from the [v0.1.0 preview release](https://github.com/orbitzone/orbitz-sticky-notes/releases/tag/v0.1.0).
3. In the download folder, install and launch it:

```sh
flatpak install --user ./orbitz-sticky-notes-x86_64.flatpak
flatpak run io.orbitz.Postits
```

If prompted to add the Flathub runtime source, follow Flatpak's prompt or add it with:

```sh
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
```

To verify a release download, use the accompanying `SHA256SUMS` file:

```sh
sha256sum -c SHA256SUMS
```

Updates are not automatic yet. Install a newer release package when one is published. Your notes are kept when the app is updated.

## Privacy and storage

The Flatpak stores its database and backups under:

```text
~/.var/app/io.orbitz.Postits/data/orbitz-postits/
```

The PIN is a **visual privacy lock**, not encryption. Note titles, text, attachment names, paths, and backups are not encrypted in the local database. Do not use secret notes as a substitute for encrypted storage. Resetting a forgotten PIN permanently deletes secret notes so a new PIN can be set; ordinary notes are preserved.

Attachments remain in their original folders. Orbitz stores their paths and names, and does not delete the original files when a note or attachment link is removed. The app asks for access to files you select; it does not request general access to your home folder or network. Email drafts are opened in your system's default email application for you to review and send.

## Compatibility and current limits

- Linux desktop with Flatpak, the GNOME 49 runtime, and an X11 display; a Wayland session needs XWayland.
- The published preview is x86_64. ARM builds and other architectures have not been validated.
- Native Wayland-only sessions without XWayland are not supported by this build.
- Window positions, workspace behavior, and always-on-top support depend on the desktop environment.
- Automated CI checks and GTK tests run in a virtual display; they are not a substitute for visual testing on GNOME, KDE, and Xfce hardware setups.
- Email handoff depends on the desktop portal and installed email client. Check the release notes for the latest tested combinations.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+N` | Create a note |
| `Ctrl+H` | Hide the current note |
| `Ctrl+0` | Restore the default note size |
| `Ctrl+B` / `Ctrl+I` / `Ctrl+U` | Bold / italic / underline selected text |
| `Ctrl+E` | Open the emoji picker |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / redo |
| `Ctrl+click` | Open a link |
| `Esc` | Close transient popups; lock an unlocked secret note while editing |

The **Shortcuts** item in the note menu shows the shortcuts available in the installed version.

## Build from source

Requirements: Flatpak, Flatpak Builder, and the Flathub runtime repository. From the repository root:

```sh
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak-builder --user --install-deps-from=flathub --assumeyes --repo=repo build-dir packaging/io.orbitz.Postits.json
flatpak build-bundle repo orbitz-sticky-notes-x86_64.flatpak io.orbitz.Postits --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo
```

For native development, install Python 3, PyGObject, GTK 3, GtkSourceView 4, and SQLite, then run `python3 sticky-notes/postits.py` from a graphical session. Set `XDG_DATA_HOME` to a temporary directory when developing or testing to keep test data separate from your personal notes. Run the test suite with `make test`.

## Project and community

Orbitz Sticky Notes is developed by **Felipe Santiago / orbitzone** and licensed under **GPL-3.0-only**. GtkSourceView is distributed under LGPL-2.1-or-later; its license is included with the package.

- [Source code](https://github.com/orbitzone/orbitz-sticky-notes)
- [Issues and feature requests](https://github.com/orbitzone/orbitz-sticky-notes/issues)
- [Preview downloads](https://github.com/orbitzone/orbitz-sticky-notes/releases)

Have an idea that would make your Linux workflow more useful? Open an issue with your desktop environment, Flatpak version, and steps to reproduce the behavior.
