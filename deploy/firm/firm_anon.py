#!/usr/bin/env python3
"""Anonymises a COPY of a firm's database, at the firm's server. See docs/runbook/PIPELINE.md.

    firm_anon.py inventory --db NAME                     tables, text columns and models, as JSON
    firm_anon.py preflight --db NAME --manifest FILE     says whether the manifest covers the database
    firm_anon.py run --db COPY --manifest FILE --dump OUT --report OUT
                                                         anonymises the copy, dumps it, scans the dump

Everything stops rather than guesses:
  - a table, a text column or a model that the manifest does not list stops the export;
  - any value kept as it is must match a strict pattern, or it is replaced;
  - the finished dump is read back as plain text and searched for every identifying value taken from
    the copy before it was touched, and for the shapes of an email, a tax number, a phone number, a
    trade register number and a bank account. One hit stops the export.

It prints table names, column names, counts and rule names. It never prints or stores a value from
the database: what it collects to search for stays in this process and dies with it.

`COPY` must be a throwaway copy: `run` refuses a name that does not start with an accepted prefix.
Standard library and psycopg2 only, the second being in Odoo's virtualenv. Runs as postgres.
"""

import argparse
import json
import os
import re
import secrets
import subprocess
import sys

EXIT_STOP = 3

# Text-like types. A column of any type not named here or in SAFE_TYPES stops the export.
TEXT_TYPES = {"character varying", "text", "character"}
JSON_TYPES = {"jsonb", "json"}
BYTE_TYPES = {"bytea"}
SAFE_TYPES = {
    "integer", "bigint", "smallint", "boolean", "numeric", "double precision", "real", "date", "oid",
    "timestamp without time zone", "timestamp with time zone", "time without time zone",
}
INSPECTED_TYPES = TEXT_TYPES | JSON_TYPES | BYTE_TYPES

CLASSES = {"reference", "firm", "purge", "relation"}
RULES = {
    "text", "html", "person", "company", "party", "email", "phone", "idnum", "hash", "null",
    "sel", "login", "answer", "emptydict", "json",
}
# These feed the search list: what they replace is what must never be seen again. `person` is not one of
# them: a control's owner is often "Le gérant", found in every definition. The columns that hold real
# people's names are named one by one in the manifest's `harvest_also`.
HARVEST_RULES = {"company", "party", "email", "phone", "idnum", "login"}
MIN_HARVEST_LENGTH = 5
SYSTEM_LOGINS = ("__system__", "default", "public", "portal", "admin")
COPY_PREFIXES = ("anon_", "ci_pipeline_")

# What a value kept inside free text or JSON may look like. Nothing here can hold a name.
AMOUNT = r"^-?[0-9][0-9 .,]{0,30}$"
DAY = r"^[0-9]{1,4}[-/.][0-9]{1,2}[-/.][0-9]{1,4}([ T][0-9:.]{4,15}Z?)?$"
TASK_CODE = r"^[A-Z]{1,2}[0-9]{1,3}(\.[0-9]{1,3})*$"
JSON_KEY = r"^[a-z][a-zA-Z0-9_]{0,40}$"


class Stop(Exception):
    """A reason to stop the export. `code` and `detail` hold names and counts, never a value."""

    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# ------------------------------------------------------------------ pure part


def check_manifest_shape(manifest):
    """A manifest with an unknown class or rule is refused before it touches anything."""
    patterns = manifest.get("patterns", {})
    for table, entry in manifest["tables"].items():
        if entry.get("class") not in CLASSES:
            raise Stop("bad-manifest", f"{table}: class")
        for column, rule in (entry.get("columns") or {}).items():
            if entry["class"] == "firm":
                name = rule[5:] if rule.startswith("keep:") else None
                if name is not None and name not in patterns:
                    raise Stop("bad-manifest", f"{table}.{column}: pattern")
                if name is None and rule not in RULES:
                    raise Stop("bad-manifest", f"{table}.{column}: rule")


def compare_inventory(manifest, inventory):
    """Every reason this database is not covered, as (code, detail). Empty means covered."""
    problems = []
    listed = manifest["tables"]
    for model in inventory["models"]:
        if model not in manifest["models"]:
            problems.append(("unlisted-model", model))
    for extra in inventory.get("other_relations", []):
        problems.append(("unlisted-relation", extra))
    for table, columns in inventory["tables"].items():
        entry = listed.get(table)
        if entry is None:
            problems.append(("unlisted-table", table))
            continue
        kind = entry["class"]
        inspected = {name: kind_ for name, kind_ in columns.items() if kind_ not in SAFE_TYPES}
        for name, data_type in inspected.items():
            if data_type not in INSPECTED_TYPES and kind != "purge":
                problems.append(("unknown-type", f"{table}.{name}"))
        if kind == "purge":
            continue  # Its rows go: what its columns hold does not matter.
        if kind == "relation":
            if inspected:
                problems.append(("text-in-relation", table))
            continue
        known = entry.get("columns", {})
        for name, data_type in inspected.items():
            if data_type not in INSPECTED_TYPES:
                continue
            if name not in known:
                problems.append(("unlisted-column", f"{table}.{name}"))
            elif kind == "firm":
                rule = known[name]
                if data_type in JSON_TYPES and rule not in ("json", "null"):
                    problems.append(("rule-does-not-fit-type", f"{table}.{name}"))
                elif data_type in TEXT_TYPES and rule == "json":
                    problems.append(("rule-does-not-fit-type", f"{table}.{name}"))
                elif data_type in BYTE_TYPES and rule != "null":
                    problems.append(("rule-does-not-fit-type", f"{table}.{name}"))
    return problems


def quote_ident(name):
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", name):
        raise Stop("bad-identifier", "a table or column name has an unexpected form")
    return f'"{name}"'


def _literal(text):
    return "'" + text.replace("'", "''") + "'"


def expression(rule, column, patterns, nullable=True, max_length=None, table=None):
    """The SQL giving a column's new value. NULL and the empty string stay as they are."""
    col = quote_ident(column)
    typed = f"{col}::text"
    h = f"pg_temp.anon_h({typed})"
    blank = "NULL" if nullable else "''"

    def fit(sql):
        return f"left({sql}, {int(max_length)})" if max_length else sql

    def replace(sql):
        return f"CASE WHEN {col} IS NULL OR {typed} = '' THEN {col} ELSE {fit(sql)} END"

    if rule == "text":
        return replace(f"'[anon ' || {h} || ']'")
    if rule == "html":
        return replace(f"'<p>[anon ' || {h} || ']</p>'")
    if rule == "person":
        return replace(f"'Personne ' || {h}")
    if rule == "company":
        return replace(f"'Societe ' || {h}")
    if rule == "party":
        return replace(f"CASE WHEN is_company THEN 'Societe ' ELSE 'Personne ' END || {h}")
    if rule == "email":
        return replace(f"'u' || {h} || '@anon.invalid'")
    if rule == "phone":
        return replace(f"'+000 ' || translate({h}, 'abcdef', '012345')")
    if rule == "idnum":
        return replace(f"'ANON-' || upper({h})")
    if rule == "hash":
        # Same length as a real one, derived from a salt that is thrown away.
        return replace(f"left(encode(sha256(convert_to(current_setting('anon.salt') || 'hash' || {typed}, 'UTF8')), 'hex'), length({typed}))")
    if rule == "null":
        return blank
    if rule == "sel":
        return f"CASE WHEN {col} IS NULL OR {typed} = '' OR {typed} IN (SELECT w FROM pg_temp.anon_words) THEN {col} ELSE {blank} END"
    if rule == "login":
        names = ", ".join(_literal(login) for login in SYSTEM_LOGINS)
        return f"CASE WHEN {col} IN ({names}) THEN {col} ELSE 'u' || {h} || '@anon.invalid' END"
    if rule == "answer":
        return f"CASE WHEN {col} IS NULL OR pg_temp.anon_safe({typed}) THEN {col} ELSE '[anon ' || {h} || ']' END"
    if rule == "emptydict":
        return "'{}'"
    if rule == "json":
        return f"pg_temp.anon_json({col})"
    if rule.startswith("keep:"):
        name = rule[5:]
        spec = patterns[name]
        fallback = spec.get("else", "text")
        if fallback == "digits":
            other = f"'9' || translate(left({h}, 8), 'abcdef', '012345')"
        elif fallback == "blank":
            other = blank
        else:
            other = f"'[anon ' || {h} || ']'"
        return f"CASE WHEN {col} IS NULL OR {typed} = '' OR {typed} ~ {_literal(spec['re'])} THEN {col} ELSE {fit(other)} END"
    raise Stop("bad-manifest", f"rule {rule}")


FUNCTIONS = """
CREATE TEMP TABLE anon_words (w text PRIMARY KEY) ON COMMIT PRESERVE ROWS;
CREATE TEMP TABLE anon_keys (w text PRIMARY KEY) ON COMMIT PRESERVE ROWS;

CREATE FUNCTION pg_temp.anon_h(value text) RETURNS text LANGUAGE sql STABLE AS $f$
    SELECT left(encode(sha256(convert_to(current_setting('anon.salt') || value, 'UTF8')), 'hex'), 10)
$f$;

CREATE FUNCTION pg_temp.anon_safe(value text) RETURNS boolean LANGUAGE sql STABLE AS $f$
    SELECT value = '' OR value ~ %(amount)s OR value ~ %(day)s OR value ~ %(task)s
        OR EXISTS (SELECT 1 FROM pg_temp.anon_words WHERE w = value)
$f$;

CREATE FUNCTION pg_temp.anon_key(value text) RETURNS text LANGUAGE sql STABLE AS $f$
    SELECT CASE WHEN value ~ %(key)s OR value ~ %(task)s
                  OR EXISTS (SELECT 1 FROM pg_temp.anon_keys WHERE w = value)
                THEN value ELSE 'k_' || pg_temp.anon_h(value) END
$f$;

CREATE FUNCTION pg_temp.anon_json(value jsonb) RETURNS jsonb LANGUAGE plpgsql STABLE AS $f$
DECLARE
    kind text := jsonb_typeof(value);
    result jsonb;
    item_key text;
    item jsonb;
    string text;
BEGIN
    IF value IS NULL THEN
        RETURN NULL;
    ELSIF kind = 'object' THEN
        result := '{}'::jsonb;
        FOR item_key, item IN SELECT * FROM jsonb_each(value) LOOP
            result := result || jsonb_build_object(pg_temp.anon_key(item_key), pg_temp.anon_json(item));
        END LOOP;
        RETURN result;
    ELSIF kind = 'array' THEN
        result := '[]'::jsonb;
        FOR item IN SELECT * FROM jsonb_array_elements(value) LOOP
            result := result || jsonb_build_array(pg_temp.anon_json(item));
        END LOOP;
        RETURN result;
    ELSIF kind = 'string' THEN
        string := value #>> '{}';
        IF pg_temp.anon_safe(string) THEN
            RETURN value;
        END IF;
        RETURN to_jsonb('[anon ' || pg_temp.anon_h(string) || ']');
    END IF;
    RETURN value;
END;
$f$;
"""


def build_scanner(denied, scan):
    """Returns check(line) giving the names of what the line shows, without saying what it read."""
    terms = sorted({term.casefold() for term in denied if len(term) >= MIN_HARVEST_LENGTH}, key=len, reverse=True)
    denylist = None
    if terms:
        # Boundaries by lookaround: a term can start or end with punctuation.
        denylist = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(term) for term in terms) + r")(?![\w])")
    shapes = {name: re.compile(pattern) for name, pattern in scan.get("patterns", {}).items()}
    email = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
    allowed_domains = {domain.casefold() for domain in scan.get("email_domains_allowed", [])}

    def check(line):
        found = []
        if denylist and denylist.search(line.casefold()):
            found.append("identifying-value")
        for name, shape in shapes.items():
            if shape.search(line):
                found.append(name)
        for match in email.finditer(line):
            domain = match.group(1).casefold()
            if domain not in allowed_domains and not any(domain.endswith("." + other) for other in allowed_domains):
                found.append("email-address")
                break
        return found

    return check


def scan_lines(lines, check, ignore=None):
    """Reads a plain-text dump. Returns {(table, what): count}. A table's name is taken from its COPY."""
    ignore = ignore or {}
    table = None
    hits = {}
    copy_start = re.compile(r"^COPY (?:public\.)?\"?([a-z0-9_]+)\"? ")
    for line in lines:
        if table is None:
            match = copy_start.match(line)
            if match:
                table = match.group(1)
                continue
        elif line.startswith("\\."):
            table = None
            continue
        for what in check(line):
            if what in ignore.get(table or "", ()) or what in ignore.get("*", ()):
                continue
            key = (table or "(schema)", what)
            hits[key] = hits.get(key, 0) + 1
    return hits


def scan_failures(hits):
    return sorted(f"{table}: {what} ({count})" for (table, what), count in hits.items())


# ------------------------------------------------------------------ database part


def _connect(db):
    import psycopg2  # Only here: the pure part is tested where psycopg2 is not installed.

    connection = psycopg2.connect(dbname=db)
    connection.autocommit = False
    return connection


def read_inventory(cursor):
    cursor.execute("""
        SELECT c.table_name, c.column_name, c.data_type
          FROM information_schema.columns c
          JOIN information_schema.tables t USING (table_schema, table_name)
         WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'
         ORDER BY 1, c.ordinal_position
    """)
    tables = {}
    for table, column, data_type in cursor.fetchall():
        tables.setdefault(table, {})[column] = data_type
    cursor.execute("SELECT model FROM ir_model ORDER BY 1")
    models = [row[0] for row in cursor.fetchall()]
    # Anything that can hold data and is not a plain table in `public` is a reason to stop.
    cursor.execute("""
        SELECT n.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE c.relkind IN ('r', 'm', 'p', 'f')
           AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
           AND n.nspname NOT LIKE 'pg_temp%%' AND n.nspname NOT LIKE 'pg_toast_temp%%'
           AND (n.nspname <> 'public' OR c.relkind <> 'r')
    """)
    other = [row[0] for row in cursor.fetchall()]
    cursor.execute("SELECT count(*) FROM pg_largeobject_metadata")
    if cursor.fetchone()[0]:
        other.append("large objects")
    return {"tables": tables, "models": models, "other_relations": other}


def preflight(cursor, manifest):
    check_manifest_shape(manifest)
    problems = compare_inventory(manifest, read_inventory(cursor))
    if problems:
        for code, detail in problems[:50]:
            print(f"STOP {code}: {detail}")
        if len(problems) > 50:
            print(f"... and {len(problems) - 50} more")
        raise Stop(problems[0][0], problems[0][1])


def column_facts(cursor):
    cursor.execute("""
        SELECT table_name, column_name, is_nullable = 'YES', character_maximum_length
          FROM information_schema.columns WHERE table_schema = 'public'
    """)
    return {(table, column): (nullable, size) for table, column, nullable, size in cursor.fetchall()}


def harvest(cursor, manifest):
    """Every identifying value in the copy, kept in this process's memory only."""
    cursor.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = 'base' AND model = 'res.partner'
           AND name IN ('partner_root', 'public_partner', 'partner_admin', 'template_portal_user_id_res_partner',
                        'default_user_res_partner', 'public_user_res_partner', 'main_partner')
    """)
    system_partners = {row[0] for row in cursor.fetchall()}
    # Words of the product or of Odoo itself would stop every export on the reference tables.
    cursor.execute("SELECT DISTINCT value FROM ir_model_fields_selection")
    common = {row[0].casefold() for row in cursor.fetchall()}
    common.update(word.casefold() for word in manifest.get("harvest_ignore", []))
    denied = set()

    def add(value):
        if not isinstance(value, str):
            return
        value = value.strip()
        if value.startswith(("{", "[")):
            # A translated field, read as text: what counts is what its JSON says.
            try:
                parsed = json.loads(value)
            except ValueError:
                parsed = None
            if parsed is not None:
                for leaf in _json_strings(parsed):
                    add(leaf)
                return
        if len(value) >= MIN_HARVEST_LENGTH and value.casefold() not in common:
            denied.add(value)
            if "@" in value:
                domain = value.rsplit("@", 1)[1].casefold()
                if domain not in {d.casefold() for d in manifest["scan"].get("email_domains_allowed", [])}:
                    add(domain)

    extras = set(manifest.get("harvest_also", []))
    for table, entry in manifest["tables"].items():
        if entry["class"] == "reference" or entry["class"] == "relation":
            continue
        if not _table_exists(cursor, table):
            continue
        for column, rule in (entry.get("columns") or {}).items():
            if rule in HARVEST_RULES or f"{table}.{column}" in extras:
                if not _column_exists(cursor, table, column):
                    continue
                where = ""
                if table == "res_partner" and system_partners:
                    where = " WHERE id NOT IN (" + ",".join(str(int(i)) for i in system_partners) + ")"
                if table == "res_users" and column == "login":
                    where = " WHERE login NOT IN (" + ", ".join(_literal(x) for x in SYSTEM_LOGINS) + ")"
                cursor.execute(f"SELECT DISTINCT {quote_ident(column)}::text FROM {quote_ident(table)}{where}")
                for row in cursor.fetchall():
                    add(row[0])
    # The purged tables hold names too, and they may also sit somewhere that is kept.
    for table, columns in manifest.get("harvest_purged", {}).items():
        if _table_exists(cursor, table):
            for column in columns:
                if _column_exists(cursor, table, column):
                    cursor.execute(f"SELECT DISTINCT {quote_ident(column)}::text FROM {quote_ident(table)}")
                    for row in cursor.fetchall():
                        add(row[0])
    return denied


def _json_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _json_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _json_strings(item)


def _table_exists(cursor, table):
    cursor.execute("SELECT to_regclass(%s)", [f"public.{quote_ident(table)}"])
    return cursor.fetchone()[0] is not None


def _column_exists(cursor, table, column):
    cursor.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
        [table, column],
    )
    return bool(cursor.fetchone())


def figures(cursor, manifest):
    """Row count and the total of each numeric column of each firm table, to compare afterwards."""
    cursor.execute("""
        SELECT table_name, column_name FROM information_schema.columns
         WHERE table_schema = 'public' AND data_type IN ('numeric', 'double precision', 'real')
    """)
    numeric = {}
    for table, column in cursor.fetchall():
        numeric.setdefault(table, []).append(column)
    result = {}
    for table, entry in manifest["tables"].items():
        if entry["class"] != "firm" or not _table_exists(cursor, table):
            continue
        parts = ["count(*)"] + [f"coalesce(round(sum({quote_ident(column)}::numeric), 6), 0)" for column in numeric.get(table, [])]
        cursor.execute(f"SELECT {', '.join(parts)} FROM {quote_ident(table)}")
        result[table] = tuple(str(value) for value in cursor.fetchone())
    return result


def repair_references(cursor, purged):
    """After the purge: a reference to a row that went is emptied, or its row goes if it is required."""
    cursor.execute("""
        SELECT c.conrelid::regclass::text, a.attname, a.attnotnull, c.confrelid::regclass::text, fa.attname
          FROM pg_constraint c
          JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
          JOIN pg_attribute fa ON fa.attrelid = c.confrelid AND fa.attnum = c.confkey[1]
         WHERE c.contype = 'f' AND array_length(c.conkey, 1) = 1 AND c.connamespace = 'public'::regnamespace
    """)
    foreign_keys = cursor.fetchall()
    deleted = {}
    while True:
        changed = 0
        for table, column, required, target, target_column in foreign_keys:
            table, target = table.strip('"'), target.strip('"')
            if table in purged:
                continue
            col, tgt, tgt_col = quote_ident(column), quote_ident(target), quote_ident(target_column)
            missing = f"{col} IS NOT NULL AND NOT EXISTS (SELECT 1 FROM {tgt} x WHERE x.{tgt_col} = t.{col})"
            if required:
                cursor.execute(f"DELETE FROM {quote_ident(table)} t WHERE {missing}")
                if cursor.rowcount:
                    deleted[table] = deleted.get(table, 0) + cursor.rowcount
                    changed += cursor.rowcount
            else:
                cursor.execute(f"UPDATE {quote_ident(table)} t SET {col} = NULL WHERE {missing}")
                changed += cursor.rowcount
        if not changed:
            return deleted


def scrub(connection, manifest, salt):
    cursor = connection.cursor()
    cursor.execute("SET session_replication_role = replica")  # The immutability triggers do not apply to a copy.
    cursor.execute("SELECT set_config('anon.salt', %s, false)", [salt])
    cursor.execute(FUNCTIONS, {"amount": AMOUNT, "day": DAY, "task": TASK_CODE, "key": JSON_KEY})
    cursor.execute("INSERT INTO pg_temp.anon_words SELECT DISTINCT value FROM ir_model_fields_selection ON CONFLICT DO NOTHING")
    for word in manifest.get("safe_words", []):
        cursor.execute("INSERT INTO pg_temp.anon_words VALUES (%s) ON CONFLICT DO NOTHING", [word])
    for word in manifest.get("json_key_words", []):
        cursor.execute("INSERT INTO pg_temp.anon_keys VALUES (%s) ON CONFLICT DO NOTHING", [word])

    facts = column_facts(cursor)
    patterns = manifest.get("patterns", {})
    purged = set()
    purged_rows = 0
    updated_tables = 0
    for table, entry in sorted(manifest["tables"].items()):
        if entry["class"] == "purge" and _table_exists(cursor, table):
            cursor.execute(f"DELETE FROM {quote_ident(table)}")
            purged_rows += cursor.rowcount
            purged.add(table)

    keep = manifest.get("config_keep", [])
    cursor.execute("SELECT id, key FROM ir_config_parameter")
    for row_id, key in cursor.fetchall():
        if not any(re.fullmatch(pattern, key) for pattern in keep):
            cursor.execute("DELETE FROM ir_config_parameter WHERE id = %s", [row_id])

    # An external id can spell a person's name (demo_user_<name>): our addons' ids for people and clients go.
    cursor.execute(
        "DELETE FROM ir_model_data WHERE module LIKE 'ea\\_%%' AND model = ANY(%s)",
        [manifest.get("xmlid_scrub_models", [])],
    )

    deleted_by_reference = repair_references(cursor, purged)

    for table, entry in sorted(manifest["tables"].items()):
        if entry["class"] != "firm" or not _table_exists(cursor, table):
            continue
        sets = []
        for column, rule in entry.get("columns", {}).items():
            if (table, column) not in facts:
                continue
            nullable, size = facts[(table, column)]
            sets.append(f"{quote_ident(column)} = {expression(rule, column, patterns, nullable, size, table)}")
        if sets:
            cursor.execute(f"UPDATE {quote_ident(table)} SET {', '.join(sets)}")
            updated_tables += 1
    # Odoo must recognise this copy for what it is. The staging rebuild checks this mark.
    cursor.execute("""
        INSERT INTO ir_config_parameter (key, value) VALUES ('ea_audit.anonymised', '1')
        ON CONFLICT (key) DO UPDATE SET value = '1'
    """)
    cursor.close()
    return {"purged_rows": purged_rows, "updated_tables": updated_tables, "deleted_by_reference": deleted_by_reference}


def compare_figures(before, after, deleted_by_reference):
    """The figures must not move. Tables that lost rows through a purged file are the one exception."""
    changed = []
    for table, values in before.items():
        if table in deleted_by_reference:
            continue
        if after.get(table) != values:
            changed.append(table)
    return changed


def dump_and_scan(db, dump_path, manifest, denied):
    with open(dump_path, "wb") as out:
        subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--no-acl", db], stdout=out, check=True)
    # What is searched is what would leave: the dump itself, read back.
    reader = subprocess.Popen(["pg_restore", "--file=-", dump_path], stdout=subprocess.PIPE, encoding="utf-8", errors="replace")
    check = build_scanner(denied, manifest["scan"])
    hits = scan_lines(reader.stdout, check, manifest["scan"].get("ignore"))
    if reader.wait() != 0:
        raise Stop("dump-not-readable")
    return hits


def run(args, manifest):
    if not args.db.startswith(COPY_PREFIXES):
        raise Stop("not-a-copy", "the database name does not start with an accepted prefix")
    connection = _connect(args.db)
    cursor = connection.cursor()
    preflight(cursor, manifest)
    denied = harvest(cursor, manifest)
    before = figures(cursor, manifest)
    connection.commit()
    print(f"preflight passed; {len(manifest['tables'])} tables listed; {len(denied)} values to search for")

    summary = scrub(connection, manifest, secrets.token_hex(32))
    cursor = connection.cursor()
    cursor.execute("SET session_replication_role = origin")
    connection.commit()
    after = figures(cursor, manifest)
    connection.close()
    moved = compare_figures(before, after, summary["deleted_by_reference"])
    if moved:
        raise Stop("figures-moved", ", ".join(moved))
    print(f"scrubbed {summary['updated_tables']} tables; {summary['purged_rows']} rows purged; figures unchanged")

    hits = dump_and_scan(args.db, args.dump, manifest, denied)
    if hits:
        os.unlink(args.dump)
        for line in scan_failures(hits)[:80]:
            print(f"STOP survivor in {line}")
        raise Stop("survivors", f"{len(hits)} table and kind pairs")
    report = {
        "schema": 1,
        "anonymised": True,
        "tables_listed": len(manifest["tables"]),
        "tables_scrubbed": summary["updated_tables"],
        "rows_purged": summary["purged_rows"],
        "rows_removed_with_their_file": summary["deleted_by_reference"],
        "values_searched": len(denied),
        "survivors": 0,
        "figures_unchanged": True,
        "files_included": False,
    }
    with open(args.report, "w", encoding="ascii") as out:
        json.dump(report, out, sort_keys=True, indent=1)
    print("dump scanned: no survivor")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["inventory", "preflight", "run"])
    parser.add_argument("--db", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--dump")
    parser.add_argument("--report")
    args = parser.parse_args(argv)
    try:
        if args.command == "inventory":
            connection = _connect(args.db)
            json.dump(read_inventory(connection.cursor()), sys.stdout, sort_keys=True)
            connection.close()
            return 0
        with open(args.manifest, encoding="utf-8") as handle:
            manifest = json.load(handle)
        if args.command == "preflight":
            connection = _connect(args.db)
            preflight(connection.cursor(), manifest)
            connection.close()
            print("the manifest covers this database")
            return 0
        if not args.dump or not args.report:
            parser.error("run needs --dump and --report")
        run(args, manifest)
        return 0
    except Stop as stop:
        print(f"STOPPED: {stop}")
        return EXIT_STOP


if __name__ == "__main__":
    sys.exit(main())
