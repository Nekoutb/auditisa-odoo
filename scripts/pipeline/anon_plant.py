#!/usr/bin/env python3
"""Plants known identities in a THROWAWAY database, to prove the anonymiser removes them. Test tool.

    anon_plant.py --db ci_pipeline_src --manifest deploy/firm/anon-manifest.json

In EVERY text-like column of EVERY table the manifest lists as `firm` or `purge`, it writes a value
holding a name, an email, a tax number, a phone number and a trade register number, adding a row
where a table is empty. Then it writes the same client name and identities into the places that matter
most: answers and their history, chatter, attachments and logs.

Refuses any database whose name does not start with ci_pipeline. Prints counts only.
"""

import argparse
import json
import sys

import psycopg2

NAME = "Jean Dupont-Mbarga"
EMAIL = "jean.dupont@planted-client.cm"
NIU = "M012345678901A"
PHONE = "+237 699 12 34 56"
REGISTER = "RC/DLA/2021/B/1234"
CLIENT = "Societe Planted Agro SA"
LINE = f"PLANTED {NAME} {EMAIL} {NIU} {PHONE} {REGISTER} {CLIENT}"

# grep -i for these in the finished dump: one match is a failure.
SENTINELS = ["planted", "dupont", "mbarga", "012345678901", "699 12 34 56", "RC/DLA/2021"]

TEXT = {"character varying", "text", "character"}
JSON = {"jsonb", "json"}
BYTES = {"bytea"}


def filler(data_type):
    if data_type in ("integer", "bigint", "smallint"):
        return 1
    if data_type in ("numeric", "double precision", "real"):
        return 0
    if data_type == "boolean":
        return False
    if data_type.startswith("timestamp") or data_type == "date":
        return "2025-01-01"
    if data_type in TEXT:
        return "x"
    if data_type in JSON:
        return "{}"
    if data_type in BYTES:
        return b"x"
    raise SystemExit(f"no filler for {data_type}")


def value_for(data_type, size):
    if data_type in JSON:
        return json.dumps({LINE: LINE, "list": [LINE, {"en_US": LINE}]})
    if data_type in BYTES:
        return LINE.encode()
    return LINE[:size] if size else LINE


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    if not args.db.startswith("ci_pipeline"):
        sys.exit("refused: not a ci_pipeline database")
    with open(args.manifest, encoding="utf-8") as handle:
        manifest = json.load(handle)
    connection = psycopg2.connect(dbname=args.db)
    cursor = connection.cursor()
    cursor.execute("SET session_replication_role = replica")
    cursor.execute("""
        SELECT table_name, column_name, data_type, is_nullable = 'YES', character_maximum_length, column_default
          FROM information_schema.columns WHERE table_schema = 'public' ORDER BY table_name, ordinal_position
    """)
    columns = {}
    for table, column, data_type, nullable, size, default in cursor.fetchall():
        columns.setdefault(table, []).append((column, data_type, nullable, size, default))
    tables = columns_planted = rows_added = 0
    skipped = []
    for table, entry in sorted(manifest["tables"].items()):
        if entry["class"] not in ("firm", "purge") or table not in columns:
            continue
        cursor.execute(f'SELECT count(*) FROM "{table}"')
        names = [c[0] for c in columns[table]]
        if cursor.fetchone()[0] == 0:
            required = [c for c in columns[table] if not c[2] and c[4] is None]
            cursor.execute("SAVEPOINT add_row")
            try:
                if required:
                    sql = f"""INSERT INTO "{table}" ({', '.join(f'"{c[0]}"' for c in required)})
                              VALUES ({', '.join(['%s'] * len(required))})"""
                    cursor.execute(sql, [filler(c[1]) for c in required])
                else:
                    cursor.execute(f'INSERT INTO "{table}" DEFAULT VALUES')
                rows_added += 1
            except psycopg2.Error:
                cursor.execute("ROLLBACK TO add_row")
                skipped.append(f"{table}: no row could be added")
        selector = "id = (SELECT min(id) FROM \"%s\")" % table if "id" in names else \
            "ctid = (SELECT min(ctid) FROM \"%s\")" % table
        sets, values = [], []
        for column, data_type, _nullable, size, _default in columns[table]:
            if data_type in TEXT | JSON | BYTES:
                sets.append(f'"{column}" = %s')
                values.append(value_for(data_type, size))
                columns_planted += 1
        if sets:
            cursor.execute("SAVEPOINT plant")
            try:
                cursor.execute(f'UPDATE "{table}" SET {", ".join(sets)} WHERE {selector}', values)
            except psycopg2.Error:
                # A CHECK constraint (replica mode only lifts triggers and foreign keys): column by column.
                cursor.execute("ROLLBACK TO plant")
                for piece, value in zip(sets, values):
                    cursor.execute("SAVEPOINT one")
                    try:
                        cursor.execute(f'UPDATE "{table}" SET {piece} WHERE {selector}', [value])
                    except psycopg2.Error:
                        cursor.execute("ROLLBACK TO one")
                        skipped.append(f"{table}.{piece.split()[0]}")
            tables += 1
    # A row added above points its foreign keys at id 1, which may not exist; a restore would refuse it.
    cursor.execute("""
        SELECT c.conrelid::regclass::text, a.attname, a.attnotnull, c.confrelid::regclass::text, fa.attname
          FROM pg_constraint c
          JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
          JOIN pg_attribute fa ON fa.attrelid = c.confrelid AND fa.attnum = c.confkey[1]
         WHERE c.contype = 'f' AND array_length(c.conkey, 1) = 1 AND c.connamespace = 'public'::regnamespace
    """)
    foreign_keys = [tuple(str(x).strip('"') if isinstance(x, str) else x for x in row) for row in cursor.fetchall()]
    removed = 0
    while True:
        changed = 0
        for table, column, required, target, target_column in foreign_keys:
            missing = f"""t."{column}" IS NOT NULL AND NOT EXISTS (SELECT 1 FROM "{target}" x WHERE x."{target_column}" = t."{column}")"""
            cursor.execute(f"""UPDATE "{table}" t SET "{column}" = (SELECT min("{target_column}") FROM "{target}") WHERE {missing}
                               AND EXISTS (SELECT 1 FROM "{target}")""")
            changed += cursor.rowcount
            if required:
                cursor.execute(f"""DELETE FROM "{table}" t WHERE {missing}""")
                removed += cursor.rowcount
            else:
                cursor.execute(f"""UPDATE "{table}" t SET "{column}" = NULL WHERE {missing}""")
            changed += cursor.rowcount
        if not changed:
            break
    # The places that matter most, on several rows and not only the first.
    for sql, params in [
        ("UPDATE res_partner SET name = %s, email = %s, vat = %s, phone = %s, street = %s, company_registry = %s "
         "WHERE id IN (SELECT id FROM res_partner ORDER BY id DESC LIMIT 3)", [NAME, EMAIL, NIU, PHONE, LINE, REGISTER]),
        ("UPDATE ea_audit_client SET name = %s, niu = %s, registration_number = %s, address = %s", [CLIENT, NIU, REGISTER, LINE]),
        ("UPDATE ea_audit_engagement SET name = %s", [f"{CLIENT} 2024"]),
        ("UPDATE ea_audit_paper_answer SET value = %s WHERE id IN (SELECT id FROM ea_audit_paper_answer ORDER BY id DESC LIMIT 50)", [LINE]),
        ("UPDATE ea_audit_paper_answer_history SET before = %s, after = %s WHERE id IN (SELECT id FROM ea_audit_paper_answer_history ORDER BY id DESC LIMIT 50)", [LINE, LINE]),
        ("UPDATE mail_message SET body = %s, subject = %s, email_from = %s WHERE id IN (SELECT id FROM mail_message ORDER BY id DESC LIMIT 50)", [f"<p>{LINE}</p>", LINE, EMAIL]),
        ("UPDATE ir_attachment SET name = %s, description = %s, index_content = %s, db_datas = %s", [f"{CLIENT}.pdf", LINE, LINE, LINE.encode()]),
        ("UPDATE ea_audit_firm_log SET actor_name = %s, target_name = %s, detail = %s, ip_address = %s", [NAME, CLIENT, LINE, "203.0.113.9"]),
        ("UPDATE ea_audit_dataset_row SET data = data || %s::jsonb WHERE id IN (SELECT id FROM ea_audit_dataset_row ORDER BY id LIMIT 20)",
         [json.dumps({"Tiers": CLIENT, "Libellé": LINE, "Compte tiers": NIU, LINE: 1, "Montant": "14137000"})]),
        ("UPDATE ea_audit_tb_line SET account_name = %s, raw_data = raw_data || %s::jsonb WHERE id IN (SELECT id FROM ea_audit_tb_line ORDER BY id LIMIT 20)",
         [CLIENT, json.dumps({"Libellé": LINE})]),
        ("UPDATE ea_audit_gl_line SET third_party_name = %s, line_description = %s, preparer = %s, reference = %s WHERE id IN (SELECT id FROM ea_audit_gl_line ORDER BY id LIMIT 20)",
         [CLIENT, LINE, NAME, NIU]),
        ("UPDATE ea_audit_document_version SET blocks = %s::jsonb WHERE id IN (SELECT id FROM ea_audit_document_version ORDER BY id LIMIT 5)",
         [json.dumps([{"s": CLIENT, "t": "title"}, {"s": LINE, "t": "p"}])]),
        ("UPDATE ea_audit_planning_ras SET signatures = %s::jsonb", [json.dumps({"partner": {"name": NAME, "uid": 8}})]),
    ]:
        cursor.execute(sql, params)
    connection.commit()
    connection.close()
    print(json.dumps({"tables_planted": tables, "columns_planted": columns_planted - len(skipped), "rows_added": rows_added, "added_rows_removed_for_lack_of_a_parent": removed, "refused_by_a_check_constraint": skipped}))


if __name__ == "__main__":
    main()
