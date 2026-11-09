#!/usr/bin/env bash
# sign-new-version.sh: what "Sign new version.cmd" runs, in Git for Windows' bash. AuditISA.
#
# Finds a new version that waits for a signature, shows what it is in plain words, asks "Sign this
# version?", then the passphrase of YOUR signing key (hidden), signs and checks the signature.
#
# Where it looks for a waiting version, in order:
#   1. the folder given as argument (or dropped on the .cmd file)
#   2. $AUDITISA_RELEASES_DIR, then Documents\Odoo-migration\console-live\release-* (the owner's computer)
#   3. your Downloads folder (files downloaded from the console, Platform > Updates > Waiting for signature)
#   4. otherwise it asks you to pick the folder.
# The key: %USERPROFILE%\auditisa-signing\*.pem with its .pub beside it ($AUDITISA_SIGNING_DIR to change
# the folder), or one you pick.
#
# It writes three files beside the version, none of them secret: <commit>.tar.gz.sig,
# <commit>.catalogue.json.sig and <commit>.attestation. The key file never leaves this computer. The
# passphrase goes to openssl on a pipe: never on a command line, never in a file, never shown.
#
# When its input is not a keyboard (tests), the answers are read from it, one per line.

set -uo pipefail
umask 077

# ---------------------------------------------------------------------------- words, in two languages

LANG_UI=${AUDITISA_LANG:-}
if [ -z "$LANG_UI" ] && command -v reg.exe >/dev/null 2>&1; then
  case "$(reg.exe query 'HKCU\Control Panel\International' /v LocaleName 2>/dev/null | tr -d '\r')" in
    *fr-*|*FR*) LANG_UI=fr ;;
  esac
fi
[ "$LANG_UI" = fr ] || LANG_UI=en

say() { if [ "$LANG_UI" = fr ]; then printf '%s\n' "$2"; else printf '%s\n' "$1"; fi; }
bold() { printf '\033[1m%s\033[0m\n' "$(say "$1" "$2")"; }
good() { printf '\033[1;32m%s\033[0m\n' "$(say "$1" "$2")"; }
bad() { printf '\033[1;31m%s\033[0m\n' "$(say "$1" "$2")"; }
rule() { printf '%s\n' "------------------------------------------------------------------------"; }

INTERACTIVE=0
[ -t 0 ] && INTERACTIVE=1

finish() {
  local code=${1:-0}
  echo
  if [ "$INTERACTIVE" = 1 ]; then
    say "Press any key to close this window." "Appuyez sur une touche pour fermer cette fenêtre."
    IFS= read -rsn1 _ </dev/tty || true
  fi
  exit "$code"
}

stop() { echo; bad "$1" "$2"; finish 1; }

ask() {  # ask "English question" "French question" -> REPLY
  printf '%s ' "$(say "$1" "$2")"
  IFS= read -r REPLY || REPLY=""
  REPLY=${REPLY%$'\r'}
}

ask_hidden() {
  printf '%s ' "$(say "$1" "$2")"
  if [ "$INTERACTIVE" = 1 ]; then
    IFS= read -rs REPLY </dev/tty || REPLY=""
    echo
  else
    IFS= read -r REPLY || REPLY=""
    REPLY=${REPLY%$'\r'}
    echo
  fi
}

winpath() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi; }
unixpath() { if command -v cygpath >/dev/null 2>&1; then cygpath -u "$1"; else printf '%s' "$1"; fi; }

# A Windows folder or file picker, through PowerShell. Empty when cancelled or unavailable.
pick_folder() {
  command -v powershell.exe >/dev/null 2>&1 || return 0
  powershell.exe -NoProfile -STA -Command "Add-Type -AssemblyName System.Windows.Forms; \$d = New-Object System.Windows.Forms.FolderBrowserDialog; \$d.Description = '$1'; if (\$d.ShowDialog() -eq 'OK') { \$d.SelectedPath }" 2>/dev/null | tr -d '\r'
}
pick_file() {
  command -v powershell.exe >/dev/null 2>&1 || return 0
  powershell.exe -NoProfile -STA -Command "Add-Type -AssemblyName System.Windows.Forms; \$d = New-Object System.Windows.Forms.OpenFileDialog; \$d.Title = '$1'; \$d.Filter = 'Signing key (*.pem)|*.pem'; if (\$d.ShowDialog() -eq 'OK') { \$d.FileName }" 2>/dev/null | tr -d '\r'
}

fingerprint_of() { openssl pkey -pubin -in "$1" -outform DER 2>/dev/null | sha256sum | cut -c1-64; }
short_fp() { local f; f=$(printf '%s' "$1" | tr 'a-f' 'A-F' | cut -c1-16); printf '%s %s %s %s' "${f:0:4}" "${f:4:4}" "${f:8:4}" "${f:12:4}"; }
grouped() { printf '%s' "$1" | sed -E 's/(.{16})/\1 /g; s/ $//'; }

# ---------------------------------------------------------------------------- start

clear 2>/dev/null || true
rule
bold "AuditISA - Sign a new version" "AuditISA - Signer une nouvelle version"
rule

if ! command -v openssl >/dev/null 2>&1 || ! openssl version >/dev/null 2>&1; then
  stop "This window needs Git for Windows. Install Git for Windows from git-scm.com, then try again." \
       "Cette fenêtre a besoin de Git pour Windows. Installez Git pour Windows depuis git-scm.com, puis recommencez."
fi

HOME_WIN=${USERPROFILE:-$HOME}
HOME_DIR=$(unixpath "$HOME_WIN")

# ---------------------------------------------------------------------------- the key

KEY_DIR=$(unixpath "${AUDITISA_SIGNING_DIR:-$HOME_WIN\\auditisa-signing}")
KEY=""
mapfile -t KEYS < <(ls "$KEY_DIR"/*.pem 2>/dev/null)
if [ "${#KEYS[@]}" = 1 ]; then
  KEY=${KEYS[0]}
elif [ "${#KEYS[@]}" -gt 1 ]; then
  say "There are several signing keys in $(winpath "$KEY_DIR"):" "Il y a plusieurs clés de signature dans $(winpath "$KEY_DIR") :"
  for i in "${!KEYS[@]}"; do printf '  %s. %s\n' "$((i + 1))" "$(basename "${KEYS[$i]}")"; done
  ask "Which one is yours? Type its number:" "Laquelle est la vôtre ? Tapez son numéro :"
  [[ $REPLY =~ ^[0-9]+$ ]] && [ "$REPLY" -ge 1 ] && [ "$REPLY" -le "${#KEYS[@]}" ] || stop "Nothing was signed." "Rien n'a été signé."
  KEY=${KEYS[$((REPLY - 1))]}
else
  say "No signing key was found in $(winpath "$KEY_DIR")." "Aucune clé de signature dans $(winpath "$KEY_DIR")."
  say "A window opens: pick your key file (it ends in .pem)." "Une fenêtre s'ouvre : choisissez votre fichier de clé (il finit par .pem)."
  picked=$(pick_file "Your AuditISA signing key (.pem)")
  [ -n "$picked" ] || stop "No key: nothing was signed. A new signer first makes a key with \"Make my signing key\"." \
                          "Pas de clé : rien n'a été signé. Un nouveau signataire crée d'abord sa clé avec \"Make my signing key\"."
  KEY=$(unixpath "$picked")
fi
[ -f "$KEY" ] && KEY=$(cd "$(dirname "$KEY")" && pwd)/$(basename "$KEY")
PUB=${KEY%.pem}.pub
[ -r "$KEY" ] || stop "The key file cannot be read: $(winpath "$KEY")" "Le fichier de clé ne peut pas être lu : $(winpath "$KEY")"
[ -r "$PUB" ] || stop "The public key file must be beside the key: $(winpath "$PUB")" \
                      "Le fichier de clé publique doit être à côté de la clé : $(winpath "$PUB")"
MY_FP=$(fingerprint_of "$PUB")
[ ${#MY_FP} = 64 ] || stop "The public key file cannot be read: $(winpath "$PUB")" "Le fichier de clé publique ne peut pas être lu : $(winpath "$PUB")"

# ---------------------------------------------------------------------------- the waiting version

# Every <commit>.tar.gz in a folder, with its catalogue, that has no signature yet.
waiting_in() {
  local folder=$1 bundle
  for bundle in "$folder"/*.tar.gz; do
    [ -f "$bundle" ] || continue
    [[ $(basename "$bundle") =~ ^[0-9a-f]{40}\.tar\.gz$ ]] || continue
    [ -f "${bundle%.tar.gz}.catalogue.json" ] || continue
    [ -e "$bundle.sig" ] && continue
    printf '%s\n' "$bundle"
  done
}

CANDIDATES=()
if [ -n "${1:-}" ]; then
  arg=$(unixpath "$1")
  [ -f "$arg" ] && arg=$(dirname "$arg")
  mapfile -t CANDIDATES < <(waiting_in "$arg")
  if [ "${#CANDIDATES[@]}" = 0 ]; then
    stop "No unsigned version in $(winpath "$arg")." "Aucune version à signer dans $(winpath "$arg")."
  fi
else
  RELEASES_DIR=$(unixpath "${AUDITISA_RELEASES_DIR:-$HOME_WIN\\Documents\\Odoo-migration\\console-live}")
  for folder in "$RELEASES_DIR"/release-* "$RELEASES_DIR" "$HOME_DIR/Downloads"; do
    [ -d "$folder" ] || continue
    while IFS= read -r found; do [ -n "$found" ] && CANDIDATES+=("$found"); done < <(waiting_in "$folder")
  done
fi

if [ "${#CANDIDATES[@]}" = 0 ]; then
  say "No version waiting for a signature was found on this computer." "Aucune version à signer n'a été trouvée sur cet ordinateur."
  say "If you downloaded it from the console (Platform > Updates > Waiting for signature), a window opens: pick the folder where the files are." \
      "Si vous l'avez téléchargée depuis la console (Plateforme > Mises à jour > En attente de signature), une fenêtre s'ouvre : choisissez le dossier des fichiers."
  picked=$(pick_folder "The folder with the files downloaded from the console")
  [ -n "$picked" ] || stop "Nothing was signed." "Rien n'a été signé."
  mapfile -t CANDIDATES < <(waiting_in "$(unixpath "$picked")")
  [ "${#CANDIDATES[@]}" -gt 0 ] || stop "No unsigned version in that folder. It needs the .tar.gz and .catalogue.json files downloaded from the console." \
                                        "Aucune version à signer dans ce dossier. Il faut les fichiers .tar.gz et .catalogue.json téléchargés depuis la console."
fi

BUNDLE=${CANDIDATES[0]}
if [ "${#CANDIDATES[@]}" -gt 1 ]; then
  say "Several versions wait for a signature:" "Plusieurs versions attendent une signature :"
  for i in "${!CANDIDATES[@]}"; do
    printf '  %s. %s   (%s)\n' "$((i + 1))" "$(basename "${CANDIDATES[$i]}" | cut -c1-12)" "$(winpath "$(dirname "${CANDIDATES[$i]}")")"
  done
  ask "Which one do you want to sign? Type its number:" "Laquelle voulez-vous signer ? Tapez son numéro :"
  [[ $REPLY =~ ^[0-9]+$ ]] && [ "$REPLY" -ge 1 ] && [ "$REPLY" -le "${#CANDIDATES[@]}" ] || stop "Nothing was signed." "Rien n'a été signé."
  BUNDLE=${CANDIDATES[$((REPLY - 1))]}
fi

DIR=$(cd "$(dirname "$BUNDLE")" && pwd)
BUNDLE=$DIR/$(basename "$BUNDLE")
SHA=$(basename "$BUNDLE" .tar.gz)
CATALOGUE=$DIR/$SHA.catalogue.json
CHANGES=$DIR/$SHA.changes.txt
DIGEST=$(sha256sum "$BUNDLE" | cut -d' ' -f1)

if tar -tzf "$BUNDLE" 2>/dev/null | grep '^addons/ea_platform_' >/dev/null; then
  stop "This bundle holds the console's own program: it must not be signed." "Ce paquet contient le programme de la console : il ne doit pas être signé."
fi
grep -q "\"release\": \"$SHA\"" "$CATALOGUE" || stop "The catalogue is not the one of this version: nothing was signed." \
                                                    "Le catalogue n'est pas celui de cette version : rien n'a été signé."

# The list of signers this version gives the firms, and who you are in it.
CARRIED=$(tar -xzOf "$BUNDLE" deploy/trust/signers.json 2>/dev/null || true)
signers_of() {  # prints "group|fingerprint|name|email" per entry, from the pretty-printed list
  printf '%s\n' "$CARRIED" | awk '
    /"retired": \[/ { group = "retired" } /"signers": \[/ { group = "signers" }
    /"email":/ { gsub(/.*"email": "|",?$/, ""); email = $0 }
    /"fingerprint":/ { gsub(/.*"fingerprint": "|",?$/, ""); fp = $0 }
    /"name":/ { gsub(/.*"name": "|",?$/, ""); name = $0 }
    /^    }/ { if (fp != "") print group "|" fp "|" name "|" email; fp = ""; name = ""; email = "" }'
}
ME=""
LIST_SERIAL=$(printf '%s\n' "$CARRIED" | sed -n 's/.*"serial": \([0-9]*\).*/\1/p' | head -n1)
while IFS='|' read -r group fp name email; do
  [ "$group" = signers ] && [ "$fp" = "$MY_FP" ] && ME="$name ($email)"
done < <(signers_of)

# ---------------------------------------------------------------------------- what is to be signed

echo
bold "The version waiting for your signature" "La version qui attend votre signature"
rule
printf '%-22s %s\n' "$(say 'Version:' 'Version :')" "${SHA:0:12}"
if [ -f "$CHANGES" ]; then
  made=$(sed -n '1s/.*made on \([0-9-]*\).*/\1/p' "$CHANGES")
fi
[ -n "${made:-}" ] || made=$(date -r "$BUNDLE" +%Y-%m-%d 2>/dev/null)
printf '%-22s %s\n' "$(say 'Date:' 'Date :')" "$made"
printf '%-22s %s\n' "$(say 'Folder:' 'Dossier :')" "$(winpath "$DIR")"
printf '%-22s %s\n' "$(say 'File fingerprint:' 'Empreinte du fichier :')" "$(grouped "$DIGEST")"
echo
bold "Changes in this version:" "Changements dans cette version :"
if [ -f "$CHANGES" ]; then
  sed -n '2,$p' "$CHANGES" | tr -d '\r' | sed 's/^/  /' | head -n 40
  [ "$(wc -l < "$CHANGES")" -le 41 ] || say "  ... (more in $SHA.changes.txt)" "  ... (la suite dans $SHA.changes.txt)"
else
  say "  (no list of changes came with this version: ask the technician what it holds)" \
      "  (aucune liste de changements avec cette version : demandez au technicien ce qu'elle contient)"
fi
echo
if [ -n "$CARRIED" ]; then
  bold "People this version lets the firms trust as signers (list number ${LIST_SERIAL:-?}):" \
       "Personnes que cette version fait reconnaître comme signataires par les cabinets (liste numéro ${LIST_SERIAL:-?}) :"
  while IFS='|' read -r group fp name email; do
    [ "$group" = signers ] && printf '  - %s (%s)  %s\n' "$name" "$email" "$(short_fp "$fp")"
  done < <(signers_of)
  say "  Check that nobody unexpected is in this list." "  Vérifiez que personne d'inattendu n'est dans cette liste."
  echo
fi
bold "You will sign as:" "Vous allez signer en tant que :"
if [ -n "$ME" ]; then
  printf '  %s, %s %s\n' "$ME" "$(say 'key fingerprint' 'empreinte de clé')" "$(short_fp "$MY_FP")"
else
  printf '  %s %s\n' "$(say 'key fingerprint' 'empreinte de clé')" "$(short_fp "$MY_FP")"
  [ -n "$CARRIED" ] || bad "  This version carries no list of signers. The console accepts the signature only if the platform owner has added you as a signer." \
    "  Cette version ne contient pas de liste de signataires. La console n'accepte la signature que si le propriétaire de la plateforme vous a ajouté comme signataire."
  [ -z "$CARRIED" ] || bad "  This key is not in the list above. The console will refuse the signature unless the platform owner has added you as a signer." \
      "  Cette clé n'est pas dans la liste ci-dessus. La console refusera la signature si le propriétaire de la plateforme ne vous a pas ajouté comme signataire."
fi
printf '  %s %s\n' "$(say 'Key file:' 'Fichier de clé :')" "$(winpath "$KEY")"
rule

ask "Sign this version? (Y/N)" "Signer cette version ? (O/N)"
case "$REPLY" in
  y|Y|yes|Yes|YES|o|O|oui|Oui|OUI) ;;
  *) stop "Not signed. Nothing was changed." "Pas signée. Rien n'a été modifié." ;;
esac

# ---------------------------------------------------------------------------- the passphrase, then the signature

PASS="" LOCKED=""
if openssl pkey -in "$KEY" -passin pass: -noout >/dev/null 2>&1; then
  bad "Warning: this key has no passphrase. Anyone who copies the file can sign. Make a new key with \"Make my signing key\"." \
      "Attention : cette clé n'a pas de phrase secrète. Quiconque copie le fichier peut signer. Créez une nouvelle clé avec \"Make my signing key\"."
else
  LOCKED=1
  opened=""
  for try in 1 2 3; do
    ask_hidden "Passphrase of your signing key (nothing shows while you type):" \
               "Phrase secrète de votre clé de signature (rien ne s'affiche pendant la frappe) :"
    PASS=$REPLY
    if printf '%s\n' "$PASS" | openssl pkey -in "$KEY" -passin stdin -noout >/dev/null 2>&1; then opened=1; break; fi
    bad "Wrong passphrase ($try of 3)." "Phrase secrète incorrecte ($try sur 3)."
  done
  REPLY=""
  [ -n "$opened" ] || { PASS=""; stop "The key did not open: nothing was signed." "La clé ne s'est pas ouverte : rien n'a été signé."; }
fi

key_pub() {
  if [ -n "$LOCKED" ]; then printf '%s\n' "$PASS" | openssl pkey -in "$KEY" -passin stdin -pubout 2>/dev/null
  else openssl pkey -in "$KEY" -pubout 2>/dev/null; fi
}
if [ "$(key_pub)" != "$(openssl pkey -pubin -in "$PUB" -pubout 2>/dev/null)" ]; then
  PASS=""
  stop "The key file and its .pub file do not belong together: nothing was signed." \
       "Le fichier de clé et son fichier .pub ne vont pas ensemble : rien n'a été signé."
fi

sign_file() {
  if [ -n "$LOCKED" ]; then
    printf '%s\n' "$PASS" | openssl pkeyutl -sign -inkey "$KEY" -passin stdin -rawin -in "$1" -out "$2"
  else
    openssl pkeyutl -sign -inkey "$KEY" -rawin -in "$1" -out "$2"
  fi
}

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
LINE=$WORK/attestation.txt
printf 'ea-promotion-v1\n%s\n%s\n' "$SHA" "$DIGEST" > "$LINE"
if ! sign_file "$BUNDLE" "$WORK/bundle.sig" || ! sign_file "$CATALOGUE" "$WORK/catalogue.sig" || ! sign_file "$LINE" "$WORK/line.sig"; then
  PASS=""
  stop "Signing failed: nothing was written." "La signature a échoué : rien n'a été écrit."
fi
PASS=""

# Checked with the public key before anything is written beside the version.
ok=1
openssl pkeyutl -verify -pubin -inkey "$PUB" -rawin -in "$BUNDLE" -sigfile "$WORK/bundle.sig" >/dev/null 2>&1 || ok=0
openssl pkeyutl -verify -pubin -inkey "$PUB" -rawin -in "$CATALOGUE" -sigfile "$WORK/catalogue.sig" >/dev/null 2>&1 || ok=0
openssl pkeyutl -verify -pubin -inkey "$PUB" -rawin -in "$LINE" -sigfile "$WORK/line.sig" >/dev/null 2>&1 || ok=0
[ "$ok" = 1 ] || stop "The signature did not check out: nothing was written." "La signature n'est pas valide : rien n'a été écrit."

umask 022
cp "$WORK/bundle.sig" "$BUNDLE.sig"
cp "$WORK/catalogue.sig" "$CATALOGUE.sig"
{ openssl base64 -A -in "$WORK/line.sig"; printf '\n'; } > "$DIR/$SHA.attestation"

echo
rule
good "Signed. Signature good." "Signée. Signature valide."
rule
say "Three files were added beside the version (not secret):" "Trois fichiers ont été ajoutés à côté de la version (pas secrets) :"
printf '  %s\n' "$SHA.tar.gz.sig" "$SHA.catalogue.json.sig" "$SHA.attestation"
echo
case "$DIR" in
  */release-*)
    say "Next: the technician uploads and registers this version (first-release.md, step 2)." \
        "Ensuite : le technicien envoie et enregistre cette version (first-release.md, étape 2)." ;;
  *)
    bold "Next: upload these three files on the console:" "Ensuite : envoyez ces trois fichiers sur la console :"
    say "  Platform > Updates > Waiting for signature > version ${SHA:0:12}, then \"Check the signatures and publish\"." \
        "  Plateforme > Mises à jour > En attente de signature > version ${SHA:0:12}, puis \"Vérifier les signatures et publier\"."
    say "  The folder opens now." "  Le dossier s'ouvre maintenant."
    if [ "$INTERACTIVE" = 1 ] && command -v explorer.exe >/dev/null 2>&1; then explorer.exe "$(winpath "$DIR")" >/dev/null 2>&1 || true; fi ;;
esac
finish 0
