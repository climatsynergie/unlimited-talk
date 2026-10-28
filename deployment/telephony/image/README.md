# Préparation d'une image de laboratoire

Ces scripts s'exécutent uniquement dans la VM de construction ViciBox vierge,
jamais sur le CRM ni sur un serveur téléphonique en service. Ils ne constituent
pas un installeur de production. La version candidate essayée et Asterisk 18
restent soumis aux réserves du [rapport de validation](../LAB-VALIDATION.md).

La VM doit utiliser un clone d'un disque officiel dont les empreintes ont été
vérifiées. Aucun disque ou secret du CRM, identifiant Twilio ou contact client ne
doit y être attaché. Garder le disque officiel intact comme fichier de base et
utiliser un overlay qcow2 pour la construction. Aucun port d'administration ne
doit être publié sur Internet pendant la préparation.

1. Installer `cloud-init` et `growpart` depuis le dépôt officiel openSUSE Leap 16
   avec contrôle des signatures. La version testée est `25.1.3-160000.3.1`.
   Utiliser un répertoire de dépôts temporaire avec `zypper --reposd-dir` pour ne
   pas modifier les dépôts VICIdial/PHP. Rafraîchir les métadonnées signées ; le
   cache livré dans l'ISO peut référencer des RPM devenus indisponibles.
2. Copier `prepare-template.sh` dans la VM, créer explicitement le marqueur
   `/run/ut-image-build-authorized` dans cette VM uniquement, puis exécuter le
   script en root. Il prépare ConfigDrive/DigitalOcean/NoCloud, NetworkManager,
   l'utilisateur `utops` et l'accès SSH par clé. La clé est fournie par les
   métadonnées au premier démarrage, jamais intégrée au modèle.
3. Copier puis exécuter `seal-template.sh` dans cette même VM. Il remplace le mot
   de passe root par une valeur inutilisable, retire ses clés autorisées ainsi
   que les clés d'hôte, nettoie cloud-init et l'identité système, puis éteint la
   VM. La connexion root de construction n'est plus utilisable après cette étape.
4. Une fois la VM arrêtée, exporter le modèle scellé avec `qemu-img convert -c
   -f qcow2 -O qcow2 MODEL.qcow2 IMAGE.qcow2`. Vérifier avec `qemu-img check`,
   vérifier l'absence de fichier de base externe dans `qemu-img info`, comparer
   le contenu avec `qemu-img compare` et calculer le SHA-256 de l'artefact.
5. Tester deux clones éphémères avec deux ConfigDrive v2 différents et des clés
   publiques différentes. Contrôler cloud-init, les identités, le réseau, SSH et
   le refus de la clé d'un clone par l'autre. Ne pas exporter ces clones : seul
   le modèle scellé, avant lecture de leurs métadonnées, est l'image de référence.

Les garde-fous refusent un système différent de Leap 16, l'absence du marqueur,
une instance cloud déjà initialisée ou des services téléphoniques actifs. Ils
ne remplacent pas la sélection de la bonne VM. Le modèle ne contient pas les
rôles VICIdial installés : leurs IP, secrets et paramètres doivent être créés
par hôte après la validation de la version et du démarrage cloud.

Le compte `utops` a un accès sudo sans mot de passe et doit recevoir uniquement
les clés d'opérateurs autorisés. Les clés privées de test restent hors de Git et
ne font jamais partie de l'image. Les scripts n'installent aucun trunk et ne
permettent aucune numérotation.
