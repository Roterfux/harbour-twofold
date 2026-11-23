Name:       harbour-twofold
Summary:    Two-factor authentication codes, Aegis compatible
Version:    0.3.1
Release:    1
License:    GPLv3+
BuildArch:  noarch
Source0:    %{name}-%{version}.tar.bz2

# UI
Requires:   sailfishsilica-qt5 >= 1.1.0
Requires:   mapplauncherd-booster-silica-qt5
Requires:   nemo-qml-plugin-configuration-qt5
# Engine: Python (standard library; OpenSSL's libcrypto through ctypes when present)
Requires:   pyotherside-qml-plugin-python3-qt5
Requires:   python3-base
# QR scanner: reading the pictures
Requires:   python3-imaging
# Fingerprint unlock: the system dialog polkit shows (as BitSailor); gi talks to polkit
Requires:   sailfish-polkit-agent

%description
Twofold shows the one-time codes (TOTP, HOTP, Steam) of your two-factor accounts.
It imports Aegis exports, encrypted or plain, and stores the accounts in an
encrypted vault in the Aegis format, protected by your password.

%prep
%setup -q -n %{name}-%{version}
# Sources may come from a filesystem without Unix modes (e.g. a Windows drive)
find . -type f -exec chmod 0644 {} +
# ... and with Windows line endings, which break the .desktop file
find . -type f \( -name '*.desktop' -o -name '*.qml' -o -name '*.py' -o -name '*.policy' \) -exec sed -i 's/\r$//' {} +

%build
# Nothing to build: QML UI + Python engine

%install
rm -rf %{buildroot}
install -d %{buildroot}%{_datadir}/%{name}
cp -r qml python %{buildroot}%{_datadir}/%{name}/
find %{buildroot}%{_datadir}/%{name} -name __pycache__ -prune -exec rm -rf {} \;
# Stamp the exact package version into the settings page (fail if the marker moved)
sed -i 's/appVersion: "[^"]*"/appVersion: "%{version}-%{release}"/' \
    %{buildroot}%{_datadir}/%{name}/qml/pages/SettingsPage.qml
grep -q 'appVersion: "%{version}-%{release}"' %{buildroot}%{_datadir}/%{name}/qml/pages/SettingsPage.qml
install -D -m 0644 harbour-twofold.desktop %{buildroot}%{_datadir}/applications/%{name}.desktop
install -D -m 0644 polkit/harbour.twofold.policy %{buildroot}%{_datadir}/polkit-1/actions/harbour.twofold.policy
for size in 86x86 108x108 128x128 172x172; do
    install -D -m 0644 icons/$size/%{name}.png %{buildroot}%{_datadir}/icons/hicolor/$size/apps/%{name}.png
done

%files
%defattr(-,root,root,-)
%{_datadir}/%{name}
%{_datadir}/applications/%{name}.desktop
%{_datadir}/polkit-1/actions/harbour.twofold.policy
%{_datadir}/icons/hicolor/*/apps/%{name}.png

%changelog
* Sun Nov 22 2026 Twofold contributors - 0.3.1-1
- Forgot the password: "Reset app" in the lock screen's pull-down menu starts over with a
  new password; the old vault is kept (renamed) and can be imported again with its password
- "Wrong password" also names the crypto libraries in use, to spot a library problem

* Sun Nov 22 2026 Twofold contributors - 0.3.0-1
- Unlock with fingerprint (Settings): the system dialog asks for the fingerprint or the
  security code; asked at start and by a button on the lock screen. While on, the vault
  key is kept on the phone (fingerprint.key next to the vault); turning it off deletes it
- The app sandbox is off: it blocks polkit, which shows that dialog

* Fri Nov 20 2026 Twofold contributors - 0.2.0-1
- Scan QR code: the camera reads an account's otpauth:// code and adds it (copies of the
  viewfinder, or photos where those come out black); "QR code from picture" reads a
  screenshot or photo. Google Authenticator export codes are recognised and explained
- Each account shows the next code small below the current one; "Copy next code" in
  its press-and-hold menu
- Sailjail permissions Camera, Pictures, MediaIndexing

* Fri Nov 20 2026 Twofold contributors - 0.1.0-1
- Initial release: TOTP, HOTP and Steam codes with a time bar, tap to copy; search;
  import of Aegis exports (encrypted or plain, groups kept); add by otpauth:// link or by
  hand; edit and delete; password-encrypted vault in the Aegis format, export to
  Documents; change password; locks after a chosen time in the background
