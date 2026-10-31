# Orbitz Sticky Notes

**Keep useful notes right on your Linux desktop.** Orbitz Sticky Notes brings colorful, always-with-you notes and a focused code snippet workspace into one lightweight desktop app—so the details that matter stay close while you work.

Create a note in seconds, give it a title, choose a color, and place it where it helps your workflow. Switch the same note to **Sticky Code** when you want a clean dark editor for a snippet. With great features and details that matter, it is an awesome, productive companion for daily tasks, planning, quick references, and development work—useful tools that make your workflow feel amazing without getting in the way.

> **Beta release — v0.2.0-beta.1:** Orbitz Sticky Notes is available as an x86_64 Flatpak for Ubuntu 22.04 and 24.04. Review the compatibility and privacy notes below before installing. There is no Flathub listing or automatic update channel yet.

## Useful features

- **Colorful desktop notes** with editable titles, rich-text shortcuts, emoji picker, links, move and resize controls.
- **Sticky Code** transforms a note into a dark code editor while keeping its title and content in the same note. It includes syntax highlighting, line numbers, indentation, language selection, and one-click code copying. The app does not execute code.
- **A smoother workflow** with hidden and archived notes, keyboard shortcuts, per-note opacity, and desktop launcher actions.
- **Private-by-default local storage:** notes and daily backups stay on your computer. Optional PIN locking hides secret notes from view.
- **Attachments and previews** for common image and PDF files, plus a handoff to your default email application with the note and selected attachments.
- **English and Brazilian Portuguese** interface options.

Details that matter: closing a note hides it; it does not delete it. Permanent deletion is a separate menu action. Resizing changes the available text area while the font stays the same. Long content scrolls within the note or code editor.

## Install the Linux beta

The beta package targets **x86_64** and the GNOME 49 Flatpak runtime. Ubuntu 22.04 and 24.04 are the supported beta targets. It uses GTK 3 with the X11 socket; a Wayland session therefore needs XWayland. Interactive workflows have been checked on Ubuntu 24.04 with GNOME; Ubuntu 22.04 has been checked for clean installation, upgrade, data migration, and startup under a virtual display. Email handoff, window management, and accessibility can vary with the installed desktop services and still need broader testing.

1. Install Flatpak for your distribution using the [Flatpak setup guide](https://flatpak.org/setup/).
2. Download `orbitz-sticky-notes-x86_64.flatpak` from the [v0.2.0-beta.1 release](https://github.com/orbitzone/orbitz-sticky-notes/releases/tag/v0.2.0-beta.1).
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

Attachments are copied into Orbitz's private per-user data folder so they remain available after a temporary file-portal grant expires. The selected originals stay in their folders. Removing an attachment or deleting a note removes Orbitz's managed copy, not the original. The app asks for access to files you select; it does not request general access to your home folder or network. Email drafts are opened in your system's default email application for you to review and send. Attachment copies are not encrypted, so protect your Linux user account and backups accordingly. Daily SQLite snapshots do not include attachment files; back up the entire app data folder to preserve both. Older attachments whose portal access has already expired must be attached again.

## Compatibility and current limits

- Ubuntu 22.04 or 24.04, x86_64, Flatpak, the GNOME 49 runtime, and an X11 display; a Wayland session needs XWayland.
- The published beta is x86_64. ARM builds and other architectures have not been validated.
- Native Wayland-only sessions without XWayland are not supported by this build.
- Window positions, workspace behavior, and always-on-top support depend on the desktop environment.
- Ubuntu 22.04 package install, upgrade, data migration, and startup were exercised in a clean VM. Targeted visual interactions were checked on Ubuntu 24.04 GNOME; other desktop environments have not been certified.
- Email handoff depends on the desktop portal and installed email client. The beta notes list the client combinations actually exercised.

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
- [Beta downloads](https://github.com/orbitzone/orbitz-sticky-notes/releases)

Have an idea that would make your Linux workflow more useful? Open an issue with your desktop environment, Flatpak version, and steps to reproduce the behavior.
