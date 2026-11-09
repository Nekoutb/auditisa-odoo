AuditISA - signing kit / kit de signature
=========================================

ENGLISH
-------

Who should have this folder
  Only the people the platform owner has chosen to sign new versions of AuditISA.
  A firm's server installs a new version only if one of these people signed it.

What is in it
  "Make my signing key"  Double-click it ONCE, the first time. It makes your own key,
                         locked by a passphrase that only you know, in the folder
                         auditisa-signing of your Windows user. It never replaces a key
                         you already have.
                         It then shows your PUBLIC key and copies it: email it to the
                         platform owner, who adds you as a signer. The owner phones you to
                         check the short fingerprint shown on your screen.
  "Sign new version"     Double-click it when a new version waits for a signature. It shows
                         the version, its date, its list of changes and its fingerprint, and
                         who you will sign as. It asks "Sign this version? (Y/N)", then your
                         passphrase. It ends with "Signed. Signature good."
                         If the version came from the console (Platform > Updates > Waiting
                         for signature), download its files first (your Downloads folder is
                         fine), then upload the three files the tool makes on the same page.

It needs Git for Windows (free, git-scm.com). If it is missing, the window says so.

NEVER
  - never send, copy or share the key file (auditisa-signing-key.pem) with anyone, not even
    the owner or a technician. Only the .pub file may be sent.
  - never tell anyone your passphrase, and never write it in an email or a message.
  - never use someone else's key: each signer has their own, so the console knows who signed
    and the owner can remove one person without touching the others.

Keep a copy of your key file on a USB stick kept in a safe place. If you lose the key or forget
the passphrase, tell the owner: they remove the old key and you make a new one.


FRANÇAIS
--------

Qui doit avoir ce dossier
  Seulement les personnes que le propriétaire de la plateforme a choisies pour signer les
  nouvelles versions d'AuditISA. Le serveur d'un cabinet n'installe une nouvelle version que
  si l'une de ces personnes l'a signée.

Ce qu'il contient
  "Make my signing key"  (Créer ma clé de signature) Double-cliquez UNE fois, la première fois.
                         Il crée votre propre clé, verrouillée par une phrase secrète connue
                         de vous seul, dans le dossier auditisa-signing de votre utilisateur
                         Windows. Il ne remplace jamais une clé existante.
                         Il affiche ensuite votre clé PUBLIQUE et la copie : envoyez-la par
                         e-mail au propriétaire de la plateforme, qui vous ajoute comme
                         signataire. Le propriétaire vous appelle pour vérifier ensemble
                         l'empreinte courte affichée à l'écran.
  "Sign new version"     (Signer une nouvelle version) Double-cliquez quand une nouvelle
                         version attend une signature. Il affiche la version, sa date, la
                         liste des changements, son empreinte, et sous quel nom vous signez.
                         Il demande "Signer cette version ? (O/N)", puis votre phrase secrète.
                         Il se termine par "Signée. Signature valide."
                         Si la version vient de la console (Plateforme > Mises à jour > En
                         attente de signature), téléchargez d'abord ses fichiers (le dossier
                         Téléchargements convient), puis envoyez sur la même page les trois
                         fichiers créés par l'outil.

Il faut Git pour Windows (gratuit, git-scm.com). S'il manque, la fenêtre le dit.

JAMAIS
  - n'envoyez, ne copiez et ne partagez jamais le fichier de clé (auditisa-signing-key.pem),
    même avec le propriétaire ou un technicien. Seul le fichier .pub peut être envoyé.
  - ne dites jamais votre phrase secrète, ne l'écrivez jamais dans un e-mail ou un message.
  - n'utilisez jamais la clé de quelqu'un d'autre : chaque signataire a la sienne, pour que la
    console sache qui a signé et que le propriétaire puisse retirer une personne sans toucher
    aux autres.

Gardez une copie de votre fichier de clé sur une clé USB rangée en lieu sûr. Si vous perdez la
clé ou oubliez la phrase secrète, prévenez le propriétaire : il retire l'ancienne clé et vous en
créez une nouvelle.
