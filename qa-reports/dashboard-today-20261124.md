# Tableau de bord — journée courante par défaut

Le filtre initial de `frontend/src/Dashboard.tsx` utilise maintenant la même date pour `start` et `end`, calculée dans le fuseau par défaut `America/Toronto`. Le rapport initial et son export utilisent donc la journée courante. Les périodes explicites, les autres fuseaux et le raccourci des 90 derniers jours conservent leur comportement.

Modification applicative : une ligne dans l'initialisation des dates. Aucun changement de téléphonie, d'API, de schéma ou de dépendance. Aucun test ajouté pour ce changement d'affichage réversible ; la suite existante du tableau de bord a été exécutée.

| Commande exécutée | Résultat | Évidence |
| --- | --- | --- |
| `npm --prefix frontend run build` | PASS, exit 0 | `evidence/dashboard-today-build-20261124.{json,log}` |
| `env UI_TEST_URL=http://127.0.0.1:18447 QA_EVIDENCE_MODE=dashboard-today-20261124 npm --prefix frontend run test:browser -- dashboard.spec.ts` | PASS, 6 scénarios Chromium, exit 0 | `evidence/dashboard-today-browser-20261124.{json,log}` |
| `git diff --check` | PASS, exit 0 | Sortie de commande conservée dans le fil d'exécution |

La capture `/tmp/ut-dashboard-desktop.png`, produite par la suite et inspectée visuellement, montre `11/05/2026` dans les deux champs avec l'horloge de test figée au 5 novembre 2026. Les scénarios existants vérifient aussi les périodes explicites, l'export, les 90 jours, l'heure répétée du changement d'heure, la séparation des indicateurs entrants/sortants, les droits administrateur, l'accessibilité et le mobile. Les API et données de ces tests sont simulées ; aucune donnée de production n'est modifiée.

La mise en ligne reste soumise à la CI complète et au déployeur protégé, sans contourner les contrôles d'appels actifs.
