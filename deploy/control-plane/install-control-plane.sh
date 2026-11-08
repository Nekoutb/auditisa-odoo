#!/usr/bin/env bash
# install-control-plane.sh: builds the admin Odoo (the console): one small server, separate from every firm.
#
#   install-control-plane.sh --env FILE                       for real, as root, on a new server
#   install-control-plane.sh --env FILE --dry-run --root DIR  prints the commands, writes the
#                                                             configuration files under DIR only
#
# The env file holds ADMIN_HOST, HEARTBEAT_HOST, OPERATOR_IPS and ADDONS_DIR (the folder holding a copy
# of addons/ea_platform_admin and addons/ea_platform_pipeline, and nothing else). See sample.env.
#
# OPERATOR_IPS is either a list of addresses (space separated) or the single word `any`:
#   - a list: the screens and port 22 answer those addresses only;
#   - any:    the screens and port 22 answer everyone (the owner's ruling of 2026-11-08: the console
#             opens from anywhere). What protects it then: sign-in, with two-factor available to every
#             user; fail2ban on failed Odoo sign-ins and on SSH; nginx rate limits on the sign-in; SSH by
#             key only; no database manager; no public sign-up; HTTPS only, with HSTS.
# A range that opens everything (0.0.0.0/0, ::/0) is refused: write `any`, so that the choice is explicit.
#
# What it sets up, besides the same base as a firm server:
#   - two addresses. ADMIN_HOST serves the screens. HEARTBEAT_HOST serves exactly one path, to anyone,
#     rate-limited: POST /platform/heartbeat. That one door is all a firm's server can reach here.
#     FIRM_DOORS (optional) opens more, each its own decision: `support` (a firm user's "Report a
#     problem": POST /platform/support/{ticket,sync,trace}) and `practice` (the practice computer's
#     POST /platform/practice-heartbeat). Default: heartbeat only.
#   - the provider's token in /etc/auditisa-platform/vultr.token and the DNS token beside it, root
#     only (600). systemd's LoadCredential gives Odoo a private copy; nothing is in odoo.conf. Until the
#     owner puts them there (docs/runbook/PREREQUISITES.md) they are empty, and the console stays in
#     simulation: no firm can be created for real.
#   - only ea_platform_* addons in the database: the addons path holds no ea_audit_* addon.
#   - no outgoing mail server, and Odoo's fallback to localhost:25 switched off: nothing is sent.
#     Outbound SMTP is not blocked, so that a mail server can be added later.
#   - a nightly local backup (database and files, 14 days, root only), and a weekly restore test.
#
# The owner's sign-in is made afterwards with set-owner.sh, the password read from stdin.

set -euo pipefail
umask 077
SCRIPT_NAME=install-control-plane
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

ENV_FILE="" DRY_RUN=0 DRY_ROOT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --env) ENV_FILE=${2:?}; shift ;;
    --dry-run) DRY_RUN=1 ;;
    --root) DRY_ROOT=${2:?}; shift ;;
    -h|--help) sed -n '2,34p' "$0"; exit 0 ;;
    *) printf 'unknown option %s\n' "$1" >&2; exit 64 ;;
  esac
  shift
done
if [ "$DRY_RUN" = 1 ]; then
  [ -n "$DRY_ROOT" ] || DRY_ROOT=$(mktemp -d)
  mkdir -p "$DRY_ROOT"
  DRY_ROOT=$(cd "$DRY_ROOT" && pwd)
fi
R=$DRY_ROOT

# shellcheck source=deploy/firm/recipe.env
. "$HERE/../firm/recipe.env"
[ -n "$ENV_FILE" ] && [ -r "$ENV_FILE" ] || { printf 'ERROR: --env FILE is required\n' >&2; exit 64; }
# shellcheck disable=SC1090
. "$ENV_FILE"
: "${ADMIN_HOST:?}" "${HEARTBEAT_HOST:?}" "${OPERATOR_IPS:?}" "${ADDONS_DIR:?}"
FIRM_DOORS=${FIRM_DOORS:-heartbeat}
# Sized for 1 vCPU and 1.6 to 2 GB: two workers, each recycled past 400 MB.
WORKERS=${WORKERS:-2}
LIMIT_SOFT=${LIMIT_SOFT:-419430400}
LIMIT_HARD=${LIMIT_HARD:-524288000}
SERVICE_MEM_HIGH=${SERVICE_MEM_HIGH:-900M}
SERVICE_MEM_MAX=${SERVICE_MEM_MAX:-1100M}
PG_SHARED=${PG_SHARED:-128MB}
BACKUP_KEEP_DAYS=${BACKUP_KEEP_DAYS:-14}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 64; }
for host in "$ADMIN_HOST" "$HEARTBEAT_HOST"; do
  [[ $host =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]] || die "bad host name $host"
done
[ "$ADMIN_HOST" != "$HEARTBEAT_HOST" ] || die "ADMIN_HOST and HEARTBEAT_HOST must differ"
[[ $BACKUP_KEEP_DAYS =~ ^[0-9]{1,3}$ ]] || die "BACKUP_KEEP_DAYS must be a number of days"

OPEN_TO_ALL=0
if [ "$OPERATOR_IPS" = any ]; then
  OPEN_TO_ALL=1
else
  for addr in $OPERATOR_IPS; do
    [ "$addr" != any ] || die "OPERATOR_IPS: 'any' stands alone, not in a list"
    [[ $addr =~ ^[0-9a-fA-F:.]+(/[0-9]{1,3})?$ ]] || die "bad operator address $addr"
    case "$addr" in 0.0.0.0*|::/0|::) die "a range that opens everything: write OPERATOR_IPS=any to choose that" ;; esac
  done
fi
DOOR_SUPPORT=0 DOOR_PRACTICE=0
for door in $FIRM_DOORS; do
  case "$door" in
    heartbeat) ;;
    support) DOOR_SUPPORT=1 ;;
    practice) DOOR_PRACTICE=1 ;;
    *) die "FIRM_DOORS: unknown door $door (heartbeat, support, practice)" ;;
  esac
done
case " $FIRM_DOORS " in *" heartbeat "*) ;; *) die "FIRM_DOORS must include heartbeat" ;; esac

DB=auditisa_platform
ETC=/etc/auditisa-platform
ODOO_PY=/opt/odoo19/venv/bin/python
ODOO_BIN=/opt/odoo19/src/odoo-bin
LIVE=/etc/letsencrypt/live/$ADMIN_HOST
log() { printf '[%s] %s\n' "$SCRIPT_NAME" "$*"; }
run() { if [ "$DRY_RUN" = 1 ]; then printf '+ %s\n' "$*"; else "$@"; fi; }
# As the odoo user, with its own home: root's is not readable to it, and uv and git look there.
as_odoo() { runuser -u odoo -- env HOME=/opt/odoo19 "$@"; }
render() {
  local path=$R$1 mode=$2 owner=$3
  mkdir -p "$(dirname "$path")"
  cat > "$path"
  chmod "$mode" "$path"
  if [ "$DRY_RUN" = 0 ]; then chown "$owner" "$path"; fi
}
secret() {
  local path=$R$1
  mkdir -p "$(dirname "$path")"
  if [ ! -s "$path" ]; then (umask 077; openssl rand -hex 32 > "$path"); fi
  chmod 600 "$path"
}

if [ "$DRY_RUN" = 0 ]; then
  [ "$(id -u)" = 0 ] || { printf 'ERROR: run as root\n' >&2; exit 1; }
  # shellcheck disable=SC1091
  . /etc/os-release
  [ "${VERSION_ID:-}" = "$UBUNTU_VERSION" ] || { printf 'ERROR: pinned to Ubuntu %s\n' "$UBUNTU_VERSION" >&2; exit 1; }
  [ -d "$ADDONS_DIR/ea_platform_admin" ] && [ -d "$ADDONS_DIR/ea_platform_pipeline" ] \
    || die "$ADDONS_DIR lacks ea_platform_admin or ea_platform_pipeline"
fi
# The console's addons path holds the platform's addons only: never a firm's.
if [ -d "$ADDONS_DIR" ] && find "$ADDONS_DIR" -mindepth 1 -maxdepth 1 ! -name 'ea_platform_*' | grep -q .; then
  die "$ADDONS_DIR holds more than ea_platform_* addons"
fi

log "packages"
run apt-get update -qq
# gcc and python3-dev: python-ldap, in Odoo's requirements, has no wheel and is compiled.
run apt-get install -y -qq --no-install-recommends "${APT_PACKAGES[@]}" gcc python3-dev
for package in "${APT_OPTIONAL_PACKAGES[@]}"; do
  if [ "$DRY_RUN" = 1 ]; then
    printf '+ apt-get install -y -qq --no-install-recommends %s (allowed to fail)\n' "$package"
  else
    apt-get install -y -qq --no-install-recommends "$package" >/dev/null 2>&1 || log "optional package $package not available"
  fi
done

log "ssh"
render /etc/ssh/sshd_config.d/00-ea-hardening.conf 644 root:root <<'EOF'
# Read before the image's own files in this folder: for sshd, the first value wins.
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
if [ "$DRY_RUN" = 0 ]; then
  grep -q '^ssh-' /root/.ssh/authorized_keys 2>/dev/null || die "no SSH key for root: refusing to switch passwords off"
fi
run passwd --lock root
run sshd -t
run systemctl reload ssh

log "firewall"
run ufw --force reset
run ufw default deny incoming
run ufw default allow outgoing
if [ "$OPEN_TO_ALL" = 1 ]; then
  run ufw allow 22/tcp comment ssh-key-only
else
  for addr in $OPERATOR_IPS; do run ufw allow from "$addr" to any port 22 proto tcp comment operator; done
fi
run ufw allow 80/tcp
run ufw allow 443/tcp
run ufw --force enable

log "fail2ban"
# Odoo writes one line per failed sign-in, with the client's address as nginx passes it (proxy_mode).
# fail2ban cuts the date off the line before it reads it.
render /etc/fail2ban/filter.d/odoo-login.conf 644 root:root <<'EOF'
[Definition]
failregex = ^.* INFO \S+ odoo\.addons\.base\.models\.res_users: Login failed for login:.* from <HOST>$
EOF
{
  cat <<'EOF'
[DEFAULT]
bantime = 1h
bantime.increment = true
findtime = 10m
maxretry = 5
EOF
  if [ "$OPEN_TO_ALL" = 1 ]; then
    printf 'ignoreip = 127.0.0.1/8 ::1\n'
  else
    printf 'ignoreip = 127.0.0.1/8 ::1 %s\n' "$OPERATOR_IPS"
  fi
  cat <<'EOF'

[sshd]
enabled = true
maxretry = 4

[odoo-login]
enabled = true
port = http,https
filter = odoo-login
logpath = /var/log/odoo/odoo.log
maxretry = 6

[nginx-limit-req]
enabled = true
port = http,https
logpath = /var/log/nginx/error.log
maxretry = 10
EOF
} | render /etc/fail2ban/jail.d/auditisa.local 644 root:root

log "security updates"
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

log "memory"
if [ "$DRY_RUN" = 1 ]; then
  printf '+ a 2 GB swap file at /swapfile, if the server has no swap\n'
elif [ -z "$(swapon --noheadings --show=NAME)" ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || printf '/swapfile none swap sw 0 0\n' >> /etc/fstab
fi
render /etc/sysctl.d/60-auditisa.conf 644 root:root <<'EOF'
vm.swappiness = 10
EOF
run sysctl -q -p /etc/sysctl.d/60-auditisa.conf

log "database"
run install -d -m 700 "$ETC"
secret "$ETC/db.password"
secret "$ETC/master.password"
if [ "$DRY_RUN" = 1 ]; then
  printf '+ create PostgreSQL role odoo (no createdb) and database %s\n' "$DB"
else
  systemctl enable --now postgresql
  if [ -z "$(runuser -u postgres -- psql -XAtc "SELECT 1 FROM pg_roles WHERE rolname = 'odoo'")" ]; then
    # Through stdin: a password on a command line would show in ps.
    runuser -u postgres -- psql -X -q -v ON_ERROR_STOP=1 -v "pw=$(cat "$ETC/db.password")" <<'SQL'
CREATE ROLE odoo LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'pw';
SQL
  fi
fi
pg_conf_dir=$(find "$R/etc/postgresql" -mindepth 2 -maxdepth 2 -type d -name main 2>/dev/null | head -n 1 || true)
[ -n "$pg_conf_dir" ] || pg_conf_dir=$R/etc/postgresql/$POSTGRES_VERSION/main
render "${pg_conf_dir#"$R"}/conf.d/auditisa.conf" 644 root:root <<EOF
listen_addresses = 'localhost'
shared_buffers = $PG_SHARED
effective_cache_size = 512MB
work_mem = 8MB
maintenance_work_mem = 64MB
max_connections = 40
EOF
run systemctl restart postgresql

log "Odoo"
if [ "$DRY_RUN" = 1 ]; then
  printf '+ useradd odoo; install uv %s, Python %s, Odoo commit %s, as in install-firm-server.sh\n' "$UV_SHA256" "$PYTHON_VERSION" "$ODOO_SHA"
else
  id odoo >/dev/null 2>&1 || useradd --system --home-dir /opt/odoo19 --no-create-home --shell /usr/sbin/nologin odoo
  install -d -o odoo -g odoo -m 750 /opt/odoo19 /var/lib/odoo /var/log/odoo
  # Done once per Odoo commit and Python: a second run keeps what is there.
  if [ "$(cat /opt/odoo19/.odoo-sha 2>/dev/null)" != "$ODOO_SHA-$PYTHON_VERSION" ] || [ ! -x "$ODOO_PY" ]; then
    curl -fsSL -o /tmp/uv.tar.gz "$UV_URL"
    printf '%s  /tmp/uv.tar.gz\n' "$UV_SHA256" | sha256sum -c --status - || die "uv digest differs"
    tar -xzf /tmp/uv.tar.gz --strip-components=1 -C /usr/local/bin
    rm -f /tmp/uv.tar.gz
    as_odoo UV_PYTHON_INSTALL_DIR=/opt/odoo19/python /usr/local/bin/uv python install -q "$PYTHON_VERSION"
    rm -rf /opt/odoo19/venv /opt/odoo19/src
    as_odoo UV_PYTHON_INSTALL_DIR=/opt/odoo19/python /usr/local/bin/uv venv -q --python "$PYTHON_VERSION" /opt/odoo19/venv
    # The commit's id is its content: the same tree as on every firm, and as CI's.
    as_odoo git init -q /opt/odoo19/src
    as_odoo git -C /opt/odoo19/src fetch -q --depth 1 https://github.com/odoo/odoo "$ODOO_SHA"
    as_odoo git -C /opt/odoo19/src checkout -q FETCH_HEAD
    rm -rf /opt/odoo19/src/.git
    # Same swap as staging and CI: no compile of psycopg2.
    sed -E 's/^psycopg2\b/psycopg2-binary/' /opt/odoo19/src/requirements.txt > /tmp/odoo-requirements.txt
    chmod 644 /tmp/odoo-requirements.txt
    as_odoo /usr/local/bin/uv pip install -q --python "$ODOO_PY" -r /tmp/odoo-requirements.txt
    rm -rf /tmp/odoo-requirements.txt /opt/odoo19/.cache
    printf '%s-%s\n' "$ODOO_SHA" "$PYTHON_VERSION" > /opt/odoo19/.odoo-sha
  fi
  chown -R root:odoo "$ADDONS_DIR"
  chmod -R u=rwX,g=rX,o= "$ADDONS_DIR"
  chown root:odoo "$(dirname "$ADDONS_DIR")"
  chmod 750 "$(dirname "$ADDONS_DIR")"
fi

render /etc/odoo/odoo.conf 640 root:odoo <<EOF
[options]
admin_passwd = $(cat "$R$ETC/master.password")
db_host = localhost
db_port = 5432
db_user = odoo
db_password = $(cat "$R$ETC/db.password")
db_name = $DB
dbfilter = ^$DB\$
list_db = False
addons_path = $ADDONS_DIR,/opt/odoo19/src/addons,/opt/odoo19/src/odoo/addons
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
limit_time_cpu = 300
limit_time_real = 600
limit_request = 8192
; No outgoing mail server yet, and no fallback to localhost:25: nothing is sent.
smtp_server = False
email_from = False
EOF

# Root-only files. Odoo gets a private copy at $CREDENTIALS_DIRECTORY, for this service only.
render /etc/systemd/system/odoo.service 644 root:root <<EOF
[Unit]
Description=Odoo 19: AuditISA console (control plane)
After=postgresql.service network.target
Requires=postgresql.service

[Service]
User=odoo
Group=odoo
ExecStart=$ODOO_PY $ODOO_BIN -c /etc/odoo/odoo.conf
LoadCredential=vultr-token:$ETC/vultr.token
LoadCredential=cloudflare-token:$ETC/cloudflare.token
Restart=on-failure
RestartSec=5
MemoryHigh=$SERVICE_MEM_HIGH
MemoryMax=$SERVICE_MEM_MAX
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/odoo /var/log/odoo
ProtectKernelTunables=yes
ProtectControlGroups=yes
Environment=LANG=C.UTF-8

[Install]
WantedBy=multi-user.target
EOF
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

if [ "$DRY_RUN" = 1 ]; then
  printf '+ odoo-bin -i ea_platform_admin,ea_platform_pipeline,auth_totp --load-language=fr_FR --stop-after-init (no demo data)\n'
  printf '+ admin: a random password in %s/admin.password (root, 600), never shown\n' "$ETC"
else
  for token in vultr.token cloudflare.token; do
    # An empty placeholder keeps the service starting in simulation mode, before the owner has any.
    [ -e "$ETC/$token" ] || install -m 600 /dev/null "$ETC/$token"
  done
  runuser -u postgres -- psql -XAtc "SELECT 1 FROM pg_database WHERE datname = '$DB'" | grep -q 1 \
    || runuser -u postgres -- createdb -O odoo -E UTF8 -T template0 --lc-collate=C --lc-ctype=C.UTF-8 "$DB"
  systemctl stop odoo 2>/dev/null || true
  # auth_totp: two-factor sign-in, which every user can switch on in their own preferences.
  as_odoo "$ODOO_PY" "$ODOO_BIN" -c /etc/odoo/odoo.conf -d "$DB" \
    -i ea_platform_admin,ea_platform_pipeline,auth_totp --load-language=fr_FR \
    --no-http --max-cron-threads=0 --workers=0 --stop-after-init
  # Odoo's admin/admin never exists on a reachable server: a long random password, kept root-only and
  # never shown. Nobody signs in as admin; the owner's own account is made by set-owner.sh.
  [ -s "$ETC/admin.password" ] || (umask 077; openssl rand -hex 32 > "$ETC/admin.password")
  chmod 600 "$ETC/admin.password"
  # The password reaches Odoo through stdin (printf is a shell builtin: no command line shows it).
  {
    printf 'ADMIN_SECRET = "%s"\n' "$(cat "$ETC/admin.password")"
    cat <<'PY'
import os

assert len(ADMIN_SECRET) >= 32
env.ref("base.user_admin").with_context(no_reset_password=True).write(
    {"password": ADMIN_SECRET, "lang": "fr_FR", "notification_type": "inbox"})
del ADMIN_SECRET
env.company.name = "AuditISA"
for code in ("fr_FR", "en_US"):
    env["res.lang"]._activate_lang(code)
params = env["ir.config_parameter"].sudo()
params.set_param("web.base.url", "https://" + os.environ["P_ADMIN_HOST"])
params.set_param("web.base.url.freeze", "True")
# No mail server yet: a "forgot password" page would only queue a mail that cannot leave.
params.set_param("auth_signup.reset_password", "False")
if not params.get_param("ea_platform.heartbeat_url"):
    params.set_param("ea_platform.heartbeat_url", "https://" + os.environ["P_HEARTBEAT_HOST"] + "/platform/heartbeat")
env["res.users"].sudo().with_context(active_test=False).search([("login", "in", ("demo", "portal"))]).write({"active": False})
env.cr.commit()
PY
  } | as_odoo P_ADMIN_HOST="$ADMIN_HOST" P_HEARTBEAT_HOST="$HEARTBEAT_HOST" \
      "$ODOO_PY" "$ODOO_BIN" shell -c /etc/odoo/odoo.conf -d "$DB" --no-http --max-cron-threads=0 --workers=0 >/dev/null
  find "$ETC" -maxdepth 1 -type f -exec chmod 600 {} +
fi
run systemctl daemon-reload
run systemctl enable odoo
run systemctl restart odoo

log "nginx"
render /etc/nginx/conf.d/auditisa-limits.conf 644 root:root <<'EOF'
server_tokens off;
limit_req_zone $binary_remote_addr zone=heartbeat:10m rate=6r/m;
limit_req_zone $binary_remote_addr zone=support:10m rate=6r/m;
limit_req_zone $binary_remote_addr zone=odoo_login:10m rate=10r/m;
limit_req_status 429;
EOF
render /etc/nginx/sites-available/control-plane-http.conf 644 root:root <<EOF
# Port 80: the certificate's challenge, and a redirect to HTTPS. Nothing else.
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 444; }
}
server {
    listen 80;
    listen [::]:80;
    server_name $ADMIN_HOST $HEARTBEAT_HOST;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://\$host\$request_uri; }
}
EOF
run install -d -m 755 /var/www/certbot
run rm -f /etc/nginx/sites-enabled/default
run ln -sfn /etc/nginx/sites-available/control-plane-http.conf /etc/nginx/sites-enabled/control-plane-http.conf
run nginx -t -q
run systemctl enable --now nginx
run systemctl reload nginx

# One certificate for both names, without an e-mail address (the owner's choice). Renewal is certbot's timer.
if [ "$DRY_RUN" = 1 ]; then
  printf '+ certbot certonly --webroot -w /var/www/certbot --cert-name %s -d %s -d %s --register-unsafely-without-email\n' \
    "$ADMIN_HOST" "$ADMIN_HOST" "$HEARTBEAT_HOST"
else
  certbot certonly --webroot -w /var/www/certbot --cert-name "$ADMIN_HOST" --expand -d "$ADMIN_HOST" -d "$HEARTBEAT_HOST" \
    --agree-tos --no-eff-email --register-unsafely-without-email --non-interactive --quiet \
    --deploy-hook "systemctl reload nginx"
  systemctl enable --now certbot.timer 2>/dev/null || true
fi

proxy_headers() {
  cat <<'EOF'
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
EOF
}
tls() {
  cat <<EOF
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    ssl_certificate $LIVE/fullchain.pem;
    ssl_certificate_key $LIVE/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:SSL:5m;
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;
    add_header X-Robots-Tag "noindex, nofollow" always;
EOF
}
door() {  # door LOCATION ZONE MAX_BODY
  printf '    location %s {\n        limit_except POST { deny all; }\n        limit_req zone=%s burst=6 nodelay;\n' "$1" "$2"
  printf '        client_max_body_size %s;\n' "$3"
  proxy_headers | sed 's/^/    /'
  printf '        proxy_pass http://127.0.0.1:8069;\n    }\n'
}
{
  printf '# Rendered by install-control-plane.sh. HTTPS only.\n\n'
  printf '# Any other name, or the bare address: no certificate, no page.\n'
  printf 'server {\n    listen 443 ssl default_server;\n    listen [::]:443 ssl default_server;\n    ssl_reject_handshake on;\n}\n\n'
  printf "# The firms' door: POST /platform/heartbeat, rate-limited. Everything else answers 404.\n"
  printf 'server {\n    server_name %s;\n' "$HEARTBEAT_HOST"
  tls
  printf '    access_log /var/log/nginx/heartbeat.access.log;\n'
  door "= /platform/heartbeat" heartbeat 16k
  if [ "$DOOR_SUPPORT" = 1 ]; then
    printf "    # FIRM_DOORS=support: a firm user's \"Report a problem\", and its replies.\n"
    door "~ ^/platform/support/(ticket|sync|trace)\$" support 16k
  fi
  if [ "$DOOR_PRACTICE" = 1 ]; then
    printf '    # FIRM_DOORS=practice: the practice computer, one heartbeat for all its spaces.\n'
    door "= /platform/practice-heartbeat" heartbeat 128k
  fi
  printf '    location / { return 404; }\n}\n\n'
  if [ "$OPEN_TO_ALL" = 1 ]; then
    printf "# The screens: open to every address (OPERATOR_IPS=any, the owner's ruling of 2026-11-08).\n"
  else
    printf '# The screens: the operator addresses only.\n'
  fi
  printf 'server {\n    server_name %s;\n' "$ADMIN_HOST"
  tls
  if [ "$OPEN_TO_ALL" = 0 ]; then
    for addr in $OPERATOR_IPS; do printf '    allow %s;\n' "$addr"; done
    printf '    deny all;\n'
  fi
  cat <<'EOF'
    add_header X-Frame-Options SAMEORIGIN always;
    client_max_body_size 16m;
    proxy_read_timeout 720s;
    proxy_send_timeout 720s;
EOF
  proxy_headers
  cat <<'EOF'
    # No database manager and no database list from the outside; no public sign-up.
    location ~ ^/web/database { return 404; }
    location ~ ^/web/signup { return 404; }
    # Sign-in, by password or by two-factor code: ten a minute per address, then 429.
    location = /web/login {
        limit_req zone=odoo_login burst=10 nodelay;
        proxy_pass http://127.0.0.1:8069;
    }
    location = /web/session/authenticate {
        limit_req zone=odoo_login burst=10 nodelay;
        proxy_pass http://127.0.0.1:8069;
    }
    location ^~ /web/login/totp {
        limit_req zone=odoo_login burst=10 nodelay;
        proxy_pass http://127.0.0.1:8069;
    }
    # The firms' doors are on the heartbeat address only.
    location = /platform/heartbeat { return 404; }
    location = /platform/practice-heartbeat { return 404; }
    location /platform/support/ { return 404; }
    location /websocket {
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_pass http://127.0.0.1:8072;
    }
    location / { proxy_pass http://127.0.0.1:8069; }
}
EOF
} | render /etc/nginx/sites-available/control-plane.conf 644 root:root
if [ "$DRY_RUN" = 1 ] || [ -s "$LIVE/fullchain.pem" ]; then
  run ln -sfn /etc/nginx/sites-available/control-plane.conf /etc/nginx/sites-enabled/control-plane.conf
  run nginx -t -q
  run systemctl reload nginx
fi
run systemctl enable fail2ban
run systemctl restart fail2ban

log "backups"
run install -d -m 700 /var/backups/auditisa-platform
{
  printf '#!/usr/bin/env bash\n'
  printf '# console-backup: the console'"'"'s database and its files, each night, kept %s days. Root only.\n' "$BACKUP_KEEP_DAYS"
  printf 'set -euo pipefail\numask 077\nDB=%s\nKEEP_DAYS=%s\n' "$DB" "$BACKUP_KEEP_DAYS"
  cat <<'EOF'
DEST=/var/backups/auditisa-platform
stamp=$(date -u +%Y%m%dT%H%M%SZ)
work=$DEST/.$stamp
mkdir -p "$work"
trap 'rm -rf "$work"' EXIT
runuser -u postgres -- pg_dump -Fc "$DB" > "$work/database.dump"
if [ -d "/var/lib/odoo/filestore/$DB" ]; then
  tar -C /var/lib/odoo/filestore -czf "$work/filestore.tar.gz" "$DB"
else
  tar -czf "$work/filestore.tar.gz" -T /dev/null
fi
(cd "$work" && sha256sum database.dump filestore.tar.gz > SHA256SUMS)
mv "$work" "$DEST/$stamp"
trap - EXIT
find "$DEST" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime +"$KEEP_DAYS" -exec rm -rf {} +
printf 'console-backup: %s (%s)\n' "$DEST/$stamp" "$(du -sh "$DEST/$stamp" | cut -f1)"
EOF
} | render /usr/local/sbin/console-backup 700 root:root
{
  printf '#!/usr/bin/env bash\n'
  printf '# console-restore-test: restores the latest backup into a throwaway database, checks it, drops it.\n'
  printf 'set -euo pipefail\numask 077\n'
  cat <<'EOF'
latest=$(find /var/backups/auditisa-platform -mindepth 1 -maxdepth 1 -type d -name '20*' | sort | tail -n 1)
[ -n "$latest" ] || { echo "console-restore-test: no backup" >&2; exit 1; }
(cd "$latest" && sha256sum -c --quiet SHA256SUMS)
test_db=restore_test_$(date -u +%Y%m%d%H%M%S)
work=$(mktemp -d)
cleanup() { runuser -u postgres -- dropdb --if-exists "$test_db"; rm -rf "$work"; }
trap cleanup EXIT
runuser -u postgres -- createdb -T template0 "$test_db"
runuser -u postgres -- pg_restore --no-owner --exit-on-error -d "$test_db" < "$latest/database.dump"
users=$(runuser -u postgres -- psql -XAt -d "$test_db" -c "SELECT count(*) FROM res_users")
modules=$(runuser -u postgres -- psql -XAt -d "$test_db" -c "SELECT count(*) FROM ir_module_module WHERE state = 'installed' AND name IN ('ea_platform_admin', 'ea_platform_pipeline')")
[ "$users" -ge 1 ] && [ "$modules" = 2 ] || { echo "console-restore-test: the restored database is not right" >&2; exit 1; }
tar -C "$work" -xzf "$latest/filestore.tar.gz"
printf 'console-restore-test: %s restored (%s users, both platform addons, %s files) and dropped\n' \
  "$(basename "$latest")" "$users" "$(find "$work" -type f | wc -l)"
EOF
} | render /usr/local/sbin/console-restore-test 700 root:root
for name in console-backup console-restore-test; do
  case $name in
    console-backup) calendar='*-*-* 02:30:00' description="Nightly backup of the AuditISA console" ;;
    *) calendar='Sun *-*-* 04:30:00' description="Weekly restore test of the AuditISA console's backup" ;;
  esac
  render "/etc/systemd/system/$name.service" 644 root:root <<EOF
[Unit]
Description=$description
After=postgresql.service

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
RandomizedDelaySec=20min

[Install]
WantedBy=timers.target
EOF
done
run systemctl daemon-reload
run systemctl enable --now console-backup.timer console-restore-test.timer

log "Status tab readings"
# Public, read-only sources only. The private Odoo repository shows "not connected" until the owner
# adds a read-only deploy key: docs/runbook/PIPELINE.md.
run python3 -I "$HERE/pipeline-collect.py" --install

log "done. Next: set-owner.sh for the owner's sign-in; see docs/runbook/PREREQUISITES.md"
