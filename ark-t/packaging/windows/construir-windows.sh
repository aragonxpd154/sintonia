#!/usr/bin/env bash
# Gera o Ark-T para Windows (x64) a partir do Linux, sem precisar de Windows:
#   dist/Ark-T-<versão>-windows-x64-instalador.exe   (NSIS, instala sem administrador)
#   dist/Ark-T-<versão>-windows-x64-portatil.zip     (descompacte e abra Ark-T.exe)
#
# Ingredientes, todos baixados com verificação de SHA-256:
#   • Python 3.14 do python-build-standalone (astral-sh)
#   • GTK 4 + libadwaita + PyGObject do gvsbuild (wingtk)
# Ferramentas: x86_64-w64-mingw32-gcc/windres, makensis, rsvg-convert,
# convert (ImageMagick), unzip, zip, python3.
#   sudo apt install gcc-mingw-w64-x86-64 binutils-mingw-w64-x86-64 nsis librsvg2-bin imagemagick unzip zip
set -euo pipefail

AQUI="$(cd "$(dirname "$0")" && pwd)"
RAIZ="$(cd "$AQUI/../.." && pwd)"
VERSAO="$(cd "$RAIZ" && python3 -c 'import arkt; print(arkt.VERSAO)')"
CACHE="${CACHE:-$RAIZ/build/cache}"
OBRA="$RAIZ/build/windows"
DIST="$RAIZ/dist"
APP="$OBRA/Ark-T"

GTK_TAG="2026.8.0"
GTK_ZIP="GTK4_Gvsbuild_${GTK_TAG}_x64.zip"
GTK_URL="https://github.com/wingtk/gvsbuild/releases/download/${GTK_TAG}/${GTK_ZIP}"
GTK_SHA="1f95a92d037f5292da05e6ab1037032ff21ddb7b20d4ac8e83e3674c864c07b0"
PY_TAG="20261110"
PY_VER="3.14.10"
PY_TGZ="cpython-${PY_VER}+${PY_TAG}-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PY_TAG}/${PY_TGZ}"
PY_SHA="32b6cf90a03e2bc15fda8d2ab7ff78c4870f138887d612932650ce764efaab8f"

msg() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

baixar() {  # url arquivo sha256
    local url="$1" arq="$CACHE/$2" sha="$3"
    mkdir -p "$CACHE"
    if [ ! -f "$arq" ] || ! echo "$sha  $arq" | sha256sum -c --status; then
        msg "baixando $2"
        curl -fL --retry 3 -o "$arq.part" "$url"
        mv "$arq.part" "$arq"
    fi
    echo "$sha  $arq" | sha256sum -c --status || { echo "SHA-256 não confere: $2" >&2; exit 1; }
}

for f in x86_64-w64-mingw32-gcc x86_64-w64-mingw32-windres makensis rsvg-convert convert unzip zip; do
    command -v "$f" >/dev/null || { echo "falta a ferramenta: $f" >&2; exit 1; }
done

baixar "$GTK_URL" "$GTK_ZIP" "$GTK_SHA"
baixar "$PY_URL" "$PY_TGZ" "$PY_SHA"

rm -rf "$OBRA"
mkdir -p "$APP/runtime" "$DIST"

# ------------------------------------------------------------------ Python
msg "Python $PY_VER"
tar -xzf "$CACHE/$PY_TGZ" -C "$APP/runtime"          # cria runtime/python
PYW="$APP/runtime/python"
rm -rf "$PYW/Lib/test" "$PYW/Lib/idlelib" "$PYW/Lib/tkinter" "$PYW/Lib/turtledemo" "$PYW/Lib/ensurepip" \
       "$PYW/tcl" "$PYW/DLLs/_tkinter.pyd" "$PYW/DLLs/tcl"*.dll "$PYW/DLLs/tk"*.dll "$PYW/Scripts" \
       "$PYW/include" "$PYW/libs"
SITE="$PYW/Lib/site-packages"
mkdir -p "$SITE"

# ------------------------------------------------------------------ GTK
msg "GTK 4 + libadwaita (gvsbuild $GTK_TAG)"
GTKTMP="$OBRA/gtk-zip"
mkdir -p "$GTKTMP"
unzip -q -o "$CACHE/$GTK_ZIP" 'bin/*.dll' 'lib/girepository-1.0/*' 'lib/gdk-pixbuf-2.0/*' \
      'share/glib-2.0/schemas/*' 'share/icons/Adwaita/*' 'share/icons/hicolor/*' 'etc/fonts/*' \
      'share/locale/pt_BR/*' 'share/doc/*' 'python/*.whl' -d "$GTKTMP"
GTK="$APP/runtime/gtk"
mkdir -p "$GTK/bin" "$GTK/lib" "$GTK/share/glib-2.0" "$GTK/share/icons" "$GTK/share/locale" "$GTK/etc"
cp -r "$GTKTMP/lib/girepository-1.0" "$GTKTMP/lib/gdk-pixbuf-2.0" "$GTK/lib/"
cp -r "$GTKTMP/share/glib-2.0/schemas" "$GTK/share/glib-2.0/"
cp -r "$GTKTMP/share/icons/Adwaita" "$GTKTMP/share/icons/hicolor" "$GTK/share/icons/"
cp -r "$GTKTMP/share/locale/pt_BR" "$GTK/share/locale/" 2>/dev/null || true
cp -r "$GTKTMP/etc/fonts" "$GTK/etc/" 2>/dev/null || true
cp -r "$GTKTMP/share/doc" "$GTK/share/" 2>/dev/null || true      # licenças das bibliotecas
find "$GTK/share/doc" -type f ! -iname 'COPYING*' ! -iname 'LICEN[CS]E*' ! -iname 'NOTICE*' -delete 2>/dev/null || true
find "$GTK/share/doc" -type d -empty -delete 2>/dev/null || true

msg "PyGObject e pycairo"
for w in "$GTKTMP"/python/*.whl; do unzip -q -o "$w" -d "$SITE"; done
find "$SITE" -name '*.lib' -delete

# só as DLLs realmente usadas: fecho de dependências a partir das
# bibliotecas citadas nas typelibs, dos .pyd e do carregador de SVG
msg "selecionando DLLs"
python3 "$AQUI/dlls.py" "$GTKTMP/bin" "$GTK/bin" "$GTK/lib/girepository-1.0" \
        "$SITE" "$GTK/lib/gdk-pixbuf-2.0"

# ------------------------------------------------------------------ Ark-T
msg "Ark-T $VERSAO"
( cd "$RAIZ" && tar --exclude='__pycache__' --exclude='*.pyc' --exclude='arkt/data/telas.json' -cf - arkt ) \
    | tar -xf - -C "$SITE"
rm -rf "$SITE"/pip "$SITE"/pip-*.dist-info

# ------------------------------------------------------------------ ícone e lançador
msg "lançador Ark-T.exe"
ICO="$OBRA/ico"
mkdir -p "$ICO"
SVG="$RAIZ/arkt/data/icons/hicolor/scalable/apps/io.github.aragonxpd154.ArkT.svg"
for s in 16 24 32 48 64 128 256; do rsvg-convert -w $s -h $s "$SVG" -o "$ICO/$s.png"; done
convert "$ICO"/16.png "$ICO"/24.png "$ICO"/32.png "$ICO"/48.png "$ICO"/64.png "$ICO"/128.png "$ICO"/256.png "$APP/Ark-T.ico"
IFS=. read -r V1 V2 V3 <<<"$VERSAO"
sed -e "s/@V1@/$V1/g; s/@V2@/$V2/g; s/@V3@/$V3/g; s/@VERSAO@/$VERSAO/g" "$AQUI/lancador.rc" > "$ICO/lancador.rc"
cp "$AQUI/lancador.manifest" "$ICO/"
cp "$APP/Ark-T.ico" "$ICO/arkt.ico"
( cd "$ICO" && x86_64-w64-mingw32-windres -c 65001 lancador.rc -O coff -o lancador.res )
x86_64-w64-mingw32-gcc -O2 -s -municode -mwindows -o "$APP/Ark-T.exe" "$AQUI/lancador.c" "$ICO/lancador.res"

# ------------------------------------------------------------------ textos
conv() { sed 's/$/\r/' "$1" > "$2"; }
LIC="$RAIZ/LICENSE"; [ -f "$LIC" ] || LIC="$RAIZ/../LICENSE"
conv "$LIC" "$APP/LICENSE.txt"
conv "$RAIZ/NOTICE" "$APP/NOTICE.txt"
conv "$AQUI/LEIA-ME.txt" "$APP/LEIA-ME.txt"
printf '@echo off\r\nrem Abre o Ark-T com console, para ver mensagens de erro.\r\n"%%~dp0runtime\\python\\python.exe" -m arkt %%*\r\npause\r\n' > "$APP/Ark-T-depuracao.bat"

# ------------------------------------------------------------------ pacotes
BASE="Ark-T-$VERSAO-windows-x64"
msg "zip portátil"
rm -f "$DIST/$BASE-portatil.zip"
( cd "$OBRA" && zip -qr -9 "$DIST/$BASE-portatil.zip" Ark-T )
msg "instalador NSIS"
LC_ALL=C.UTF-8 makensis -V2 -DVERSAO="$VERSAO" -DORIGEM="$APP" -DSAIDA="$DIST/$BASE-instalador.exe" "$AQUI/instalador.nsi"
( cd "$DIST" && sha256sum "$BASE-portatil.zip" "$BASE-instalador.exe" > "$BASE.sha256" )
du -sh "$APP" "$DIST/$BASE"*
msg "pronto: $DIST/$BASE-instalador.exe"
