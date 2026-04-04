Name:           sparklink
Version:        0.1.0
Release:        1%{?dist}
Summary:        SparkLink wireless protocol userspace stack

License:        Proprietary
URL:            https://gitee.com/sparklinkZ/sparklink-userspace
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  cargo >= 1.85
BuildRequires:  rust >= 1.85
BuildRequires:  systemd-rpm-macros
Requires:       dbus

%description
Complete userspace infrastructure for the SparkLink wireless
communication protocol. Includes the management daemon (slkd),
command-line tools, and shared library.

%package -n libsparklink
Summary:        SparkLink shared library

%description -n libsparklink
C-compatible shared library providing programmatic access to
SparkLink hardware.

%package -n libsparklink-devel
Summary:        SparkLink development headers
Requires:       libsparklink = %{version}-%{release}

%description -n libsparklink-devel
C header for developing applications against libsparklink.

%prep
%autosetup

%build
cargo build --release --workspace

%install
# Binaries
install -Dm755 target/release/slkd        %{buildroot}%{_sbindir}/slkd
install -Dm755 target/release/slkconfig    %{buildroot}%{_bindir}/slkconfig
install -Dm755 target/release/slctl        %{buildroot}%{_bindir}/slctl
install -Dm755 target/release/slkmon       %{buildroot}%{_bindir}/slkmon
install -Dm755 target/release/slkdump      %{buildroot}%{_bindir}/slkdump

# Shared library
install -Dm755 target/release/libsparklink.so %{buildroot}%{_libdir}/libsparklink.so.0.1.0
ln -sf libsparklink.so.0.1.0 %{buildroot}%{_libdir}/libsparklink.so.0
ln -sf libsparklink.so.0     %{buildroot}%{_libdir}/libsparklink.so

# Header
install -Dm644 crates/libsparklink/include/sparklink.h %{buildroot}%{_includedir}/sparklink.h

# Configuration
install -Dm644 data/config/main.conf      %{buildroot}%{_sysconfdir}/sparklink/main.conf
install -Dm644 data/dbus/org.sparklink.service  %{buildroot}%{_datadir}/dbus-1/system-services/org.sparklink.service
install -Dm644 data/dbus/sparklink.conf         %{buildroot}%{_datadir}/dbus-1/system.d/sparklink.conf
install -Dm644 data/systemd/sparklink.service   %{buildroot}%{_unitdir}/sparklink.service

install -dm755 %{buildroot}%{_sharedstatedir}/sparklink

%check
cargo test --workspace

%post
%systemd_post sparklink.service

%preun
%systemd_preun sparklink.service

%postun
%systemd_postun_with_restart sparklink.service

%post -n libsparklink -p /sbin/ldconfig
%postun -n libsparklink -p /sbin/ldconfig

%files
%config(noreplace) %{_sysconfdir}/sparklink/main.conf
%{_sbindir}/slkd
%{_bindir}/slkconfig
%{_bindir}/slctl
%{_bindir}/slkmon
%{_bindir}/slkdump
%{_datadir}/dbus-1/system-services/org.sparklink.service
%{_datadir}/dbus-1/system.d/sparklink.conf
%{_unitdir}/sparklink.service
%dir %{_sharedstatedir}/sparklink

%files -n libsparklink
%{_libdir}/libsparklink.so.0*

%files -n libsparklink-devel
%{_includedir}/sparklink.h
%{_libdir}/libsparklink.so
