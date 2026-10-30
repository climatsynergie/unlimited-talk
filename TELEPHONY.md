# Téléphonie Unlimited Talks — Twilio Programmable Voice

## Choix courant et état réel

Le parcours retenu utilise Twilio Programmable Voice directement avec l'interface
Unlimited Talks. VICIdial/Asterisk n'est plus un prérequis de cette intégration.
L'[exploration SIP précédente](deployment/telephony/SIP-EXPLORATION.md), ses profils
privés et son image de laboratoire sont conservés comme historique. Ne pas créer
les deux serveurs proposés dans cette exploration pour le parcours Twilio direct.

Le CRM, PostgreSQL, les imports, campagnes, notes, calendrier et rappels restent
le socle. Les communications de l'application déployée sont toujours désactivées.
L'API de test contrôlé, sa migration additive et la validation des notifications
signées sont déployées dans la révision `90e3cfc58a7a216cc79307c990e1440e14756fba`,
schéma 7 et communications désactivées. Cette branche prépare maintenant le
worker de rapprochement ; il n'est pas encore installé ni démarré. Aucun accès
public aux webhooks, jeton navigateur réel ou numérotation n'est activé. Les identifiants de la nouvelle clé
Voice ont été saisis dans un fichier privé du serveur ; sa lecture du numéro de
test a réussi. Une nouvelle application TwiML distincte a ensuite été créée et
vérifiée le 29 octobre 2026. Les trois applications précédentes et les paramètres
des quatre numéros sont restés identiques après création. Aucun numéro n'a été
assigné à cette nouvelle application ; son VoiceUrl n'est pas encore accessible.
Les outils de préparation restent séparés des conteneurs applicatifs.

## Responsabilités cibles

```mermaid
flowchart LR
    Agent["Agent : interface et casque navigateur"] --> CRM["API : identité et décisions"]
    CRM --> PG["PostgreSQL : réservations, appels, historique"]
    CRM --> Jobs["Travaux durables : lancement et rapprochement"]
    Jobs --> Twilio["Twilio Programmable Voice"]
    Agent <-->|"Audio Voice SDK"| Twilio
    Twilio <-->|"Notifications signées"| CRM
    Twilio <--> Phone["Destinataire autorisé"]
    Jobs --> Archive["Archive privée Spaces"]
```

Twilio transporte les médias et établit les communications. Le module applicatif
communications doit décider qui appeler et quand, avec PostgreSQL comme autorité.
Redis/Celery transporte du travail, pas la seule copie des réservations. L'API
ne doit pas lancer indépendamment deux appels pour la même intention après un
délai ou une notification tardive. Chaque commande externe est persistée avant
son effet ; tout résultat incertain est rapproché avant une nouvelle tentative.

Twilio devient le producteur des enregistrements, ensuite archivés dans Spaces
privé avec métadonnées et permissions dans PostgreSQL. Ce choix remplace celui
d'Asterisk dans l'exploration précédente. Le réglage d'enregistrement du trunk SIP
historique n'est pas modifié : il ne sert pas au parcours Programmable Voice.
Les SMS restent une livraison distincte ; aucune messagerie n'est envoyée ici.

## Frontière fournisseur livrée

`backend/app/telephony/twilio_voice.py` fournit des fonctions sans client réseau :

- Profil contrôlé : compte, application TwiML, origine HTTPS canonique et unique
  destinataire approuvé côté serveur. Aucun paramètre navigateur `To` n'est utilisé.
- Jeton Voice SDK de cinq minutes, identité liée à l'agent et à l'intention,
  autorisation sortante pour une seule application TwiML, sans réception d'appels.
- Vérification des formulaires signés avec le validateur du SDK officiel, origine
  et chemin construits depuis la configuration. Les en-têtes Host/Forwarded ne
  décident pas de l'URL signée. Les paramètres supplémentaires et répétés restent
  inclus dans la vérification ; les champs critiques ambigus sont refusés.
- Entrée initiale fixe `/api/telephony/twilio/voice`, correspondant à l'unique
  VoiceUrl d'une application TwiML. Le champ `Intent` est vérifié après la
  signature, sous forme UUID canonique, et doit correspondre à l'identité SDK
  `From`. Cette cohérence ne remplace pas la réservation durable. Le statut parent
  utilise `/api/telephony/twilio/parent-status` et exige un CallSid déjà lié en
  base. Les autres notifications conservent un chemin comprenant l'intention.
- Signature avec une SharedKey dédiée ; identifiant et algorithme doivent
  correspondre au profil. Aucun repli vers le jeton principal du compte. Le SDK
  Python 9.12.0 utilise ici son validateur HMAC_SHA1 ; HMAC_SHA256 est refusé tant
  qu'un validateur officiel compatible n'est pas intégré et vérifié.
- TwiML du premier essai : destination fixe, sonnerie de 20 secondes maximum,
  durée de 180 secondes maximum, enregistrement double canal depuis la réponse,
  notifications de statut/enregistrement et raccrochage final.

**Ces fonctions ne constituent pas une autorisation d'appel.** Un jeton n'est pas
une réservation à usage unique. Une signature authentique n'empêche pas le rejeu.
Le service `telephony/service.py` consomme donc atomiquement une intention non
expirée et vérifie l'administrateur, sa session toujours active et son identité
SDK. La transaction est validée avant de retourner le premier TwiML Dial. Même
une seconde requête avec le même CallSid reçoit seulement Hangup. Les routes
restent indisponibles (503) dans le mode `disabled`, qui reste le défaut des
déploiements locaux et gérés.

## API contrôlée et historique durable

Le schéma `0007_voice` ajoute intentions, événements immuables et métadonnées des
enregistrements sans réécrire les tables métier. Les sessions ne sont pas une
clé étrangère des intentions : leur révocation ne supprime jamais l'historique.
Un index unique interdit deux intentions actives pour le même utilisateur ; un
autre interdit deux appels de test simultanés vers le même destinataire du compte.

- `POST /api/telephony/test/intents` accepte uniquement un UUID d'idempotence,
  jamais un numéro choisi par le navigateur. Il exige une session administrateur
  récente avec MFA, CSRF et origine valide. La réservation de deux minutes est
  validée en base avant émission du jeton de cinq minutes. La même session peut
  reprendre la même réservation encore disponible ; aucun jeton n'est réémis pour
  une réservation consommée ou une autre session.
- L'annulation libère seulement une réservation non consommée. Ni le navigateur,
  ni un délai local ne peut libérer un appel déjà autorisé. Après une réponse
  perdue, l'intention reste bloquée jusqu'à un résultat terminal du fournisseur
  ou un rapprochement contrôlé. Le worker décrit ci-dessous ne peut créer aucun
  appel ; aucune nouvelle tentative aveugle.
- Au webhook Voice, utilisateur, session et intention sont verrouillés dans cet
  ordre. Une révocation, désactivation, modification de rôle ou expiration entre
  le jeton et l'appel empêche le Dial. La destination et le CallerID sont figés
  dans le profil et l'intention, pas lus depuis les champs du navigateur.
- Les statuts enfants exigent le parent déjà lié, le destinataire et le CallerID
  attendus. Les événements sont dédoublonnés sur leur contenu métier, pas sur des
  champs arbitraires du fournisseur. SequenceNumber et la progression monotone
  empêchent une notification ancienne de réactiver un appel terminé. Le résultat
  détaillé de Dial prime sur le statut générique du parent, même reçu plus tard.
- Les notifications d'enregistrement exigent la source DialVerb et le parent
  déjà lié, conformément au contrat Twilio. Elles peuvent donc arriver avant
  tous les statuts enfants, tout en vérifiant SID, durée et deux canaux. Les
  métadonnées passent à `pending_archive` ; aucune URL de formulaire
  n'est stockée ni téléchargée. Une même RecordingSid ne peut pas être réaffectée.
  Cette réception ne prouve pas encore une copie Spaces ni une lecture audio.
- Les routes POST précises refusent en-têtes ambigus, compression, requêtes avec
  query string et corps supérieurs à 16 Kio, y compris sans Content-Length. Le
  gateway ajoute une limite de taille et de fréquence dédiée. Son adresse vue
  derrière le proxy est partagée : ce plafond est celui du premier essai, à
  mesurer et dimensionner pour les vingt agents.

`COMMUNICATIONS_MODE=controlled_test` exige un profil privé complet via
`VOICE_TEST_PROFILE_FILE`, lié exactement à APP_ORIGIN, à l'environnement staging
et au rôle runtime. Les modes généraux `live` et `production` restent refusés. Le
fichier accepte seulement un propriétaire root/runtime, sans accès aux autres
et sans liens ; son montage en lecture seule est requis. Seuls l'API et le worker
Voice dédié recevront ce profil, dans leurs propres processus ;
le migrateur, les imports et leurs workers restent en `disabled`. Aucun secret
réel n'est monté par cette livraison.

## Récupération après notification perdue

`backend/app/telephony/reconciliation.py` prépare le worker dédié
`python -m app.telephony.reconciliation`. Son rôle est uniquement de consulter
Twilio pour les intentions déjà consommées, âgées d'au moins vingt secondes.
Une réservation sans appel autorisé ne peut pas être consommée par ce worker.
La réservation durable reste la source de reprise après un arrêt du processus.

- La lecture est limitée au compte configuré, à un parent déjà lié, à la liste
  de ses enfants et à l'enfant attendu. GET seulement, origine Twilio fixe,
  certificat TLS vérifié, aucun suivi de redirection et réponse limitée à 64 Kio.
  Les lectures ont un délai maximal de cinq secondes chacune. Les URL présentes
  dans une réponse ne sont jamais suivies.
- Chaque enfant doit appartenir au parent, au CallerID et au destinataire figés,
  avec direction `outbound-dial`. Le parent doit correspondre à l'identité SDK
  originale. Une page incomplète ou plusieurs enfants imposent une vérification.
  Un enfant déjà lié est relu directement même s'il manque dans la liste.
- La réservation n'est libérée que si le parent et tout enfant attendu sont
  terminés. Une réponse 404, 429, une coupure, une identité différente ou un état
  encore actif conserve la réservation. Il n'existe aucun repli vers une
  expiration locale d'un appel consommé.
- Le réseau est consulté hors transaction PostgreSQL. À la réception du résultat,
  une nouvelle transaction verrouille et vérifie l'intention. Un enfant associé
  entre-temps invalide une observation qui ne le connaissait pas ; un webhook
  ayant déjà terminé l'appel garde son autorité. Deux workers peuvent lire le
  même appel, mais un seul applique sa récupération.
- Les événements de rapprochement sont dédoublonnés sur les états observés, sans
  répéter une ligne d'historique à chaque passage inchangé. Les compteurs et codes
  d'échec sont bornés et expurgés : aucun numéro, secret ou corps Twilio dans les
  journaux. Les métadonnées de conversation restent dans PostgreSQL.

Le processus est séparé des workers d'import et de l'API. Il traite au plus vingt
intentions par passage avec quatre lectures concurrentes maximum, puis attend
dix secondes. Un heartbeat est écrit seulement après un passage sans échec ; le
contrôle d'exploitation doit tenir compte du temps maximal d'un lot. Ces bornes
ne prouvent pas une capacité audio ni le délai de connexion de vingt agents.

Le service n'est pas ajouté aux déploiements actuels. Son raccordement exige le
profil privé et une sortie réseau explicitement limitée au fournisseur, sans
retirer le blocage WAN des conteneurs existants. Il devra fonctionner avant
d'armer le premier appel réel. Les tests utilisent des réponses synthétiques et
un vrai PostgreSQL jetable ; aucun appel réel n'a été interrogé ou relancé.

## Ordre de déploiement

1. Déployer la version de compatibilité main
   `6e2c3c97a418f3bebde690f0c206e90ccbebfa6c` après Foundation CI réussi. Elle reste
   sur le schéma 6, accepte aussi le futur schéma 7 et ne modifie aucune donnée.
2. Vérifier sur le serveur cette révision et `communications=disabled`. Préparer
   le déployeur et le gateway depuis les fichiers revus. Le déployeur du schéma 7
   refuse une migration depuis une version qui n'accepte pas son retour arrière.
3. Intégrer et déployer cette branche via l'image attestée. La migration 7 est
   additive, et le retour à la version de compatibilité conserve toutes les
   données, y compris les nouvelles réservations et métadonnées. Aucun downgrade.
4. Préparer la SharedKey/règle limitée au nouveau préfixe, tester sa signature,
   puis exposer uniquement les routes POST précises au travers de BasicAuth.
   Armer un profil réel est une opération distincte, après raccordement et
   vérification de l'interface, des notifications et du rapprochement.

Les tests HTTP/PostgreSQL utilisent une base jetable, des profils et signatures
synthétiques et un serveur local dans un processus séparé. Ils n'activent pas le
profil réel du conteneur déployé et ne prouvent ni l'acceptation du jeton par Twilio
ni l'audio. L'application existante n'est jamais utilisée comme base de test.

## Informations nécessaires avant l'essai réel

Le 29 octobre 2026, l'utilisatrice a désigné le téléphone d'Omar comme destinataire
de l'essai et confirmé que le compte sert uniquement à Unlimited Talks. Le numéro
complet autorisé est conservé dans le plan privé du serveur, pas dans ce dépôt.
Une lecture fournisseur avec les identifiants déjà configurés pour l'ancienne
application a confirmé l'existence de son application TwiML et de son numéro.
Le compte correspond à celui du numéro réservé aux tests ; les deux numéros sont
distincts. Cette lecture ne prouve pas un appel actuel ni l'état du serveur ancien.

1. Utiliser uniquement le destinataire de test confirmé. Aucun numéro de la
   base importée ne sert au test. Son pays doit être permis dans le compte retenu.
2. Conserver le compte Unlimited Talks confirmé. Une clé Standard peut
   signer les jetons SDK mais possède des droits plus larges qu'une clé Restricted.
   Créer une clé distincte et une nouvelle application TwiML pour la nouvelle
   version ; préserver les identifiants, l'application et les routes de l'ancienne.
   Si d'autres services sont ajoutés, préférer un sous-compte dédié. Vérifier alors ses
   propres limites, numéros et capacités ; ne pas supposer qu'il hérite des 5 CPS.
3. Préparer la clé Standard US1 et l'application TwiML dans ce compte, puis une
   SharedKey de webhook et une règle limitée exactement au nouveau préfixe URL.
   Ne pas appliquer une règle DEFAULT à tout le compte. Stockage privé, saisie
   invisible, aucune valeur secrète dans le chat, Git ou navigateur.

La clé actuelle en lecture seule et le mot de passe SIP ne satisfont pas ces
besoins. Aucun déplacement de numéro vers un autre compte ne doit être fait sans
vérification préalable de son usage et de son routage. La validation statique du
profil ne prouve pas l'appartenance de la clé, du numéro ou de l'application : un
contrôle fournisseur et l'appel réel devront confirmer ces associations.

### Saisie de la clé Voice

`scripts/twilio_voice_preflight.py` réutilise les contrôles de fichiers privés de
`staging_twilio_preflight.py`. Les deux fichiers doivent être installés côte à côte
dans un dossier root privé. Les actions sont séparées :

- `plan` reçoit sur l'entrée standard uniquement le destinataire autorisé et
  l'origine HTTPS ; il lie le plan au compte et au numéro déjà configurés. Il
  refuse de remplacer un plan existant. L'origine actuelle est bornée au domaine
  de la nouvelle application ; un changement de domaine demande une revue du code.
- `store` demande invisiblement le SID SK et le secret de la nouvelle clé Standard
  US1, avec confirmation. Il refuse la clé Restricted déjà configurée et tout
  remplacement. Le fichier root 600 reste hors des conteneurs et du dépôt.
- `check` fait seulement un GET du numéro PN sélectionné avec la nouvelle clé,
  sans redirection. La réponse vérifie compte, numéro et capacité voix ; le rapport
  masque les secrets et numéros complets. Il ne prétend pas vérifier le type
  Standard, l'acceptation d'un jeton SDK ou un appel. Une clé Restricted dotée du
  droit de lecture pourrait aussi réussir ce GET : choisir Standard en console
  reste nécessaire, puis prouver l'acceptation SDK lors de l'essai contrôlé.

Ces actions ne créent aucune application TwiML ni SharedKey, ne modifient aucun
routage et n'activent aucun appel. Ne pas réutiliser les clés de l'ancienne version.

### Provisionnement de l'application TwiML

`scripts/twilio_voice_application.py`, installé avec les deux outils précédents,
sépare `prepare`, `apply` et `check`. Le nom est `unlimited-talk-voice`, sans suffixe
d'environnement. VoiceUrl et StatusCallback utilisent les deux routes fixes
ci-dessus, en POST. CNAM payant et connexion publique depuis d'autres comptes
sont désactivés ; aucune route SMS ni repli vers l'ancienne application.

`prepare` lit l'inventaire du compte, vérifie le numéro de test et refuse un nom
déjà occupé. Il conserve dans un journal root 600 les empreintes de toutes les
propriétés des applications et numéros existants, hormis les dates. `apply` écrit
et synchronise l'état `requested` avant l'unique POST de création autorisé. Une
réponse perdue laisse ce résultat incertain ; les invocations suivantes font
uniquement un rapprochement en lecture, sans deuxième création. Un nom ambigu,
une modification concurrente ou une configuration différente impose une revue.

La vérification relit la nouvelle application par son SID, vérifie ses paramètres
et compare toutes les ressources précédentes. Aucun endpoint d'appel, modification
de numéro ou modification d'application existante n'est autorisé par le transport.
Un verrou exclusif protège les exécutions concurrentes ; les journaux sont écrits
par remplacement atomique et synchronisation disque. Le SID AP vérifié reste dans
`/etc/unlimited-talk-staging/twilio-voice-application.json`, hors du dépôt.

La création du conteneur de configuration TwiML ne prouve pas les webhooks, une
SharedKey, les jetons SDK ni l'audio. Aucune règle de signature n'a encore été
appliquée. Le service durable et les routes publiques signées devront être livrés
avant de distribuer un jeton réel ou de permettre un appel.

## Livraison de bout en bout à réaliser

1. Déployer le schéma et l'API préparés ci-dessus dans l'ordre de compatibilité,
   puis vérifier le profil et la règle de signature réels.
2. Raccorder le worker de rapprochement préparé et sa sortie WAN bornée avant
   d'armer le premier appel. Une intention au résultat incertain ne s'expire pas.
3. Exposer uniquement les POST précis au travers de BasicAuth après test de la
   signature ; conserver MFA/permissions sur toutes les opérations humaines.
4. Interface française : préparation du casque, appel, état réel, raccrochage et
   erreurs lisibles. Mettre à jour CSP et Permissions-Policy selon les domaines
   du SDK et tester depuis les réseaux réels. Ne pas désactiver globalement CSP.
5. Événements dupliqués, tardifs et désordonnés : progression monotone de l'appel,
   aucun retour d'un état terminal à un état actif ; rapprochement après coupure.
6. Archivage durable : charger le recording par SID attendu depuis les endpoints
   Twilio autorisés, jamais une URL arbitraire du formulaire. Vérifier métadonnées,
   deux canaux et copie privée avant suppression du fournisseur. Reprise après
   échec d'upload et contrôle de lecture agent/admin ; aucun lien fournisseur public.
7. Enchaînement, campagnes et rappels seulement après cette preuve : réservations
   canoniques globales, pas de doublon entre campagnes, deux tentatives/jour local,
   intervalle de deux heures, plages de campagne, exclusions et rappels attribués.
   Pause/arrêt, changement de campagne et formulaire RDV doivent arbitrer l'état
   réel de l'agent avant chaque lancement ; un RDV non sauvegardé conserve l'attente.
8. Monter progressivement jusqu'à vingt agents avec médias réels, pannes,
   raccrochages et enregistrements. Mesurer délai entre conversations, délai de
   connexion après réponse, taux de réponse, erreurs et coût. Aucun test simulé
   de cette livraison ne prouve la capacité ou la qualité audio.

Le réseau des conteneurs bloque actuellement les sorties WAN arbitraires. Les
flux fournisseur nécessaires devront passer par une sortie explicitement bornée,
avec vérification TLS. La nouvelle configuration des webhooks et des secrets doit
être prête avant toute ouverture. L'interface ne doit pas proposer de bouton
fonctionnel tant que ces prérequis et la réservation durable ne sont pas validés.

## CPS et attente des agents

La console du compte consulté indique 5 CPS. Cela concerne les appels créés par
l'API REST ; les appels `<Dial>` et entrants ne partagent pas cette limitation.
Le premier essai navigateur/TwiML ne démontre donc pas la capacité de lancement
d'un composeur REST à vingt agents. Ni 5 CPS, ni vingt comptes utilisateurs ne
prouvent vingt conversations ni une attente minimale. Ne pas engager une nouvelle
augmentation payante sans vérifier le compte, son tarif et le parcours final.

Le taux de réponse et la durée des conversations déterminent les besoins de
lancement. L'AMD peut introduire un délai ou classer une personne à tort. Son mode
et ses seuils devront être mesurés ; aucun objectif de zéro attente n'est promis.

## Références officielles

- [Voice SDK](https://www.twilio.com/docs/voice/sdks/javascript).
- [Applications TwiML](https://www.twilio.com/docs/usage/api/applications).
- [Notifications d'enregistrement Dial](https://www.twilio.com/docs/voice/twiml/dial#recordingstatuscallback).
- [Jetons SDK : clés Main/Standard, pas Restricted](https://www.twilio.com/docs/iam/access-tokens).
- [Signatures dédiées SharedKey](https://www.twilio.com/docs/usage/webhooks/webhook-shared-keys).
- [Validation des notifications](https://www.twilio.com/docs/usage/webhooks/webhooks-security).
- [CPS et Calls API](https://www.twilio.com/docs/voice/api/call-resource).
- [Détection des répondeurs](https://www.twilio.com/docs/voice/answering-machine-detection).

La correction d'espacement des boutons du contact est livrée dans la révision
`90e3cfc58a7a216cc79307c990e1440e14756fba`, avec l'API contrôlée.
