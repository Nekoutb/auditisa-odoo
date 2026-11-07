#!/usr/bin/env bash
# install-control-plane.sh: builds the admin Odoo: one small server, separate from every firm.
#
#   install-control-plane.sh --env FILE                       for real, as root, on a new server
#   install-control-plane.sh --env FILE --dry-run --root DIR  prints the commands, writes the
#                                                             configuration files under DIR only
#
# The env file holds ADMIN_HOST, HEARTBEAT_HOST, OPERATOR_IPS (space separated) and ADDONS_DIR
# (the folder holding a copy of addons/ea_platform_admin). See sample.env beside this script.
#
# What it sets up, besides the same base as a firm server:
#   - two addresses. ADMIN_HOST serves the screens, to OPERATOR_IPS only. HEARTBEAT_HOST serves
#     exactly one path, POST /platform/heartbeat, to anyone, rate-limited: that one door is all a
#     firm's server can reach here.
#   - the provider's token in /etc/auditisa-platform/vultr.token and the DNS token beside it, root
#     only (600). systemd's LoadCredential gives Odoo a private copy; nothing is in odoo.conf.
#     The tokens are put there by hand, by the owner: see docs/runbook/PREREQUISITES.md.
#   - only ea_platform_admin in the database: the addons path holds no ea_audit_* addon.
#
# Not yet run on a real server: only --dry-run has been.

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
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
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
for addr in $OPERATOR_IPS; do
  [[ $addr =~ ^[0-9a-fA-F:.]+(/[0-9]{1,3})?$ ]] || { printf 'ERROR: bad operator address %s\n' "$addr" >&2; exit 64; }
  case "$addr" in 0.0.0.0*|::/0) printf 'ERROR: the screens are not open to everyone\n' >&2; exit 64 ;; esac
done

DB=auditisa_platform
log() { printf '[%s] %s\n' "$SCRIPT_NAME" "$*"; }
run() { if [ "$DRY_RUN" = 1 ]; then printf '+ %s\n' "$*"; else "$@"; fi; }
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
fi

log "packages"
run apt-get update -qq
run apt-get install -y -qq --no-install-recommends "${APT_PACKAGES[@]}"

log "ssh and firewall"
render /etc/ssh/sshd_config.d/00-ea-hardening.conf 644 root:root <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
PermitEmptyPasswords no
MaxAuthTries 4
X11Forwarding no
AllowUsers root
EOF
run passwd --lock root
run sshd -t
run systemctl reload ssh
run ufw --force reset
run ufw default deny incoming
run ufw default allow outgoing
for addr in $OPERATOR_IPS; do run ufw allow from "$addr" to any port 22 proto tcp; done
run ufw allow 80/tcp
run ufw allow 443/tcp
run ufw --force enable
run systemctl enable --now fail2ban unattended-upgrades

log "database and Odoo"
secret /etc/auditisa-platform/db.password
secret /etc/auditisa-platform/master.password
if [ "$DRY_RUN" = 1 ]; then
  printf '+ create PostgreSQL role odoo (no createdb) and database %s\n' "$DB"
else
  systemctl enable --now postgresql
  if [ -z "$(runuser -u postgres -- psql -XAtc "SELECT 1 FROM pg_roles WHERE rolname = 'odoo'")" ]; then
    runuser -u postgres -- psql -X -q -v ON_ERROR_STOP=1 -v "pw=$(cat /etc/auditisa-platform/db.password)" <<'SQL'
CREATE ROLE odoo LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'pw';
SQL
  fi
fi
run useradd --system --home-dir /opt/odoo19 --no-create-home --shell /usr/sbin/nologin odoo
run install -d -o odoo -g odoo -m 750 /opt/odoo19 /var/lib/odoo /var/log/odoo
if [ "$DRY_RUN" = 1 ]; then
  printf '+ install uv %s, Python %s, Odoo commit %s, as in install-firm-server.sh\n' "$UV_SHA256" "$PYTHON_VERSION" "$ODOO_SHA"
else
  curl -fsSL -o /tmp/uv.tar.gz "$UV_URL"
  printf '%s  /tmp/uv.tar.gz\n' "$UV_SHA256" | sha256sum -c --status -
  tar -xzf /tmp/uv.tar.gz --strip-components=1 -C /usr/local/bin
  runuser -u odoo -- env UV_PYTHON_INSTALL_DIR=/opt/odoo19/python /usr/local/bin/uv python install "$PYTHON_VERSION"
  runuser -u odoo -- env UV_PYTHON_INSTALL_DIR=/opt/odoo19/python /usr/local/bin/uv venv --python "$PYTHON_VERSION" /opt/odoo19/venv
  runuser -u odoo -- git init -q /opt/odoo19/src
  runuser -u odoo -- git -C /opt/odoo19/src fetch -q --depth 1 https://github.com/odoo/odoo "$ODOO_SHA"
  runuser -u odoo -- git -C /opt/odoo19/src checkout -q FETCH_HEAD
  rm -rf /opt/odoo19/src/.git
  sed -E 's/^psycopg2\b/psycopg2-binary/' /opt/odoo19/src/requirements.txt > /tmp/odoo-requirements.txt
  chmod 644 /tmp/odoo-requirements.txt
  runuser -u odoo -- /usr/local/bin/uv pip install -q --python /opt/odoo19/venv/bin/python -r /tmp/odoo-requirements.txt
fi

render /etc/odoo/odoo.conf 640 root:odoo <<EOF
[options]
admin_passwd = $(cat "$R/etc/auditisa-platform/master.password")
db_host = localhost
db_user = odoo
db_password = $(cat "$R/etc/auditisa-platform/db.password")
db_name = $DB
dbfilter = ^$DB\$
list_db = False
addons_path = $ADDONS_DIR,/opt/odoo19/src/addons,/opt/odoo19/src/odoo/addons
data_dir = /var/lib/odoo
logfile = /var/log/odoo/odoo.log
log_handler = :INFO,werkzeug:WARNING
http_interface = 127.0.0.1
http_port = 8069
gevent_port = 8072
proxy_mode = True
workers = 2
max_cron_threads = 1
limit_memory_hard = 943718400
limit_memory_soft = 754974720
EOF

# Root-only files. Odoo gets a private copy at $CREDENTIALS_DIRECTORY, for this service only.
run install -d -m 700 /etc/auditisa-platform
render /etc/systemd/system/odoo.service 644 root:root <<'EOF'
[Unit]
Description=Odoo 19: AuditISA control plane
After=postgresql.service network.target
Requires=postgresql.service

[Service]
User=odoo
Group=odoo
ExecStart=/opt/odoo19/venv/bin/python /opt/odoo19/src/odoo-bin -c /etc/odoo/odoo.conf
LoadCredential=vultr-token:/etc/auditisa-platform/vultr.token
LoadCredential=cloudflare-token:/etc/auditisa-platform/cloudflare.token
Restart=on-failure
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/odoo /var/log/odoo

[Install]
WantedBy=multi-user.target
EOF
if [ "$DRY_RUN" = 1 ]; then
  printf '+ odoo-bin -i ea_platform_admin,ea_platform_pipeline --without-demo=True --load-language=fr_FR --stop-after-init\n'
else
  for token in vultr.token cloudflare.token; do
    # An empty placeholder keeps the service starting in simulation mode, before the owner has any.
    [ -e "/etc/auditisa-platform/$token" ] || install -m 600 /dev/null "/etc/auditisa-platform/$token"
  done
  runuser -u postgres -- psql -XAtc "SELECT 1 FROM pg_database WHERE datname = '$DB'" | grep -q 1 \
    || runuser -u postgres -- createdb -O odoo -E UTF8 -T template0 --lc-collate=C --lc-ctype=C.UTF-8 "$DB"
  runuser -u odoo -- /opt/odoo19/venv/bin/python /opt/odoo19/src/odoo-bin -c /etc/odoo/odoo.conf -d "$DB" \
    -i ea_platform_admin,ea_platform_pipeline --without-demo=True --load-language=fr_FR --no-http --max-cron-threads=0 --workers=0 --stop-after-init
  # No default admin: Odoo's admin/admin never exists on a reachable server. Root reads the password
  # once from this file, keeps it in the owner's safe and deletes the file.
  if [ ! -e /etc/auditisa-platform/admin.password ]; then
    (umask 077; openssl rand -hex 16 > /etc/auditisa-platform/admin.password)
    { printf 'NEW_PASSWORD = "%s"\n' "$(cat /etc/auditisa-platform/admin.password)"
      printf 'env.ref("base.user_admin").write({"password": NEW_PASSWORD, "lang": "fr_FR"})\nenv.company.name = "AuditISA"\nenv["res.lang"]._activate_lang("en_US")\nenv.cr.commit()\n'
    } | runuser -u odoo -- /opt/odoo19/venv/bin/python /opt/odoo19/src/odoo-bin shell -c /etc/odoo/odoo.conf -d "$DB" \
        --no-http --max-cron-threads=0 >/dev/null
  fi
fi
run systemctl daemon-reload
run systemctl enable --now odoo

log "nginx"
{
  cat <<'EOF'
server_tokens off;
limit_req_zone $binary_remote_addr zone=heartbeat:10m rate=6r/m;
limit_req_zone $binary_remote_addr zone=support:10m rate=6r/m;

EOF
  printf '# The one door a firm has: POST /platform/heartbeat. Everything else answers 404.\n'
  printf 'server {\n    listen 80;\n    server_name %s;\n' "$HEARTBEAT_HOST"
  cat <<'EOF'
    client_max_body_size 16k;
    # A problem a firm's user reports, and its replies: signed like the heartbeat, its own prefix.
    location ~ ^/platform/support/(ticket|sync|trace)$ {
        limit_except POST { deny all; }
        limit_req zone=support burst=6 nodelay;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_pass http://127.0.0.1:8069;
    }
    # The practice computer's heartbeat: one for all its spaces, so a larger body.
    location = /platform/practice-heartbeat {
        limit_except POST { deny all; }
        limit_req zone=heartbeat burst=6 nodelay;
        client_max_body_size 128k;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_pass http://127.0.0.1:8069;
    }
    location = /platform/heartbeat {
        limit_except POST { deny all; }
        limit_req zone=heartbeat burst=6 nodelay;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_pass http://127.0.0.1:8069;
    }
    location / { return 404; }
}

EOF
  printf '# The screens: the operator addresses only.\n'
  printf 'server {\n    listen 80;\n    server_name %s;\n' "$ADMIN_HOST"
  for addr in $OPERATOR_IPS; do printf '    allow %s;\n' "$addr"; done
  cat <<'EOF'
    deny all;
    client_max_body_size 16m;
    proxy_read_timeout 720s;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    location ~ ^/web/database { return 404; }
    location = /platform/heartbeat { return 404; }
    location = /platform/practice-heartbeat { return 404; }
    location /platform/support/ { return 404; }
    location /websocket {
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_pass http://127.0.0.1:8072;
    }
    location / { proxy_pass http://127.0.0.1:8069; }
}
EOF
} | render /etc/nginx/sites-available/control-plane.conf 644 root:root
run rm -f /etc/nginx/sites-enabled/default
run ln -sfn /etc/nginx/sites-available/control-plane.conf /etc/nginx/sites-enabled/control-plane.conf
run nginx -t
run systemctl reload nginx
run certbot --nginx -d "$ADMIN_HOST" -d "$HEARTBEAT_HOST" --redirect --agree-tos --no-eff-email --register-unsafely-without-email --non-interactive

log "done. The admin password is in /etc/auditisa-platform/admin.password: see docs/runbook/PREREQUISITES.md"
