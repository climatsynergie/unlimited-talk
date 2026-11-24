# Réception entrante — interruptions et reconnexion automatique

Date : 24 novembre 2026. Branche : `qa/full-audit-20261108`.
Base examinée et version actuellement installée : `6e9adaed2caf1a0a34a2664d96b1162e07333ed3`.

## Périmètre et observation en production

L'utilisateur a reporté le chantier de détection des répondeurs pour traiter la réception qui exige plusieurs clics sur « Recevoir les appels ». Aucun code AMD, appel réel, réglage Twilio, déploiement ou écriture de données de production n'a été effectué pendant cette investigation.

Une lecture SSH/PostgreSQL a été exécutée dans une transaction `READ ONLY`, avec délai SQL de cinq secondes, sans exporter de secrets, jetons, coordonnées de clients ou enregistrements. Le serveur était sur la version attendue, les services étaient démarrés et les contrôles de santé configurés étaient sains. Sur sept jours : 27 événements `inbound.ready`, 27 `inbound.pause` et 12 créations de réception ; Kawtar comptait 18 événements de chaque type ready/pause. Plusieurs interruptions suivent une ouverture de quelques minutes.

**Limite d'attribution :** l'audit actuel ne distingue pas la pause volontaire de la pause envoyée par le navigateur après une erreur et ne conserve pas le code SDK qui la précède. Ces 27 événements ne sont donc pas 27 pannes automatiques prouvées. La périodicité est compatible avec un problème de renouvellement, sans établir le déclencheur exact de chaque incident. Les journaux HTTP de l'API sont désactivés ; l'absence d'entrées d'accès n'établit pas l'absence d'erreurs réseau.

Commande : `python3 qa-reports/evidence/reception-readonly-20261124.py`. Exécution corrigée : **PASS, exit 0**, [métadonnées](evidence/reception-readonly-20261124-corrected.json), [sortie](evidence/reception-readonly-20261124-corrected.log). Une première requête de diagnostic utilisait `created_at` au lieu de `received_at` pour les appels entrants : échec SQL conservé dans `evidence/reception-readonly-20261124.{json,log}`. Aucune écriture n'a eu lieu.

## Défauts reproduits et corrections

| Défaut | Preuve | Correction locale |
| --- | --- | --- |
| Une erreur SDK temporaire désactive immédiatement le choix de recevoir les appels. Trois échecs de contrôle HTTP le désactivent également. | Deux régressions échouent avant correction, exit 1 : `reception-regressions-before-20261124`. | Conserver le choix de l'agent et reprendre automatiquement avec délais progressifs de 2 à 30 secondes. Afficher « Reconnexion automatique… » pendant la récupération. |
| L'état SDK « registered » peut subsister après expiration du JWT, alors que le renouvellement de présence est arrêté. L'ancien bouton de reprise peut alors croire la réception active. | Test exécutant la bibliothèque installée : signal 31205 → erreur 20104, arrêt du renouvellement et état toujours registered. Régression navigateur conservant cet état : échec avant correction dans `reception-sdk-state-regression-before-20261124`. | Conserver le code d'erreur. Après une erreur, recréer le récepteur inactif avec un jeton neuf, plutôt que se fier à l'ancien état. Ignorer les événements de l'ancien appareil. |
| L'inscription initiale SDK peut rester en attente, tandis que la boucle lance un renouvellement concurrent. | Nouveau scénario navigateur d'inscription bloquée : échec conservé dans `reception-browser-final-20261124`. | Borner l'inscription SDK à dix secondes ; attendre la fin de la tentative initiale avant de relancer ; recréer le téléphone à la prochaine tentative. |
| Une ancienne réponse de pause ou de renouvellement peut affecter une réception reprise entre-temps. | Régressions unitaires de pause/reprise concurrente et de jeton retardé. | Vérifier la génération du téléphone et la révision du choix de disponibilité ; une pause volontaire annule la récupération. |

Le jeton de réception reste limité à cinq minutes. Son renouvellement est anticipé à quatre minutes, avec avertissement SDK à une minute de l'échéance et contrôle de secours si l'événement SDK est manqué. Les événements de retour réseau et de retour sur l'onglet réveillent la vérification. L'expiration ne provoque pas de modification de jeton ni de reconstruction du téléphone pendant un appel : la récupération attend la fin du média.

Une réception hors ligne ne doit pas être annoncée prête au serveur. La récupération ne libère pas une occupation d'appel sur la seule base d'un événement navigateur : la confirmation terminale du serveur reste nécessaire. Les erreurs d'authentification, d'accès, de configuration et de permission microphone demandent une intervention. Une déconnexion du compte ou une pause volontaire ne déclenche aucune reprise automatique.

Les campagnes, les règles de composition sortante, les appels entrants côté fournisseur, les migrations et le schéma PostgreSQL ne sont pas modifiés. La révision reste `0012_incoming_runtime`. Les vérifications de migration/rollback n'ont pas été réexécutées dans cette tâche, qui ne change aucune donnée ou structure SQL.

## Validation exécutée

Les fichiers JSON d'évidence contiennent les commandes exactes, le répertoire, les dates, le code de sortie et l'empreinte des journaux. Les tests navigateur exécutent Chromium avec l'application compilée ; les API et le média Twilio sont simulés et ne contactent aucun destinataire réel.

| Vérification | Commande exécutée | Résultat | Évidence |
| --- | --- | --- | --- |
| Régressions initiales, avant correction | `node --experimental-strip-types --test --test-name-pattern='transient receiver signaling\|repeated control-plane outages' frontend/tests/incoming-controller.unit.ts` | FAIL attendu, 2 échecs, exit 1 | `evidence/reception-regressions-before-20261124.{json,log}` |
| Tests téléphone et bibliothèque SDK | `npm --prefix frontend run test:phone` | PASS, 175 tests, exit 0 | `evidence/reception-unit-setup-guard-20261124.{json,log}` |
| TypeScript et compilation web finale | `npm --prefix frontend run build` | PASS, exit 0 | `evidence/reception-build-setup-guard-20261124.{json,log}` |
| Image applicative finale | `sudo -n docker build --build-arg GIT_REVISION=qa-reception-recovery-20261124 -t unlimited-talk-reception-qa:20261124 .` | PASS, exit 0 | `evidence/reception-image-final-build-20261124.{json,log}` |
| Tests backend dans cette image, sans réseau | Commande Docker complète dans les métadonnées, exécutant `python -m unittest discover -s /tests -p 'test_*.py' -v` | PASS, 246 tests, exit 0 | `evidence/reception-backend-final-20261124.{json,log}` |
| Réception et composition sortante, Chromium | `env UI_TEST_URL=http://127.0.0.1:18447 QA_EVIDENCE_MODE=reception-acceptance-20261124 npm --prefix frontend run test:browser -- incoming.spec.ts incoming-session.spec.ts autodialer.spec.ts` | PASS, 38 scénarios (7 réception et 31 composeur), aucun ignoré, exit 0 | `evidence/reception-browser-acceptance-20261124.{json,log}` |
| Format et intégrité du diff | `npm --prefix frontend run format:check` ; `git diff --check` | PASS, exit 0 pour chaque commande | `evidence/reception-format-release-20261124.{json,log}` ; `evidence/reception-diff-release-20261124.{json,log}` |
| Identité des actifs navigateur et image | `python3 qa-reports/evidence/reception-asset-equivalence-20261124.py` | PASS, exit 0 ; toutes les empreintes SHA256 concordent | `evidence/reception-asset-equivalence-20261124.{json,log}` |

Le serveur local d'actifs a été lancé par `./node_modules/.bin/vite preview --host 127.0.0.1 --port 18447 --strictPort`, depuis `frontend/`.

Image locale testée : `unlimited-talk-reception-qa:20261124`. Les empreintes de chaque fichier livré dans `/app/web` concordent avec celles du build utilisé par Chromium. Les 38 scénarios passent les assertions d'absence d'exception JavaScript non gérée. Les réponses négatives simulées, notamment trois indisponibilités successives du renouvellement, restent dans les observations navigateur ; elles ne sont pas masquées.

Échecs intermédiaires conservés : deux assertions d'anciens tests décrivaient la pause automatique désormais corrigée ; elles ont été remplacées par des assertions plus complètes sur la récupération et la conservation du média, sans suppression de test. Une erreur de calendrier simulé dans le test de backoff a été corrigée. Deux erreurs TypeScript ont été corrigées avant compilation finale. Un premier lancement backend sur une ancienne image locale a donné 244/246 tests réussis et deux échecs de politique d'image (présence de pip/ensurepip) ; il ne valide pas l'image candidate. Les assertions de sécurité n'ont pas été changées. Une exécution navigateur lancée après l'échec de compilation servait encore un ancien build et a été interrompue (exit 130) ; elle n'est pas une validation. Les fichiers `reception-browser-sdk-final-20261124` conservent cette limite. Les régressions avant/après, captures et traces restent dans `qa-reports/evidence/`.

## Limites et validation opérationnelle restante

- **NOT TESTED :** appels PSTN réels, sonnerie et audio sur les postes des agents, panne du réseau réel d'un agent et comportement réel de l'opérateur. Aucun appel facturable n'a été initié.
- **NOT TESTED :** réception d'appels lorsque l'ordinateur est en veille, le navigateur fermé ou l'onglet supprimé par le système. Une application web ne peut garantir la réception dans ces conditions.
- **NOT TESTED :** nouvelle campagne de charge à 17–20 agents, audit de sécurité complet, migration/rollback et validation globale de toutes les fonctionnalités ; aucun changement backend ou de dépendance n'est introduit ici.
- **À confirmer après déploiement contrôlé :** ouvrir une réception, la laisser au moins quinze minutes, provoquer une brève coupure réseau puis revenir en ligne, vérifier la reprise sans clic, recevoir un appel réel, vérifier la conservation de son audio, puis vérifier qu'une pause volontaire reste active. Le déploiement devra respecter les appels en cours et les protections existantes.

Ce rapport valide un correctif ciblé en environnement isolé. Il ne certifie pas l'ensemble de l'application et ne prouve pas que chaque pause historique avait le même déclencheur. Aucun déploiement ni changement de `main` n'est effectué dans cette tâche.

## Publication autorisée et correction du test de confirmation de pause

Après l'audit ci-dessus, l'utilisateur a explicitement demandé le déploiement. Le commit `2a68924ab2b7758f46934f2211fa3533847d866f` a été publié sur `main`. La CI complète [45393956102](https://github.com/climatsynergie/unlimited-talk/actions/runs/45393956102) a **FAIL** au scénario de réception « renouvellement après trois indisponibilités sans pause et pause volontaire respectée », comparaison à la ligne 328 ; la publication d'image a été ignorée et aucun déploiement n'a été tenté. Les annotations publiques sont conservées dans `evidence/reception-release-20261124/failed-ci-annotations.json`. Les journaux complets du job ne sont pas accessibles sans authentification supplémentaire (HTTP 403).

La cause a été reproduite localement en retardant explicitement la confirmation réseau de la pause : le test capturait sa référence avant la destruction attendue du téléphone. Il observait ensuite `destroyed: 1` au lieu de `0`, bien que la réception reste correctement en pause. La régression déterministe **FAIL, exit 1** et sa trace sont conservées dans `evidence/reception-pause-ack-regression-before-20261124.{json,log}` et `evidence/browser-artifacts/reception-pause-ack-before-20261124/`.

Le test conserve sa comparaison complète, attend désormais la confirmation et la fermeture attendue avant de prendre la référence, et vérifie aussi l'absence de reprise automatique **pendant** que la confirmation est retenue. Aucun code applicatif ni assertion de sécurité n'est modifié pour cette correction de test. La commande `env UI_TEST_URL=http://127.0.0.1:18447 QA_EVIDENCE_MODE=reception-pause-ack-after-20261124 npm --prefix frontend run test:browser -- incoming-session.spec.ts --grep 'trois indisponibilités' --repeat-each=3` a **PASS, 3/3, exit 0**, sans relance automatique ni test ignoré : `evidence/reception-pause-ack-regression-after-20261124.{json,log}`.

La nouvelle validation CI complète est requise avant publication de l'image et déploiement avec les protections existantes. Les contrôles de production exécutés jusqu'ici restent en lecture seule : aucun appel actif, aucun bail de composeur actif, application disponible sur `6e9adaed2caf1a0a34a2664d96b1162e07333ed3`, appels toujours activés. Les autres rapports locaux préexistants ne sont pas inclus dans la publication.
