#!/usr/bin/env bash
# install-practice-server.sh: builds the client practice computer, or the preview of it.
#
#   install-practice-server.sh --env FILE --release DIR             for real, as root, on a new server
#   install-practice-server.sh --env FILE --release DIR --preview   on a machine that already runs Odoo 19
#                                                                   (staging): adds a second service beside it
#   install-practice-server.sh --env FILE --dry-run --root DIR      writes every file under DIR, prints the
#                                                                   commands, changes nothing else
#
# --release DIR is an unpacked release (addons/ at its top) that has been checked: a signed bundle
# unpacked by practice-update.sh, or on the preview a release staging already runs.
#
# What it sets up (see docs/runbook/PRACTICE-SPACES.md):
#   - one Odoo 19 service, odoo-practice, as its own system user and PostgreSQL role, serving every
#     practice_<slug> database by host name (dbfilter ^practice_%d$), no database list, no manager
#   - nginx for *.<domain>: HTTP until the wildcard certificate exists (practice-cert.sh, later)
#   - no outgoing mail: Odoo's SMTP off, every space's mail servers off, the firewall rejects mail ports
#   - practice-guard before every start and every ten minutes: only copies of the demo template are served
#   - practice-heartbeat every ten minutes: figures only
#
# Generated here and never printed: the PostgreSQL password and Odoo's master password.

set -euo pipefail
umask 077
SCRIPT_NAME=install-practice-server
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)

ENV_FILE="" RELEASE_DIR="" DRY_RUN=0 DRY_ROOT="" PREVIEW=0
while [ $# -gt 0 ]; do
  case "$1" in
    --env) ENV_FILE=${2:?}; shift ;;
    --release) RELEASE_DIR=${2:?}; shift ;;
    --preview) PREVIEW=1 ;;
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
  export PRACTICE_PREFIX=$DRY_ROOT
fi
# shellcheck source=deploy/practice/practice-lib.sh
. "$HERE/practice-lib.sh"
# shellcheck source=deploy/firm/recipe.env
. "$HERE/../firm/recipe.env"
R=$PRACTICE_PREFIX

[ -n "$ENV_FILE" ] && [ -r "$ENV_FILE" ] || pl_die "--env FILE is required"
grep -Evq "^([A-Z0-9_]+='[A-Za-z0-9 ._:@/%+=,-]*'|#.*|)$" "$ENV_FILE" && pl_die "$ENV_FILE holds an unexpected line"
# shellcheck disable=SC1090
. "$ENV_FILE"
: "${PRACTICE_NAME:?}" "${PRACTICE_DOMAIN:?}" "${PRACTICE_PORT:?}" "${PRACTICE_PUBLIC_URL:?}"
: "${PRACTICE_SERVICE:=odoo-practice}" "${PRACTICE_CONF:=/etc/odoo/practice.conf}" "${PRACTICE_DATA_DIR:=/var/lib/odoo-practice}"
: "${PRACTICE_ENTRY_URL:=$PRACTICE_PUBLIC_URL/web/login}"
: "${PRACTICE_WORKERS:=2}" "${PRACTICE_MEMORY:=2400M}" "${PRACTICE_LANG:=fr_FR}" "${PRACTICE_HOLD_DAYS:=7}"
: "${PRACTICE_HEARTBEAT_URL:=}" "${PRACTICE_SSH_ALLOWLIST:=}" "${PRACTICE_UPDATE_MEM:=1400M}"
: "${PREVIEW_PORT:=}" "${PREVIEW_HOST:=}" "${PREVIEW_CERT:=}"
[ "$PREVIEW" = 1 ] || [ "${PRACTICE_PREVIEW:-0}" = 0 ] || pl_die "$ENV_FILE is a preview's: add --preview"
[[ $PRACTICE_NAME =~ ^[a-z][a-z0-9-]{1,30}$ ]] || pl_die "invalid PRACTICE_NAME"
[[ $PRACTICE_DOMAIN =~ ^[a-z0-9-]+(\.[a-z0-9-]+)+$ ]] || pl_die "invalid PRACTICE_DOMAIN"
[[ $PRACTICE_PORT =~ ^[0-9]{4,5}$ ]] || pl_die "invalid PRACTICE_PORT"
[[ $PRACTICE_WORKERS =~ ^[0-9]$ ]] || pl_die "PRACTICE_WORKERS is 0 to 9"
[[ $PRACTICE_SERVICE =~ ^[a-z][a-z0-9-]+$ ]] || pl_die "invalid PRACTICE_SERVICE"
[[ $PRACTICE_PUBLIC_URL == https://* ]] || pl_die "PRACTICE_PUBLIC_URL must be https"
[[ $PRACTICE_HEARTBEAT_URL == "" || $PRACTICE_HEARTBEAT_URL == https://* ]] || pl_die "PRACTICE_HEARTBEAT_URL must be https"
if [ "$PREVIEW" = 1 ]; then
  [[ $PREVIEW_PORT =~ ^[0-9]{4,5}$ ]] || pl_die "a preview needs PREVIEW_PORT"
  [[ $PREVIEW_HOST =~ ^[a-z0-9.-]+$ ]] || pl_die "a preview needs PREVIEW_HOST"
  [[ $PREVIEW_CERT =~ ^[a-z0-9.-]+$ ]] || pl_die "a preview needs PREVIEW_CERT (a certificate name under /etc/letsencrypt/live)"
fi

STATE_FILE=$R/root/.practice-install-state
LIMIT_HARD=$((PRACTICE_WORKERS > 0 ? 1100 * 1048576 : 900 * 1048576))
LIMIT_SOFT=$((LIMIT_HARD * 7 / 10))
LOG_DIR=/var/log/$PRACTICE_SERVICE
PREVIEW_SITE=practice-preview.conf
SITE=practice.conf

log() { pl_log "$*"; }
die() { pl_die "$*"; }
run() { if [ "$DRY_RUN" = 1 ]; then printf '+ %s\n' "$*"; else "$@"; fi; }

render() {
  local path=$R$1 mode=$2 owner=$3
  mkdir -p "$(dirname "$path")"
  cat > "$path"
  chmod "$mode" "$path"
  if [ "$DRY_RUN" = 0 ]; then chown "$owner" "$path"; fi
}

secret() {
  local path=$R$1 mode=$2
  mkdir -p "$(dirname "$path")"
  if [ ! -s "$path" ]; then (umask 077; openssl rand -hex 32 > "$path"); fi
  chmod "$mode" "$path"
  if [ "$DRY_RUN" = 0 ]; then chown root:root "$path"; fi
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
  [ -n "$RELEASE_DIR" ] && [ -d "$RELEASE_DIR/addons" ] || die "--release DIR (with addons/) is required"
  if [ "$PREVIEW" = 1 ]; then
    [ -x "$ODOO_PY" ] && [ -f "$ODOO_BIN" ] || die "a preview needs Odoo 19 already installed at $ODOO_PY"
    [ -r "/etc/letsencrypt/live/$PREVIEW_CERT/fullchain.pem" ] || die "no certificate $PREVIEW_CERT"
    if ss -ltn | awk '{print $4}' | grep -Eq "[:.]($PRACTICE_PORT|$PREVIEW_PORT)\$"; then
      systemctl is-active --quiet "$PRACTICE_SERVICE" || die "port $PRACTICE_PORT or $PREVIEW_PORT is already in use"
    fi
  else
    # shellcheck disable=SC1091
    . /etc/os-release
    [ "${VERSION_ID:-}" = "$UBUNTU_VERSION" ] || die "this recipe is pinned to Ubuntu $UBUNTU_VERSION, found ${VERSION_ID:-unknown}"
  fi
}

prepare_folders() {
  mkdir -p "$PRACTICE_ETC" "$PRACTICE_SECRETS" "$PRACTICE_LOGINS" "$PRACTICE_SPACES" "$PRACTICE_STATUS" \
    "$PRACTICE_LOGS" "$PRACTICE_RELEASES" "$PRACTICE_BIN"
  chmod 755 "$PRACTICE_ETC"
  chmod 700 "$PRACTICE_SECRETS" "$PRACTICE_LOGINS" "$PRACTICE_SPACES" "$PRACTICE_LOGS"
  chmod 755 "$PRACTICE_STATUS"
  render /etc/auditisa-practice/practice.env 644 root:root <<EOF
# Rendered by install-practice-server.sh. No secret here.
PRACTICE_NAME='$PRACTICE_NAME'
PRACTICE_DOMAIN='$PRACTICE_DOMAIN'
PRACTICE_PORT='$PRACTICE_PORT'
PRACTICE_SERVICE='$PRACTICE_SERVICE'
PRACTICE_CONF='$PRACTICE_CONF'
PRACTICE_DATA_DIR='$PRACTICE_DATA_DIR'
PRACTICE_PUBLIC_URL='$PRACTICE_PUBLIC_URL'
PRACTICE_ENTRY_URL='$PRACTICE_ENTRY_URL'
PRACTICE_PREVIEW='$PREVIEW'
PRACTICE_STRICT_CLUSTER='$((1 - PREVIEW))'
PRACTICE_LANG='$PRACTICE_LANG'
PRACTICE_HOLD_DAYS='$PRACTICE_HOLD_DAYS'
PRACTICE_HEARTBEAT_URL='$PRACTICE_HEARTBEAT_URL'
PRACTICE_UPDATE_MEM='$PRACTICE_UPDATE_MEM'
EOF
}

install_packages() {
  [ "$PREVIEW" = 0 ] || return 0
  run apt-get update -qq
  run apt-get install -y -qq --no-install-recommends "${APT_PACKAGES[@]}" python3-certbot-dns-cloudflare
  local package
  for package in "${APT_OPTIONAL_PACKAGES[@]}"; do
    if [ "$DRY_RUN" = 1 ]; then
      printf '+ apt-get install -y -qq --no-install-recommends %s (allowed to fail)\n' "$package"
    else
      apt-get install -y -qq --no-install-recommends "$package" >/dev/null 2>&1 || log "optional package $package not available"
    fi
  done
}

# The practice computer only ever needs DNS, the web (packages, certificates, the heartbeat) and
# time. Everything else going out is refused, mail ports first and by name.
configure_firewall() {
  if [ "$PREVIEW" = 1 ]; then
    # A shared machine: its own rules stay. The mail ports must already be closed, and the
    # preview's one port is opened.
    if [ "$DRY_RUN" = 0 ]; then
      ufw status | grep -Eq '25,465,587,2525/tcp +REJECT OUT' \
        || run ufw reject out 25,465,587,2525/tcp comment 'practice: no email'
    else
      printf '+ ufw reject out 25,465,587,2525/tcp (if not already)\n'
    fi
    run ufw allow "$PREVIEW_PORT/tcp" comment 'practice spaces preview'
    return 0
  fi
  run ufw --force reset
  run ufw default deny incoming
  run ufw default deny outgoing
  run ufw reject out 25,465,587,2525/tcp comment 'practice: no email'
  run ufw allow out 53 comment dns
  run ufw allow out 123/udp comment ntp
  run ufw allow out 80/tcp comment 'packages and certificates'
  run ufw allow out 443/tcp comment 'packages, certificates and the heartbeat'
  local cidr
  for cidr in $PRACTICE_SSH_ALLOWLIST; do
    run ufw allow from "$cidr" to any port 22 proto tcp comment operator
  done
  run ufw allow 80/tcp
  run ufw allow 443/tcp
  run ufw --force enable
}

configure_postgres() {
  secret /etc/auditisa-practice/secrets/db.password 600
  if [ "$DRY_RUN" = 1 ]; then
    printf '+ create PostgreSQL role %s (LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE), password read from a file\n' "$DB_ROLE"
    return 0
  fi
  if [ "$PREVIEW" = 0 ]; then
    systemctl enable --now postgresql
    local conf_dir
    conf_dir=$(find /etc/postgresql -mindepth 2 -maxdepth 2 -type d -name main | head -n 1)
    printf "listen_addresses = 'localhost'\nssl = off\n" > "$conf_dir/conf.d/practice.conf"
    systemctl restart postgresql
  fi
  # Through stdin: a password on a command line would show in ps.
  if [ -z "$(psql_q "SELECT 1 FROM pg_roles WHERE rolname = '$DB_ROLE'")" ]; then
    runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 -q -v "pw=$(cat "$PRACTICE_SECRETS/db.password")" <<SQL
CREATE ROLE $DB_ROLE LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'pw';
SQL
  else
    runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 -q -v "pw=$(cat "$PRACTICE_SECRETS/db.password")" <<SQL
ALTER ROLE $DB_ROLE LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'pw';
SQL
  fi
}

install_odoo() {
  if [ "$PREVIEW" = 1 ]; then
    log "Odoo 19 is already on this machine: $ODOO_BIN"
    return 0
  fi
  # Same pins as a firm's server (deploy/firm/recipe.env). Root owns the code; the service reads it.
  run install -d -m 755 /opt/odoo19
  run curl -fsSL -o /tmp/uv.tar.gz "$UV_URL"
  if [ "$DRY_RUN" = 1 ]; then
    printf '+ check uv against sha256 %s\n' "$UV_SHA256"
  else
    printf '%s  /tmp/uv.tar.gz\n' "$UV_SHA256" | sha256sum -c --status - || die "uv digest differs"
  fi
  run tar -xzf /tmp/uv.tar.gz --strip-components=1 -C /usr/local/bin
  run env UV_PYTHON_INSTALL_DIR=/opt/odoo19/python /usr/local/bin/uv python install "$PYTHON_VERSION"
  run env UV_PYTHON_INSTALL_DIR=/opt/odoo19/python /usr/local/bin/uv venv --python "$PYTHON_VERSION" /opt/odoo19/venv
  run git init -q /opt/odoo19/src
  run git -C /opt/odoo19/src fetch -q --depth 1 https://github.com/odoo/odoo "$ODOO_SHA"
  run git -C /opt/odoo19/src checkout -q FETCH_HEAD
  run rm -rf /opt/odoo19/src/.git
  if [ "$DRY_RUN" = 1 ]; then
    printf '+ install Odoo requirements with uv (psycopg2 replaced by psycopg2-binary)\n'
  else
    sed -E 's/^psycopg2\b/psycopg2-binary/' /opt/odoo19/src/requirements.txt > /tmp/odoo-requirements.txt
    /usr/local/bin/uv pip install -q --python /opt/odoo19/venv/bin/python -r /tmp/odoo-requirements.txt
    chmod -R a+rX /opt/odoo19
  fi
  run curl -fsSL -o /tmp/wkhtmltox.deb "$WKHTMLTOX_URL"
  if [ "$DRY_RUN" = 1 ]; then
    printf '+ check wkhtmltopdf against sha256 %s\n' "$WKHTMLTOX_SHA256"
  else
    printf '%s  /tmp/wkhtmltox.deb\n' "$WKHTMLTOX_SHA256" | sha256sum -c --status - || die "wkhtmltopdf digest differs"
    dpkg -i /tmp/wkhtmltox.deb || apt-get install -y -f -qq
    rm -f /tmp/wkhtmltox.deb
  fi
}

create_user() {
  if [ "$DRY_RUN" = 1 ]; then
    printf '+ useradd --system %s; folders %s and %s owned by it\n' "$ODOO_USER" "$PRACTICE_DATA_DIR" "$LOG_DIR"
    return 0
  fi
  id "$ODOO_USER" >/dev/null 2>&1 || useradd --system --home-dir "$PRACTICE_DATA_DIR" --no-create-home --shell /usr/sbin/nologin "$ODOO_USER"
  install -d -o "$ODOO_USER" -g "$ODOO_USER" -m 750 "$PRACTICE_DATA_DIR" "$LOG_DIR"
}

install_release() {
  local name source
  if [ "$DRY_RUN" = 1 ]; then
    name=0123456789ab
    mkdir -p "$PRACTICE_RELEASES/$name"
    ln -sfn "$PRACTICE_RELEASES/$name" "$PRACTICE_CURRENT"
    source=$HERE/../..
  else
    source=$(cd "$RELEASE_DIR" && pwd)
    name=$(sed -n 's/^sha=//p' "$source/RELEASE" 2>/dev/null | cut -c1-12 || true)
    [ -n "$name" ] || name=$(basename "$source")
    valid_release "$name" || die "cannot tell the release of $source (a RELEASE file with sha=, or a folder named after it)"
    if [ ! -d "$PRACTICE_RELEASES/$name" ]; then
      install -d -m 750 "$PRACTICE_RELEASES/$name.tmp"
      cp -a "$source/addons" "$PRACTICE_RELEASES/$name.tmp/"
      [ ! -f "$source/RELEASE" ] || cp "$source/RELEASE" "$PRACTICE_RELEASES/$name.tmp/"
      rm -rf "$PRACTICE_RELEASES/$name.tmp/addons"/ea_platform_*
      chown -R root:"$ODOO_USER" "$PRACTICE_RELEASES/$name.tmp"
      chmod -R u=rwX,g=rX,o= "$PRACTICE_RELEASES/$name.tmp"
      mv -T "$PRACTICE_RELEASES/$name.tmp" "$PRACTICE_RELEASES/$name"
    fi
    ln -sfn "$PRACTICE_RELEASES/$name" "$PRACTICE_CURRENT"
    chown root:"$ODOO_USER" "$PRACTICE_ROOT" "$PRACTICE_RELEASES"
    chmod 750 "$PRACTICE_ROOT" "$PRACTICE_RELEASES"
    # The scripts come from this checkout, the one being installed.
    source=$HERE/../..
  fi
  local script link
  for script in practice-lib.sh practice-space.sh practice-template.sh practice-update.sh practice-guard.sh \
                practice-cert.sh practice_heartbeat.py practice_isolation_test.py; do
    cp -f "$source/deploy/practice/$script" "$PRACTICE_BIN/$script"
    chmod 700 "$PRACTICE_BIN/$script"
    case "$script" in
      practice-lib.sh|practice_isolation_test.py) ;;
      *) link=${script%.*}; run ln -sfn "/opt/auditisa-practice/bin/$script" "/usr/local/sbin/${link//_/-}" ;;
    esac
  done
  printf '%s\n' "$name" > "$PRACTICE_STATUS/release"
}

configure_odoo() {
  secret /etc/auditisa-practice/secrets/master.password 600
  # dbfilter: the first part of the host name, and only a practice_ database. No db_name: one
  # service, many databases, none of them a default.
  render "$PRACTICE_CONF" 640 "root:$ODOO_USER" <<EOF
[options]
admin_passwd = $(cat "$PRACTICE_SECRETS/master.password")
db_host = localhost
db_port = 5432
db_user = $DB_ROLE
db_password = $(cat "$PRACTICE_SECRETS/db.password")
dbfilter = ^${SPACE_DB_PREFIX}%d\$
list_db = False
addons_path = /opt/auditisa-practice/current/addons,/opt/odoo19/src/addons,/opt/odoo19/src/odoo/addons
data_dir = $PRACTICE_DATA_DIR
logfile = $LOG_DIR/odoo.log
log_level = info
log_handler = :INFO,werkzeug:WARNING
http_interface = 127.0.0.1
http_port = $PRACTICE_PORT
gevent_port = $((PRACTICE_PORT + 1))
proxy_mode = True
workers = $PRACTICE_WORKERS
max_cron_threads = 1
limit_memory_soft = $LIMIT_SOFT
limit_memory_hard = $LIMIT_HARD
limit_time_cpu = 300
limit_time_real = 600
limit_request = 8192
; practice spaces never send mail
email_from = False
smtp_server = False
EOF
  render "/etc/systemd/system/$PRACTICE_SERVICE.service" 644 root:root <<EOF
[Unit]
Description=Odoo 19 client practice spaces ($PRACTICE_NAME)
After=postgresql.service network.target
Requires=postgresql.service

[Service]
User=$ODOO_USER
Group=$ODOO_USER
# Root's guard first: only copies of the demo template are ever served.
ExecStartPre=+/usr/local/sbin/practice-guard check
ExecStart=$ODOO_PY $ODOO_BIN -c $PRACTICE_CONF
Restart=on-failure
RestartSec=5
Nice=5
MemoryMax=$PRACTICE_MEMORY
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=$PRACTICE_DATA_DIR $LOG_DIR
ProtectKernelTunables=yes
ProtectControlGroups=yes
Environment=LANG=C.UTF-8

[Install]
WantedBy=multi-user.target
EOF
  render "/etc/logrotate.d/$PRACTICE_SERVICE" 644 root:root <<EOF
$LOG_DIR/*.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
    copytruncate
}
EOF
  run systemctl daemon-reload
}

# The headers Odoo receives. Repeated in every location that sets one of its own, because nginx
# drops the inherited proxy_set_header lines of a location that has any.
proxy_headers() {
  local slug_var=$1 indent=$2
  cat <<EOF
${indent}proxy_set_header Host $slug_var.$PRACTICE_DOMAIN;
${indent}proxy_set_header X-Forwarded-Host $slug_var.$PRACTICE_DOMAIN;
${indent}proxy_set_header X-Forwarded-Proto https;
${indent}proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
${indent}proxy_set_header X-Real-IP \$remote_addr;
${indent}# Choosing a database by header is not offered.
${indent}proxy_set_header X-Odoo-Database "";
EOF
}

# The proxy part shared by the real site and the preview: the host Odoo sees is always
# <slug>.<domain>, built here from a checked slug, so Odoo's dbfilter can only ever pick that space.
# proxy_block <slug variable> [origin variable]: the preview rewrites the websocket's Origin to the
# space's name when it was the preview's own; the real site passes it as the browser sent it.
proxy_block() {
  local slug_var=$1 origin_var=${2:-}
  cat <<EOF
    client_max_body_size 64m;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
EOF
  proxy_headers "$slug_var" "    "
  cat <<EOF

    add_header X-Robots-Tag "noindex, nofollow" always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;
    add_header X-Frame-Options SAMEORIGIN always;

    # No database manager from the outside: no list, no backup, no restore, no upload of a dump.
    location ~ ^/web/database { return 404; }

    location = /web/login {
        limit_req zone=practice_login burst=20 nodelay;
        proxy_pass http://practice_odoo;
    }
    location /websocket {
        proxy_http_version 1.1;
EOF
  proxy_headers "$slug_var" "        "
  # shellcheck disable=SC2016  # nginx variables, written as they are
  printf '        proxy_set_header Upgrade $http_upgrade;\n        proxy_set_header Connection "upgrade";\n'
  if [ -n "$origin_var" ]; then printf '        proxy_set_header Origin %s;\n' "$origin_var"; fi
  cat <<EOF
        proxy_pass http://practice_odoo_ws;
    }
    location / { proxy_pass http://practice_odoo; }
EOF
}

configure_nginx() {
  local ws_port=$PRACTICE_PORT
  [ "$PRACTICE_WORKERS" = 0 ] || ws_port=$((PRACTICE_PORT + 1))
  render /etc/nginx/conf.d/practice-common.conf 644 root:root <<EOF
upstream practice_odoo { server 127.0.0.1:$PRACTICE_PORT; }
upstream practice_odoo_ws { server 127.0.0.1:$ws_port; }
limit_req_zone \$binary_remote_addr zone=practice_login:10m rate=30r/m;
EOF
  if [ "$PREVIEW" = 1 ]; then
    configure_preview_site
    return 0
  fi
  # Until the wildcard certificate exists (practice-cert.sh), port 80 says so and serves nothing.
  render "/etc/nginx/sites-available/practice-http.conf" 644 root:root <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    location / { return 301 https://\$host\$request_uri; }
}
EOF
  local cert=/etc/letsencrypt/live/$PRACTICE_DOMAIN
  {
    cat <<EOF
# *.$PRACTICE_DOMAIN: the first part of the name is the space. Any other name gets nothing.
server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name _;
    ssl_reject_handshake on;
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name ~^(?<practice_slug>[a-z][a-z0-9-]{1,30}[a-z0-9])\.${PRACTICE_DOMAIN//./\\.}\$;

    ssl_certificate $cert/fullchain.pem;
    ssl_certificate_key $cert/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    add_header Strict-Transport-Security "max-age=31536000" always;

EOF
    proxy_block "\$practice_slug"
    printf '}\n'
  } | render "/etc/nginx/sites-available/$SITE" 644 root:root
  run rm -f /etc/nginx/sites-enabled/default
  run ln -sfn /etc/nginx/sites-available/practice-http.conf /etc/nginx/sites-enabled/practice-http.conf
  if [ "$DRY_RUN" = 0 ] && [ -r "$cert/fullchain.pem" ]; then
    ln -sfn "/etc/nginx/sites-available/$SITE" "/etc/nginx/sites-enabled/$SITE"
  else
    log "no wildcard certificate yet: HTTPS waits for practice-cert.sh (docs/runbook/PRACTICE-SPACES.md)"
  fi
  run nginx -t
  run systemctl enable --now nginx
  run systemctl reload nginx
}

# The preview has no wildcard name: one extra HTTPS port on a name that exists. A link
# /practice/<slug> chooses the space with a cookie, and nginx turns the cookie into the host name
# the real computer would have received. Odoo's configuration is the same as on the real one.
configure_preview_site() {
  {
    cat <<EOF
# Preview of the practice spaces on $PREVIEW_HOST:$PREVIEW_PORT. The space comes from the
# ea_practice_space cookie, set by /practice/<slug>; without it, nothing reaches Odoo.
map \$cookie_ea_practice_space \$practice_preview_slug {
    "~^[a-z][a-z0-9-]{1,30}[a-z0-9]\$" \$cookie_ea_practice_space;
    default "";
}
map \$http_origin \$practice_ws_origin {
    "https://$PREVIEW_HOST:$PREVIEW_PORT" "https://\$practice_preview_slug.$PRACTICE_DOMAIN";
    default "";
}

server {
    listen $PREVIEW_PORT ssl;
    listen [::]:$PREVIEW_PORT ssl;
    server_name $PREVIEW_HOST;

    ssl_certificate /etc/letsencrypt/live/$PREVIEW_CERT/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$PREVIEW_CERT/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    access_log /var/log/nginx/practice-preview.access.log;
    error_log /var/log/nginx/practice-preview.error.log;

    # The link to a space: sets the cookie and goes to its login page. Odoo logs out a session of
    # another space by itself (its dbfilter refuses the session's database).
    location ~ "^/practice/(?<practice_pick>[a-z][a-z0-9-]{1,30}[a-z0-9])/?\$" {
        add_header Set-Cookie "ea_practice_space=\$practice_pick; Path=/; Secure; HttpOnly; SameSite=Lax" always;
        return 302 /web/login;
    }
    location = /practice { return 404; }

    # Without a chosen space nothing reaches Odoo. Server-level rewrites run before the locations,
    # hence the exception for the links.
    set \$practice_gate \$practice_preview_slug;
    if (\$uri ~ "^/practice/") { set \$practice_gate pick; }
    if (\$practice_gate = "") { return 403 "Practice space: open the link you were given. / Espace d'entrainement : ouvrez le lien qui vous a ete donne.\n"; }
    default_type "text/plain; charset=utf-8";

EOF
    proxy_block "\$practice_preview_slug" "\$practice_ws_origin"
    printf '}\n'
  } | render "/etc/nginx/sites-available/$PREVIEW_SITE" 644 root:root
  if [ "$DRY_RUN" = 1 ]; then
    printf '+ back up /etc/nginx to /root/nginx-backup-<stamp>.tar.gz before enabling the site\n'
  else
    tar -czf "/root/nginx-backup-$(date -u +%Y%m%dT%H%M%SZ).tar.gz" -C / etc/nginx
  fi
  run ln -sfn "/etc/nginx/sites-available/$PREVIEW_SITE" "/etc/nginx/sites-enabled/$PREVIEW_SITE"
  if [ "$DRY_RUN" = 0 ]; then
    if ! nginx -t -q; then
      rm -f "/etc/nginx/sites-enabled/$PREVIEW_SITE" "$R/etc/nginx/conf.d/practice-common.conf"
      die "nginx refused the preview site: removed again, nothing else changed"
    fi
    systemctl reload nginx
  fi
}

timer() {
  local name=$1 calendar=$2 description=$3
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

[Install]
WantedBy=timers.target
EOF
  run systemctl daemon-reload
  run systemctl enable --now "$name.timer"
}

configure_timers() {
  # The guard's timer runs `practice-guard`, which checks and stops the service on a finding.
  timer practice-guard '*:0/10' "Practice spaces: only copies of the demo template are served"
  timer practice-heartbeat '*:3/10' "Practice spaces: figures for the control room"
  if [ "$PREVIEW" = 0 ]; then
    secret /etc/auditisa-practice/secrets/heartbeat.token 600
  fi
}

finish() {
  log "next: practice-template build, then practice-space create (see docs/runbook/PRACTICE-SPACES.md)"
}

# ---------------------------------------------------------------------------- the recipe

step check_system check_system
step folders prepare_folders
step packages install_packages
step firewall configure_firewall
step postgres configure_postgres
step odoo install_odoo
step user create_user
step release install_release
step odoo_conf configure_odoo
step nginx configure_nginx
step timers configure_timers
step finish finish
log "the practice computer $PRACTICE_NAME is set up"
