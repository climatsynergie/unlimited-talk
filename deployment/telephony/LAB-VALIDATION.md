# Validation locale de l'image téléphonique

28 octobre 2026. Ce rapport décrit des essais réels dans QEMU/KVM, sans serveur
payant, sans modification du CRM et sans appel. Une validation locale ne constitue
pas une validation DigitalOcean, de VICIdial en cluster ou de capacité téléphonique.

## Résultat et décision

Le démarrage BIOS du disque officiel ViciBox 13 candidate est confirmé. Après
ajout de cloud-init et préparation du modèle, deux clones ConfigDrive v2 démarrent
avec accès SSH par clé et identités distinctes. Le choix du moteur reste **non
approuvé pour la production** : le paquet Asterisk inclus est en branche 18 et
aucun engagement de maintenance de sécurité de cette branche par VICIdial n'a
été établi. La publication stable de ViciBox 13 n'est pas encore constatée.

## Origine contrôlée

- ISO officielle : `ViciBox_V13.x86_64-13.0.0-beta4.iso`, 2 672 447 488 octets.
- MD5 publié, vérifié : `b4fcb7e185e6b05f8f0159980bd686be`.
- SHA-256 calculé : `b39edd9958f6c1a47772c53b008a9b4e67b2ac1bd58ff41761c2098b44d5239f`.
- Le SquashFS de cette ISO contient un disque brut de 21 474 836 480 octets.
- SHA-256 du disque brut, vérifié contre le contrôle interne fourni :
  `01a90c9442d88cf97eeef9daeec7977f064e24329624449e8b6f1d7aa6a82df2`.

Le disque installé fourni par l'éditeur a été extrait et utilisé comme fichier
de base, sans exécuter l'installeur sur un disque de l'hôte. Les modifications du
modèle et des essais se font dans des overlays. Le SHA-256 calculé du disque
brut correspond au contrôle embarqué. Le MD5 et le téléchargement HTTPS ne
constituent pas une signature cryptographique indépendante de l'éditeur.

## Vérifications réellement exécutées

| Contrôle | Résultat |
| --- | --- |
| Virtualisation matérielle KVM et démarrage BIOS | Réussite |
| Système réellement démarré | openSUSE Leap 16.0 / ViciBox 13.0 candidate |
| Système de fichiers racine | ext4 |
| Accès SSH du modèle de construction | Boucle locale uniquement |
| cloud-init dans l'image officielle | Absent ; ajouté depuis le dépôt signé openSUSE |
| cloud-init installé | 25.1.3-160000.3.1 |
| Clones A et B avec ConfigDrive v2 | Deux démarrages réussis, cloud-init terminé sans erreur |
| Utilisateur `utops` créé, clé injectée depuis les métadonnées | Réussite sur les deux clones |
| Mot de passe root et mot de passe administrateur | Verrouillés sur les deux clones |
| Authentification SSH par mot de passe / clavier interactif | Désactivée sur les deux clones |
| Connexion SSH root | Désactivée sur les deux clones |
| Identités système et clés d'hôte SSH | Différentes entre A et B |
| Clé de connexion de A présentée à B | Refusée ; la clé propre à B fonctionne |
| Services téléphoniques, Apache et MariaDB dans le modèle | Désactivés ; rôles non installés/configurés |
| Démarrage DigitalOcean / réseau VPC réel | Non testé |
| Authentification SIP / audio / appels / archivage | Non testé |
| Vingt agents et numérotation automatique | Non testé |

Le réseau QEMU est restreint. Seul SSH est redirigé vers `127.0.0.1` sur l'hôte.
L'installation des paquets utilise un relais HTTPS limité aux dépôts officiels,
via un tunnel SSH local temporaire. Le dépôt autorisé a répondu ; une destination
non autorisée a été refusée. Aucun identifiant ou contact du CRM, ni secret
Twilio, n'a été copié dans la VM. Chaque essai utilise une clé de laboratoire
séparée, absente du modèle scellé.

## Export autonome vérifié

L'artefact de laboratoire `unlimited-talk-vicibox13-beta4-cloud-lab.qcow2` est
conservé hors Git dans le répertoire privé de construction. Son
[manifeste d'export](lab-export-manifest.json) contient les contrôles suivants :

- Fichier qcow2 autonome de 2 771 845 120 octets, disque virtuel de 20 Gio,
  compression zlib, sans fichier de base externe.
- SHA-256 : `8f11f7f63588d1d27ac9af000ffcadd93179107a64aadfa2a9564ee348265bf6`.
- `qemu-img check` : aucune erreur de cohérence ou corruption signalée.
- `qemu-img compare` : contenu identique au modèle scellé utilisé pour les clones.
- Copie persistante vérifiée contre l'empreinte de l'export temporaire.

L'export provient du modèle scellé avant injection des métadonnées des clones A
et B. Ces clones et leurs clés privées temporaires ont été supprimés après
validation. Les VM et le relais logiciel temporaire sont arrêtés ; le disque de
travail dispose de nouveau d'environ 8,2 Gio libres. L'image est une pièce de
laboratoire, **pas une autorisation de déploiement en production**.

## Versions observées et réserve sur Asterisk

Inventaire extrait du système effectivement démarré :

| Paquet | Version |
| --- | --- |
| Asterisk | 18.26.4-lp160.11.35 |
| PHP | 8.4.27-160000.1.1 |
| MariaDB | 11.8.8-160000.1.1 |
| OpenSSH serveur | 10.0p2-160000.7.1 |
| NetworkManager | 1.52.0-160000.5.1 |

[Asterisk annonce la fin du support de la branche 18 depuis octobre 2025](https://www.asterisk.org/asterisk-18-now-end-of-life-asterisk-21-security-fix-only/).
Le paquet observé provient du dépôt VICIdial sur openSUSE Build Service. Son
journal installé contient des changements de compilation/performance en septembre
2026. Cela prouve une activité sur le paquet, pas une politique de correction des
vulnérabilités après la fin du support amont. Ne pas conclure automatiquement que
le fournisseur n'applique aucun correctif ; sa couverture doit être établie.

Attendre uniquement la sortie stable de ViciBox 13 ne résout pas à lui seul ce
point. Ne pas remplacer Asterisk par une version plus récente sans preuve de
compatibilité avec la révision VICIdial, PJSIP, ConfBridge, MixMonitor, WebRTC,
AMI, AMD et le contrôle CRM avant chaque numérotation.

## Question technique prête pour le mainteneur

Ce texte est un brouillon ; aucun message n'a été envoyé :

> We are preparing a new VICIdial deployment for 20 agents, using Twilio Elastic
> SIP Trunking with TLS/SRTP, browser audio, PJSIP/ConfBridge and call recording.
> Our CRM remains the business authority and requires a fail-closed gate before
> every origination. The official ViciBox 13 beta4 image we tested contains
> asterisk-18.26.4-lp160.11.35. Can you confirm the supported engine/version and
> VICIdial revision for this new deployment? If Asterisk 18 is required, please
> provide the security-backport policy, supported period and patch provenance.
> If a maintained Asterisk 22 deployment is supported, please identify the tested
> packages, required patches and upgrade/support path. We also need confirmation
> of a supported DigitalOcean custom-image installation and API integration path.

La décision suivante est de vérifier cette maintenance ou une combinaison plus
récente prise en charge. Ne pas engager les deux serveurs définitifs avant ce
choix. Les essais cloud d'une image candidate devront rester isolés et ne pas
charger les contacts clients.

## Reproduction et pièces de preuve

Les [scripts du modèle](image/README.md) documentent les modifications cloud-init
et SSH. Les scripts ajoutent également des refus explicites pour un hôte déjà
initialisé ou des services téléphoniques actifs. Ces garde-fous ont été vérifiés
syntaxiquement ; le comportement du modèle est vérifié par les deux démarrages
réels décrits ci-dessus. Aucun essai de numérotation n'est simulé comme un appel
réel réussi.

Les manifestes ISO, disque brut, clones et export sont conservés dans le
répertoire privé de construction `/home/codexdev/unlimited-talk-image-lab`.
L'image et les clés privées sont hors du dépôt Git. Le manifeste d'export précisera
son empreinte, son contrôle de cohérence et l'absence de fichier de base externe.

Références : [ViciBox officiel](https://www.vicibox.com/server/),
[ConfigDrive cloud-init](https://docs.cloud-init.io/en/latest/reference/datasources/configdrive.html),
[exigences d'image DigitalOcean](https://docs.digitalocean.com/products/custom-images/how-to/upload/).
