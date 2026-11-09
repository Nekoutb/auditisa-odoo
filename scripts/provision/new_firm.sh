#!/usr/bin/env bash
# new_firm.sh: create one firm's Odoo database (decision I-1: one database per firm).
#
#   new_firm.sh --db <name> --name "<firm>" --admin-email <email> [options]
#
#   --db NAME            database name: lower case, digits, underscore
#   --name TEXT          the firm's name (res.company)
#   --admin-email EMAIL  e-mail of the firm's administrator
#   --admin-login TEXT   login of the administrator (default: the e-mail)
#   --admin-name TEXT    display name of the administrator (default: Administrateur)
#   --lang CODE          language (default: fr_FR)
#   --tz ZONE            time zone (default: Africa/Douala)
#   --addons a,b,c       addons to install (default: base,web,mail plus every ea_audit_*
#                        addon of the current release)
#   --allow-mail         keep the mail crons on. Default is off: a new database sends nothing
#   --dry-run            print what would be done and change nothing
#
# Runs as root on the server. The admin password is generated here and written only to
# $SECRETS_DIR/<db>.admin (root, mode 600); it is never printed, logged or put on a command line.
#
# No demo data. An existing database is never touched, and the staging database is refused by
# name. If the script fails, the half-built database stays for inspection; nothing is dropped.
#
# The role in odoo.conf has NOCREATEDB, so the database is created as the postgres OS user.
# A new database is not reachable over HTTP until `dbfilter` and nginx allow it: the script warns.

set -euo pipefail
umask 077

: "${ODOO_PY:=/opt/odoo19/venv/bin/python}"
: "${ODOO_BIN:=/opt/odoo19/src/odoo-bin}"
: "${ODOO_CONF:=/etc/odoo/odoo.conf}"
: "${ODOO_USER:=odoo}"
: "${SECRETS_DIR:=/root/.auditisa/firms}"
: "${ADDONS_ROOT:=/opt/auditisa-odoo/current/addons}"
: "${LOG_DIR:=/var/log/odoo}"
: "${INIT_MEM:=1400M}"

# Not overridable from the environment.
readonly PROTECTED_DBS="ea_audit_odoo_staging postgres template0 template1"

DB="" FIRM="" ADMIN_EMAIL="" ADMIN_LOGIN="" ADMIN_NAME="Administrateur"
LANG_CODE=fr_FR TZ_NAME=Africa/Douala ADDONS="" MAIL_OFF=1 DRY_RUN=0

log() { printf '[new_firm] %s\n' "$*"; }
warn() { printf '[new_firm] WARNING: %s\n' "$*" >&2; }
die() { printf '[new_firm] ERROR: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,24p' "$0"; exit 64; }

while [ $# -gt 0 ]; do
  case "$1" in
    --db) DB=${2:?--db needs a value}; shift ;;
    --name) FIRM=${2:?--name needs a value}; shift ;;
    --admin-email) ADMIN_EMAIL=${2:?--admin-email needs a value}; shift ;;
    --admin-login) ADMIN_LOGIN=${2:?--admin-login needs a value}; shift ;;
    --admin-name) ADMIN_NAME=${2:?--admin-name needs a value}; shift ;;
    --lang) LANG_CODE=${2:?--lang needs a value}; shift ;;
    --tz) TZ_NAME=${2:?--tz needs a value}; shift ;;
    --addons) ADDONS=${2:?--addons needs a value}; shift ;;
    --allow-mail) MAIL_OFF=0 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage ;;
    *) die "unknown option $1 (see --help)" ;;
  esac
  shift
done

[ -n "$DB" ] && [ -n "$FIRM" ] && [ -n "$ADMIN_EMAIL" ] || usage
[[ $DB =~ ^[a-z][a-z0-9_]{1,62}$ ]] || die "invalid database name '$DB'"
[[ $DB != *_predeploy && $DB != *_failed_* ]] || die "'$DB' is a name reserved for deployment snapshots"
for protected in $PROTECTED_DBS; do
  [ "$DB" != "$protected" ] || die "refusing to provision '$DB': it is a protected database"
done
[[ $ADMIN_EMAIL =~ ^[^[:space:]@]+@[^[:space:]@]+$ ]] || die "invalid e-mail '$ADMIN_EMAIL'"
[[ $LANG_CODE =~ ^[a-z]{2,3}(_[A-Z]{2})?$ ]] || die "invalid language '$LANG_CODE'"
[[ $TZ_NAME =~ ^[A-Za-z_+-]+(/[A-Za-z0-9_+-]+)*$ ]] || die "invalid time zone '$TZ_NAME'"
ADMIN_LOGIN=${ADMIN_LOGIN:-$ADMIN_EMAIL}

if [ -z "$ADDONS" ]; then
  ADDONS=base,web,mail
  if [ -d "$ADDONS_ROOT" ]; then
    while IFS= read -r manifest; do
      ADDONS="$ADDONS,$(basename "$(dirname "$manifest")")"
    done < <(find "$ADDONS_ROOT" -mindepth 2 -maxdepth 2 -name __manifest__.py -path '*/ea_audit_*' | sort)
  fi
fi
[[ $ADDONS =~ ^[a-z0-9_]+(,[a-z0-9_]+)*$ ]] || die "invalid addon list '$ADDONS'"
[[ ,$ADDONS, == *,base,* ]] || ADDONS="base,$ADDONS"

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
SECRET_FILE=$SECRETS_DIR/$DB.admin
ODOO_LOG=$LOG_DIR/provision-$DB-$STAMP.log

if [ "$DRY_RUN" = 1 ]; then
  log "DRY RUN: nothing is changed"
  log "database:  $DB (owner $ODOO_USER, UTF-8, created as postgres, extension pg_trgm)"
  log "firm:      $FIRM"
  log "language:  $LANG_CODE, time zone: $TZ_NAME"
  log "admin:     $ADMIN_NAME, login $ADMIN_LOGIN, e-mail $ADMIN_EMAIL"
  log "password:  would be generated and written to $SECRET_FILE (root, 600)"
  log "addons:    $ADDONS (no demo data)"
  log "mail:      $([ "$MAIL_OFF" = 1 ] && echo 'crons and mail servers off' || echo 'left as installed')"
  log "odoo log:  $ODOO_LOG"
  if [ "$(id -u)" = 0 ] && command -v psql >/dev/null; then
    if [ -n "$(runuser -u postgres -- psql -XAtc "SELECT 1 FROM pg_database WHERE datname = '$DB'" 2>/dev/null)" ]; then
      warn "database $DB already exists: a real run would refuse"
    fi
    [ ! -e "$SECRET_FILE" ] || warn "$SECRET_FILE already exists: a real run would refuse"
  else
    log "(existing database and secret file not checked: needs root and psql)"
  fi
  exit 0
fi

[ "$(id -u)" = 0 ] || die "run as root"
cd /
for tool in runuser psql createdb systemd-run openssl; do
  command -v "$tool" >/dev/null || die "$tool is not installed"
done
[ -x "$ODOO_PY" ] && [ -f "$ODOO_BIN" ] && [ -r "$ODOO_CONF" ] || die "Odoo not found ($ODOO_PY, $ODOO_BIN, $ODOO_CONF)"

pg_admin() { runuser -u postgres -- "$@"; }
psql_db() { pg_admin psql -X -v ON_ERROR_STOP=1 -At -d "$1" -c "$2"; }

[ -z "$(psql_db postgres "SELECT 1 FROM pg_database WHERE datname = '$DB'")" ] \
  || die "database $DB already exists: nothing was changed"
[ ! -e "$SECRET_FILE" ] || die "$SECRET_FILE already exists from an earlier attempt: move it away first"

# The memory ceiling keeps an installation from squeezing the running service.
odoo_cli() {
  systemd-run --quiet --scope --collect -p "MemoryMax=$INIT_MEM" -p MemorySwapMax=2G \
    nice -n 10 runuser -u "$ODOO_USER" -- "$@"
}

log "generating the admin password"
install -d -o root -g root -m 700 "$(dirname "$SECRETS_DIR")" "$SECRETS_DIR"
ADMIN_PASSWORD=$(openssl rand -hex 24)
(
  umask 077
  printf 'database=%s\nlogin=%s\npassword=%s\n' "$DB" "$ADMIN_LOGIN" "$ADMIN_PASSWORD" > "$SECRET_FILE"
)
chown root:root "$SECRET_FILE"
chmod 600 "$SECRET_FILE"

log "creating database $DB"
pg_admin createdb -O "$ODOO_USER" -E UTF8 -T template0 --lc-collate=C --lc-ctype=C.UTF-8 "$DB"
psql_db "$DB" "CREATE EXTENSION IF NOT EXISTS pg_trgm" >/dev/null

log "installing $ADDONS (log: $ODOO_LOG)"
install -d -o "$ODOO_USER" -g "$ODOO_USER" -m 750 "$LOG_DIR"
odoo_cli "$ODOO_PY" "$ODOO_BIN" -c "$ODOO_CONF" -d "$DB" -i "$ADDONS" --without-demo=True \
  --load-language="$LANG_CODE" --no-http --max-cron-threads=0 --stop-after-init --logfile="$ODOO_LOG" \
  || die "installation failed, see $ODOO_LOG; database $DB is left for inspection"
if grep -qE ' (ERROR|CRITICAL) ' "$ODOO_LOG"; then
  grep -E ' (ERROR|CRITICAL) ' "$ODOO_LOG" | tail -n 5 | cut -c1-300 >&2
  die "the installation logged errors, see $ODOO_LOG; database $DB is left for inspection"
fi

# Every requested addon must really be installed: Odoo only warns about an unknown name.
IFS=, read -ra addon_list <<<"$ADDONS"
printf -v wanted "'%s'," "${addon_list[@]}"
wanted=${wanted%,}
missing=$(psql_db "$DB" "SELECT string_agg(w, ', ') FROM unnest(ARRAY[$wanted]) w
  WHERE w NOT IN (SELECT name FROM ir_module_module WHERE state = 'installed')")
[ -z "$missing" ] || die "not installed: $missing (see $ODOO_LOG)"

log "setting the firm's name, language, time zone and administrator"
# The password travels on the script's stdin, never in argv or in the environment.
{
  printf 'ADMIN_PASSWORD = "%s"\n' "$ADMIN_PASSWORD"
  cat <<'PY'
import os

firm = os.environ["FIRM_NAME"]
email = os.environ["FIRM_ADMIN_EMAIL"]
lang = os.environ["FIRM_LANG"]
tz = os.environ["FIRM_TZ"]

if os.environ["FIRM_MAIL_OFF"] == "1" and "_notify_security_setting_update" in dir(env["res.users"]):
    # A brand-new database has nobody to tell that its admin's login and password were set, and
    # mail is off: Odoo 19 would still try to send both notices at once, to localhost:25 (seen on
    # the test firms, 2026-11-09). Skipped for this script only.
    type(env["res.users"])._notify_security_setting_update = lambda *args, **kwargs: None

company = env.ref("base.main_company")
company.write({"name": firm, "email": email})
company.partner_id.write({"lang": lang, "tz": tz})

env.ref("base.user_admin").write({
    "name": os.environ["FIRM_ADMIN_NAME"],
    "login": os.environ["FIRM_ADMIN_LOGIN"],
    "email": email,
    "lang": lang,
    "tz": tz,
    "password": ADMIN_PASSWORD,
})
env.ref("base.partner_root").write({"lang": lang, "tz": tz})
env["ir.default"].set("res.partner", "lang", lang)
env["ir.default"].set("res.partner", "tz", tz)

if os.environ["FIRM_MAIL_OFF"] == "1":
    for xmlid in ("mail.ir_cron_mail_scheduler_action", "mail.ir_cron_mail_gateway_action"):
        cron = env.ref(xmlid, raise_if_not_found=False)
        if cron:
            cron.write({"active": False})
    env["ir.mail_server"].search([]).write({"active": False})
    env["ir.config_parameter"].set_param("mail.catchall.domain", False)

env.cr.commit()
print("FIRM_CONFIGURED")
PY
} | odoo_cli env FIRM_NAME="$FIRM" FIRM_ADMIN_EMAIL="$ADMIN_EMAIL" FIRM_ADMIN_LOGIN="$ADMIN_LOGIN" \
    FIRM_ADMIN_NAME="$ADMIN_NAME" FIRM_LANG="$LANG_CODE" FIRM_TZ="$TZ_NAME" FIRM_MAIL_OFF="$MAIL_OFF" \
    "$ODOO_PY" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$DB" --no-http --max-cron-threads=0 --logfile="$ODOO_LOG" \
  | grep -x FIRM_CONFIGURED >/dev/null || die "configuring the firm failed, see $ODOO_LOG"
unset ADMIN_PASSWORD

filter=$(sed -n 's/^[[:space:]]*dbfilter[[:space:]]*=[[:space:]]*//p' "$ODOO_CONF" | head -n 1)
if [ -n "$filter" ] && [[ $filter != *%* ]] && ! [[ $DB =~ $filter ]]; then
  warn "dbfilter in $ODOO_CONF does not match $DB: the firm is not reachable over HTTP until it is changed"
fi

log "firm '$FIRM' is ready in database $DB"
log "admin login: $ADMIN_LOGIN; password in $SECRET_FILE (root only)"
