#!/usr/bin/env bash
# make-my-signing-key.sh: what "Make my signing key.cmd" runs, in Git for Windows' bash. AuditISA.
#
# Makes YOUR OWN signing key, once, for a person the platform owner has chosen to sign new versions:
#   %USERPROFILE%\auditisa-signing\auditisa-signing-key.pem   the private key, locked by your passphrase
#   %USERPROFILE%\auditisa-signing\auditisa-signing-key.pub   the public key, to send to the platform owner
# ($AUDITISA_SIGNING_DIR changes the folder.) It never overwrites a key that exists.
#
# Each signer has their own key and passphrase, never a shared one: the console can then tell who
# signed, and the owner can remove one person without touching the others.
#
# When its input is not a keyboard (tests), the answers are read from it, one per line, and nothing
# is copied to the clipboard if AUDITISA_NO_CLIPBOARD=1.

set -uo pipefail
umask 077

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
  echo
  if [ "$INTERACTIVE" = 1 ]; then
    say "Press any key to close this window." "Appuyez sur une touche pour fermer cette fenêtre."
    IFS= read -rsn1 _ </dev/tty || true
  fi
  exit "${1:-0}"
}
stop() { echo; bad "$1" "$2"; finish 1; }

ask_hidden() {
  printf '%s ' "$(say "$1" "$2")"
  if [ "$INTERACTIVE" = 1 ]; then
    IFS= read -rs REPLY </dev/tty || REPLY=""
  else
    IFS= read -r REPLY || REPLY=""
    REPLY=${REPLY%$'\r'}
  fi
  echo
}

winpath() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi; }
unixpath() { if command -v cygpath >/dev/null 2>&1; then cygpath -u "$1"; else printf '%s' "$1"; fi; }
short_fp() { local f; f=$(printf '%s' "$1" | tr 'a-f' 'A-F' | cut -c1-16); printf '%s %s %s %s' "${f:0:4}" "${f:4:4}" "${f:8:4}" "${f:12:4}"; }

clear 2>/dev/null || true
rule
bold "AuditISA - Make my signing key" "AuditISA - Créer ma clé de signature"
rule

if ! command -v openssl >/dev/null 2>&1 || ! openssl version >/dev/null 2>&1; then
  stop "This window needs Git for Windows. Install Git for Windows from git-scm.com, then try again." \
       "Cette fenêtre a besoin de Git pour Windows. Installez Git pour Windows depuis git-scm.com, puis recommencez."
fi

HOME_WIN=${USERPROFILE:-$HOME}
DIR=$(unixpath "${AUDITISA_SIGNING_DIR:-$HOME_WIN\\auditisa-signing}")
KEY=$DIR/auditisa-signing-key.pem
PUB=$DIR/auditisa-signing-key.pub

existing=""
for found in "$DIR"/*.pem; do [ -e "$found" ] && existing=$found && break; done
if [ -n "$existing" ] || [ -e "$PUB" ]; then
  stop "You already have a signing key: $(winpath "${existing:-$PUB}"). It was not changed. If you lost it or forgot its passphrase, ask the platform owner to remove it as a signer, then move the old files out of this folder yourself before making a new one." \
       "Vous avez déjà une clé de signature : $(winpath "${existing:-$PUB}"). Elle n'a pas été modifiée. Si vous l'avez perdue ou avez oublié sa phrase secrète, demandez au propriétaire de la plateforme de vous retirer des signataires, puis déplacez vous-même les anciens fichiers hors de ce dossier avant d'en créer une nouvelle."
fi

say "This makes your own key to sign new versions of AuditISA. It stays on this computer." \
    "Cette opération crée votre propre clé pour signer les nouvelles versions d'AuditISA. Elle reste sur cet ordinateur."
say "Choose a passphrase: at least 12 characters, one that only you know. Nobody, not even the owner, must ever know it." \
    "Choisissez une phrase secrète : au moins 12 caractères, connue de vous seul. Personne, pas même le propriétaire, ne doit connaître votre phrase secrète."
echo

for _ in 1 2 3; do
  ask_hidden "Your passphrase (nothing shows while you type):" "Votre phrase secrète (rien ne s'affiche pendant la frappe) :"
  first=$REPLY
  if [ "${#first}" -lt 12 ]; then
    bad "The passphrase must have at least 12 characters." "La phrase secrète doit avoir au moins 12 caractères."
    continue
  fi
  ask_hidden "Type it a second time:" "Tapez-la une deuxième fois :"
  if [ "$REPLY" != "$first" ]; then
    bad "The two passphrases are not the same." "Les deux phrases ne sont pas identiques."
    first=""
    continue
  fi
  break
done
REPLY=""
[ -n "${first:-}" ] && [ "${#first}" -ge 12 ] || stop "Cancelled: no key was made." "Annulé : aucune clé n'a été créée."

mkdir -p "$DIR"
TMP=$DIR/.new-key.$$
if ! printf '%s\n' "$first" | openssl genpkey -algorithm ed25519 -aes-256-cbc -pass stdin -out "$TMP" 2>/dev/null \
   || ! printf '%s\n' "$first" | openssl pkey -in "$TMP" -passin stdin -pubout -out "$TMP.pub" 2>/dev/null; then
  first=""
  rm -f "$TMP" "$TMP.pub"
  stop "Making the key failed. Nothing was made." "La création de la clé a échoué. Rien n'a été créé."
fi
first=""
# Never overwrite: a key made in the meantime wins.
if [ -e "$KEY" ] || [ -e "$PUB" ]; then
  rm -f "$TMP" "$TMP.pub"
  stop "A key appeared in the folder meanwhile: it was kept, nothing was changed." \
       "Une clé est apparue dans le dossier entre-temps : elle a été gardée, rien n'a été modifié."
fi
mv "$TMP" "$KEY"
mv "$TMP.pub" "$PUB"
chmod 600 "$KEY" 2>/dev/null || true
chmod 644 "$PUB" 2>/dev/null || true
# Windows: only this user may read the key file.
if command -v icacls.exe >/dev/null 2>&1; then
  icacls.exe "$(winpath "$KEY")" /inheritance:r /grant:r "${USERNAME:-$USER}:F" >/dev/null 2>&1 || true
fi

FP=$(openssl pkey -pubin -in "$PUB" -outform DER | sha256sum | cut -c1-64)

echo
rule
good "Your key was made." "Votre clé a été créée."
rule
printf '%s %s\n' "$(say 'Private key (never send it):' "Clé privée (ne l'envoyez jamais) :")" "$(winpath "$KEY")"
printf '%s %s\n' "$(say 'Public key (to send):' 'Clé publique (à envoyer) :')" "$(winpath "$PUB")"
echo
bold "Your public key:" "Votre clé publique :"
cat "$PUB"
echo
printf '%s %s\n' "$(say 'Fingerprint of your key:' 'Empreinte de votre clé :')" "$(short_fp "$FP")"
echo
if [ "${AUDITISA_NO_CLIPBOARD:-}" != 1 ] && command -v clip.exe >/dev/null 2>&1 && clip.exe < "$PUB"; then
  say "The public key is copied: paste it into an email (Ctrl+V)." "La clé publique est copiée : collez-la dans un e-mail (Ctrl+V)."
fi
echo
bold "Send this public key to the platform owner to be added as a signer. Never send the other file." \
     "Envoyez cette clé publique au propriétaire de la plateforme pour être ajouté comme signataire. N'envoyez jamais l'autre fichier."
say "The owner will phone you to check the fingerprint above together: it must be the same on their screen." \
    "Le propriétaire vous appellera pour vérifier ensemble l'empreinte ci-dessus : elle doit être la même sur son écran."
say "Keep a copy of the key file on a USB stick kept in a safe place. If you lose the key or forget the passphrase, you will need a new key." \
    "Gardez une copie du fichier de clé sur une clé USB rangée en lieu sûr. Si vous perdez la clé ou oubliez la phrase secrète, il faudra une nouvelle clé."
finish 0
