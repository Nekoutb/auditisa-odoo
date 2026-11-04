"""AuditISA's pure calculation logic, ported from platform/lib (TypeScript).

No module in this package imports Odoo, so the whole package runs under plain
pytest (tests_pure/), against fixtures recorded from the real TypeScript.

Conventions:

- one module per source file; function names in snake_case, one per source export;
- data keeps its source shape: rows and summaries are plain dicts with the source's
  camelCase field names (``openingDebit``, ``sampledValue``), so a summary stored
  by the old platform and one produced here read the same;
- where the source mixes logic and queries, the module takes the query results as
  arguments and returns what the source would have stored;
- what is odd in the source is ported as it is. See _js.py for the JavaScript
  behaviour the ports reproduce.
"""
