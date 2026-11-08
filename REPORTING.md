# Tableau de bord administrateur

`/admin/tableau-de-bord` affiche la supervision en direct et les rapports d’activité.
Les endpoints `/api/reporting/live`, `/report`, `/export.xlsx` exigent un compte
administrateur authentifié avec MFA. Les agents n’ont pas accès aux rapports des
équipes ni aux exports. `/presence` accepte uniquement une session authentifiée,
l’origine applicative et son jeton CSRF.

La page ouverte envoie une présence toutes les 30 secondes. Le direct est relu
chaque 10 secondes et considère une présence récente pendant 90 secondes. Une
conversation connue du serveur reste visible même en cas de perte de présence
navigateur. La présence et une session ouverte ne mesurent pas le temps travaillé.
Aucun appel n’est lancé par le tableau de bord ou son signal de présence.

## Définitions des rapports

La période est inclusive, dans le fuseau choisi, et limitée à trois mois
calendaires. Les bornes locales sont converties en UTC. Les jours sans activité
sont inclus et le détail horaire conserve les journées de 23 ou 25 heures avec
leur décalage UTC. La vue équipe et les fiches d’agent s’actualisent chaque minute.

- **Appels lancés** : `voice_intents.consumed_at` est renseigné ; une préparation
  ou réservation annulée sans autorisation fournisseur n’est pas une tentative.
- **Décrochés** : progression en conversation, résultat `completed`, ou présence
  d’un enregistrement de durée positive. Une connexion peut être un répondeur ;
  aucun taux de réponses humaines n’est inventé.
- **Contacts distincts** : numéros distincts dans la période et le regroupement.
  La synthèse équipe calcule ses propres distincts et ses propres ratios, sans
  additionner les distincts ni moyenner les pourcentages des agents.
- **Durée connue** : durée du statut final fournisseur quand elle est disponible,
  sinon durée de l’enregistrement. Une durée absente reste inconnue. La moyenne
  utilise uniquement les décrochés disposant d’une durée. La durée entière est
  attribuée à l’heure de lancement de l’appel, pas ventilée en temps travaillé.
- **Appels entrants proposés** : une présentation à un agent, comptée à sa date
  et heure de présentation. Le même appel présenté successivement à deux agents
  compte une proposition pour chacun. Les appels restés dans la file sans agent
  ne sont pas attribués à une personne.
- **Entrants décrochés** : propositions avec une connexion établie. Leur
  **conversation entrante connue** utilise la durée finale fournisseur, sinon la
  durée de l’enregistrement de conversation ; une durée absente n’est pas inventée.
  Ces trois compteurs sont séparés des appels sortants dans chaque synthèse, jour,
  heure et export Excel. Les comptes administrateurs qui reçoivent des appels
  apparaissent également dans les rapports et dans le direct pendant leur appel.
- **RDV créés** : création dans la période, au nom du créateur. Les annulations
  reflètent le statut actuel de ces RDV, pas la date à laquelle ils ont été annulés.
  RDV / 100 appels compare les volumes de la période, sans prouver un rattachement
  individuel du RDV à un appel.
- **Pauses et arrêts enregistrés** : actions du journal d’audit du composeur.
  L’historique ancien peut inclure des pauses de sécurité. Les nouvelles pauses
  automatiques sont journalisées séparément. Ces compteurs ne prétendent pas
  mesurer les durées de pause ni reconstruire les heures de présence passées.

Les appels, RDV et actions d’audit proviennent d’une même requête d’agrégation
PostgreSQL. La compatibilité avec le schéma précédent sans réception téléphonique
retourne des compteurs entrants à zéro sans lire les tables absentes. Les réponses sont limitées en période et ne chargent pas les appels
individuels dans la mémoire applicative. Une requête a un délai maximum de 15 s. Une seule agrégation lourde s’exécute
à la fois par processus API ; les autres attendent jusqu’à 15 s avant un 429
avec Retry-After. L’attente n’acquiert aucune connexion ni verrou SQL. Cette
limite laisse une connexion du pool runtime disponible pour les opérations
d’appel et les présences. Le navigateur autorise 40 s pour un rapport mis en file.
Les verrous d’authentification sont
libérés avant le calcul et les droits sont revérifiés après.
Les seules écritures ajoutées sont le signal de session, les événements de pause
automatique et la trace des exports ; aucune migration de schéma n’est nécessaire.

## Excel

Les fichiers `.xlsx` natifs utilisent openpyxl 3.1.5 et et_xmlfile 2.0.0, versions
figées. Les onglets sont **Synthèse**, **Par jour**, **Par heure** pour un agent
choisi, et **Repères**. L’export équipe conserve la synthèse et les jours de tous
les agents ; l’export individuel ajoute les heures. Les dates et compteurs sont
typés ; les noms et courriels restent des textes, jamais des formules ou liens.
L’export ne contient pas les numéros clients ou les enregistrements audio.

La génération du fichier libère d’abord la connexion PostgreSQL et reste limitée
à un export simultané par processus API pour préserver la mémoire et les appels.
Les réponses sont privées (`Cache-Control: no-store`). L’activité des exports est
journalisée, sans mettre les réponses ou fichiers dans des logs ou le navigateur.

Validation : `test_reporting.py`, `verify_reporting.py` (HTTP/PostgreSQL/XLSX),
`verify_reporting_incoming.py` (agrégats entrants, durée, export, direct admin,
compatibilité et absence de doublons),
`frontend/tests/dashboard.spec.ts` (admin, clavier, 22 agents, mobile, accessibilité,
90 jours, changement d’heure, export et erreurs) ainsi que les preuves Voice et
composeur existantes. Aucun appel PSTN réel n’est nécessaire aux tests.

Références de conception :
- [Twilio Flex — Workload reporting](https://www.twilio.com/docs/flex/end-user-guide/insights/workload-reporting)
- [Genesys — Agent Performance Dashboard](https://all.docs.genesys.com/PEC-REP/Current/RPRT/HRCXIAgntPerfDshbrd)
