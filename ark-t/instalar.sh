#!/usr/bin/env bash
# Instala o Ark-T a partir do código (gera o .deb e instala com o apt).
#   ./instalar.sh [--jar arkT_v5_5s.jar]
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")" && pwd)"
JAR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --jar) JAR="$2"; shift ;;
    -h|--help) sed -n '2,3p' "$0"; exit 0 ;;
    *) echo "opção desconhecida: $1" >&2; exit 2 ;;
  esac
  shift
done
if [ "$(id -u)" = 0 ]; then echo "Rode sem sudo; a senha é pedida só para o apt." >&2; exit 1; fi
command -v dpkg-deb >/dev/null || { echo "Precisa do dpkg-deb (Debian/Ubuntu/Zorin)." >&2; exit 1; }
DEB="$("$RAIZ/packaging/construir-deb.sh" | tail -1)"
sudo apt-get install -y "$RAIZ/$DEB"
[ -n "$JAR" ] && arkt importar-jar "$JAR"
echo "Ark-T instalado. Abra pelo menu de aplicativos ou com: arkt"
