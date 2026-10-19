#!/usr/bin/env bash
# Désinstallation de Youns Terminal Hub. --purge supprime aussi vos données.
set -euo pipefail
APP="youns-terminal-hub"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/$APP"
BIN="${YHELP_BIN_DIR:-$HOME/.local/bin}"
CONF="${YHELP_HOME:-${XDG_CONFIG_HOME:-$HOME/.config}/yhelp}"

for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
    [ -f "$rc" ] || continue
    if grep -qF "# >>> $APP >>>" "$rc"; then
        tmp="$(mktemp)"
        awk -v b="# >>> $APP >>>" -v e="# <<< $APP <<<" '
            $0 == b { skip = 1; next }
            $0 == e { skip = 0; next }
            !skip { print }' "$rc" > "$tmp"
        cat "$tmp" > "$rc"
        rm -f "$tmp"
        echo "→ bloc retiré de $rc"
    fi
done
rm -f "$BIN/yhelp-tui"
rm -rf "$DATA"
if [ "${1:-}" = "--purge" ]; then
    rm -rf "$CONF"
    echo "→ données supprimées ($CONF)"
else
    echo "→ vos données sont conservées dans $CONF (utilisez --purge pour les supprimer)"
fi
echo "✔ Désinstallé."
