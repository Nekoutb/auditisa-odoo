#!/usr/bin/env bash
# practice-template.sh: the demo template every practice space is copied from.
#
#   practice-template build [--lang fr_FR]    builds it on the current release (a few minutes)
#   practice-template status                  which release and when
#
# The template is a database of made-up data only: the firm "Cabinet Démo", its five people and
# its clients and files, from ea_audit_ui/demo (the same as the demonstration on staging). Odoo's
# own demonstration records are not loaded. Every password is cleared, Odoo's demo and portal
# accounts are archived, mail is off. Each build gets a new random id, written in the template and
# in template.env: practice-guard serves only databases that carry the id of a build of this
# computer.
#
# The new template is built under another name and swapped in at the end, so a failed build
# leaves the previous one in place. Once built, nobody can connect to it: PostgreSQL copies it
# (createdb -T), Odoo never opens it.

set -euo pipefail
umask 077
SCRIPT_NAME=practice-template
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/practice/practice-lib.sh
. "$HERE/practice-lib.sh"

cmd_status() {
  load_practice_env
  if [ -r "$PRACTICE_VAR/template.env" ]; then
    sed -n "s/^\(RELEASE\|BUILT_AT\|LANG\)='\(.*\)'$/\1 \2/p" "$PRACTICE_VAR/template.env"
  else
    printf 'no template yet\n'
  fi
}

# Drops a database this script owns (the template or its build) and its files.
drop_own() {
  local db=$1
  case "$db" in
    "$TEMPLATE_DB"|"$TEMPLATE_BUILD_DB") ;;
    *) pl_die "refused: practice-template only drops its own databases" ;;
  esac
  if db_exists "$db"; then
    psql_q "ALTER DATABASE \"$db\" IS_TEMPLATE false" >/dev/null
    psql_q "ALTER DATABASE \"$db\" ALLOW_CONNECTIONS true" >/dev/null
    terminate_connections "$db"
    psql_q "DROP DATABASE \"$db\"" >/dev/null
  fi
  rm -rf "${PRACTICE_PREFIX}${PRACTICE_DATA_DIR:?}/filestore/$db"
}

cmd_build() {
  local lang=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --lang) lang=${2:?}; shift ;;
      *) pl_die "unknown option $1" ;;
    esac
    shift
  done
  load_practice_env
  lang=${lang:-$PRACTICE_LANG}
  valid_lang "$lang" || pl_die "invalid language '$lang'"
  [ "$(id -u)" = 0 ] || pl_die "run as root"
  cd /
  exec 7>/run/lock/practice-template.lock
  flock -n 7 || pl_die "another template build is running"

  local release addons stamp ulog id
  release=$(current_release)
  [ -n "$release" ] || pl_die "no current release"
  addons=$(base_addons "$PRACTICE_CURRENT/addons")
  [[ $addons == *ea_audit_ui* ]] || pl_die "the release has no ea_audit_ui: no demonstration data to build from"
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  ulog=$ODOO_LOGS/template-$release-$stamp.log
  : > "$ulog"
  chown "$ODOO_USER" "$ulog"
  id=$(openssl rand -hex 16)

  drop_own "$TEMPLATE_BUILD_DB"
  pl_log "creating $TEMPLATE_BUILD_DB on release $release (log: $ulog)"
  runuser -u postgres -- createdb -O "$DB_ROLE" -E UTF8 -T template0 --lc-collate=C --lc-ctype=C.UTF-8 "$TEMPLATE_BUILD_DB"
  psql_q "CREATE EXTENSION IF NOT EXISTS pg_trgm" "$TEMPLATE_BUILD_DB" >/dev/null

  pl_log "installing $addons, no Odoo demonstration records"
  odoo_run "$TEMPLATE_BUILD_DB" "$ulog" -i "$addons" --without-demo=True --load-language="$lang,en_US" 7>&- \
    || { show_errors "$ulog"; pl_die "the installation failed, see $ulog"; }
  if log_has_errors "$ulog"; then show_errors "$ulog"; pl_die "the installation logged errors, see $ulog"; fi

  pl_log "loading the demonstration firm and setting the template up"
  local result
  result=$(cat <<'PY' | odoo_shell "$TEMPLATE_BUILD_DB" "$ulog" P_ID="$id" P_RELEASE="$release" P_LANG="$lang" EA_AUDIT_DEMO_LANG="$lang" 7>&-
import os
import time

from odoo.tools.convert import convert_file

lang = os.environ["P_LANG"]
for code in {lang, "en_US"}:
    env["res.lang"]._activate_lang(code)
env.ref("base.main_company").partner_id.lang = lang
env.ref("base.user_admin").lang = lang
# ea_audit_ui's demonstration data, as the module's demo files load it, without Odoo's own.
convert_file(env, "ea_audit_ui", "demo/demo_data.xml", {}, mode="init", noupdate=True)

params = env["ir.config_parameter"].sudo()
params.set_param("ea_practice.template_id", os.environ["P_ID"])
params.set_param("ea_practice.template_release", os.environ["P_RELEASE"])
# Mail: nothing can leave a practice space. The running service's scheduler may be touching these jobs in
# this new database at the same moment: what is done so far is saved first, then the jobs are switched off
# in a short step of their own, tried again if the scheduler was on them.
env.cr.commit()
mail_jobs = [cron.id for cron in (env.ref(xmlid, raise_if_not_found=False) for xmlid in
             ("mail.ir_cron_mail_scheduler_action", "mail.ir_cron_mail_gateway_action")) if cron]
for attempt in range(10):
    try:
        if mail_jobs:
            env.cr.execute("UPDATE ir_cron SET active = false WHERE id = ANY(%s)", [mail_jobs])
        env.cr.commit()
        break
    except Exception:
        env.cr.rollback()
        if attempt == 9:
            raise
        time.sleep(3)
env.invalidate_all()
env["ir.mail_server"].sudo().search([]).write({"active": False})
params.set_param("mail.catchall.domain", False)
params.set_param("ea_firm_agent.mail_gate", "1")
for key in ("ea_firm_agent.mail_tested", "ea_firm_agent.heartbeat_url", "ea_firm_agent.slug"):
    params.search([("key", "=", key)]).unlink()
# Odoo's own demo and portal accounts, if any: archived.
env["res.users"].sudo().with_context(active_test=False).search([("login", "in", ("demo", "portal"))]).write({"active": False})
env.cr.commit()
print("PRACTICE_TEMPLATE_READY", env["ea.audit.engagement"].sudo().search_count([]))
PY
  ) || true
  [[ $result == *PRACTICE_TEMPLATE_READY* ]] || { show_errors "$ulog"; pl_die "setting the template up failed, see $ulog"; }
  local missions=${result##*PRACTICE_TEMPLATE_READY }
  [[ $missions =~ ^[0-9]+$ ]] && [ "$missions" -ge 1 ] || pl_die "the template has no demonstration file, see $ulog"
  if log_has_errors "$ulog"; then show_errors "$ulog"; pl_die "setting the template up logged errors, see $ulog"; fi

  # No password at all in the template: each space's first administrator gets one of its own.
  psql_q "UPDATE res_users SET password = NULL" "$TEMPLATE_BUILD_DB" >/dev/null
  # No session token, no API key, no secret shared by the copies: each space draws its own.
  psql_q "DELETE FROM res_users_apikeys" "$TEMPLATE_BUILD_DB" >/dev/null 2>&1 || true
  psql_q "DELETE FROM ir_config_parameter WHERE key IN ('database.secret', 'database.uuid')" "$TEMPLATE_BUILD_DB" >/dev/null

  pl_log "swapping the new template in ($missions demonstration files)"
  drop_own "$TEMPLATE_DB"
  terminate_connections "$TEMPLATE_BUILD_DB"
  psql_q "ALTER DATABASE \"$TEMPLATE_BUILD_DB\" RENAME TO \"$TEMPLATE_DB\"" >/dev/null
  psql_q "ALTER DATABASE \"$TEMPLATE_DB\" IS_TEMPLATE true ALLOW_CONNECTIONS false" >/dev/null
  local store=$PRACTICE_PREFIX$PRACTICE_DATA_DIR/filestore
  if [ -d "$store/$TEMPLATE_BUILD_DB" ]; then mv -T "$store/$TEMPLATE_BUILD_DB" "$store/$TEMPLATE_DB"; fi

  local tmp
  tmp=$(mktemp "$PRACTICE_VAR/.template.XXXXXX")
  printf "TEMPLATE_ID='%s'\nRELEASE='%s'\nBUILT_AT='%s'\nLANG='%s'\n" "$id" "$release" "$(now_utc)" "$lang" > "$tmp"
  chmod 644 "$tmp"
  mv -f "$tmp" "$PRACTICE_VAR/template.env"
  audit_line "template built release=$release"
  pl_log "template ready on release $release"
}

case "${1:-}" in
  build) shift; cmd_build "$@" ;;
  status) cmd_status ;;
  *) sed -n '2,17p' "$0"; exit 64 ;;
esac
