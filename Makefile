PREFIX ?= /usr/local
SBINDIR ?= $(PREFIX)/sbin
BINDIR ?= $(PREFIX)/bin
LIBDIR ?= $(PREFIX)/lib
INCLUDEDIR ?= $(PREFIX)/include
SYSCONFDIR ?= /etc
DBUSSERVICEDIR ?= /usr/share/dbus-1/system-services
DBUSCONFDIR ?= /usr/share/dbus-1/system.d
UNITDIR ?= /usr/lib/systemd/system
STATEDIR ?= /var/lib/sparklink
MANDIR ?= $(PREFIX)/share/man

CARGO ?= cargo +1.96.1
CARGO_FLAGS ?= --release --workspace
CARGO_TARGET_DIR ?= $(shell python3 tools/install_layout.py --print-target)
export CARGO_TARGET_DIR
ARTIFACT_DIR ?= $(CARGO_TARGET_DIR)/release
INSTALL_GENERATED_DIR ?= $(CARGO_TARGET_DIR)/install-generated
VERSION := $(shell python3 tools/install_layout.py --print-version)
PKGCONFIGDIR ?= $(LIBDIR)/pkgconfig
UDEVDIR ?= /usr/lib/udev/rules.d
SYSUSERSDIR ?= /usr/lib/sysusers.d
DATADIR ?= $(PREFIX)/share/sparklink
DOCDIR ?= $(PREFIX)/share/doc/sparklink
INSTALL ?= install
UV ?= uv
DOCS_RUN = $(UV) run --locked --only-group docs
BUILD_RUN = python3 tools/build_resources.py --
SPHINX_FLAGS = -n -W --keep-going

.PHONY: all build check test arch-check install install-files uninstall clean docs docs-live docs-linkcheck

all: build

build:
	$(BUILD_RUN) $(CARGO) build --locked $(CARGO_FLAGS)

arch-check:
	python3 tools/check_production_dependencies.py
	PYTHONPATH=tools python3 -m unittest discover -s tools/tests -p test_production_dependencies.py
	python3 tools/check_retired_interfaces.py
	PYTHONPATH=tools python3 -m unittest discover -s tools/tests -p test_retired_interfaces.py
	PYTHONPATH=tools python3 -m unittest discover -s tools/tests -p test_public_symbols.py

check: arch-check
	$(BUILD_RUN) $(CARGO) check --locked --workspace

test: arch-check
	$(BUILD_RUN) $(CARGO) test --locked --workspace

clippy:
	$(BUILD_RUN) $(CARGO) clippy --locked --workspace -- -W clippy::all

fmt:
	$(CARGO) fmt --all

install:
	test "$(abspath $(ARTIFACT_DIR))" = "$(abspath $(CARGO_TARGET_DIR))/release"
	$(BUILD_RUN) $(CARGO) build --locked --release --workspace
	$(MAKE) install-files

# Packaging reuses this list after its own locked build, with an explicit root.
install-files:
	python3 tools/install_layout.py --check-artifacts "$(ARTIFACT_DIR)"
	python3 tools/install_layout.py --output "$(INSTALL_GENERATED_DIR)" --prefix "$(PREFIX)" --sbindir "$(SBINDIR)" --libdir "$(LIBDIR)" --includedir "$(INCLUDEDIR)" --sysconfdir "$(SYSCONFDIR)" --statedir "$(STATEDIR)"
	$(INSTALL) -Dm755 "$(ARTIFACT_DIR)/slkd" "$(DESTDIR)$(SBINDIR)/slkd"
	$(INSTALL) -Dm755 "$(ARTIFACT_DIR)/slkconfig" "$(DESTDIR)$(BINDIR)/slkconfig"
	$(INSTALL) -Dm755 "$(ARTIFACT_DIR)/slctl" "$(DESTDIR)$(BINDIR)/slctl"
	$(INSTALL) -Dm755 "$(ARTIFACT_DIR)/slktest" "$(DESTDIR)$(BINDIR)/slktest"
	$(INSTALL) -Dm755 "$(ARTIFACT_DIR)/slkmon" "$(DESTDIR)$(BINDIR)/slkmon"
	$(INSTALL) -Dm755 "$(ARTIFACT_DIR)/slkdump" "$(DESTDIR)$(BINDIR)/slkdump"
	$(INSTALL) -Dm644 data/man/man1/slctl.1 "$(DESTDIR)$(MANDIR)/man1/slctl.1"
	$(INSTALL) -Dm644 data/man/man1/slktest.1 "$(DESTDIR)$(MANDIR)/man1/slktest.1"
	$(INSTALL) -Dm644 data/man/man5/sparklink.conf.5 "$(DESTDIR)$(MANDIR)/man5/sparklink.conf.5"
	$(INSTALL) -Dm644 data/man/man8/slkd.8 "$(DESTDIR)$(MANDIR)/man8/slkd.8"
	$(INSTALL) -Dm755 "$(ARTIFACT_DIR)/liblibsparklink.so" "$(DESTDIR)$(LIBDIR)/libsparklink.so.$(VERSION)"
	ln -sfn "libsparklink.so.$(VERSION)" "$(DESTDIR)$(LIBDIR)/libsparklink.so.0"
	ln -sfn libsparklink.so.0 "$(DESTDIR)$(LIBDIR)/libsparklink.so"
	$(INSTALL) -Dm755 "$(ARTIFACT_DIR)/libslk_native.so" "$(DESTDIR)$(LIBDIR)/libslk_native.so.$(VERSION)"
	ln -sfn "libslk_native.so.$(VERSION)" "$(DESTDIR)$(LIBDIR)/libslk_native.so.0"
	ln -sfn libslk_native.so.0 "$(DESTDIR)$(LIBDIR)/libslk_native.so"
	$(INSTALL) -Dm644 crates/libsparklink/include/sparklink.h "$(DESTDIR)$(INCLUDEDIR)/sparklink.h"
	$(INSTALL) -Dm644 crates/slk-native/include/sparklink_native.h "$(DESTDIR)$(INCLUDEDIR)/sparklink_native.h"
	$(INSTALL) -Dm644 "$(INSTALL_GENERATED_DIR)/sparklink.pc" "$(DESTDIR)$(PKGCONFIGDIR)/sparklink.pc"
	$(INSTALL) -Dm644 "$(INSTALL_GENERATED_DIR)/sparklink-native.pc" "$(DESTDIR)$(PKGCONFIGDIR)/sparklink-native.pc"
	# Existing configuration (including symlinks) and state are administrator-owned.
	if test ! -e "$(DESTDIR)$(SYSCONFDIR)/sparklink" && test ! -L "$(DESTDIR)$(SYSCONFDIR)/sparklink"; then $(INSTALL) -dm755 "$(DESTDIR)$(SYSCONFDIR)/sparklink"; fi
	if test ! -e "$(DESTDIR)$(SYSCONFDIR)/sparklink/main.conf" && test ! -L "$(DESTDIR)$(SYSCONFDIR)/sparklink/main.conf"; then $(INSTALL) -m644 data/config/main.conf "$(DESTDIR)$(SYSCONFDIR)/sparklink/main.conf"; fi
	$(INSTALL) -Dm644 data/config/main.conf "$(DESTDIR)$(DATADIR)/main.conf.example"
	$(INSTALL) -Dm644 LICENSE "$(DESTDIR)$(DOCDIR)/LICENSE"
	$(INSTALL) -Dm644 debian/copyright "$(DESTDIR)$(DOCDIR)/copyright"
	$(INSTALL) -Dm644 "$(INSTALL_GENERATED_DIR)/org.sparklink.service" "$(DESTDIR)$(DBUSSERVICEDIR)/org.sparklink.service"
	$(INSTALL) -Dm644 data/dbus/sparklink.conf "$(DESTDIR)$(DBUSCONFDIR)/sparklink.conf"
	$(INSTALL) -Dm644 "$(INSTALL_GENERATED_DIR)/sparklink.service" "$(DESTDIR)$(UNITDIR)/sparklink.service"
	$(INSTALL) -Dm644 data/udev/99-sparklink.rules "$(DESTDIR)$(UDEVDIR)/99-sparklink.rules"
	$(INSTALL) -Dm644 data/sysusers/sparklink.conf "$(DESTDIR)$(SYSUSERSDIR)/sparklink.conf"
	if test ! -e "$(DESTDIR)$(STATEDIR)" && test ! -L "$(DESTDIR)$(STATEDIR)"; then $(INSTALL) -dm700 "$(DESTDIR)$(STATEDIR)"; fi

uninstall:
	rm -f "$(DESTDIR)$(SBINDIR)/slkd"
	rm -f $(addprefix "$(DESTDIR)$(BINDIR)/,$(addsuffix ",slkconfig slctl slktest slkmon slkdump))
	rm -f "$(DESTDIR)$(LIBDIR)/libsparklink.so" "$(DESTDIR)$(LIBDIR)/libsparklink.so.0" "$(DESTDIR)$(LIBDIR)/libsparklink.so.$(VERSION)"
	rm -f "$(DESTDIR)$(LIBDIR)/libslk_native.so" "$(DESTDIR)$(LIBDIR)/libslk_native.so.0" "$(DESTDIR)$(LIBDIR)/libslk_native.so.$(VERSION)"
	rm -f "$(DESTDIR)$(INCLUDEDIR)/sparklink.h" "$(DESTDIR)$(INCLUDEDIR)/sparklink_native.h"
	rm -f "$(DESTDIR)$(PKGCONFIGDIR)/sparklink.pc" "$(DESTDIR)$(PKGCONFIGDIR)/sparklink-native.pc"
	rm -f "$(DESTDIR)$(MANDIR)/man1/slctl.1" "$(DESTDIR)$(MANDIR)/man1/slktest.1" "$(DESTDIR)$(MANDIR)/man5/sparklink.conf.5" "$(DESTDIR)$(MANDIR)/man8/slkd.8"
	rm -f "$(DESTDIR)$(DBUSSERVICEDIR)/org.sparklink.service" "$(DESTDIR)$(DBUSCONFDIR)/sparklink.conf" "$(DESTDIR)$(UNITDIR)/sparklink.service"
	rm -f "$(DESTDIR)$(UDEVDIR)/99-sparklink.rules" "$(DESTDIR)$(SYSUSERSDIR)/sparklink.conf" "$(DESTDIR)$(DATADIR)/main.conf.example"
	rm -f "$(DESTDIR)$(DOCDIR)/LICENSE" "$(DESTDIR)$(DOCDIR)/copyright"
	# Configuration, state, unrelated files and other library versions survive.

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
