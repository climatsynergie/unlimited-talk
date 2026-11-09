# Recette contrôlée des appels réels — Unlimited Talks

**État : plan préparé, aucun appel exécuté par ce plan.** Rédigé le 9 novembre 2026 sur `qa/full-audit-20261108`, source inspectée `c42b68cd9c40a766cefc7690f0d4bea29cfc05ec`. Les validations locales sont décrites dans [la matrice QA](test-matrix.md) et [les résultats](regression-results.md) ; elles ne prouvent pas la qualité opérateur/casque réelle. Le [verdict de livraison](release-readiness.md) reste l'autorité pour les blocages, notamment les images natives et l'acceptation opérateur. Relire son état après la remédiation en cours.

Ce document n'autorise ni fusion vers main, ni déploiement, ni changement Twilio, ni appel, ni SMS. Une approbation explicite doit désigner la version, l'environnement, la ligne, les participants, la fenêtre, le plafond de coût/minutes et chaque palier autorisé. Les destinataires consentants sont une règle de recette, sans ajout d'une restriction permanente de numérotation au produit.

## Pilote court avec 3 agents : préparation séparée, puis 30 minutes de session

**Les correctifs QA et les nouvelles images ne sont pas déployés.** La production observée pendant l'audit était au schéma 11 ; sa réception ne doit pas être supposée prête pour le candidat schéma 12. Le NO-GO production subsiste notamment pour Expat embarqué par un fournisseur. Un pilote restreint exige une revue et une acceptation explicites de ce risque résiduel, ainsi que la bonne version revue effectivement présente. Une échéance ne vaut ni acceptation du risque, ni autorisation de déployer ou d'appeler. Les contrôleurs simulés ne certifient ni l'audio réel ni les transferts en conversation.

### Avant la session — hors des 30 minutes

- [ ] Responsable nommé ; approbation du seul pilote 3 agents, de sa fenêtre, des correspondants, de l'enregistrement et du plafond de coût ; risque résiduel Expat examiné explicitement.
- [ ] SHA/digest revus et version réellement active confirmés. Tout déploiement ou raccordement nécessaire possède son autorisation distincte ; sinon **NO-GO**, sans mise à jour précipitée.
- [ ] Pour tester les entrants : schéma 12, ligne UT réservée et connectée, fournisseur/capacité et workers sains vérifiés. Un serveur encore au schéma 11 ne satisfait pas ce prérequis.
- [ ] Trois comptes/postes/casques et trois correspondants réels distincts disponibles ; comptes dédiés sans autre campagne ni rappel réel dû ; campagne/queue/numéros de recette préparés.
- [ ] QA et opérateur prêts à relever les heures/IDs privés, écouter les deux sens et mettre les nouveaux départs en pause ; critères et conduite d'urgence compris.

### Session approuvée — 30 minutes proposées

| Minute | Travail limité |
|---|---|
| 0–5 | Vérifier les trois casques ; un sortant court puis un entrant explicite sur la ligne prévue. Si l'un échoue, arrêter la progression. |
| 5–15 | Trois conversations simultanées, dont une vague mixte 2 sortantes + 1 entrante ; chaque correspondant confirme voix/identité et note la qualité dans les deux sens. Naviguer sans interrompre la conversation. |
| 15–23 | Contrôler fin serveur, délai 10 s, Attendre/reprise et un cas de refus/non-réponse/message vocal. Si le budget le permet, garder une conversation commencée vers minute 5 jusqu'après minute 16 pour dépasser l'ancien seuil 10 min. |
| 23–30 | Écouter les archives disponibles, vérifier le suivi manqué et les compteurs, consigner PASS/FAIL/BLOCKED et décider de la suite. Une archive attendue mais absente reste un écart, pas un succès différé implicite. |

**GO limité aux parcours effectivement réalisés à 3 agents** : bonne version, autorisation/risque acceptés, audio clair dans les deux sens, aucun mélange/doublon, historique/archives cohérents et aucun critique/haut nouveau. **NO-GO** si l'un de ces éléments manque, si les entrants reposent encore sur le schéma 11, si un appel vise un tiers imprévu, ou si audio/identité/occupation sont incorrects. Ce pilote ne valide ni 20 agents, ni la limite 30 min, ni un transfert audio, ni une mise en production. Le palier 20 et le GO production gardent leurs décisions séparées.

## 1. Périmètre réel et transferts

Le parcours inspecté est **Twilio Programmable Voice + SDK navigateur**, sans prérequis VICIdial/Asterisk pour cette livraison.

| Fonction | État constaté dans le code | Attente de recette |
|---|---|---|
| Appel sortant manuel et composeur progressif | Implémenté : une conversation par agent, destination commune protégée, 30 min en mode normal | Tester le média réel ; mode de validation 3 min distinct |
| Réception et offre à un agent attribué | Implémenté au schéma 12 ; connexion explicite d'une ligne nécessaire | Tester entrée externe → agent, réponse/refus, attente et message vocal |
| Réoffre à un autre agent avant réponse | Implémentée par offres successives et disponibilité | A refuse/ne répond pas ; B reçoit le même appel entrant, sans double conversation |
| Réattribution administrative d'un suivi | Implémentée dans le pipeline entrant | Déplacer la responsabilité d'une fiche, sans déplacer un média actif |
| « Parle anglais » | Classement CRM vers Contacts anglophones, identité/historique conservés | Vérifier le classement ; puis un éventuel nouvel appel distinct par B |
| Transfert audio à chaud/à l'aveugle, consultation ou conférence | **NON IMPLÉMENTÉ dans le périmètre inspecté** : aucune commande de transfert dans le poste, aucun endpoint de transfert identifié, TwiML sortant Dial/Number et entrant Dial/Client | **BLOCKED pour l'acceptation d'un transfert en cours de conversation**. Si exigé à la livraison, décision produit et lot dédié avant ce GO |
| SMS, prédictif, détection automatique de répondeur | Hors recette ; « Boîte vocale » est une disposition manuelle | Ne pas les présenter comme des fonctions validées |

Preuves de périmètre : [TwiML sortant](../backend/app/telephony/twilio_voice.py), [TwiML entrant](../backend/app/telephony/incoming_hooks.py), [contrôles de réception](../backend/app/telephony/incoming_routes.py), [classement anglais](../backend/app/campaigns/language.py), [bouton agent](../frontend/src/Campaigns.tsx), [déploiement entrant](../deployment/telephony/INCOMING-ROLLOUT.md). Les anciens paragraphes d'INBOUND/TELEPHONY décrivant des jalons précédents ne valent pas preuve de l'état actif du serveur.

## 2. Fiche d'approbation avant exécution

À compléter dans le registre privé, avec un lien expurgé dans le compte rendu :

- Responsable métier / responsable opérateur / QA observatrice / personne autorisée à arrêter la recette.
- SHA complet, digest immuable, CI/attestation, environnement et origine HTTPS ; aucune version « latest ».
- Ligne UT dédiée et numéro fournisseur sélectionnés, route précédente sauvegardée, propriétaire de la ligne ; aucun déplacement de la ligne de l'ancienne application sans décision explicite.
- Comptes agents A01–A03, puis A01–A20 ; correspondants C01–C20 et leurs téléphones réels distincts dans une liste privée. Aucun numéro client importé choisi au hasard ; aucun numéro 555 fictif composé.
- Heure début/fin en UTC et équivalences `America/Toronto` / `Africa/Casablanca`, confirmées pour la date réelle.
- Paliers autorisés : 1, 3, puis 20 ; nombre de tentatives, minutes et coût maximal ; appels longs/charge mixte et perturbation locale éventuelle cochés séparément.
- Information des participants sur l'enregistrement, modalités approuvées par l'entreprise et conservation des preuves ; consentement reconfirmé au début.
- Politique d'arrêt, accès de l'opérateur et retour de routage prévus. Aucun arrêt global affectant d'autres utilisateurs sans autorisation.

La [matrice automatisation/humain/identifiants](real-call-acceptance-matrix.md) précise qui peut faire quoi. Aucun secret n'est à copier dans ce document, Git, le chat, une capture ou une commande shell.

## 3. Prérequis bloquants

1. Les blocages du rapport de livraison sont résolus ou disposent d'une décision formelle. La recette de la nouvelle version exige son déploiement approuvé et attesté ; elle ne peut pas certifier le candidat en appelant une ancienne version.
2. Pour les entrants : schéma 12 réellement actif, workers de rapprochement/archivage sains, ligne connectée et vérifiée. Une file créée au schéma 11 ou « Réception inactive » n'est pas un raccordement. Préparer/connecter/restaurer une ligne et activer la numérotation sont des mutations séparées, à faire seulement par l'opérateur après autorisation.
3. Compte Twilio et pays autorisés vérifiés en lecture : disponibilité du service, solde/plafond de dépense, statut du compte, capacité et éventuelles restrictions. **20 agents connectés à l'app ne prouvent pas 20 conversations.** Une conversation peut avoir plusieurs branches fournisseur ; budgéter les branches SDK/PSTN et celles d'attente. Le plafond applicatif partagé ne se déduit pas du nombre de CallSid Twilio.
4. Vérifier le chemin réellement utilisé : le code inspecté émet Dial, pas un moteur de campagnes REST. Les CPS REST ne limitent pas directement les appels entrants/Dial ; une autre limite de concurrence du compte peut toutefois les bloquer. Ne pas acheter une augmentation sur la seule mention historique «5 CPS ». Voir [Calls/CPS](https://www.twilio.com/docs/voice/api/call-resource) et [limite de concurrence 10004](https://www.twilio.com/docs/api/errors/10004).
5. Comptes de recette dédiés, casque/ordinateur/réseau représentatifs, navigateur/version et permissions microphone inventoriés.20 onglets ou 20 sessions sur un même poste ne remplacent pas 20 postes et 20 casques réels.
6. Campagne `RECETTE-<date>` et queue dédiées, uniquement des contacts/correspondants consentants. **Le composeur traite aussi les rappels dus des autres campagnes de l'agent** : comptes de recette sans autre attribution ni rappel réel, et vérification de Rappels avant chaque vague. La sélection de la seule campagne de recette ne suffit pas.
7. Définir dans cette seule campagne la politique de tentatives nécessaire aux répétitions approuvées, ou disposer de nouvelles destinations. Les valeurs par défaut 2 tentatives/2 heures peuvent bloquer une deuxième vague automatique : ne pas les changer sur les campagnes métier ou supprimer des historiques pour contourner cela.
8. Un numéro émetteur vérifié par campagne ; second numéro seulement s'il est déjà autorisé. Les règles régionales avancées ne sont testées que si elles existent réellement. Une route UK est un sous-périmètre distinct, pas implicite dans la recette Canada.
9. Zéro appel métier en cours sur la fenêtre réservée ; sauvegardes/restauration et moyen de retour de route disponibles. Aucun test de panne de PostgreSQL, redémarrage de service, coupure réseau serveur ou suppression d'enregistrement réel dans cette recette.

### Contrôles exacts sans appel ni mutation de configuration

**Commandes proposées, non exécutées pour ce plan.** Après autorisation de lecture, l'opérateur les lance sur l'hôte désigné. Elles ne chargent pas de secrets dans la sortie. Le SHA à renseigner est celui réellement approuvé/déployé, pas nécessairement celui de ce document.

```bash
set -euo pipefail
ACCEPTANCE_SHA='REMPLACER_PAR_LE_SHA_COMPLET_APPROUVE'
[[ "$ACCEPTANCE_SHA" =~ ^[a-f0-9]{40}$ ]] || exit 1
ACCEPTANCE_RELEASE="/srv/unlimited-talk-staging/releases/git-$ACCEPTANCE_SHA"
test "$(readlink -f /srv/unlimited-talk-staging/current)" = "$ACCEPTANCE_RELEASE"
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8110/health/live
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8110/health/ready
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8110/api/system
docker compose --project-directory "$ACCEPTANCE_RELEASE" --env-file "$ACCEPTANCE_RELEASE/.env" -f "$ACCEPTANCE_RELEASE/compose.managed.yaml" ps
ACCEPTANCE_API_ID=$(docker compose --project-directory "$ACCEPTANCE_RELEASE" --env-file "$ACCEPTANCE_RELEASE/.env" -f "$ACCEPTANCE_RELEASE/compose.managed.yaml" ps -q api)
test -n "$ACCEPTANCE_API_ID"
docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}} {{.Image}} {{index .Config.Labels "org.opencontainers.image.revision"}}' "$ACCEPTANCE_API_ID"
```

Attendus : révision exacte, READY, migration 12 pour entrants, bon mode/profil, activation cohérente avec la fenêtre approuvée ; api/gateway/worker/dispatcher/broker/voice-reconciler/voice-archiver opérationnels. Un statut live seul ne prouve ni DB, ni média, ni route entrante. Les endpoints de santé peuvent être cachés sur l'origine publique : ne pas les exposer pour ce test.

Dans la session navigateur normale, inspecter les réponses existantes de `GET /api/telephony/test/session`, `GET /api/telephony/dialer/session`, `GET /api/inbound/reception` et le dashboard admin ; ne pas coller de cookie/jeton dans curl. L'UI affiche les états réels et les seules queues attribuées. Les lectures peuvent contenir des données privées : preuve expurgée uniquement.

Ne pas lancer `tests/verify_browser.py`, les fixtures de restauration/panne, ni les suites d'intégration sur ce serveur : elles recréent des services ou manipulent une base jetable. `control_manual_voice.py check` n'est pas un audit strictement sans écriture : il renouvelle un reçu privé de vérification. Les commandes prepare/enable/public-access/connect/restore/migrate/deploy restent soumises à l'approbation de mise en service.

## 4. Campagne de recette, un palier à la fois

Chaque cas commence **BLOCKED/non exécuté** tant que ses prérequis et son palier ne sont pas approuvés, puis NOT TESTED avant son lancement. PASS exige la preuve, FAIL conserve l'erreur originale. Une vague arrêtée n'est pas PASS.

| ID / palier | Action réelle contrôlée | Résultat vérifiable |
|---|---|---|
| R01 /1 | Tester mon casque, puis appel manuel vers C01 ;30–60 s de dialogue avec chiffres et phrase témoin dans les deux sens | Bon émetteur, bon destinataire, audio bidirectionnel intelligible, Appeler/Raccrocher/historique cohérents ; aucun autre appel |
| R02 /1 | C01 appelle la ligne UT ; A01 a ouvert Recevoir les appels puis clique Répondre | Bon appelant/queue, acceptation explicite avant conversation, annonce entrante française, un seul agent connecté |
| R03 /1 | Naviguer vers Calendrier/Conversations pendant le dialogue ; pause de réception ou du composeur | Média conservé ; pause bloque seulement le prochain appel. Raccrocher termine le média et l'état serveur finit sans libération anticipée |
| R04 /1 | Terminer, attendre l'archivage ; écouter les phrases témoins, début et fin, depuis les droits agent/admin | Conversation et 2 canaux attendus ; durée/acteur/numéro corrects, archive privée lisible. Autre agent non autorisé refusé selon le contrat |
| R05 /1 | Réception ouverte au repos plus de 5 min ; nouvel appel ensuite, puis conversation dépassant 10 min | Renouvellement SDK sans reconnexion spontanée ; aucun ancien plafond 10 min. Un essai dédié du plafond normal 30 min demande son budget séparé ; contrôler fin fournisseur et marge navigateur de signalisation |
| R06 /3 | A01–A03 lancent trois appels sortants à trois correspondants distincts, puis vague 2 sortants+1 entrant | Trois conversations réelles en même temps ; aucun agent doublement occupé, aucune destination doublée, aucune voix/histoire mélangée |
| R07 /3 | Les 3 agents ouvrent la réception ; A refuse/ne répond pas, B est disponible ; refaire avec A occupé, en pause, en RDV ou en délai après-appel | Réoffre avant réponse à un agent éligible, disponibilité/fairness observables ; aucun faux transfert audio et aucun appel parallèle pour A |
| R08 /3 | Composeur progressif, au moins 2 contacts par agent ; attendre 10 s, cliquer Attendre sur une itération, reprendre explicitement | Aucune réservation suivante avant le délai ; Attendre persiste après navigation ; reprise seule relance. Contacts actuels/drafts antérieurs distincts |
| R09 /3 | Pendant un appel sortant de campagne : note, Non intéressé, rappel à une échéance approuvée, qualification puis RDV ; cas séparé sans RDV | Bon contact mis à jour ; RDV+réponses+campagne conservés, rappel au bon agent ; sans RDV, pas de fiche précédente bloquante. Ne pas contacter reste bloquant ; Non intéressé reste appelable manuellement |
| R10 /3 | Un répondeur volontaire est marqué Boîte vocale ; autre appel entrant sans agent disponible, message témoin laissé | Premier cas raccroche/classe une fois et sort des conversations connues ; second cas crée un suivi visible et son message mono privé, sans doublon après actualisation |
| R11 /3 | Parle anglais sur un contact éligible ; réattribution admin d'un suivi ; B rappelle seulement après fin du premier appel et accord du correspondant | Même identité/historique, bonne campagne/étape/responsabilité. Le média actif ne passe pas à B : transfert à chaud/aveugle reste hors livraison |
| R12 /3 | Après information du correspondant : actualisation complète ou déconnexion d'un agent test ; reconnexion normale | Ancien média fermé, pas de rappel/SDK relancé seul, état serveur rapproché ; réception/composeur demandent une reprise explicite. Pas de partage de comptes |
| R13 /20 | Après signature du palier 3, montée 3 → 5 → 10 → 20, vague sortante progressive avec 20 destinations distinctes | 20 conversations réellement reliées, maintenues ensemble 10 min ; administrateur et chronologie fournisseur concordent, pas seulement 20 sessions connectées |
| R14 /20 | Vague entrante 20 correspondants → ligne UT ; puis vague mixte 10 sortantes+10 entrantes, environ 2 min chacune | Occupation commune et 20 conversations ; pas de famine, mauvais agent, double destination, appel perdu ou attente serveur inexpliquée |
| R15 /20 | Répéter fin/reprise, enregistrement et contrôle d'échantillons par agent ; vérifier dashboard/jour/heure/Excel | Chaque appel a son acteur, issue et archive ; entrants/sortants séparés, boîte vocale exclue du temps de conversation, pas de double compte |
| R16 /option approuvée | Pendant la tenue 20 : un import synthétique 100 lignes et un rapport/export borné, séquentiels | Le travail métier ne dégrade pas l'admission/audio au-delà des seuils signés ; aucune vraie campagne appelée par cet import. Le débit import 100000 lignes reste une recette distincte |
| R17 /option approuvée | 21 e tentative contrôlée avec 20 places occupées, ou brève perte réseau sur un seul poste test | Refus/attente conforme au plafond, pas de 21 econversation ou double appel ; retour réseau sans relance aveugle. Jamais de panne réseau serveur improvisée |

Pour R09/R11, préparer des contacts éligibles distincts ou une clôture explicitement approuvée des seuls RDV/rappels de recette. Un classement anglais refusé parce qu’un RDV ou un rappel est encore actif doit conserver cet engagement ; ce refus prévu ne se contourne pas en supprimant l’historique. Pour R07, expiration/refus d'une offre ne vaut pas fin du parent fournisseur. Pour R10, attendre le délai configuré de queue puis la messagerie ; ne pas confondre sonnerie volontaire, délai 10 s et latence technique. Pour les rappels entrants, le pipeline permet un rappel manuel ; il n'est pas automatiquement une tâche du composeur de campagne.

Les trois vagues 20 correspondent à au moins 60 conversations de test et environ 280 minutes-agent avec les durées proposées, avant sonneries/branches. L'opérateur calcule le coût réel avec son compte et peut réduire les vagues avant approbation. Si20 postes/correspondants ou la capacité manquent, **BLOCKED**, pas PASS avec 20 faux clients SDK.

## 5. Mesures et seuils à signer avant l'essai

Seuils de recette proposés, pas SLA déjà démontrés. p95 désigne le 95e percentile ; indiquer le nombre de mesures et le maximum, surtout pour un petit pilote. Le responsable peut les ajuster **avant** l'exécution ; aucune modification a posteriori pour effacer un FAIL.

| Mesure | Proposition d'acceptation / preuve |
|---|---|
| Identité/occupation | 0 mauvais destinataire, 0 audio croisé, 0 double conversation par agent/destination, 0 appel hors périmètre ; corrélation de chaque intent/call/offer et branches |
| Connexion après réponse | Temps Répondre/décroché → premier audio intelligible : p95≤2 s ; noter maximum, taille d'échantillon et toute valeur>3 s. À20, surcharge inexpliquée≤1 s par rapport au palier 3 ; sonnerie et délai voulu exclus |
| Qualité audible | Chaque interlocuteur note ≥4/5 dans les deux sens (note humaine distincte du MOS réseau) ; aucun audio unidirectionnel, écho gênant, voix robotique durable, mauvaise voix ou coupure inexpliquée |
| Réseau/SDK | Collecter disponibilité et chronologie des avertissements, pertes/jitter/RTT/MOS quand accessibles. Les avertissements Twilio portent notamment sur RTT>400 ms, jitter>30 ms, pertes>1% ou MOS<3,5 sur plusieurs échantillons ; ce sont des signaux d'investigation, pas une preuve suffisante de l'expérience humaine. [Référence SDK](https://www.twilio.com/docs/voice/voice-insights/api/call/details-sdk-call-quality-events), [limites d'interprétation](https://www.twilio.com/docs/voice/voice-insights/frequently-asked-questions) |
| Reprise/fin | Fin nominale reflétée en≤30 s ; si incertaine, conserver l'occupation et mettre la vague en pause. Absence de convergence>90 s impose un FAIL à analyser, jamais une libération SQL forcée |
| Archivage | Appels courts : lecture privée cible≤5 min après fin ; lot 20 prolongé : cible≤10 min après dernière fin. Inventaire de tous les appels, écoute d'au moins un extrait par agent et de tous les échecs ; absence inexpliquée=FAIL |
| Charge | Relever CPU/RAM/OOM, latence API, connexions PostgreSQL, files de travaux/âge, erreurs fournisseur/HTTP.0 OOM/redémarrage inattendu ; saturation durable ou croissance sans rattrapage interdit le palier suivant |
| Rapports | Comparer les totaux au registre de recette par période/fuseau, en distinguant propositions entrantes, entrants décrochés, sortants, messages vocaux, conversations connues, RDV et pauses |

Voice Insights peut demander des droits/options du compte ; ne pas activer une option payante implicitement. À défaut, les outils WebRTC du navigateur et les notes humaines complètent la preuve, avec données réseau privées. Si une mesure obligatoire n'est pas accessible, la marquer BLOCKED ; ne pas inventer de RTT/MOS ni promettre « zéro attente ».

## 6. Arrêt et décision

**Arrêt immédiat des nouveaux départs** au premier appel hors liste consentie, audio/fiche croisé, accès indu à un enregistrement, double occupation, route héritée modifiée sans accord, boucle de rappels, erreur d'authentification fournisseur ou perte de contrôle du plafond/coût. Terminer l'appel de test concerné sans provoquer d'autres appels. Les agents utilisent pause/arrêt ; l'opérateur n'effectue un arrêt global ou retour de route que dans l'autorisation d'urgence préétablie. Conserver les notifications/récupérations/archives nécessaires aux appels déjà engagés.

Une dégradation audio persistante, un état terminal incertain>90 s, un worker malsain, une archive absente ou un mauvais total suspend le passage au palier suivant. Photographier l'état expurgé, relever les identifiants privés, ouvrir un défaut avec horodatages, puis reprendre seulement après correction et répétition du scénario en échec. Aucun déploiement pendant les appels ; aucune suppression/manipulation de ligne SQL pour rendre un test vert.

- **GO palier 3** : R01–R05 satisfaits, mesures accessibles, aucun critique/haut applicatif ouvert et approbation du responsable. Toute acceptation du risque de dépendance doit viser explicitement ce pilote ; elle ne lève pas le NO-GO production.
- **GO palier 20** : cas obligatoires du palier 3 passés, capacité/coût/participants confirmés et approbation distincte. Les options non exécutées restent NOT TESTED.
- **GO périmètre livré** : toutes les vagues obligatoires réellement passées, rapports/archives rapprochés, défauts critiques/hauts absents et résiduels acceptés. Les transferts en conversation ne peuvent figurer dans ce GO.
- Ce GO de recette n'autorise ni merge main, ni publication d'image, ni déploiement production : chacun garde son approbation et son processus de livraison.

## 7. Preuves et compte rendu

Créer un répertoire privé par session `acceptance-<UTC>-<SHA>` ; déposer dans Git seulement un résumé expurgé. Conserver : approbation et budget ; révision/digest/schéma/services ; inventaire anonymisé des postes ; journal par appel (cas, vague, agent/correspondant alias, direction, campagne/queue, émetteur masqué, intent/CallSid/offer privés, début/sonnerie/réponse/premier audio/fin/archivage, scores et avertissements) ; captures/console/réseau expurgées ; rapports Excel et rapprochement ; chemins d'archives privés et intégrité ; écarts/arrêts/contre-tests.

Chaque ligne de résultat porte **PASS / FAIL / BLOCKED / NOT TESTED**, exécutant, heure, preuve et périmètre exact. Les captures WebRTC/Voice Insights peuvent contenir IP, appareils, numéros ou jetons : accès restreint, conservation selon la politique approuvée, aucune URL signée/clé/cookie transcrite. Ne pas publier les enregistrements.

Après la session : confirmer zéro appel test actif et archives terminées, fermer explicitement les composeurs/réceptions de test selon le plan, vérifier la route finale approuvée, isoler/archiver les objets de recette avec historique conservé. Aucune suppression de contacts, d'audit ou d'enregistrement fournisseur n'est implicite. La signature finale indique aussi les cas non exécutés, notamment transfert audio, médias opérateur non testés et montée 20 si bloquée.
