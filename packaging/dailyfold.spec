Name:           dailyfold
Version:        0.1.0
Release:        %{?dailyfold_release}%{!?dailyfold_release:1}%{?dist}
Summary:        Daily journal outliner

License:        GPL-3.0-only
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  desktop-file-utils
BuildRequires:  gtk3
BuildRequires:  gtksourceview4
BuildRequires:  python3
BuildRequires:  python3-cairo
BuildRequires:  python3-gobject

Requires:       gtk3
Requires:       gtksourceview4
Requires:       python3
Requires:       python3-cairo
Requires:       python3-gobject

%description
dailyfold is a daily journal outliner.

%prep
%autosetup

%build

%install
install -d %{buildroot}%{_libexecdir}/dailyfold
install -pm 0644 app.py history.py markdown.py model.py search.py storage.py \
    %{buildroot}%{_libexecdir}/dailyfold/
install -Dpm 0755 packaging/dailyfold \
    %{buildroot}%{_bindir}/dailyfold
install -Dpm 0644 packaging/dailyfold.desktop \
    %{buildroot}%{_datadir}/applications/dailyfold.desktop
install -Dpm 0644 packaging/dailyfold.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/dailyfold.svg

%check
/usr/bin/python3 -m unittest discover -q
desktop-file-validate packaging/dailyfold.desktop

%files
%license LICENSE
%doc README.md TODO.md
%{_bindir}/dailyfold
%dir %{_libexecdir}/dailyfold
%{_libexecdir}/dailyfold/*.py
%{_datadir}/applications/dailyfold.desktop
%{_datadir}/icons/hicolor/scalable/apps/dailyfold.svg

%changelog
* Sun Sep 20 2026 Rian <rian@localhost> - 0.1.0-1
- Initial private package
