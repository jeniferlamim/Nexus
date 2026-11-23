"""Emit an idempotent SQL upsert of the rule catalog for nexus.tax_rules (run on each deploy).

    python -m nexus_engine.rules.sync_sql > ../../supabase/seed/tax_rules.sql
"""
import json

from .catalog import DEFAULT_CATALOG, OPEN_END


def lit(v) -> str:
    return "null" if v is None else "'" + str(v).replace("'", "''") + "'"


def main() -> None:
    print("-- Generated from services/engine/nexus_engine/rules/catalog.py — do not edit by hand.")
    print("begin;")
    for r in sorted(DEFAULT_CATALOG.all(), key=lambda r: (r.code, r.version)):
        vt = None if r.valid_to == OPEN_END else r.valid_to.isoformat()
        print(
            "insert into nexus.tax_rules (code, version, name, category, valid_from, valid_to, parameters, methodology, "
            "legal_basis, legal_review_status, change_note) values ("
            f"{lit(r.code)}, {r.version}, {lit(r.name)}, {lit(r.category.value)}, {lit(r.valid_from.isoformat())}, "
            f"{lit(vt)}, {lit(json.dumps(r.parameters, ensure_ascii=False))}::jsonb, {lit(r.methodology)}, "
            f"{lit(r.legal_basis)}, {lit(r.legal_review_status)}, {lit(r.change_note)}) "
            "on conflict (code, version) do update set name = excluded.name, parameters = excluded.parameters, "
            "methodology = excluded.methodology, legal_basis = excluded.legal_basis, "
            "legal_review_status = excluded.legal_review_status, valid_to = excluded.valid_to;"
        )
    print("commit;")


if __name__ == "__main__":
    main()
