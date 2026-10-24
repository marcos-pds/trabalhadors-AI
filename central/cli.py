"""Operator CLI: diagnostics, encrypted snapshots, isolated restore and checks."""
import argparse
import json
import os
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m central.cli')
    parser.add_argument('--data-dir', default=os.environ.get('CENTRAL_DATA_DIR', 'data'))
    actions = parser.add_subparsers(dest='action', required=True)
    actions.add_parser('doctor')
    actions.add_parser('release-check').add_argument('--probe-docker', action='store_true')
    actions.add_parser('backup').add_argument('destination')
    restore = actions.add_parser('restore')
    restore.add_argument('source'); restore.add_argument('destination')
    args = parser.parse_args(argv)
    from .backups import create, restore as restore_backup
    if args.action == 'restore':
        print(json.dumps(restore_backup(args.source, args.destination), indent=2))
        return 0
    data_dir = Path(args.data_dir).resolve()
    database = data_dir / 'central.sqlite3'
    if not database.is_file():
        parser.error('Data directory has no central.sqlite3; diagnostics never create a database')
    from .database import Database
    db = Database(database)
    try:
        if args.action == 'backup':
            result = create(db, data_dir, args.destination)
        else:
            from .release_checks import report
            result = report(db, probe_docker=getattr(args, 'probe_docker', False))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if any(c['status'] == 'failed' for c in result.get('checks', [])):
            return 1
        if args.action == 'release-check' and not result.get('production_ready'):
            return 2  # pending gates must never be interpreted as release approval
        return 0
    finally:
        db.close()


if __name__ == '__main__':
    raise SystemExit(main())
