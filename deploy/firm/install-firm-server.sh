#!/usr/bin/env bash
# install-firm-server.sh: builds one firm's server, from the pins in recipe.env.
#
#   install-firm-server.sh --env FILE --bundle FILE          for real, as root, on a new server
#   install-firm-server.sh --env FILE --dry-run --root DIR   prints every command and writes the
#                                                            configuration files under DIR, nothing else
#
# Run by cloud-init on first boot (the control plane's step "Création du serveur"). Each step leaves
# a marker in /root/.firm-install-state, so running it again carries on where it stopped.
#
# Generated here and never sent anywhere: the PostgreSQL password, Odoo's master password, the admin
# account's throwaway password, the backup key. The operator copies the backup key to a safe by
# hand: see docs/runbook/BACKUP-RESTORE.md.
#
# Modelled on the staging install (Documents/Odoo-migration/server/install-odoo19-staging.sh).
# Not yet run on a real server: only --dry-run has been. See docs/runbook/PREREQUISITES.md.

set -euo pipefail
umask 077
SCRIPT_NAME=install-firm-server
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

ENV_FILE="" BUNDLE="" DRY_RUN=0 DRY_ROOT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --env) ENV_FILE=${2:?}; shift ;;
    --bundle) BUNDLE=${2:?}; shift ;;
    --dry-run) DRY_RUN=1 ;;
    --root) DRY_ROOT=${2:?}; shift ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) printf 'unknown option %s\n' "$1" >&2; exit 64 ;;
  esac
  shift
done

if [ "$DRY_RUN" = 1 ]; then
  [ -n "$DRY_ROOT" ] || DRY_ROOT=$(mktemp -d)
  mkdir -p "$DRY_ROOT"
  DRY_ROOT=$(cd "$DRY_ROOT" && pwd)
  # Everything below writes under this folder.
  export FIRM_PREFIX=$DRY_ROOT
fi
# cloud-init starts this from /root, which the odoo user cannot read: uv then fails on
# /root/uv.toml (seen on the first real firm, 2026-11-09). Work from / and ignore uv config files.
export UV_NO_CONFIG=1
if [ "$DRY_RUN" = 0 ]; then
  [ -z "$ENV_FILE" ] || ENV_FILE=$(readlink -f "$ENV_FILE")
  [ -z "$BUNDLE" ] || BUNDLE=$(readlink -f "$BUNDLE")
  cd /
fi
# shellcheck source=deploy/firm/firm-lib.sh
. "$HERE/firm-lib.sh"
# shellcheck source=deploy/firm/recipe.env
. "$HERE/recipe.env"
R=$FIRM_PREFIX

[ -n "$ENV_FILE" ] && [ -r "$ENV_FILE" ] || fl_die "--env FILE is required"
# The control plane only writes A-Za-z0-9 and ._:@/+=,- in this file (services/recipe.py).
grep -Evq "^[A-Z0-9_]+='[A-Za-z0-9 ._:@/+=,-]*'$" "$ENV_FILE" && fl_die "$ENV_FILE holds an unexpected line"
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
: "${FIRM_SLUG:?}" "${FIRM_NAME_B64:?}" "${FIRM_HOST:?}" "${FIRM_SIZE:?}" "${FIRM_LANG:?}" "${FIRM_ADMIN_EMAIL:?}"
: "${RELEASE_SHA:?}" "${RELEASE_BASE_URL:?}" "${HEARTBEAT_URL:?}" "${HEARTBEAT_TOKEN:?}" "${FIRST_ADMIN_TOKEN_SHA256:?}"
: "${SSH_ALLOWLIST:?}" "${S3_ENDPOINT:?}" "${S3_REGION:?}" "${S3_BUCKET:?}" "${S3_ACCESS_KEY:?}" "${S3_SECRET_KEY:?}"
: "${FIRM_ALLOWED_DOMAINS:=}" "${RELEASE_BUNDLE_URL_B64:=}" "${RELEASE_SIG_URL_B64:=}"
[[ $FIRM_SLUG =~ ^[a-z][a-z0-9-]{1,30}[a-z0-9]$ ]] || fl_die "invalid slug"
valid_release "$RELEASE_SHA" || fl_die "invalid release"
for cidr in $SSH_ALLOWLIST; do valid_cidr "$cidr" || fl_die "refused address for port 22: $cidr"; done

FIRM_DB=firm_${FIRM_SLUG//-/_}
FIRM_NAME=$(printf '%s' "$FIRM_NAME_B64" | base64 -d)

# Same figures as services/catalogue.py; a test keeps them in step.
case "$FIRM_SIZE" in
  small) WORKERS=3; LIMIT_HARD_MB=1100; PG_SHARED=1GB; SERVICE_MEM=3200M ;;
  standard) WORKERS=5; LIMIT_HARD_MB=1400; PG_SHARED=2GB; SERVICE_MEM=6000M ;;
  large) WORKERS=9; LIMIT_HARD_MB=1500; PG_SHARED=4GB; SERVICE_MEM=12000M ;;
  *) fl_die "unknown size $FIRM_SIZE" ;;
esac
LIMIT_HARD=$((LIMIT_HARD_MB * 1048576))
LIMIT_SOFT=$((LIMIT_HARD * 8 / 10))

STATE_FILE=$R/root/.firm-install-state

log() { fl_log "$*"; }
die() { fl_die "$*"; }

# Prints in a dry run, runs otherwise. Never give it a secret as an argument.
run() {
  if [ "$DRY_RUN" = 1 ]; then printf '+ %s\n' "$*"; else "$@"; fi
}

# render <path> <mode> <owner:group>, content on stdin.
render() {
  local path=$R$1 mode=$2 owner=$3
  mkdir -p "$(dirname "$path")"
  cat > "$path"
  chmod "$mode" "$path"
  if [ "$DRY_RUN" = 0 ]; then chown "$owner" "$path"; fi
}

# A secret is generated once and survives a re-run.
secret() {
  local path=$R$1 owner=$2 mode=$3
  mkdir -p "$(dirname "$path")"
  if [ ! -s "$path" ]; then (umask 077; openssl rand -hex 32 > "$path"); fi
  chmod "$mode" "$path"
  if [ "$DRY_RUN" = 0 ]; then chown "$owner" "$path"; fi
}

step() {
  local name=$1
  shift
  mkdir -p "$(dirname "$STATE_FILE")"
  if grep -qx "$name" "$STATE_FILE" 2>/dev/null; then
    log "already done: $name"
    return 0
  fi
  log "step: $name"
  "$@"
  printf '%s\n' "$name" >> "$STATE_FILE"
}

# ---------------------------------------------------------------------------- the steps

check_system() {
  [ "$DRY_RUN" = 1 ] && return 0
  [ "$(id -u)" = 0 ] || die "run as root"
  # shellcheck disable=SC1091
  . /etc/os-release
  [ "${VERSION_ID:-}" = "$UBUNTU_VERSION" ] || die "this recipe is pinned to Ubuntu $UBUNTU_VERSION, found ${VERSION_ID:-unknown}"
}

prepare_folders() {
  run install -d -m 755 /etc/auditisa-firm /var/lib/auditisa-firm /var/log/auditisa-firm /opt/auditisa-firm /opt/auditisa-odoo
  mkdir -p "$FIRM_ETC" "$FIRM_SECRETS" "$FIRM_STATUS" "$FIRM_SPOOL" "$FIRM_LOGS" "$BIN_DIR" "$PROVISION_DIR"
  chmod 700 "$FIRM_SECRETS"
  chmod 755 "$FIRM_STATUS"
  render /etc/auditisa-firm/firm.env 644 root:root <<EOF
FIRM_SLUG='$FIRM_SLUG'
FIRM_HOST='$FIRM_HOST'
FIRM_DB='$FIRM_DB'
FIRM_SIZE='$FIRM_SIZE'
RELEASE_BASE_URL='$RELEASE_BASE_URL'
EOF
  printf '%s\n' "$FIRM_HOST" | render /etc/auditisa-firm/domains 644 root:root
  printf '%s\n' "$SSH_ALLOWLIST" | tr ' ' '\n' | render /etc/auditisa-firm/ssh_allowlist 644 root:root
  if [ "$DRY_RUN" = 1 ] && [ ! -s "$FIRM_ETC/release-signing.pub" ]; then
    printf 'DRY-RUN SIGNING KEY\n' | render /etc/auditisa-firm/release-signing.pub 644 root:root
  fi
}

harden_ssh() {
  # 00-: sshd keeps the first value it reads, and cloud-init's 50- file says otherwise.
  render /etc/ssh/sshd_config.d/00-ea-hardening.conf 644 root:root <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
PermitEmptyPasswords no
MaxAuthTries 4
LoginGraceTime 30
X11Forwarding no
AllowUsers root
EOF
  # One key: this firm's. Whatever the image or the provider added goes.
  local key=$FIRM_ETC/ssh_authorized_key
  if [ "$DRY_RUN" = 1 ] && [ ! -s "$key" ]; then
    printf '%s\n' "${DRY_RUN_SSH_KEY:-ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI$(printf '%s' "$FIRM_SLUG" | sha256sum | cut -c1-32) dry-run}" > "$key"
  fi
  [ "$(grep -c '^ssh-ed25519 ' "$key")" = 1 ] || die "expected exactly one SSH key in $key"
  render /root/.ssh/authorized_keys 600 root:root < "$key"
  run chmod 700 /root/.ssh
  run rm -f /home/ubuntu/.ssh/authorized_keys
  run passwd --lock root
  run sshd -t
  run systemctl reload ssh

  # Every login leaves a line. Root could still erase it: see SECURITY-MODEL.md.
  render /etc/ssh/sshrc 755 root:root <<'EOF'
#!/bin/sh
printf '%s ssh-login %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(id -un)" "${SSH_CONNECTION%% *}" >> /var/log/auditisa-firm/break-glass.log
EOF
  : >> "$BREAK_GLASS_LOG"
  chmod 640 "$BREAK_GLASS_LOG"
}

install_packages() {
  # On first boot Ubuntu's own unattended-upgrades holds the dpkg lock for minutes: wait for it
  # rather than fail (seen on the first real firm, 2026-11-09). Every later apt call waits too.
  render /etc/apt/apt.conf.d/90auditisa-lock-wait 644 root:root <<'EOF'
DPkg::Lock::Timeout "900";
EOF
  export DEBIAN_FRONTEND=noninteractive
  run apt-get update -qq
  run apt-get install -y -qq --no-install-recommends "${APT_PACKAGES[@]}"
  # Optional or renamed packages: wkhtmltopdf's fonts and X libraries.
  local package
  for package in "${APT_OPTIONAL_PACKAGES[@]}"; do
    if [ "$DRY_RUN" = 1 ]; then
      printf '+ apt-get install -y -qq --no-install-recommends %s (allowed to fail)\n' "$package"
    else
      apt-get install -y -qq --no-install-recommends "$package" >/dev/null 2>&1 || log "optional package $package not available"
    fi
  done
}

configure_firewall() {
  run ufw --force reset
  run ufw default deny incoming
  run ufw default allow outgoing
  local cidr
  for cidr in $SSH_ALLOWLIST; do
    run ufw allow from "$cidr" to any port 22 proto tcp comment operator
  done
  run ufw allow 80/tcp
  run ufw allow 443/tcp
  run ufw --force enable
  { printf '# Rendered by install-firm-server.sh; applied by the commands above.\n'
    printf 'default deny incoming\n'
    for cidr in $SSH_ALLOWLIST; do printf 'allow 22/tcp from %s\n' "$cidr"; done
    printf 'allow 80/tcp\nallow 443/tcp\n'
  } | render /etc/auditisa-firm/firewall.rules 644 root:root

  # The provider's metadata address repeats the first-boot text, which holds secrets. Root only.
  render /usr/local/sbin/firm-metadata-block 755 root:root <<'EOF'
#!/bin/sh
# First in OUTPUT: appended after ufw's chains it was never reached, since ufw accepts outgoing
# connections first (first real firm, 2026-11-09: the odoo user could read the first-boot text).
iptables -D OUTPUT -d 169.254.169.254 -m owner ! --uid-owner 0 -j REJECT 2>/dev/null || true
iptables -I OUTPUT 1 -d 169.254.169.254 -m owner ! --uid-owner 0 -j REJECT
EOF
  render /etc/systemd/system/firm-metadata-block.service 644 root:root <<'EOF'
[Unit]
Description=Only root reaches the provider's metadata address
After=network-pre.target ufw.service
PartOf=ufw.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/firm-metadata-block
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
  run systemctl daemon-reload
  run systemctl enable --now firm-metadata-block.service
}

configure_fail2ban() {
  render /etc/fail2ban/filter.d/odoo-login.conf 644 root:root <<'EOF'
[Definition]
failregex = ^.* Login failed for login:.* from <HOST>$
EOF
  {
    cat <<'EOF'
[DEFAULT]
bantime = 1h
findtime = 10m
maxretry = 5
EOF
    printf 'ignoreip = 127.0.0.1/8 ::1 %s\n' "$SSH_ALLOWLIST"
    cat <<'EOF'

[sshd]
enabled = true
maxretry = 4

[odoo-login]
enabled = true
port = http,https
filter = odoo-login
logpath = /var/log/odoo/odoo.log
EOF
  } | render /etc/fail2ban/jail.d/auditisa.local 644 root:root
  run systemctl enable --now fail2ban
}

configure_unattended_updates() {
  render /etc/apt/apt.conf.d/20auto-upgrades 644 root:root <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
  # Security updates only; a reboot stays the operator's decision.
  render /etc/apt/apt.conf.d/51auditisa-unattended 644 root:root <<'EOF'
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
EOF
  run systemctl enable --now unattended-upgrades
}

configure_postgres() {
  secret /etc/auditisa-firm/secrets/db.password root:root 600
  if [ "$DRY_RUN" = 1 ]; then
    printf '+ create PostgreSQL role odoo (LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE), password read from a file\n'
  else
    systemctl enable --now postgresql
    if [ -z "$(psql_q "SELECT 1 FROM pg_roles WHERE rolname = 'odoo'")" ]; then
      # Through stdin: a password on a command line would show in ps.
      runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 -q -v "pw=$(cat "$FIRM_SECRETS/db.password")" <<'SQL'
CREATE ROLE odoo LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'pw';
SQL
    fi
  fi
  # Reachable from this machine only, and only with a password.
  local conf_dir
  conf_dir=$(find "$R/etc/postgresql" -mindepth 2 -maxdepth 2 -type d -name main 2>/dev/null | head -n 1 || true)
  [ -n "$conf_dir" ] || conf_dir=$R/etc/postgresql/$POSTGRES_VERSION/main
  render "${conf_dir#"$R"}/conf.d/auditisa.conf" 644 root:root <<EOF
listen_addresses = 'localhost'
shared_buffers = $PG_SHARED
work_mem = 32MB
ssl = off
EOF
  run systemctl restart postgresql
}

install_odoo() {
  # A re-run after a stop finds the user already there.
  if [ "$DRY_RUN" = 1 ] || ! id -u odoo >/dev/null 2>&1; then
    run useradd --system --home-dir /opt/odoo19 --no-create-home --shell /usr/sbin/nologin odoo
  fi
  run install -d -o odoo -g odoo -m 750 /opt/odoo19 /var/lib/odoo /var/log/odoo
  # uv from its pinned release, checked by digest.
  run curl -fsSL -o /tmp/uv.tar.gz "$UV_URL"
  if [ "$DRY_RUN" = 1 ]; then
    printf '+ check uv against sha256 %s\n' "$UV_SHA256"
  else
    printf '%s  /tmp/uv.tar.gz\n' "$UV_SHA256" | sha256sum -c --status - || die "uv digest differs"
  fi
  run tar -xzf /tmp/uv.tar.gz --strip-components=1 -C /usr/local/bin
  run runuser -u odoo -- env UV_PYTHON_INSTALL_DIR=/opt/odoo19/python /usr/local/bin/uv python install "$PYTHON_VERSION"
  run runuser -u odoo -- env UV_PYTHON_INSTALL_DIR=/opt/odoo19/python /usr/local/bin/uv venv --allow-existing --python "$PYTHON_VERSION" /opt/odoo19/venv
  # The commit's id is its content: this is the same tree on every firm, and the same as CI's.
  # From an empty folder, so that a re-run after a stop does not trip on the files already there.
  run rm -rf /opt/odoo19/src
  run runuser -u odoo -- git init -q /opt/odoo19/src
  run runuser -u odoo -- git -C /opt/odoo19/src fetch -q --depth 1 https://github.com/odoo/odoo "$ODOO_SHA"
  run runuser -u odoo -- git -C /opt/odoo19/src checkout -q FETCH_HEAD
  run rm -rf /opt/odoo19/src/.git
  # Same swap as staging and CI: no compile of psycopg2.
  if [ "$DRY_RUN" = 1 ]; then
    printf '+ install Odoo requirements with uv (psycopg2 replaced by psycopg2-binary)\n'
  else
    sed -E 's/^psycopg2\b/psycopg2-binary/' /opt/odoo19/src/requirements.txt > /tmp/odoo-requirements.txt
    chmod 644 /tmp/odoo-requirements.txt
    runuser -u odoo -- /usr/local/bin/uv pip install -q --python /opt/odoo19/venv/bin/python -r /tmp/odoo-requirements.txt
  fi
  run curl -fsSL -o /tmp/wkhtmltox.deb "$WKHTMLTOX_URL"
  if [ "$DRY_RUN" = 1 ]; then
    printf '+ check wkhtmltopdf against sha256 %s\n' "$WKHTMLTOX_SHA256"
  else
    printf '%s  /tmp/wkhtmltox.deb\n' "$WKHTMLTOX_SHA256" | sha256sum -c --status - || die "wkhtmltopdf digest differs"
    # Through apt, not dpkg -i: dpkg does not wait for the lock unattended-upgrades holds (first real
    # firm, 2026-11-09), and apt fetches the package's dependencies in the same go.
    chmod 644 /tmp/wkhtmltox.deb
    apt-get install -y -qq --no-install-recommends /tmp/wkhtmltox.deb
    rm -f /tmp/wkhtmltox.deb
  fi
}

install_scripts_from() {
  local source=$1 script
  mkdir -p "$BIN_DIR" "$PROVISION_DIR"
  for script in firm-lib.sh firm-backup.sh firm-restore-test.sh firm-update.sh firm-export.sh firm-anon-export.sh \
                firm-apply-desired.sh firm-addons.sh firm-support-visit.sh firm-status.sh firm-cert.sh firm-first-admin-link.sh firm-add-domain.sh \
                firm-isolation.sh firm-mail-server.sh firm_mail.py recipe.env; do
    cp -f "$source/deploy/firm/$script" "$BIN_DIR/$script"
    chmod 700 "$BIN_DIR/$script"
    case "$script" in
      firm-lib.sh|recipe.env|firm_mail.py) ;;
      *) run ln -sfn "/opt/auditisa-firm/bin/$script" "/usr/local/sbin/${script%.sh}" ;;
    esac
  done
  cp -f "$source/scripts/provision/new_firm.sh" "$source/scripts/provision/backup_firm.sh" "$PROVISION_DIR/"
  chmod 700 "$PROVISION_DIR"/*.sh
}

install_release() {
  # In a dry run the bundle is not there: the source tree of this repository stands in for it.
  local source=$HERE/../..
  if [ "$DRY_RUN" = 0 ]; then
    [ -n "$BUNDLE" ] && [ -r "$BUNDLE" ] || die "--bundle FILE is required"
    run install -d -m 750 "$RELEASES_DIR"
    local target=$RELEASES_DIR/$RELEASE_SHA
    rm -rf "$target.tmp"
    install -d -m 750 "$target.tmp"
    tar -xzf "$BUNDLE" -C "$target.tmp"
    chown -R root:odoo "$target.tmp"
    chmod -R u=rwX,g=rX,o= "$target.tmp"
    mv -T "$target.tmp" "$target"
    ln -sfn "$target" "$CURRENT_LINK"
    chown root:odoo "$(dirname "$RELEASES_DIR")" "$RELEASES_DIR"
    chmod 750 "$(dirname "$RELEASES_DIR")" "$RELEASES_DIR"
    source=$target
  else
    printf '+ unpack the signed bundle to %s/%s and point current at it\n' /opt/auditisa-odoo/releases "$RELEASE_SHA"
  fi
  install_scripts_from "$source"
  mkdir -p "$FIRM_STATUS"
  set_status release "$RELEASE_SHA"
  set_status odoo_version "$ODOO_VERSION"
  set_status update_state idle
  set_status export_state none
  set_status ssh_sessions_24h 0
}

configure_odoo() {
  secret /etc/auditisa-firm/secrets/master.password root:root 600
  # Unique to this server, and known to nothing else. No database manager is reachable anyway.
  render /etc/odoo/odoo.conf 640 root:odoo <<EOF
[options]
admin_passwd = $(cat "$FIRM_SECRETS/master.password")
db_host = localhost
db_port = 5432
db_user = odoo
db_password = $(cat "$FIRM_SECRETS/db.password")
db_name = $FIRM_DB
dbfilter = ^$FIRM_DB\$
list_db = False
addons_path = /opt/auditisa-odoo/current/addons,/opt/odoo19/src/addons,/opt/odoo19/src/odoo/addons
data_dir = /var/lib/odoo
logfile = /var/log/odoo/odoo.log
log_level = info
log_handler = :INFO,werkzeug:WARNING
http_interface = 127.0.0.1
http_port = 8069
gevent_port = 8072
proxy_mode = True
workers = $WORKERS
max_cron_threads = 1
limit_memory_soft = $LIMIT_SOFT
limit_memory_hard = $LIMIT_HARD
limit_time_cpu = 600
limit_time_real = 1200
limit_request = 8192
EOF
  render /etc/systemd/system/odoo.service 644 root:root <<EOF
[Unit]
Description=Odoo 19 for $FIRM_SLUG
After=postgresql.service network.target
Requires=postgresql.service

[Service]
User=odoo
Group=odoo
ExecStart=/opt/odoo19/venv/bin/python /opt/odoo19/src/odoo-bin -c /etc/odoo/odoo.conf
Restart=on-failure
MemoryMax=$SERVICE_MEM
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/odoo /var/log/odoo /var/lib/auditisa-firm/spool
ProtectKernelTunables=yes
ProtectControlGroups=yes

[Install]
WantedBy=multi-user.target
EOF
  # render makes missing folders under umask 077: Odoo must be able to open its own folder
  # (seen on the first real firm, 2026-11-09: the database step failed on an unreadable config).
  chmod 750 "$R/etc/odoo"
  if [ "$DRY_RUN" = 0 ]; then chown root:odoo /etc/odoo; fi
  render /etc/logrotate.d/odoo 644 root:root <<'EOF'
/var/log/odoo/*.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
    copytruncate
}
EOF
  run systemctl daemon-reload
}

install_secrets_for_agent() {
  printf '%s\n' "$HEARTBEAT_TOKEN" | render /etc/auditisa-firm/secrets/heartbeat.token 640 root:odoo
  # The agent has to get through the secrets folder to read its one file.
  if [ "$DRY_RUN" = 0 ]; then
    chown root:odoo "$FIRM_ETC" "$FIRM_SECRETS"
    chmod 750 "$FIRM_ETC"
    chmod 710 "$FIRM_SECRETS"
    chown odoo:odoo "$FIRM_SPOOL"
    chmod 770 "$FIRM_SPOOL"
    chown root:odoo "$BREAK_GLASS_LOG"
    chattr +a "$BREAK_GLASS_LOG" || fl_warn "could not make the access log append-only"
  fi
}

create_database() {
  if [ "$DRY_RUN" = 1 ]; then
    bash "$PROVISION_DIR/new_firm.sh" --dry-run --db "$FIRM_DB" --name "$FIRM_NAME" --admin-email "$FIRM_ADMIN_EMAIL" \
      --lang "$FIRM_LANG" --addons base,web,mail,ea_audit_firm_agent
    printf '+ erase the admin password file from new_firm.sh: the first administrator sets a password through the link\n'
    printf '+ set the agent parameters, the mail gate, web.base.url and the hash of the first administrator link\n'
    return 0
  fi
  # new_firm.sh: no demo data, admin renamed to the contact, a random password, mail crons off.
  SECRETS_DIR=/root/.auditisa/firms ADDONS_ROOT=/opt/auditisa-odoo/current/addons \
    bash "$PROVISION_DIR/new_firm.sh" --db "$FIRM_DB" --name "$FIRM_NAME" --admin-email "$FIRM_ADMIN_EMAIL" --lang "$FIRM_LANG"
  # Nobody may hold that password: the first administrator chooses one through the link.
  shred -u "/root/.auditisa/firms/$FIRM_DB.admin"

  cat <<'PY' | runuser -u odoo -- env \
    P_URL="$HEARTBEAT_URL" P_SLUG="$FIRM_SLUG" P_HOST="$FIRM_HOST" P_HASH="$FIRST_ADMIN_TOKEN_SHA256" P_DOMAINS="$FIRM_ALLOWED_DOMAINS" P_LANG="$FIRM_LANG" \
    "$ODOO_PY" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$FIRM_DB" --no-http --max-cron-threads=0 >/dev/null
import datetime
import os

params = env["ir.config_parameter"].sudo()
params.set_param("ea_firm_agent.heartbeat_url", os.environ["P_URL"])
params.set_param("ea_firm_agent.slug", os.environ["P_SLUG"])
params.set_param("ea_firm_agent.mail_gate", "1")
params.set_param("web.base.url", "https://" + os.environ["P_HOST"])
params.set_param("web.base.url.freeze", "True")
params.set_param("ea_firm_agent.first_admin_hash", os.environ["P_HASH"])
expires = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(hours=72)
params.set_param("ea_firm_agent.first_admin_expires", expires.strftime("%Y-%m-%d %H:%M:%S"))
company = env.company.sudo()
if "ea_allowed_email_domains" in company._fields:
    company.ea_allowed_email_domains = "\n".join(os.environ["P_DOMAINS"].split())
env["res.users"].sudo().with_context(active_test=False).search([("login", "in", ("demo", "portal"))]).write({"active": False})
# French and English are both there, so each user can choose in their preferences. The firm's
# language (new_firm.sh sets it on the company, the admin and the defaults) also serves public pages.
for code in ("fr_FR", "en_US"):
    env["res.lang"]._activate_lang(code)
env["ir.module.module"].sudo().search([("state", "=", "installed")])._update_translations(["fr_FR"])
env.ref("base.public_user").sudo().write({"lang": os.environ["P_LANG"]})
env.cr.commit()
PY
}

configure_nginx() {
  # HTTP only until the certificate exists: firm-cert.sh then writes the HTTPS block.
  # No version in error pages and headers. Ubuntu's nginx.conf already sets server_tokens, and a
  # second one in conf.d fails nginx -t (first real firm, 2026-11-09): changed there, as on the console.
  run sed -i -E 's/^[[:space:]]*#?[[:space:]]*server_tokens[[:space:]]+[a-z]+;.*$/	server_tokens off;/' /etc/nginx/nginx.conf
  render /etc/nginx/conf.d/auditisa-limits.conf 644 root:root <<'EOF'
limit_req_zone $binary_remote_addr zone=odoo_login:10m rate=30r/m;
EOF
  render /etc/nginx/sites-available/firm-http.conf 644 root:root <<EOF
server {
    listen 80 default_server;
    server_name _;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$FIRM_HOST\$request_uri; }
}
EOF
  run install -d -m 755 /var/www/certbot
  run rm -f /etc/nginx/sites-enabled/default
  run ln -sfn /etc/nginx/sites-available/firm-http.conf /etc/nginx/sites-enabled/firm-http.conf
  run nginx -t
  run systemctl enable --now nginx
  run systemctl reload nginx
  if [ "$DRY_RUN" = 1 ]; then
    FIRM_PREFIX=$R bash "$BIN_DIR/firm-cert.sh" --dry-run
  fi
}

configure_backups() {
  secret /etc/auditisa-firm/secrets/restic.key root:root 600
  render /etc/auditisa-firm/secrets/s3.env 600 root:root <<EOF
AWS_ACCESS_KEY_ID=$S3_ACCESS_KEY
AWS_SECRET_ACCESS_KEY=$S3_SECRET_KEY
AWS_DEFAULT_REGION=$S3_REGION
RESTIC_REPOSITORY=s3:https://$S3_ENDPOINT/$S3_BUCKET/restic
EOF
  if [ "$DRY_RUN" = 1 ]; then
    printf '+ restic init, on this firm'"'"'s own storage, with its own key\n'
  else
    load_backup_env
    restic cat config >/dev/null 2>&1 || restic init
  fi
}

timer() {
  local name=$1 calendar=$2 description=$3 extra=${4:-}
  render "/etc/systemd/system/$name.service" 644 root:root <<EOF
[Unit]
Description=$description

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/$name
Nice=10
EOF
  render "/etc/systemd/system/$name.timer" 644 root:root <<EOF
[Unit]
Description=$description

[Timer]
OnCalendar=$calendar
Persistent=true
$extra

[Install]
WantedBy=timers.target
EOF
  run systemctl enable --now "$name.timer"
}

configure_timers() {
  timer firm-cert '*:0/5' "HTTPS certificate of this firm, until it exists"
  timer firm-status '*:0/10' "Health figures for the heartbeat"
  timer firm-backup '*-*-* 02:30:00' "Nightly encrypted backup of this firm" "RandomizedDelaySec=30min"
  timer firm-restore-test 'Sun *-*-* 04:30:00' "Weekly restore test of this firm's backup" "RandomizedDelaySec=60min"
  timer firm-apply-desired '*:0/5' "Applies what the control plane asked"
  run systemctl daemon-reload
}

finish() {
  run systemctl enable --now odoo
  if [ "$DRY_RUN" = 1 ]; then
    printf '+ erase /etc/auditisa-firm/bootstrap.env and cloud-init'"'"'s copies of the first-boot text\n'
    printf '+ run firm-cert, firm-status and the first backup\n'
    return 0
  fi
  shred -u "$ENV_FILE" || rm -f "$ENV_FILE"
  rm -f /var/lib/cloud/instance/user-data.txt /var/lib/cloud/instance/user-data.txt.i \
        /var/lib/cloud/instance/cloud-config.txt /var/lib/cloud/instance/scripts/runcmd
  rm -rf /root/firm-bundle
  rm -f /root/bundle.tar.gz /root/bundle.sig
  /usr/local/sbin/firm-cert || fl_warn "no certificate yet: the timer tries again every five minutes"
  /usr/local/sbin/firm-status
  /usr/local/sbin/firm-backup || fl_warn "first backup failed: the board will say so"
}

# ---------------------------------------------------------------------------- the recipe

step check_system check_system
step folders prepare_folders
step packages install_packages
step ssh harden_ssh
step firewall configure_firewall
step fail2ban configure_fail2ban
step unattended configure_unattended_updates
step postgres configure_postgres
step odoo install_odoo
step release install_release
step odoo_conf configure_odoo
step agent_secrets install_secrets_for_agent
step database create_database
step nginx configure_nginx
step backups configure_backups
step timers configure_timers
step finish finish
log "$FIRM_SLUG is built"
