# Réception et suivi des appels entrants

Ce lot ajoute le paramétrage des files et le suivi manuel des appels manqués.
Il ne connecte aucun numéro Twilio et n'active ni réception navigateur, ni appel
sortant. L'interface affiche « Réception inactive » et explique que les appels
ne sont pas encore acheminés aux agents. Ce statut ne signale pas un numéro
invalide et ne constitue pas un test de raccordement Twilio. Le test réel
audio/enregistrement a été reporté.

## Paramétrage

Un administrateur crée une file par numéro international : nom, fuseau IANA,
plages hebdomadaires, attente maximale (60 s par défaut), sonnerie par agent
(20 s par défaut) et jusqu'à 20 comptes attribués. Les attributions sont
indépendantes des campagnes sortantes. Les permissions globales de numérotation
et la présence média restent du ressort du futur coordinateur de distribution.
La sélection actuelle n'octroie aucune nouvelle autorisation d'appel.

L'interface propose les lignes vocales déjà présentes dans le répertoire du
compte Twilio. Le numéro identifie la ligne de l'entreprise appelée par les
clients. La création d'une file ne commande pas de nouveau numéro. Une ancienne
ligne enregistrée reste sélectionnable pour modifier son équipe lorsque le
répertoire est indisponible. L'activation future du routage devra vérifier la
propriété et la route fournisseur réelle avant tout changement externe.

Les agents et la ligne sont les réglages principaux ; attente, sonnerie et
horaires sont regroupés dans une section dépliable. La liste des agents propose
une recherche, une sélection conservée et une limite de 20 comptes.

Les plages sont locales et semi-ouvertes : le début est inclus, la fin exclue.
Sans plage, la file reste hors horaires. Une ouverture de nuit se représente par
une plage jusqu'à minuit puis une plage sur la journée suivante. Les doublons
d'agents, chevauchements et sonneries plus longues que l'attente sont refusés.
L'archivage conserve tous les suivis et les appels tardifs vérifiés. Un numéro
ayant un historique ne peut pas être remplacé sur la même file.

Les réglages et attributions changent dans une transaction avec leur historique.
Un numéro/nom est unique ; une version protège les modifications concurrentes.
Les identifiants de requête permettent de reprendre une réponse perdue sans
appliquer une seconde modification. Seuls les administrateurs authentifiés avec
MFA récent peuvent écrire les réglages. Les agents voient leurs seules files.

## Appels et pipeline

Chaque appel manqué vérifié est une interaction immuable identifiée par compte
et CallSid. Le service interne `record_missed` exige un appel terminal dont le
routage, l'appartenance et le résultat ont déjà été établis par un adaptateur
fiable. Aucune route HTTP ne permet d'inventer un appel ou de contourner la
signature Twilio. Cet adaptateur, la réception média, les offres d'agents et la
messagerie vocale ne sont pas encore reliés dans ce lot.

Le résultat téléphonique est séparé de l'étape du suivi : À traiter, Pris en
charge, Rappel programmé, Traité. Un changement d'étape n'appelle jamais un
numéro, ne raccroche pas et ne crée pas de rendez-vous fictif.

La vue Liste regroupe les suivis par statut, affiche le contact, son numéro,
le responsable et la date du rappel ou du suivi. Les compteurs filtrent les
statuts, la pagination reste bornée, et la vue Pipeline reste disponible. Une
file vide affiche un seul état vide. Une erreur de chargement n'est jamais
présentée comme l'absence de suivis.

Plusieurs appels du même numéro dans une file rejoignent le suivi encore ouvert,
avec une interaction par appel. Une répétition de la même notification ne crée
ni interaction ni fiche supplémentaire. Un résultat contradictoire est refusé
et doit être rapproché par le coordinateur, jamais écrasé. Les appels masqués
restent séparés. Un nouvel appel après clôture crée une nouvelle fiche et laisse
l'historique précédent intact. Le contact connu est lié sans modifier son profil,
ses campagnes, ses notes, ses rendez-vous ni ses restrictions globales.

Une transaction et la version du suivi arbitrent sa prise en charge. Les agents
peuvent traiter leurs suivis ou prendre un suivi libre. Un administrateur peut
réattribuer à un compte actif déjà membre de la file. Retirer un agent ayant des
suivis ouverts est refusé jusqu'à leur réattribution. Les notes sont partagées,
append-only et identifiées de façon idempotente, y compris après clôture.

Un rappel manuel exige un propriétaire, un numéro visible, une date future et
un fuseau. Le résolveur horaire partagé refuse les heures inexistantes et demande
le décalage UTC pour une heure répétée. Ces rappels sont visibles dans le pipeline
Appels entrants ; ils ne deviennent pas des rappels de campagne ou des tâches de
numérotation automatique. Un contact bloqué ne peut pas recevoir un nouveau
rappel. Les restrictions actuelles sont toujours relues dans sa fiche : un appel
entrant ne réactive jamais un contact, et une programmation n'autorise aucun appel.

Les listes d'appels et d'événements utilisent des pages bornées et des curseurs.
Les vues ne contiennent ni appels de démonstration ni statistiques simulées.
Les enregistrements/voicemails entrants seront reliés à leur archivage privé
lors de la livraison du récepteur ; aucune fausse lecture n'est présentée ici.

## Migration et exploitation

`0009_inbound` ajoute six tables sans réécrire les tables existantes. Les appels
et événements ne peuvent pas être modifiés ou supprimés par le rôle applicatif.
La migration ne configure ni numéro, ni route fournisseur, ni file par défaut.

Le déploiement exige d'abord la version de compatibilité
`acc101c5071beea7fc37553297e3529921e3aef1` (schéma 8 acceptant aussi le schéma 9).
Elle inclut le champ de saisie du numéro. Le déployeur refuse la migration depuis
une autre version du schéma 8 ; il garde ainsi un retour arrière applicatif réel.
Ensuite seulement, publier et déployer le lot du schéma 9 depuis main avec sa CI
et son attestation. Aucun downgrade de données n'est exécuté en cas de retour
arrière. Les sauvegardes et tests de restauration incluent les six nouvelles tables.

La configuration gérée conserve `webhooks_only`, sans modifier les routes ou
numéros de l'ancienne application. La réception réelle nécessite encore la
réservation atomique commune aux deux directions, la présence et disponibilité
média, les offres confirmées, le récepteur signé, la récupération après perte de
notification et les preuves audio/voicemail. La décision pure `inbound.py` reste
un composant de politique ; ce pipeline ne constitue pas une preuve de capacité
pour vingt conversations simultanées.
