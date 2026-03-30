#!/usr/bin/env python3
"""
5Eyes WealthArchitekten — Ersteinrichtung
=========================================
Dieses Script läuft einmalig beim ersten Start.
Es erstellt die Datenbank, lädt das Schema, und legt den ersten Admin-Benutzer an.
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

script_dir = Path(__file__).parent
os.chdir(script_dir)


def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def main():
    parser = argparse.ArgumentParser(description='5Eyes Ersteinrichtung')
    parser.add_argument('--username', default='admin', help='Benutzername (default: admin)')
    parser.add_argument('--password', default=None, help='Passwort (wird abgefragt wenn nicht angegeben)')
    parser.add_argument('--name', default='Administrator', help='Vollständiger Name')
    parser.add_argument('--email', default=None, help='E-Mail Adresse (optional)')
    args = parser.parse_args()

    print('=' * 60)
    print('  5Eyes WealthArchitekten — Ersteinrichtung')
    print('=' * 60)
    print()

    try:
        from config import settings
        from database import SessionLocal, bootstrap_sqlite_schema, init_db, new_uuid
        import models.allocation
        import models.clients
        import models.mandates
        import models.profiling
        import models.review
        import models.users
        import models.wealth
        from models.users import User
        from services.auth import hash_password
    except ImportError as e:
        print(f'✗ Import fehlgeschlagen: {e}')
        print('  Bitte sicherstellen dass alle Pakete installiert sind:')
        print('  pip install -r requirements.txt')
        sys.exit(1)

    password = args.password
    if not password:
        import getpass

        print(f'Admin-Benutzer: {args.username}')
        password = getpass.getpass('Passwort eingeben: ')
        password_confirm = getpass.getpass('Passwort bestätigen: ')
        if password != password_confirm:
            print('✗ Passwörter stimmen nicht überein.')
            sys.exit(1)
        if len(password) < 5:
            print('✗ Passwort muss mindestens 5 Zeichen lang sein.')
            sys.exit(1)

    print(f'\nDatenbank: {settings.db_path}')
    try:
        bootstrap_sqlite_schema(db_key=getattr(settings, 'db_key', None))
        init_db()
        print('✓ Datenbank initialisiert')
    except Exception as e:
        print(f'✗ Datenbank-Initialisierung fehlgeschlagen: {e}')
        sys.exit(1)

    with SessionLocal() as db:
        existing = db.query(User).filter(User.username == args.username, User.deleted_at.is_(None)).first()

        if existing:
            print(f"\n⚠ Benutzer '{args.username}' existiert bereits.")
            answer = input('Passwort aktualisieren? [j/N]: ').strip().lower()
            if answer == 'j':
                existing.password_hash = hash_password(password)
                existing.updated_at = utc_now()
                db.commit()
                print(f"✓ Passwort für '{args.username}' aktualisiert.")
            else:
                print('Keine Änderungen vorgenommen.')
        else:
            now = utc_now()
            admin = User(
                id=new_uuid(),
                username=args.username,
                password_hash=hash_password(password),
                full_name=args.name,
                email=args.email,
                role='admin',
                is_active=1,
                created_at=now,
                updated_at=now,
            )
            db.add(admin)
            db.commit()
            print('\n✓ Admin-Benutzer angelegt:')
            print(f'   Benutzername : {args.username}')
            print(f'   Name         : {args.name}')
            print('   Rolle        : admin')

    print('\n' + '=' * 60)
    print('  Einrichtung abgeschlossen.')
    print('=' * 60)


if __name__ == '__main__':
    main()
