#!/bin/sh
# Gera dist/arkt_<versão>_all.deb
set -e
cd "$(dirname "$0")/.."
VERSAO=$(sed -n 's/^VERSAO = "\(.*\)"/\1/p' arkt/__init__.py)
R=build/deb
rm -rf "$R"
mkdir -p "$R/DEBIAN" "$R/usr/lib/arkt" "$R/usr/bin" "$R/usr/share/applications" \
         "$R/usr/share/metainfo" "$R/usr/share/icons/hicolor/scalable/apps" \
         "$R/usr/share/icons/hicolor/symbolic/apps" "$R/usr/share/doc/arkt"
cp -r arkt "$R/usr/lib/arkt/"
find "$R/usr/lib/arkt" -name __pycache__ -prune -exec rm -rf {} +
install -m 755 packaging/arkt "$R/usr/bin/arkt"
install -m 644 packaging/io.github.aragonxpd154.ArkT.desktop "$R/usr/share/applications/"
install -m 644 packaging/io.github.aragonxpd154.ArkT.metainfo.xml "$R/usr/share/metainfo/"
install -m 644 arkt/data/icons/hicolor/scalable/apps/*.svg "$R/usr/share/icons/hicolor/scalable/apps/"
install -m 644 arkt/data/icons/hicolor/symbolic/apps/*.svg "$R/usr/share/icons/hicolor/symbolic/apps/"
install -m 644 README.md "$R/usr/share/doc/arkt/"
LIC=LICENSE; [ -f "$LIC" ] || LIC=../LICENSE
install -m 644 "$LIC" NOTICE "$R/usr/share/doc/arkt/"
[ -f CHANGELOG.md ] && install -m 644 CHANGELOG.md "$R/usr/share/doc/arkt/"
rm -f "$R/usr/lib/arkt/arkt/data/telas.json"      # nada do fabricante no pacote
TAM=$(du -sk "$R/usr" | cut -f1)
cat > "$R/DEBIAN/control" <<CTRL
Package: arkt
Version: $VERSAO
Section: net
Priority: optional
Architecture: all
Installed-Size: $TAM
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.5), librsvg2-common
Maintainer: Marcos Santos <aragonxpd154@users.noreply.github.com>
Homepage: https://github.com/aragonxpd154/sintonia/tree/main/ark-t
Description: Gerência dos excitadores ARK-T sem Java
 Substituto nativo (GTK4 + libadwaita) do ARK-T Installer Utility,
 o applet Java que acompanha os excitadores ARK-T da MB International /
 Screen Service. Lê o status pela porta TCP 10001, mostra visão geral,
 alarmes e eventos, altera a configuração com modo edição e confirmação,
 e edita a pré-correção AM/PM e linear (porta 5000).
CTRL
for s in preinst prerm; do
cat > "$R/DEBIAN/$s" <<'SH'
#!/bin/sh
set -e
find /usr/lib/arkt -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
exit 0
SH
done
cat > "$R/DEBIAN/postinst" <<'SH'
#!/bin/sh
set -e
find /usr/lib/arkt -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -f /usr/share/icons/hicolor || true
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
exit 0
SH
chmod 755 "$R/DEBIAN/preinst" "$R/DEBIAN/prerm" "$R/DEBIAN/postinst"
mkdir -p dist
dpkg-deb --root-owner-group --build "$R" "dist/arkt_${VERSAO}_all.deb" >/dev/null
( cd dist && sha256sum "arkt_${VERSAO}_all.deb" > "arkt_${VERSAO}_all.deb.sha256" )
echo "dist/arkt_${VERSAO}_all.deb"
