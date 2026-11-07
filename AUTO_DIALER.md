# Composeur et numéros émetteurs

Le schéma `0010_dialer` ajoute l’enchaînement progressif des appels : un seul appel
actif par agent, lancé par son navigateur connecté. Un administrateur configure
les campagnes ; chaque agent démarre explicitement son composeur. Aucun appel ne
part uniquement parce qu’un rappel devient dû ou qu’un worker redémarre.

## Parcours administrateur

Dans **Campagnes → Téléphonie de la campagne**, ou **Poste d’appel → Régler la
 téléphonie**, choisir un numéro vérifié et enregistrer. Cet enregistrement active
le composeur de la campagne. L’interface ne demande ni plage horaire ni règle
régionale : un numéro suffit. Les appels partent uniquement quand l’agent démarre
son composeur et s’arrêtent après sa pause ou son arrêt.

Le catalogue provient du compte Twilio configuré, sans achat ni modification de
routage fournisseur. Une liste ancienne est renouvelée par le worker. Les anciens
réglages avancés restent lisibles par l’API pour compatibilité ; enregistrer depuis
le formulaire simple retire leurs horaires et règles de cette campagne.

La sélection d’un numéro vérifié est un réglage courant d’administrateur. Elle
requiert la session individuelle, la MFA déjà validée, l’origine et la protection
CSRF, sans imposer une nouvelle connexion après quinze minutes. Les opérations
sensibles sur les identités et les accès conservent leur réauthentification.

## Parcours agent

Dans **Poste d’appel**, choisir une campagne attribuée puis **Démarrer les appels**.
Le microphone est demandé sur ce clic. Le composeur donne priorité aux rappels dus
de cet agent dans toutes ses campagnes attribuées, en conservant la campagne et la
règle de numéro du rappel. Les autres contacts suivent la file de la campagne
sélectionnée. Les rendez-vous futurs et contacts réservés pour un rappel sont
exclus de la file ordinaire.

**Mettre en pause** et **Arrêter l’enchaînement** empêchent le prochain appel ;
la conversation déjà autorisée continue. **Raccrocher** termine le média actuel.
Le résultat serveur doit confirmer la fin avant un nouvel appel. Après chaque
appel automatique, un compte à rebours de dix secondes précède la réservation
du contact suivant. Le bandeau reste visible pendant la navigation interne.
Son bouton rouge **Attendre** met l’enchaînement en pause sans réserver le contact
suivant ; l’agent peut compléter la fiche ou rappeler manuellement, puis utiliser
**Reprendre les appels**. Sans clic, le composeur continue à la fin du délai.
Le premier appel et une reprise explicite ne demandent pas ce délai.

Le clic de prise de rendez-vous suspend aussi le composeur et le classement
automatique pendant la saisie ; enregistrer ou annuler la saisie rend la main au composeur seulement s’il
était actif auparavant et n’a pas été mis en pause entre-temps.

La navigation interne conserve le téléphone. Un rechargement, une session expirée,
une présence serveur périmée ou une erreur média demande une reprise explicite.
Une erreur réseau isolée déclenche une nouvelle vérification sans nouvel appel.
Trois échecs consécutifs suspendent l’enchaînement ; un refus de session ou de
contrôle (401/403/409) le suspend immédiatement. Une vérification réussie remet
le compteur à zéro. Le bail serveur de 90 secondes continue à faire autorité.
Les fenêtres concurrentes ne peuvent pas contrôler simultanément le même agent.

Les restrictions globales, l’attribution et le propriétaire/date du
rappel sont revérifiés au moment de l’autorisation signée. Un numéro destinataire
utilise par défaut deux tentatives de prospection par jour local, espacées
de deux heures. L’administrateur peut régler ces valeurs par campagne dans
**Tentatives et sonnerie** : 1–20 tentatives, 0–1440 minutes entre tentatives,
15–60 secondes de sonnerie (35 par défaut, également en manuel dans la campagne).
Les appels au même numéro restent comptés ensemble, même en changeant de campagne.
Une tentative de rappel explicitement programmé bénéficie d’une priorité à son
échéance, sans délai ni quota de prospection. L’exemption est unique par version
de rappel : un résultat fournisseur incertain ne crée pas de boucle de relance.
Une reprogrammation explicite crée une nouvelle version. Un appel manuel
explicite reste possible sans délai ni quota automatique. Les restrictions
du contact, le propriétaire d’un rappel et l’exclusion des appels simultanés restent
vérifiés. Le premier fuseau enregistré
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

Les paramètres supplémentaires sont conservés dans l’événement immuable et
indexé `calling.settings_changed`, dans la même transaction que la version des
réglages. Le formulaire, la sélection SQL des candidats et l’autorisation finale
utilisent cette projection. Les événements précédents héritent des valeurs par
défaut ; les anciens formulaires préservent les paramètres qu’ils ne connaissent
pas. Aucun changement de schéma n’est nécessaire.

La vérification des numéros se renouvelle toutes les cinq minutes. Dès douze
heures de retard, l’administration affiche une alerte. Les réessais automatiques
respectent le Retry-After fournisseur (entre dix secondes et une heure), avec
une minute par défaut. Une panne de disponibilité du fournisseur
peut accorder au numéro déjà vérifié une continuité jusqu’à 48 heures depuis sa
dernière vérification. Un numéro retiré, désactivé, jamais vérifié ou une erreur
d’authentification ne bénéficie pas de cette continuité.

La fiche de l’appel courant reste toujours affichée en premier. Une note ou un
formulaire précédent non terminé reste dans une section repliable liée à son
appel ; il ne retient plus l’affichage sur l’ancien client. Sans rendez-vous ni
autre saisie à conserver, la qualification repart sur le contact suivant.

Une confirmation « Non intéressé » ou « Ne pas contacter » peut suivre la seule
mise à jour automatique de fin du même appel sans second clic. Le serveur vérifie
l’agent, la campagne, le contact et les versions de réservation et de classement
figées dans cet appel. Un changement humain intervenu depuis conserve la priorité :
la fiche se recharge et une nouvelle confirmation explicite est requise. Les
anciennes requêtes sans contexte d’appel conservent leur garde de version strict.

## Déploiements courants

Terminer les appels et mettre les composeurs en pause, puis utiliser **Deploy
staging** avec le SHA main validé par Foundation CI. Le déployeur ferme brièvement
l’admission et rétablit l’état d’appel précédent après contrôle de santé. Une
fermeture volontaire par administrateur reste respectée ; ne pas exécuter
manuellement `disable` comme étape habituelle du déploiement.

## Mise en place initiale (historique)

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
6. Choisir le numéro de chaque campagne dans l’interface, puis faire l’acceptation
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
