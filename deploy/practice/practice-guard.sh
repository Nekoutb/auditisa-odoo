#!/usr/bin/env bash
# practice-guard.sh: real client data never lands on the practice computer.
#
#   practice-guard check     exit 1 if a database is not what it should be (run before Odoo starts)
#   practice-guard           the timer's run: check, and on a finding stop the practice service
#
# Every practice_<slug> database must be a copy of this computer's demo template: registered by
# practice-space, carrying its slug and the id of the template build it was copied from, and none
# of the marks of a firm's database (the firm agent's settings) or of an anonymised copy. A
# database loaded from a dump has none of that. A finding:
#   - makes `check` fail, so the service does not start (ExecStartPre);
#   - closes that database to connections (nothing is dropped: the operator looks, then drops it
#     by hand, see docs/runbook/PRACTICE-SPACES.md);
#   - stops the service when the timer finds it.
#
# On the real practice computer (PRACTICE_STRICT_CLUSTER=1) every other database of the cluster is
# a finding too, whatever its name. On the preview, which shares staging's PostgreSQL, only the
# practice_ and tpl_practice_ names are looked at.
#
# Each run also switches every mail server of every space off again.

set -euo pipefail
SCRIPT_NAME=practice-guard
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/practice/practice-lib.sh
. "$HERE/practice-lib.sh"

# Keys that only a firm's database or an anonymised copy has.
readonly FOREIGN_KEYS="'ea_firm_agent.slug','ea_firm_agent.heartbeat_url','ea_firm_agent.first_admin_hash','ea_audit.anonymised'"

# judge <db> <strict 0|1> <registered 0|1> <space mark> <template mark> <expected template> <foreign marks>
# Prints "ok" or the finding. Pure: the tests call it directly.
judge() {
  local db=$1 strict=$2 registered=$3 space=$4 template=$5 expected=$6 foreign=$7 slug
  case "$db" in
    "$TEMPLATE_DB"|"$TEMPLATE_BUILD_DB") printf 'ok\n'; return ;;
  esac
  if [[ $db =~ ^upd_practice_(.+)$ ]] && valid_slug "${BASH_REMATCH[1]}"; then
    printf 'ok\n'  # a space's copy during an update, closed to connections
    return
  fi
  if ! slug=$(slug_of_db "$db"); then
    if [[ $db == "$SPACE_DB_PREFIX"* || $db == tpl_practice* ]]; then
      printf 'not a valid practice space name\n'
    elif [ "$strict" = 1 ]; then
      printf 'a database that is not a practice space\n'
    else
      printf 'ok\n'
    fi
    return
  fi
  if [ "$registered" != 1 ]; then printf 'not created by practice-space\n'; return; fi
  if [ "$foreign" != 0 ]; then printf "carries a firm's or an anonymised copy's marks\n"; return; fi
  if [ "$space" != "$slug" ]; then printf 'its space mark is missing or wrong\n'; return; fi
  if [ -z "$expected" ] || [ "$template" != "$expected" ]; then printf 'not a copy of this computer'"'"'s demo template\n'; return; fi
  printf 'ok\n'
}

# The marks of one database, read as postgres: "<space>|<template>|<foreign count>", or "unreadable".
marks_of() {
  local db=$1
  psql_q "SELECT coalesce((SELECT value FROM ir_config_parameter WHERE key = 'ea_practice.space'), '')
            || '|' || coalesce((SELECT value FROM ir_config_parameter WHERE key = 'ea_practice.template_id'), '')
            || '|' || (SELECT count(*) FROM ir_config_parameter WHERE key IN ($FOREIGN_KEYS))" "$db" 2>/dev/null \
    || printf 'unreadable\n'
}

FINDINGS=0

check_all() {
  local db slug registered marks space template foreign expected verdict allowconn
  while read -r db; do
    [ -n "$db" ] || continue
    if [ "$PRACTICE_STRICT_CLUSTER" != 1 ] && [[ $db != practice_* && $db != tpl_practice* && $db != upd_practice_* ]]; then
      continue
    fi
    registered=0 space="" template="" foreign=0 expected=""
    if slug=$(slug_of_db "$db"); then
      if [ -r "$(space_file "$slug")" ]; then
        registered=1
        expected=$(sed -n "s/^TEMPLATE_ID='\([0-9a-f]\{32\}\)'$/\1/p" "$(space_file "$slug")")
      fi
      allowconn=$(psql_q "SELECT datallowconn FROM pg_database WHERE datname = '$db'")
      if [ "$allowconn" = t ]; then
        marks=$(marks_of "$db")
        if [ "$marks" = unreadable ]; then
          space="" template="" foreign=1
        else
          IFS='|' read -r space template foreign <<<"$marks"
        fi
      else
        foreign=1  # closed by an earlier finding: stays a finding until the operator drops it
      fi
    fi
    verdict=$(judge "$db" "$PRACTICE_STRICT_CLUSTER" "$registered" "$space" "$template" "$expected" "$foreign")
    if [ "$verdict" != ok ]; then
      FINDINGS=$((FINDINGS + 1))
      pl_warn "database $db: $verdict"
      if [[ $db == "$SPACE_DB_PREFIX"* ]] || [ "$PRACTICE_STRICT_CLUSTER" = 1 ]; then
        psql_q "ALTER DATABASE \"$db\" ALLOW_CONNECTIONS false" >/dev/null 2>&1 || true
      fi
      audit_line "guard finding db=$db: $verdict"
    elif [ -n "$slug" ] && [ "$registered" = 1 ]; then
      # Mail off, every time.
      psql_q "UPDATE ir_mail_server SET active = false WHERE active; DELETE FROM ir_config_parameter WHERE key = 'ea_firm_agent.mail_tested'" "$db" >/dev/null 2>&1 || true
    fi
  done < <(cluster_databases)
  mkdir -p "$PRACTICE_STATUS"
  if [ "$FINDINGS" = 0 ]; then
    printf 'ok %s\n' "$(now_utc)" > "$PRACTICE_STATUS/guard"
  else
    printf 'refused %s %s\n' "$(now_utc)" "$FINDINGS" > "$PRACTICE_STATUS/guard"
  fi
}

case "${1:-watch}" in
  check)
    load_practice_env
    check_all
    [ "$FINDINGS" = 0 ] || pl_die "$FINDINGS database(s) refused: the practice service will not serve them"
    ;;
  watch)
    load_practice_env
    # A space half-way through practice-space has no marks yet: the timer waits for its next run.
    # (`check` takes no lock: it runs when the service starts, which those scripts may do.)
    exec 7>/run/lock/practice-space.lock
    flock -n 7 || { pl_log "a practice operation is running: next run"; exit 0; }
    check_all
    if [ "$FINDINGS" != 0 ]; then
      systemctl stop "$PRACTICE_SERVICE" || true
      pl_die "$FINDINGS database(s) refused: $PRACTICE_SERVICE stopped"
    fi
    ;;
  judge) shift; judge "$@" ;;
  *) sed -n '2,22p' "$0"; exit 64 ;;
esac
