#!/usr/bin/env bash
# Remove o Ark-T. Com --tudo, apaga também os equipamentos cadastrados e as
# telas importadas (~/.config/arkt e ~/.local/share/arkt).
set -euo pipefail
sudo apt-get remove -y arkt || true
if [ "${1:-}" = "--tudo" ]; then
  rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/arkt" "${XDG_DATA_HOME:-$HOME/.local/share}/arkt"
  echo "Configurações e telas importadas apagadas."
fi
echo "Ark-T removido."
