# Git — Fondamentaux & Bonnes Pratiques

**Description.** Cours structuré sur Git : du modele interne (objets, refs, HEAD) aux workflows collaboratifs avancés (branches, rebases, hooks, CI).
**Pre-requis.** Aucun pre-requis specifique (les bases Linux sont un plus).

---

## Sommaire des chapitres

| Chapitre | Sujet |
|----------|-------|
| 01 | Introduction & Installation |
| 02 | Le modele interne de Git (objets, arbres, commits) |
| 03 | Les bases : init, add, commit, status, log |
| 04 | Branches & fusion (merge, rebase) |
| 05 | Travailler a distance (remote, push, pull, fetch) |
| 06 | Workflows collaboratifs (GitFlow, trunk-based, fork) |
| 07 | Historique avance (reset, revert, cherry-pick, reflog) |
| 08 | Tags & gestion des versions |
| 09 | Hooks & automatisation |
| 10 | Git dans la CI/CD (actions, pipelines) |
| 11 | Bonnes pratiques & conventions de commits |
| 12 | Depannage & recovery (corruption, perte de commits) |

---

## Objectifs d'apprentissage

- Comprendre le **modele de donnees** de Git (graphe de commits, objets immuables).
- Maitriser les **operations courantes** (branch, merge, rebase, stash).
- Savoir travailler en **equipe** avec des workflows adaptes.
- Utiliser Git dans un contexte **CI/CD** et **DevOps**.
- Diagnostiquer et **reparer** les problemes courants.

---

## Commandes essentielles (aperçu)

```bash
git init
git add .
git commit -m "message"
git branch feature/ma-feature
git checkout feature/ma-feature
git merge feature/ma-feature
git push origin main
git pull --rebase
git log --oneline --graph --all
git stash / git stash pop
git reflog
```

---

## Progression recommandee

1. **Modele interne** (comprendre *comment* Git fonctionne)
2. **Bases** (init → commit)
3. **Branches** (le coeur de Git)
4. **Remote** (travailler a plusieurs)
5. **Workflows** (organiser la collaboration)
6. **Avance** (hooks, CI, debugging)
