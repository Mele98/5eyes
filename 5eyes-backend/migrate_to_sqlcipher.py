#!/usr/bin/env python3
"""Migriert eine bestehende SQLite-Datenbank nach SQLCipher."""
import argparse
import shutil
import sqlite3
import sys
from pathlib import Path


def escape_sql_string(value: str) -> str:
    return value.replace("'", "''")


def main():
    parser = argparse.ArgumentParser(description='SQLite → SQLCipher Migration für 5Eyes')
    parser.add_argument('--db-path', default=None, help='Pfad zur bestehenden SQLite-DB')
    parser.add_argument('--key', required=True, help='SQLCipher Key / Passphrase')
    args = parser.parse_args()

    try:
        import sqlcipher3  # type: ignore
    except ImportError:
        print('✗ sqlcipher3 ist nicht installiert.')
        print('  Bitte zuerst ausführen: pip install sqlcipher3-binary')
        sys.exit(1)

    from config import settings

    db_path = Path(args.db_path or settings.db_path).expanduser().resolve()
    if not db_path.exists():
        print(f'✗ Datenbank nicht gefunden: {db_path}')
        sys.exit(1)

    backup_path = db_path.with_suffix(db_path.suffix + '.pre-sqlcipher-backup')
    encrypted_path = db_path.with_suffix(db_path.suffix + '.encrypted')
    escaped_key = escape_sql_string(args.key)

    print('=' * 60)
    print('  5Eyes — SQLite → SQLCipher Migration')
    print('=' * 60)
    print(f'\n1. Backup erstellen → {backup_path}')
    shutil.copy2(db_path, backup_path)
    print('   ✓ Backup erstellt')

    try:
        if encrypted_path.exists():
            encrypted_path.unlink()

        print(f'\n2. Daten nach SQLCipher migrieren → {encrypted_path}')
        plain_conn = sqlite3.connect(str(db_path))
        cipher_conn = sqlcipher3.connect(str(encrypted_path))
        cipher_conn.execute(f"PRAGMA key = '{escaped_key}'")
        cipher_conn.execute('PRAGMA cipher_page_size = 4096')
        cipher_conn.execute('PRAGMA kdf_iter = 256000')
        cipher_conn.execute('PRAGMA cipher_hmac_algorithm = HMAC_SHA512')
        cipher_conn.execute('PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512')

        schema = plain_conn.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type DESC, name"
        ).fetchall()
        for (sql,) in schema:
            try:
                cipher_conn.execute(sql)
            except Exception as e:
                print(f'   ⚠ Schema: {e} — {sql[:60]}')

        cipher_conn.commit()

        tables = plain_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()

        total_rows = 0
        for (table_name,) in tables:
            rows = plain_conn.execute(f'SELECT * FROM [{table_name}]').fetchall()
            if not rows:
                continue
            cursor = plain_conn.execute(f'SELECT * FROM [{table_name}] LIMIT 0')
            cols = len(cursor.description)
            placeholders = ','.join(['?'] * cols)
            cipher_conn.executemany(
                f'INSERT OR IGNORE INTO [{table_name}] VALUES ({placeholders})', rows
            )
            total_rows += len(rows)
            print(f'   ✓ {table_name}: {len(rows)} Zeilen')

        cipher_conn.commit()
        cipher_conn.close()
        plain_conn.close()
        print(f'\n   ✓ {total_rows} Zeilen total übertragen')

    except Exception as e:
        print(f'\n✗ Migration fehlgeschlagen: {e}')
        if encrypted_path.exists():
            encrypted_path.unlink()
        print('  Die ursprüngliche DB wurde nicht verändert.')
        sys.exit(1)

    print('\n3. Verschlüsselte DB verifizieren...')
    try:
        verify_conn = sqlcipher3.connect(str(encrypted_path))
        verify_conn.execute(f"PRAGMA key = '{escaped_key}'")
        verify_conn.execute('SELECT 1')
        verify_tables = verify_conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        verify_conn.close()
        print(f'   ✓ {verify_tables} Tabellen in verschlüsselter DB verifiziert')
    except Exception as e:
        print(f'   ✗ Verifikation fehlgeschlagen: {e}')
        sys.exit(1)

    print(f'\n4. Verschlüsselte DB aktivieren → {db_path}')
    db_path.unlink()
    encrypted_path.rename(db_path)
    print('   ✓ Fertig')

    print('\n' + '=' * 60)
    print('  Migration erfolgreich!')
    print()
    print('  Nächste Schritte:')
    print('  1. In .env setzen:')
    print(f'     DB_KEY={args.key}')
    print('     DB_USE_SQLCIPHER=true')
    print()
    print('  2. Backend wie gewohnt starten.')
    print()
    print(f'  3. Backup aufbewahren: {backup_path}')
    print('=' * 60)


if __name__ == '__main__':
    main()
