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

CARGO ?= cargo
CARGO_FLAGS ?= --release --workspace
INSTALL ?= install

.PHONY: all build check test install uninstall clean

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
	$(INSTALL) -Dm755 target/release/slkmon       $(DESTDIR)$(BINDIR)/slkmon
	$(INSTALL) -Dm755 target/release/slkdump      $(DESTDIR)$(BINDIR)/slkdump
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
