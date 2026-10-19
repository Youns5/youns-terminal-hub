# ---------------------------------------------------------------------------
# yhelp.sh - Fonction shell pour Youns Terminal Hub (Bash & Zsh, Linux)
#
# POURQUOI CE FICHIER EST INDISPENSABLE :
# Un processus enfant (le programme Python) ne peut jamais changer le
# répertoire courant de son shell parent. On définit donc `yhelp` comme une
# FONCTION SHELL (et non un binaire), qui :
#   1. crée un fichier temporaire unique ;
#   2. lance le vrai programme Python `yhelp-tui` en lui indiquant ce fichier
#      via la variable d'environnement YHELP_CD_FILE ;
#   3. si le programme Python a écrit un chemin dans ce fichier (parce que
#      l'utilisateur a choisi un raccourci de dossier), la fonction shell
#      lit ce chemin et exécute ELLE-MÊME `cd`, ce qui fonctionne car
#      c'est le shell interactif qui l'exécute, pas un processus enfant.
#
# Ce fichier est sourcé automatiquement depuis ~/.bashrc ou ~/.zshrc par
# install.sh. Vous pouvez aussi le sourcer manuellement :
#   source /chemin/vers/yhelp.sh
# ---------------------------------------------------------------------------

yhelp() {
    local cd_file rc target

    if ! command -v yhelp-tui >/dev/null 2>&1; then
        echo "yhelp: 'yhelp-tui' est introuvable dans le PATH (lancez ./install.sh)" >&2
        return 127
    fi

    cd_file="$(mktemp "${TMPDIR:-/tmp}/yhelp-cd.XXXXXX" 2>/dev/null || mktemp)" || return 1

    YHELP_CD_FILE="$cd_file" command yhelp-tui "$@"
    rc=$?   # NB : `status` est en lecture seule sous zsh, on utilise donc `rc`

    if [ -s "$cd_file" ]; then
        target="$(cat "$cd_file")"
        if [ -n "$target" ] && [ -d "$target" ]; then
            cd -- "$target" || echo "yhelp: impossible d'accéder à $target" >&2
        fi
    fi
    rm -f "$cd_file"

    return $rc
}
