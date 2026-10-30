PREFIX ?= /usr/local
DESTDIR ?=
APPDIR = $(DESTDIR)$(PREFIX)/share/orbitz-sticky-notes

.PHONY: install test
install:
	install -d "$(APPDIR)/sticky-notes" "$(APPDIR)/i18n"
	install -m644 sticky-notes/*.py "$(APPDIR)/sticky-notes/"
	install -m644 sticky-notes/*.png "$(APPDIR)/sticky-notes/"
	install -m644 i18n/*.py i18n/*.json "$(APPDIR)/i18n/"
	install -Dm755 data/orbitz-sticky-notes "$(DESTDIR)$(PREFIX)/bin/orbitz-sticky-notes"
	install -Dm644 data/io.orbitz.Postits.desktop "$(DESTDIR)$(PREFIX)/share/applications/io.orbitz.Postits.desktop"
	install -Dm644 sticky-notes/postits.svg "$(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/io.orbitz.Postits.svg"
	install -Dm644 data/io.orbitz.Postits.metainfo.xml "$(DESTDIR)$(PREFIX)/share/metainfo/io.orbitz.Postits.metainfo.xml"
	install -Dm644 data/io.orbitz.Postits.gschema.xml "$(DESTDIR)$(PREFIX)/share/glib-2.0/schemas/io.orbitz.Postits.gschema.xml"
	install -Dm644 LICENSE "$(DESTDIR)$(PREFIX)/share/licenses/orbitz-sticky-notes/LICENSE"
	install -Dm644 packaging/licenses/GtkSourceView-LGPL-2.1.txt "$(DESTDIR)$(PREFIX)/share/licenses/gtksourceview4/COPYING"
	glib-compile-schemas "$(DESTDIR)$(PREFIX)/share/glib-2.0/schemas"

test:
	GSETTINGS_BACKEND=memory python3 -m unittest discover -s tests -v
