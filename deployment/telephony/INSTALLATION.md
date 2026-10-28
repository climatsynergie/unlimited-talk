# Installation téléphonique Unlimited Talks

Évaluation du 28 octobre 2026. Statut : architecture et procédure préparées,
image installable et démarrage DigitalOcean non validés. Aucun achat, nouvel
hôte, appel ou changement du CRM effectué par cette évaluation.

## Décision proposée

Conserver VICIdial/Asterisk comme moteur unique, sous réserve des preuves de
TELEPHONY.md. Préparer une image ViciBox officielle sur une machine de construction
isolée, puis importer un disque compatible DigitalOcean. Ne pas exécuter un
installeur communautaire non audité sur le serveur du CRM.

ViciBox 13.0.0-beta4 est une candidate, pas une version de production approuvée.
Sa sortie stable est annoncée pour le 31 octobre : vérifier la publication réelle
et les correctifs à la date de construction. Une date annoncée ne constitue pas
une garantie de livraison. La candidate peut servir à une preuve isolée et sans
contacts clients, jamais être implicitement promue vers la production.

ViciBox 12 repose sur Leap 15.6, dont la maintenance communautaire est terminée.
Ne pas le retenir comme nouvelle base sans preuve d'une maintenance alternative
couvrant réellement le système et les composants. Appliquer uniquement les
correctifs PHP ne résout pas ce problème de cycle de vie.

## Topologie cible à chiffrer avant création

| Hôte proposé | Rôles | Point de départ proposé |
| --- | --- | --- |
| ut-dialer-control | Interface/API VICIdial et MariaDB interne | 4 vCPU dédiés, 16 Gio RAM, 500 Gio SSD au total |
| ut-dialer-media | Asterisk, conférences, audio navigateur, enregistrement temporaire | 4 vCPU dédiés, 16 Gio RAM, 500 Gio SSD au total |

Ce sont des enveloppes initiales, pas une capacité certifiée. Le guide de
ViciBox distingue Express (tous les rôles) et cluster ; ses recommandations pour
la téléphonie avec enregistrement justifient de séparer les rôles. La charge
réelle dépend aussi des canaux, du taux de numérotation et de la compression.
Le test de 20 agents reste obligatoire.

Toronto TOR1, réseau privé existant ; noms visibles sans suffixe « staging ».
Les identifiants d'infrastructure existants ne changent pas. Conserver les IP
finales avant la configuration des rôles VICIdial, qui dépend de ces adresses.
MariaDB appartient au moteur ; les contacts, rendez-vous et décisions restent
sous l'autorité du PostgreSQL applicatif. Aucun accès du moteur au mot de passe
PostgreSQL du CRM.

Prix catalogue vérifié : General Purpose Regular, 4 vCPU dédiés / 16 Gio / 50 Gio
inclus, 126 USD par mois par hôte, soit 252 USD de calcul pour les deux. Ce montant
n'inclut pas les 450 Gio SSD supplémentaires par hôte, les sauvegardes, l'image,
les taxes, ni les communications Twilio. Le disque doit être chiffré séparément
et son montage validé ; ne pas acheter le plan de base en le présentant comme
la configuration complète. Disponibilité et devis final à confirmer dans TOR1.
Le stockage objet sert à l'archive, pas à héberger MariaDB ni le spool actif.

## Construction de l'image : procédure à exécuter et vérifier

1. Télécharger l'ISO standard officielle de la version retenue et son contrôle
   d'intégrité. Vérifier le contrôle publié et calculer un SHA-256 pour figer
   l'artefact local. MD5 seul ne prouve pas l'authenticité d'un éditeur. Enregistrer
   URL, version, date, empreintes, dépôts et versions des paquets installés.
2. Installer dans une VM jetable x86_64, BIOS, disque virtuel neuf exclusivement.
   L'installeur détruit le disque sélectionné : aucun disque de l'hôte, du CRM ou
   volume de données existant ne doit être présenté à cette VM.
3. Contrôler le partitionnement, le chargeur BIOS, les pilotes VirtIO et un
   système de fichiers compatible ext4. Ne pas supposer que l'ISO officielle
   satisfait automatiquement aux exigences des images personnalisées.
4. Installer/configurer cloud-init avec une source DigitalOcean/ConfigDrive
   appropriée ; ConfigDrive doit précéder NoCloud. Vérifier DHCP, SSH par clé,
   console série et redémarrage sans ISO. Tester l'injection de clés et la
   réinitialisation de l'identité sur deux clones indépendants.
5. Mettre à jour les paquets et enregistrer leurs versions. Enlever les comptes
   et mots de passe par défaut, désactiver SSH par mot de passe. Aucun identifiant
   Twilio, clé privée, certificat privé, contact ou donnée réelle dans l'image.
6. Garder la configuration des rôles VICIdial pour les IP finales, après import.
   Ne pas cloner une base déjà liée aux IP de la machine de construction.
7. Nettoyer cloud-init et l'identité propre au clone, arrêter la VM et exporter
   un qcow2 autonome sans fichier de base externe. Vérifier sa cohérence et son
   démarrage à froid. La taille virtuelle décompressée de l'image doit rester
   sous 100 Go ; la croissance vers le disque cible se vérifie après import.
8. Produire un manifeste avec empreinte SHA-256 du disque, taille, version, liste
   des paquets et résultats des tests. Stocker l'image sans données ni secrets.
   L'import et le démarrage cloud demeurent un test payant à approuver sur devis.

## Réseau et installation après import

Créer les hôtes sur le VPC prévu, configurer les disques supplémentaires et les
sauvegardes, puis installer les rôles avec le mode Cluster officiel. MariaDB,
AMI/ARI et API de contrôle accessibles uniquement aux pairs autorisés sur réseau
privé ou VPN ; aucune exposition générale des consoles d'administration.

Séparer les règles de contrôle, signalisation et média. Relever les ports
réellement configurés avant d'écrire les règles. La présence d'un service sur
UDP 5061 ne prouve pas TLS : la documentation ViciBox décrit aussi un second
stack SIP en UDP sur ce port. Configurer explicitement TLS et SRTP sur la liaison
Twilio, WSS/DTLS-SRTP pour le navigateur et les paramètres NAT/ICE nécessaires.
Vérifier certificat, horloge, DNS et audio dans les deux sens. Déterminer si un
relais TURN est nécessaire lors des essais depuis les réseaux réels des agents.

Les plages Twilio, transports, ports média et URI localisée seront repris de la
documentation Twilio à la date d'installation, pas d'une ancienne capture console.
Les flux navigateur ont une politique distincte des plages opérateur. Ne pas
ouvrir tous les ports en réponse à un problème d'audio.

Transférer uniquement les identifiants SIP nécessaires par canal privé vers le
moteur. Le profil actuel sur le serveur applicatif n'est pas une configuration
Asterisk et n'a pas encore prouvé l'authentification SIP. Garder l'enregistrement
Twilio désactivé ; Asterisk produit une seule archive vérifiée dans Spaces privé.

## Preuves avant autorisation d'utiliser les campagnes

- Démarrage cloud et redémarrage : clés uniques, réseau public/privé, disque
  persistant, correctifs, sauvegarde et restauration effectivement testés.
- Un agent et une destination explicitement approuvée : appel, identité sortante,
  chiffrement, audio bidirectionnel, raccrochage et récupération après coupure.
- Contrôle CRM : réservation atomique et blocage avant chaque numérotation,
  pause/arrêt, formulaire RDV, rappel attribué, aucun doublon après délai/réessai.
- Enregistrement : deux voix, liaison à l'appel initial, archive privée intègre,
  reprise après panne d'upload et lecture autorisée uniquement aux bons rôles.
- Vingt agents avec vrais médias : mesurer canaux simultanés, appels par seconde,
  CPU/steal, mémoire, spool, latence, pertes, délais de connexion et erreurs.
  Fixer les seuils d'acceptation avant le test, puis retenir les ressources sur
  les résultats. Le nombre d'agents créés ne constitue pas une preuve de capacité.

## Limites constatées de cette session

L'environnement local dispose d'environ 11 Gio libres, sans QEMU, qemu-img,
virt-install ou Packer installés. /dev/kvm existe mais n'est pas directement
accessible au compte courant. Aucun environnement cloud managé ni accès API
DigitalOcean n'est attaché à cette session. L'accès SSH au CRM ne fournit pas une
machine de construction isolée. Ne pas remplir son disque ou y exécuter une
installation ViciBox pour contourner cette limite.

Aucune image n'a été construite, importée ou démarrée. Le prochain besoin concret
est une machine de construction isolée avec virtualisation et espace suffisants,
ou une image maintenue et une installation fournies par l'éditeur avec preuves
équivalentes. Ne pas confondre cette procédure préparée avec une compatibilité
DigitalOcean démontrée.

## Références officielles consultées

- Versions et support : https://www.vicibox.com/server/
- Documentation et correctifs : https://docs.vicibox.com/en/latest/
- Installation : https://docs.vicibox.com/en/latest/installation/phase1.html
- Rôles : https://docs.vicibox.com/en/latest/installation/phase2.html
- Dimensionnement : https://docs.vicibox.com/en/latest/introduction/hardware/dimensioning.html
- Matériel : https://docs.vicibox.com/en/latest/introduction/hardware/specifications.html
- Stack SIP : https://docs.vicibox.com/en/latest/maintenance/sipstack.html
- Fin de maintenance Leap 15 : https://news.opensuse.org/2026/04/01/leap-15-eol/
- Images DigitalOcean : https://docs.digitalocean.com/products/custom-images/how-to/upload/
- Limites : https://docs.digitalocean.com/products/custom-images/details/limits/
- Prix : https://www.digitalocean.com/pricing/droplets
