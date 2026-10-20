"""Importa datos desde recovery.db a PostgreSQL sin borrar ni modificar el origen.

Uso (PowerShell):
  $env:DATABASE_URL = "postgresql://..."
  python migrar_sqlite_a_postgres.py --source "C:/ruta/recovery.db"

La importación es idempotente: filas que ya existan por su clave primaria se omiten.
No imprime correos, hashes, tokens ni contenido de eventos.
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

TABLE_COLUMNS = {
    "cuentas": ("correo", "hash_contrasena", "verificado", "creado_en", "actualizado_en"),
    "instalaciones": ("id_instalacion", "correo", "verificado", "actualizado_en"),
    "tokens": ("id", "id_instalacion", "proposito", "hash_token", "expira_en", "usado"),
    "eventos_seguridad": ("id", "correo", "id_instalacion", "accion", "resultado", "detalle", "creado_en"),
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS cuentas (
 correo TEXT PRIMARY KEY, hash_contrasena TEXT NOT NULL,
 verificado INTEGER NOT NULL DEFAULT 0, creado_en TEXT NOT NULL, actualizado_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS instalaciones (
 id_instalacion TEXT PRIMARY KEY, correo TEXT NOT NULL,
 verificado INTEGER NOT NULL DEFAULT 0, actualizado_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tokens (
 id BIGSERIAL PRIMARY KEY, id_instalacion TEXT NOT NULL, proposito TEXT NOT NULL,
 hash_token TEXT NOT NULL, expira_en TEXT NOT NULL, usado INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS eventos_seguridad (
 id BIGSERIAL PRIMARY KEY, correo TEXT NOT NULL, id_instalacion TEXT NOT NULL,
 accion TEXT NOT NULL, resultado TEXT NOT NULL, detalle TEXT NOT NULL DEFAULT '', creado_en TEXT NOT NULL
);
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Ruta al recovery.db original")
    args = parser.parse_args()
    source = Path(args.source).expanduser().resolve()
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not source.is_file():
        print(f"ERROR: no existe la base de origen: {source}", file=sys.stderr)
        return 2
    if not database_url:
        print("ERROR: configurá DATABASE_URL en la sesión antes de ejecutar.", file=sys.stderr)
        return 2

    src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        integrity = src.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            print(f"ERROR: integrity_check devolvió {integrity!r}; no se importó nada.", file=sys.stderr)
            return 2
        existing = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {}
        data = {}
        for table, columns in TABLE_COLUMNS.items():
            if table not in existing:
                data[table] = []
                counts[table] = 0
                continue
            source_cols = {r[1] for r in src.execute(f'PRAGMA table_info("{table}")')}
            selected = [c for c in columns if c in source_cols]
            rows = src.execute(f'SELECT {", ".join(selected)} FROM "{table}"').fetchall()
            data[table] = [{k: row[k] for k in selected} for row in rows]
            counts[table] = len(rows)
        # If an old tokens table did not have usado, supply the historical default.
        for row in data["tokens"]:
            row.setdefault("usado", 0)
        # If old events table did not have detalle, supply its schema default.
        for row in data["eventos_seguridad"]:
            row.setdefault("detalle", "")

        inserted = {t: 0 for t in TABLE_COLUMNS}
        skipped = {t: 0 for t in TABLE_COLUMNS}
        with psycopg.connect(database_url, connect_timeout=10, row_factory=dict_row) as dst:
            with dst.cursor() as cur:
                for statement in SCHEMA.strip().split(";\n"):
                    if statement.strip():
                        cur.execute(statement)
                for table, columns in TABLE_COLUMNS.items():
                    if not data[table]:
                        continue
                    cols = list(columns)
                    # Do not invent absent required source fields; this only supports optional legacy columns.
                    for row in data[table]:
                        values = [row.get(c) for c in cols]
                        placeholders = ",".join(["%s"] * len(cols))
                        cur.execute(
                            f'INSERT INTO "{table}" ({", ".join(cols)}) VALUES ({placeholders}) ON CONFLICT DO NOTHING',
                            values,
                        )
                        if cur.rowcount == 1:
                            inserted[table] += 1
                        else:
                            skipped[table] += 1
                for table in ("tokens", "eventos_seguridad"):
                    cur.execute(f"SELECT COALESCE(MAX(id), 0) AS max_id FROM {table}")
                    max_id = cur.fetchone()["max_id"]
                    cur.execute(
                        "SELECT setval(pg_get_serial_sequence(%s, 'id'), GREATEST(%s, 1), %s)",
                        (table, max_id, max_id > 0),
                    )
        print("Integridad del origen: ok")
        print("Registros encontrados en SQLite:")
        for table in TABLE_COLUMNS:
            print(f"  {table}: {counts[table]}")
        print("Importación completada. Insertados / omitidos por conflicto:")
        for table in TABLE_COLUMNS:
            print(f"  {table}: {inserted[table]} / {skipped[table]}")
        print("La base SQLite de origen no se modificó.")
        return 0
    finally:
        src.close()


if __name__ == "__main__":
    raise SystemExit(main())
