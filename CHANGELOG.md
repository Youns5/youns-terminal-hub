# Changelog

## 2.1.0
- **Édition dans l'interface** : ajouter (`a`), modifier (`e`) et supprimer (`d`) raccourcis de dossiers *et* commandes, sans ouvrir les JSON.
- Réordonner les raccourcis de dossiers avec `J` / `K`.
- Formulaire intégré (champs texte, choix de catégorie, case « dangereuse »), validation et enregistrement immédiat.
- La section **Navigation** reste toujours visible, même sans raccourci (on peut donc en recréer un).
- Le dossier courant est pré-rempli à l'ajout d'un raccourci.
- README réécrit, nouvelles captures, tests d'édition.

## 2.0.0
- Refonte complète du design : thème sombre premium, cyan néon, touches violettes, dégradés, cadres arrondis.
- TUI en Python pur (aucune dépendance), truecolor avec repli 256 couleurs, `NO_COLOR` respecté.
- Données utilisateur déplacées dans `~/.config/yhelp` (hors du dépôt), sauvegarde atomique, fichiers corrompus mis en `.bak`.
- Recherche globale, favoris, confirmation des commandes dangereuses, historique, raccourcis dossiers.
- `yhelp.sh` : correction d'un bug zsh (`status` est en lecture seule), vérification de `yhelp-tui`.
- Scripts `install.sh` / `uninstall.sh`, tests automatisés, CI GitHub Actions.
