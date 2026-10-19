#!/usr/bin/env bash
# Installation de Youns Terminal Hub (Linux, Bash/Zsh). Aucune dépendance Python.
set -euo pipefail

APP="youns-terminal-hub"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/$APP"
BIN="${YHELP_BIN_DIR:-$HOME/.local/bin}"
BEGIN="# >>> $APP >>>"
END="# <<< $APP <<<"
UPDATE_RC=1

for arg in "$@"; do
    case "$arg" in
        --no-rc) UPDATE_RC=0 ;;
        -h|--help) echo "Usage: ./install.sh [--no-rc]   (--no-rc : ne modifie pas ~/.bashrc / ~/.zshrc)"; exit 0 ;;
        *) echo "Option inconnue : $arg" >&2; exit 2 ;;
    esac
done

if [ "$(uname -s)" != "Linux" ]; then
    echo "Attention : ce projet est conçu et testé pour Linux (système détecté : $(uname -s))." >&2
fi

command -v python3 >/dev/null 2>&1 || { echo "Erreur : python3 est requis." >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' \
    || { echo "Erreur : Python 3.9 ou plus récent est requis." >&2; exit 1; }

echo "→ Copie des fichiers dans $DATA"
rm -rf "$DATA/src"
mkdir -p "$DATA" "$BIN"
cp -R "$SRC/src" "$DATA/src"
find "$DATA/src" -name '__pycache__' -type d -prune -exec rm -rf {} +
cp "$SRC/yhelp.sh" "$DATA/yhelp.sh"

echo "→ Création du lanceur $BIN/yhelp-tui"
cat > "$BIN/yhelp-tui" <<LAUNCHER
#!/bin/sh
# Généré par install.sh — Youns Terminal Hub
PYTHONPATH="$DATA/src\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m yhelp_tui "\$@"
LAUNCHER
chmod +x "$BIN/yhelp-tui"

add_block() {
    local rc="$1"
    [ -f "$rc" ] || return 0
    if grep -qF "$BEGIN" "$rc"; then
        echo "→ $rc déjà configuré"
        return 0
    fi
    {
        printf '\n%s\n' "$BEGIN"
        printf 'case ":$PATH:" in *":%s:"*) ;; *) export PATH="%s:$PATH" ;; esac\n' "$BIN" "$BIN"
        printf '[ -f "%s/yhelp.sh" ] && . "%s/yhelp.sh"\n' "$DATA" "$DATA"
        printf '%s\n' "$END"
    } >> "$rc"
    echo "→ $rc mis à jour"
}

if [ "$UPDATE_RC" -eq 1 ]; then
    add_block "$HOME/.bashrc"
    [ -f "$HOME/.zshrc" ] || { [ "${SHELL##*/}" = "zsh" ] && touch "$HOME/.zshrc"; } || true
    add_block "$HOME/.zshrc"
fi

echo
echo "✔ Installation terminée. Ouvrez un nouveau terminal (ou : source $DATA/yhelp.sh)"
echo "  puis tapez : yhelp"
