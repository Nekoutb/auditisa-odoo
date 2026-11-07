#!/usr/bin/env bash
# practice-space.sh: a firm's practice space on the practice computer.
#
#   practice-space create --slug SLUG --name "FIRM" --admin-login LOGIN [--addons a,b] [--lang fr_FR]
#   practice-space reset --slug SLUG [--new-password]
#   practice-space delete --slug SLUG --yes
#   practice-space addons --slug SLUG --set a,b       the add-ons switched on, as on the firm's real system
#   practice-space list
#
# A space is the database practice_<slug>, copied from the demo template (practice-template.sh),
# reached at <slug>.<practice domain>. Every command refuses a name that is not practice_<valid slug>
# before it touches anything: the staging, firm, system and template databases cannot be named.
#
# The first administrator: create generates a password and writes it, with the login and the
# address, to /etc/auditisa-practice/secrets/logins/<slug> (root only, mode 600). It is never
# printed, logged or put on a command line.
#
# Reset puts the space back to fresh demonstration data: the database is dropped and copied again
# from the template, with the same add-ons. The first administrator KEEPS the same login and
# password, so the firm is not locked out; --new-password draws a new one into the same file. All
# else typed in the space is gone, including passwords given to the demonstration people.
#
# Add-ons beyond the base ones must be add-ons of the release in use (never ea_platform_*). One the
# space no longer lists stays installed until the next reset, which installs only the listed ones.

set -euo pipefail
umask 077
SCRIPT_NAME=practice-space
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/practice/practice-lib.sh
. "$HERE/practice-lib.sh"

SLUG="" NAME="" ADMIN_LOGIN="" ADDONS="" LANG_CODE="" NEW_PASSWORD=0 YES=0 SET_ADDONS="" HAS_SET=0

parse() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --slug) SLUG=${2:?--slug needs a value}; shift ;;
      --name) NAME=${2:?--name needs a value}; shift ;;
      --admin-login) ADMIN_LOGIN=${2:?--admin-login needs a value}; shift ;;
      --addons) ADDONS=${2-}; shift ;;
      --set) SET_ADDONS=${2-}; HAS_SET=1; shift ;;
      --lang) LANG_CODE=${2:?--lang needs a value}; shift ;;
      --new-password) NEW_PASSWORD=1 ;;
      --yes) YES=1 ;;
      *) pl_die "unknown option $1 (see --help)" ;;
    esac
    shift
  done
  [ -n "$SLUG" ] || pl_die "--slug is required"
  valid_slug "$SLUG" || pl_die "refused: '$SLUG' is not a valid practice space name"
  require_space_db "$(space_db "$SLUG")"
}

# Checks a comma list of add-ons against the release in use.
checked_addons() {
  local list=$1 allowed name out=""
  [ -n "$list" ] || return 0
  [[ $list =~ ^[a-z][a-z0-9_]*(,[a-z][a-z0-9_]*)*$ ]] || pl_die "invalid add-on list"
  allowed=$(release_addons "$PRACTICE_CURRENT/addons") || pl_die "the release's manifests cannot be read"
  IFS=, read -ra names <<<"$list"
  for name in "${names[@]}"; do
    valid_addon "$name" || pl_die "refused add-on '$name'"
    grep -qxF -- "$name" <<<"$allowed" || pl_die "'$name' is not an add-on of release $(current_release)"
    [[ ,$out, == *,$name,* ]] || out=${out:+$out,}$name
  done
  printf '%s' "$out"
}

take_lock() {
  exec 7>/run/lock/practice-space.lock
  flock -w 600 7 || pl_die "another practice operation is running"
}

require_template() {
  TEMPLATE_ID=$(template_id)
  [ -n "$TEMPLATE_ID" ] || pl_die "no demo template yet: run practice-template build"
  db_exists "$TEMPLATE_DB" || pl_die "the demo template database is missing: run practice-template build"
  local built_on
  built_on=$(sed -n "s/^RELEASE='\(.*\)'$/\1/p" "$PRACTICE_VAR/template.env")
  [ "$built_on" = "$(current_release)" ] || pl_die "the demo template is from release ${built_on:-unknown}, the spaces run $(current_release): run practice-template build"
}

# Drops a space's database and files. The only DROP in this script, behind the name gate.
drop_space() {
  local db
  db=$(space_db "$1")
  require_space_db "$db"
  if db_exists "$db"; then
    psql_q "ALTER DATABASE \"$db\" ALLOW_CONNECTIONS false" >/dev/null
    psql_q "DROP DATABASE \"$db\" WITH (FORCE)" >/dev/null
  fi
  rm -rf "${PRACTICE_PREFIX}${PRACTICE_DATA_DIR:?}/filestore/$db"
}

# Copies the template into practice_<slug>, with its files, and installs the space's add-ons.
copy_template() {
  local slug=$1 addons=$2 db store log
  db=$(space_db "$slug")
  require_space_db "$db"
  db_exists "$db" && pl_die "$db exists already"
  pl_log "copying the demo template to $db"
  runuser -u postgres -- createdb -O "$DB_ROLE" -T "$TEMPLATE_DB" "$db"
  # Odoo keeps a loaded space in memory. A new registry number makes it reload this one, should
  # the same name have existed before (a reset, or a space deleted and created again).
  psql_q "SELECT setval(pg_get_serial_sequence('orm_signaling_registry', 'id'), extract(epoch from now())::int); INSERT INTO orm_signaling_registry DEFAULT VALUES" "$db" >/dev/null
  store=$PRACTICE_PREFIX$PRACTICE_DATA_DIR/filestore
  if [ -d "$store/$TEMPLATE_DB" ]; then
    rm -rf "${store:?}/$db"
    cp -a "$store/$TEMPLATE_DB" "$store/$db"
    chown -R "$ODOO_USER:$ODOO_USER" "$store/$db"
  fi
  if [ -n "$addons" ]; then
    log=$ODOO_LOGS/space-$slug-addons-$(date -u +%Y%m%dT%H%M%SZ).log
    pl_log "installing the add-ons $addons (log: $log)"
    odoo_run "$db" "$log" -i "$addons" --without-demo=True 7>&- || { show_errors "$log"; pl_die "add-ons failed, see $log"; }
    if log_has_errors "$log"; then show_errors "$log"; pl_die "add-ons logged errors, see $log"; fi
  fi
}

new_password() { openssl rand -base64 18 | tr '+/' '-_' | tr -d '=\n'; }

write_login() {
  local slug=$1 login=$2 password=$3 file
  file=$(login_file "$slug")
  install -d -m 700 "$PRACTICE_LOGINS"
  (
    umask 077
    printf 'space=%s\naddress=%s\nlogin=%s\npassword=%s\n' "$slug" "$(space_entry_url "$slug")" "$login" "$password" > "$file.tmp"
  )
  chmod 600 "$file.tmp"
  mv -f "$file.tmp" "$file"
}

read_password() { sed -n 's/^password=//p' "$(login_file "$1")" 2>/dev/null | head -n 1 || true; }

# The space's own identity: the firm's name, its first administrator, its addresses, fresh secrets.
# Secrets go on stdin; the rest are names checked above.
configure_space() {
  local slug=$1 name=$2 login=$3 lang=$4 password=$5 db log result
  db=$(space_db "$slug")
  log=$ODOO_LOGS/space-$slug-$(date -u +%Y%m%dT%H%M%SZ).log
  result=$({
    printf 'ADMIN_PASSWORD = "%s"\nDB_SECRET = "%s"\nDB_UUID = "%s"\n' "$password" "$(openssl rand -hex 32)" "$(cat /proc/sys/kernel/random/uuid)"
    cat <<'PY'
import os

slug = os.environ["P_SLUG"]
lang = os.environ["P_LANG"]
params = env["ir.config_parameter"].sudo()
assert params.get_param("ea_practice.template_id") == os.environ["P_TEMPLATE_ID"], "not a copy of this template"
params.set_param("database.secret", DB_SECRET)
params.set_param("database.uuid", DB_UUID)
params.set_param("ea_practice.space", slug)
params.set_param("ea_practice.reset_at", os.environ["P_NOW"])
params.set_param("web.base.url", os.environ["P_PUBLIC_URL"])
params.set_param("web.base.url.freeze", "True")
params.set_param("report.url", os.environ["P_LOCAL_URL"])
# Mail, again: nothing leaves a practice space.
params.set_param("ea_firm_agent.mail_gate", "1")
for key in ("ea_firm_agent.mail_tested", "ea_firm_agent.heartbeat_url", "ea_firm_agent.slug"):
    params.search([("key", "=", key)]).unlink()
env["ir.mail_server"].sudo().with_context(active_test=False).search([]).write({"active": False})

env["res.lang"]._activate_lang(lang)
company = env.ref("base.main_company")
company.name = os.environ["P_NAME"]
company.partner_id.lang = lang
admin = env.ref("base.user_admin")
admin.with_context(no_reset_password=True).write({
    "login": os.environ["P_LOGIN"],
    "name": os.environ["P_ADMIN_NAME"],
    "email": os.environ["P_LOGIN"] if "@" in os.environ["P_LOGIN"] else False,
    "lang": lang,
    "active": True,
    "password": ADMIN_PASSWORD,
})
env.cr.commit()
print("PRACTICE_SPACE_READY")
PY
  } | odoo_shell "$db" "$log" P_SLUG="$slug" P_LANG="$lang" P_NAME="$name" P_LOGIN="$login" \
        P_ADMIN_NAME="$( [ "${lang%%_*}" = fr ] && echo 'Administrateur' || echo 'Administrator')" \
        P_TEMPLATE_ID="$TEMPLATE_ID" P_NOW="$(now_utc)" P_PUBLIC_URL="$(space_public_url "$slug")" \
        P_LOCAL_URL="$(space_local_url "$slug")" 7>&-) || true
  [[ $result == *PRACTICE_SPACE_READY* ]] || { show_errors "$log"; pl_die "setting the space up failed, see $log"; }
}

build_space() {
  local slug=$1 password=$2 name
  name=$(printf '%s' "$SPACE_NAME_B64" | base64 -d)
  copy_template "$slug" "$SPACE_ADDONS"
  configure_space "$slug" "$name" "$SPACE_ADMIN_LOGIN" "$SPACE_LANG" "$password"
  if ! space_answers "$slug"; then
    pl_warn "the space does not answer yet at $(space_local_url "$slug") (is $PRACTICE_SERVICE running?)"
  fi
}

cmd_create() {
  parse "$@"
  [ -n "$NAME" ] && [ -n "$ADMIN_LOGIN" ] || pl_die "create needs --name and --admin-login"
  [ "${#NAME}" -le 80 ] && [[ $NAME != *$'\n'* ]] || pl_die "invalid firm name"
  valid_login "$ADMIN_LOGIN" || pl_die "invalid login '$ADMIN_LOGIN'"
  load_practice_env
  [ "$(id -u)" = 0 ] || pl_die "run as root"
  cd /
  LANG_CODE=${LANG_CODE:-$PRACTICE_LANG}
  valid_lang "$LANG_CODE" || pl_die "invalid language '$LANG_CODE'"
  take_lock
  require_template
  [ ! -e "$(space_file "$SLUG")" ] || pl_die "space '$SLUG' exists already: reset or delete it"
  [ ! -e "$(login_file "$SLUG")" ] || pl_die "$(login_file "$SLUG") exists from an earlier space: move it away first"

  SPACE_NAME_B64=$(printf '%s' "$NAME" | base64 -w0)
  SPACE_ADMIN_LOGIN=$ADMIN_LOGIN
  SPACE_ADDONS=$(checked_addons "$ADDONS")
  SPACE_LANG=$LANG_CODE
  SPACE_CREATED_AT=$(now_utc)
  SPACE_RESET_AT=$SPACE_CREATED_AT
  SPACE_TEMPLATE_ID=$TEMPLATE_ID

  local password
  password=$(new_password)
  write_login "$SLUG" "$ADMIN_LOGIN" "$password"
  # Recorded before the copy, so practice-guard knows the database being made is expected.
  write_space "$SLUG"
  build_space "$SLUG" "$password"
  unset password
  audit_line "create slug=$SLUG addons=${SPACE_ADDONS:-none}"
  pl_log "space ready: $(space_entry_url "$SLUG")"
  pl_log "first administrator: $ADMIN_LOGIN; password in $(login_file "$SLUG") (root only)"
}

cmd_reset() {
  parse "$@"
  load_practice_env
  [ "$(id -u)" = 0 ] || pl_die "run as root"
  cd /
  take_lock
  require_template
  load_space "$SLUG"
  local password=""
  if [ "$NEW_PASSWORD" = 0 ]; then password=$(read_password "$SLUG"); fi
  if [ -z "$password" ]; then
    password=$(new_password)
    write_login "$SLUG" "$SPACE_ADMIN_LOGIN" "$password"
    pl_log "a new password for the first administrator, in $(login_file "$SLUG")"
  fi
  SPACE_RESET_AT=$(now_utc)
  SPACE_TEMPLATE_ID=$TEMPLATE_ID
  write_space "$SLUG"
  pl_log "putting $SLUG back to fresh demonstration data"
  drop_space "$SLUG"
  build_space "$SLUG" "$password"
  unset password
  audit_line "reset slug=$SLUG new_password=$NEW_PASSWORD"
  pl_log "space reset: $(space_entry_url "$SLUG")"
}

cmd_delete() {
  parse "$@"
  [ "$YES" = 1 ] || pl_die "delete removes the space and its logins: add --yes"
  load_practice_env
  [ "$(id -u)" = 0 ] || pl_die "run as root"
  cd /
  take_lock
  [ -e "$(space_file "$SLUG")" ] || db_exists "$(space_db "$SLUG")" || pl_die "no practice space '$SLUG'"
  drop_space "$SLUG"
  if [ -e "$(login_file "$SLUG")" ]; then shred -u "$(login_file "$SLUG")" 2>/dev/null || rm -f "$(login_file "$SLUG")"; fi
  rm -f "$(space_file "$SLUG")"
  audit_line "delete slug=$SLUG"
  pl_log "space $SLUG deleted"
}

cmd_addons() {
  parse "$@"
  [ "$HAS_SET" = 1 ] || pl_die "addons needs --set a,b (empty for none)"
  load_practice_env
  [ "$(id -u)" = 0 ] || pl_die "run as root"
  cd /
  take_lock
  load_space "$SLUG"
  local wanted new=() name log db
  wanted=$(checked_addons "$SET_ADDONS")
  db=$(space_db "$SLUG")
  IFS=, read -ra names <<<"$wanted"
  for name in ${names[@]+"${names[@]}"}; do
    [[ ,$SPACE_ADDONS, == *,$name,* ]] || new+=("$name")
  done
  if [ ${#new[@]} -gt 0 ]; then
    log=$ODOO_LOGS/space-$SLUG-addons-$(date -u +%Y%m%dT%H%M%SZ).log
    pl_log "installing ${new[*]} on $SLUG (log: $log)"
    odoo_run "$db" "$log" -i "$(IFS=,; echo "${new[*]}")" --without-demo=True 7>&- || { show_errors "$log"; pl_die "add-ons failed, see $log"; }
    if log_has_errors "$log"; then show_errors "$log"; pl_die "add-ons logged errors, see $log"; fi
    # The running service learns of new modules through the registry number.
    psql_q "INSERT INTO orm_signaling_registry DEFAULT VALUES" "$db" >/dev/null
  fi
  SPACE_ADDONS=$wanted
  write_space "$SLUG"
  audit_line "addons slug=$SLUG set=${wanted:-none}"
  pl_log "add-ons of $SLUG: ${wanted:-none}"
}

cmd_list() {
  load_practice_env
  local slug
  printf '%-24s %-22s %-22s %s\n' SPACE CREATED LAST_RESET ADDONS
  while read -r slug; do
    [ -n "$slug" ] || continue
    ( load_space "$slug"; printf '%-24s %-22s %-22s %s\n' "$slug" "$SPACE_CREATED_AT" "$SPACE_RESET_AT" "${SPACE_ADDONS:--}" )
  done < <(list_spaces)
}

case "${1:-}" in
  create) shift; cmd_create "$@" ;;
  reset) shift; cmd_reset "$@" ;;
  delete) shift; cmd_delete "$@" ;;
  addons) shift; cmd_addons "$@" ;;
  list) cmd_list ;;
  *) sed -n '2,25p' "$0"; exit 64 ;;
esac
