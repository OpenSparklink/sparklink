PREFIX ?= /usr/local
SBINDIR ?= $(PREFIX)/sbin
BINDIR ?= $(PREFIX)/bin
LIBDIR ?= $(PREFIX)/lib
INCLUDEDIR ?= $(PREFIX)/include
SYSCONFDIR ?= /etc
DBUSSERVICEDIR ?= $(PREFIX)/share/dbus-1/system-services
DBUSCONFDIR ?= $(PREFIX)/share/dbus-1/system.d
UNITDIR ?= $(PREFIX)/lib/systemd/system
STATEDIR ?= /var/lib/sparklink
MANDIR ?= $(PREFIX)/share/man

CARGO ?= cargo
CARGO_FLAGS ?= --release --workspace
INSTALL ?= install
UV ?= uv
DOCS_RUN = $(UV) run --locked --only-group docs
SPHINX_FLAGS = -n -W --keep-going

.PHONY: all build check test install uninstall clean docs docs-live docs-linkcheck

all: build

build:
	$(CARGO) build $(CARGO_FLAGS)

check:
	$(CARGO) check --workspace

test:
	$(CARGO) test --workspace

clippy:
	$(CARGO) clippy --workspace -- -W clippy::all

fmt:
	$(CARGO) fmt --all

install: build
	# Daemon
	$(INSTALL) -Dm755 target/release/slkd        $(DESTDIR)$(SBINDIR)/slkd
	# CLI tools
	$(INSTALL) -Dm755 target/release/slkconfig    $(DESTDIR)$(BINDIR)/slkconfig
	$(INSTALL) -Dm755 target/release/slctl        $(DESTDIR)$(BINDIR)/slctl
	$(INSTALL) -Dm755 target/release/slktest        $(DESTDIR)$(BINDIR)/slktest
	$(INSTALL) -Dm755 target/release/slkmon       $(DESTDIR)$(BINDIR)/slkmon
	$(INSTALL) -Dm755 target/release/slkdump      $(DESTDIR)$(BINDIR)/slkdump
	$(INSTALL) -Dm644 data/man/man1/slktest.1 $(DESTDIR)$(MANDIR)/man1/slktest.1
	# Shared library
	$(INSTALL) -Dm755 target/release/liblibsparklink.so $(DESTDIR)$(LIBDIR)/libsparklink.so.0.1.0
	ln -sf libsparklink.so.0.1.0 $(DESTDIR)$(LIBDIR)/libsparklink.so.0
	ln -sf libsparklink.so.0     $(DESTDIR)$(LIBDIR)/libsparklink.so
	# Header
	$(INSTALL) -Dm644 crates/libsparklink/include/sparklink.h $(DESTDIR)$(INCLUDEDIR)/sparklink.h
	# Configuration
	$(INSTALL) -Dm644 data/config/main.conf       $(DESTDIR)$(SYSCONFDIR)/sparklink/main.conf
	# D-Bus
	$(INSTALL) -Dm644 data/dbus/org.sparklink.service $(DESTDIR)$(DBUSSERVICEDIR)/org.sparklink.service
	$(INSTALL) -Dm644 data/dbus/sparklink.conf        $(DESTDIR)$(DBUSCONFDIR)/sparklink.conf
	# systemd
	$(INSTALL) -Dm644 data/systemd/sparklink.service  $(DESTDIR)$(UNITDIR)/sparklink.service
	# State directory
	$(INSTALL) -dm755 $(DESTDIR)$(STATEDIR)

uninstall:
	rm -f $(DESTDIR)$(SBINDIR)/slkd
	rm -f $(DESTDIR)$(BINDIR)/slkconfig
	rm -f $(DESTDIR)$(BINDIR)/slctl
	rm -f $(DESTDIR)$(BINDIR)/slktest
	rm -f $(DESTDIR)$(MANDIR)/man1/slktest.1
	rm -f $(DESTDIR)$(BINDIR)/slkmon
	rm -f $(DESTDIR)$(BINDIR)/slkdump
	rm -f $(DESTDIR)$(LIBDIR)/libsparklink.so*
	rm -f $(DESTDIR)$(INCLUDEDIR)/sparklink.h
	rm -rf $(DESTDIR)$(SYSCONFDIR)/sparklink
	rm -f $(DESTDIR)$(DBUSSERVICEDIR)/org.sparklink.service
	rm -f $(DESTDIR)$(DBUSCONFDIR)/sparklink.conf
	rm -f $(DESTDIR)$(UNITDIR)/sparklink.service

clean:
	$(CARGO) clean

# Documentation has its own locked Python environment and no hardware access.
docs:
	PYTHONPATH=tools python3 -m unittest discover -s tools/tests -p test_docs_integrity.py -v
	python3 tools/check_doc_examples.py
	python3 tools/check_qualifications.py
	$(DOCS_RUN) python tools/check_docs.py
	rm -rf docs/_build/html
	$(DOCS_RUN) sphinx-build -E -d docs/_build/doctrees/html $(SPHINX_FLAGS) -b html docs docs/_build/html
	$(DOCS_RUN) python tools/check_docs.py --html docs/_build/html --report docs/_build/documentation-audit.json

docs-live:
	$(DOCS_RUN) python tools/check_docs.py
	$(DOCS_RUN) sphinx-autobuild -d docs/_build/doctrees/live $(SPHINX_FLAGS) --host 127.0.0.1 docs docs/_build/html

docs-linkcheck:
	$(DOCS_RUN) sphinx-build -d docs/_build/doctrees/linkcheck $(SPHINX_FLAGS) -b linkcheck docs docs/_build/linkcheck
