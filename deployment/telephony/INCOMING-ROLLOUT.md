# Réception des appels et classements agents

La livraison de compatibilité `662b450501a70431b0effbb087501e727111099d` conserve la migration `0011_long_recordings`.
Elle contient l’intégralité du futur runtime entrant, mais les nouvelles commandes
ne peuvent recevoir de média avant la migration additive et la connexion d’une
ligne. Les fonctions « Boîte vocale » et « Parle anglais » fonctionnent sur le
schéma 11 et ne nécessitent aucune modification des routes Twilio existantes.

## Fonctions agents et rapports

« Boîte vocale », à côté de « Raccrocher », ferme immédiatement le média et
journalise une seule disposition pour l’appel et la session de l’agent. Une
confirmation perdue est réessayée sans doubler les compteurs. Un échec persistant
est visible et suspend l’enchaînement ; la reprise de l’enregistrement vise
l’identifiant de l’ancien appel, jamais le nouvel interlocuteur. Les appels
marqués sont comptés dans « Boîtes vocales » et retirés des décrochés clients,
durées connues et moyennes du dashboard et de l’Excel. Il s’agit d’un classement
manuel, pas d’une détection automatique des répondeurs.

« Parle anglais » conserve le contact et l’historique, marque son origine par
l’étape Anglais et l’inscrit une seule fois dans Contacts anglophones. Un admin
attribue les agents anglophones à cette campagne. L’enchaînement des campagnes
francophones exclut ces contacts ; les appels manuels restent soumis au statut
Ne pas contacter. Les RDV/rappels futurs et restrictions existants sont protégés.

## Déploiement en deux livraisons

1. Publier, attendre Foundation CI (image testée + attestation), puis déployer la
   livraison de compatibilité sur le SHA exact de main. Vérifier la révision
   réellement servie et les étiquettes `schema12-compatible=1` et
   `incoming-runtime=1` et `incoming-recovery=1`. Ne pas avancer main vers la seconde livraison avant
   d’avoir déployé celle-ci : Deploy staging exige le SHA actuel de main.
2. Cette seconde livraison place le fichier revu dans
   `backend/migrations/versions/0012_incoming_runtime.py` et porte l’étiquette
   Docker à 12. Les preuves CI couvrent la migration de données existantes et le
   repli sur l’image exacte de compatibilité ci-dessus. Publier,
   tester et déployer par le même workflow ; aucune DDL manuelle sur la base.
3. Avant cette seconde livraison, installer les opérateurs root revus
   `deploy_staging.py`, `control_manual_voice.py`, `resume_managed_runtime.py`,
   `prepare_voice_runtime.py`, `connect_incoming_line.py` avec leurs dépendances
   root déjà installées. Sauvegarder les anciennes versions, vérifier leurs
   empreintes et compiler. Le déployeur refuse la migration sans runtime de
   repli complet et refuse le remplacement pendant un appel entrant, y compris
   l’attente ou un message vocal en cours. Le retour automatique au runtime de
   compatibilité ne relance pas Alembic et ne rétrograde jamais les données.
4. Exécuter `prepare_voice_runtime.py upgrade-incoming-gateway` : extension
   additive des GET privés à 21 branches maximum et à l’audio mono. La validation
   Caddy et le retour au fragment précédent en cas d’échec précèdent tout
   changement public. Les GET sortants déjà autorisés restent identiques ; cet
   opérateur ne change pas le mode d’appel.
5. Lire les files et les routes actuelles, puis choisir la ligne destinée à la
   nouvelle application. Exécuter sur le serveur root :

   ```sh
   python3 /root/unlimited-talk-voice-tools/connect_incoming_line.py prepare --revision SHA_DEPLOYE_COMPLET --queue UUID_FILE --number-sid PN_SELECTIONNE
   python3 /root/unlimited-talk-voice-tools/connect_incoming_line.py connect --revision SHA_DEPLOYE_COMPLET --queue UUID_FILE --number-sid PN_SELECTIONNE
   ```

   `prepare` sauvegarde en privé les URL, méthodes, application et trunk de cette
   seule ligne. `connect` vérifie le plan et le runtime de nouveau, marque la
   connexion en cours, modifie cette seule ressource puis confirme le résultat
   par GET avant de rendre la réception disponible aux agents. Une réponse POST
   perdue est résolue par lecture, sans créer d’appel. `restore` restaure le
   snapshot si la route n’a pas été modifiée par un tiers. Aucun SMS, achat,
   appel de test ou modification de la configuration d’un trunk n’est effectué
   par cet opérateur. L’association éventuelle de cette seule ligne à un trunk
   ou à une application est sauvegardée puis remplacée pour permettre le webhook.

## Fonctionnement et validation

Chaque agent attribué ouvre Appels entrants et clique Recevoir les appels.
L’autorisation du microphone et l’enregistrement du téléphone précèdent la
présence disponible. La réception reste ouverte pendant la navigation interne.
Après un rechargement complet, l’agent la rouvre explicitement. Mettre la
réception en pause bloque la prochaine proposition et conserve la conversation
actuelle. Répondre confirme le choix de l’agent avant la connexion audio.

La file propose les appels aux agents disponibles depuis le plus longtemps.
Un agent en appel sortant, déjà sollicité, en prise de RDV ou dans les dix
secondes après une conversation ne reçoit pas un second appel. Le plafond du
compte est partagé entre les appels entrants et sortants. Les offres expirées
ou les pertes de présence ne libèrent jamais une branche dont la fin n’est pas
confirmée par Twilio. Les callbacks signés et le rapprochement GET indépendant
rétablissent l’état après une réponse HTTP perdue.

Sans réponse pendant l’attente configurée, un accueil français permet de laisser
un message de 120 secondes. L’appel crée un suivi dans la file, avec son message
vocal privé lorsqu’il est disponible. L’historique reçu est paginé par 20 appels.
L’audio n’est accessible qu’aux administrateurs, aux agents actuellement attribués
à la file ou à l’agent ayant traité la conversation ; aucun URL fournisseur ou
objet public n’est renvoyé au navigateur. Les appels masqués restent identifiés
comme tels, sans créer de faux numéro.

Les preuves isolées couvrent trois agents, vingt réservations concurrentes,
l’occupation partagée entrant/sortant, les callbacks dupliqués ou incohérents,
le rapprochement après perte de callback, les droits de lecture et l’archivage
mono réel dans le stockage S3 local avec contrôle d’intégrité et lecture Range.
Le test navigateur remplace uniquement le SDK média et ne passe aucun appel
PSTN. Un appel réel entrant depuis un téléphone externe reste nécessaire après
connexion de la ligne pour valider le chemin audio opérateur → casque, puis un
appel sans réponse pour valider le message vocal. Ne pas déclarer cette preuve
réelle acquise à partir des seuls tests synthétiques.
