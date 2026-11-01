# Composeur et numéros émetteurs

Le schéma `0010_dialer` ajoute l’enchaînement progressif des appels : un seul appel
actif par agent, lancé par son navigateur connecté. Un administrateur configure
les campagnes ; chaque agent démarre explicitement son composeur. Aucun appel ne
part uniquement parce qu’un rappel devient dû ou qu’un worker redémarre.

## Parcours administrateur

Dans **Campagnes → Téléphonie de la campagne**, ou **Poste d’appel → Régler la
téléphonie**, synchroniser les numéros Twilio, choisir le numéro par défaut et les
horaires dans le fuseau de la campagne. Activer le composeur et enregistrer.
Les numéros affichés proviennent exclusivement de l’inventaire Voice du compte
Twilio configuré. Cette synchronisation ne modifie ni numéro ni routage Twilio.

Ajouter éventuellement des règles par pays ISO (`CA`, `GB`) et/ou préfixe
international (`+1514`, `+44`). Le préfixe correspondant le plus long prime, puis
le pays le plus précis. Sans règle correspondante, le numéro par défaut est utilisé.
Une règle dont le numéro est devenu indisponible bloque cet appel plutôt que de
substituer silencieusement une autre identité. La vérification expire après 24 h ;
le worker tente de renouveler le catalogue toutes les cinq minutes.

## Parcours agent

Dans **Poste d’appel**, choisir une campagne attribuée puis **Démarrer les appels**.
Le microphone est demandé sur ce clic. Le composeur donne priorité aux rappels dus
de cet agent dans toutes ses campagnes attribuées, en conservant la campagne et la
règle de numéro du rappel. Les autres contacts suivent la file de la campagne
sélectionnée. Les rendez-vous futurs et contacts réservés pour un rappel sont
exclus de la file ordinaire.

**Mettre en pause** et **Arrêter l’enchaînement** empêchent le prochain appel ;
la conversation déjà autorisée continue. **Raccrocher** termine le média actuel.
Le résultat serveur doit confirmer la fin avant un nouvel appel. Le clic de prise
de rendez-vous suspend aussi le composeur et le classement automatique pendant la
saisie ; enregistrer ou annuler la saisie rend la main au composeur seulement s’il
était actif auparavant et n’a pas été mis en pause entre-temps.

La navigation interne conserve le téléphone. Un rechargement, une session expirée,
une présence serveur périmée ou une erreur média demande une reprise explicite.
Les fenêtres concurrentes ne peuvent pas contrôler simultanément le même agent.

Les restrictions globales, l’attribution, les horaires et le propriétaire/date du
rappel sont revérifiés au moment de l’autorisation signée. Un numéro destinataire
ne peut recevoir que deux tentatives autorisées par jour local, espacées d’au
moins deux heures, même en changeant de campagne. Le premier fuseau enregistré
pour ce numéro reste la référence du quota. Les réservations annulées avant
autorisation ne comptent pas comme tentatives.

## Résultats et historique

Les résultats signés et rapprochés alimentent une boîte de travaux durable dans
PostgreSQL. **Pas de réponse** et **occupé** classent en « Pas de réponse » ; sans
autre choix de l’agent, les autres résultats classent en « Autre ». Le contact
retourne en fin de file, y compris si l’étape était déjà identique. Une nouvelle
décision humaine, un rendez-vous, une restriction ou un rappel reprogrammé prime
sur un événement fournisseur retardé. Un rappel devient traité après un véritable
résultat terminal de sa branche d’appel, avec le propriétaire et la version attendus.
Une simple réservation ne le traite pas.

Le destinataire, le numéro émetteur, la campagne, le contact, le rappel éventuel et
la session sont figés dans la réservation. Le navigateur transmet uniquement son
identifiant au SDK. Les règles modifiées ultérieurement ne réécrivent pas les appels
historiques. Les archives privées et permissions de lecture restent appliquées.

## Déploiement

1. Déployer par le workflow attesté la compatibilité
   `c59c839937eaa96b2d42c055c0efd82027d26070` et constater sa santé au schéma 9.
   Elle sait servir le CRM au schéma 10 en maintenant les appels fermés lors d’un
   retour arrière.
2. Installer le déployeur hôte revu comprenant le garde de migration 10. Fermer
   les appels et attendre zéro appel actif avant la migration.
3. Déployer l’image du composeur uniquement après CI, publication et attestation
   du SHA exact. La migration est additive et ne crée aucune règle ni faux numéro.
4. Installer l’outil hôte `prepare_voice_runtime.py` revu puis exécuter
   `upgrade-directory-gateway`. Cela ajoute uniquement le GET paginé
   `IncomingPhoneNumbers` du compte prévu à la passerelle privée existante ; les
   autres ressources/méthodes restent refusées. Validation Caddy et sauvegarde
   précèdent le rechargement, avec restauration en cas d’échec.
5. Employer l’opérateur `control_manual_voice.py` du schéma 10 avec la révision
   réellement active : `prepare`, `check`, `public-access`, `enable`. Le catalogue
   vérifié et l’identité principale sont exigés avant l’ouverture des appels.
6. Configurer les numéros et horaires dans l’interface, puis faire l’acceptation
   avec trois agents, trois casques et des destinataires disponibles.

L’opérateur ne lance pas de conversation et ne contourne pas la chaîne attestée.
Un retour arrière applicatif conserve le schéma et les données ; il faut fermer
les appels et résoudre les conversations/archives avant toute restauration.

## Vérification et limites

Les tests locaux/CI couvrent la migration de données existantes, les quotas entre
campagnes, les numéros régionaux, les claims de trois agents, les courses
pause/autorisation, les rappels reprogrammés, les décisions humaines, la présence,
les rendez-vous pendant appel et les parcours navigateur. Les tests ne composent
aucun numéro réel. Ils ne prouvent ni l’audio PSTN, ni la livraison des
enregistrements réels, ni la capacité média de vingt agents.

Il s’agit d’un composeur progressif : une ligne par agent. La détection de répondeur,
la numérotation prédictive, la réception audio et la messagerie vocale restent des
lots distincts. Les SMS sont exclus à la demande de l’utilisateur.
