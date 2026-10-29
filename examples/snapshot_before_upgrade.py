"""Create and verify an encrypted operator recovery point without bootstrapping DB.

Run only into a new, access-restricted directory. Keep recovery.key offline.
"""
import os
from pathlib import Path
import sqlite3
import sys
import threading
from types import SimpleNamespace

from cryptography.fernet import Fernet
from central.backups import create, verify


def main():
    source, destination = map(Path, sys.argv[1:3])
    key = Fernet.generate_key()
    with (destination / 'recovery.key').open('xb') as output:
        output.write(key)
    os.chmod(destination / 'recovery.key', 0o600)
    os.environ['CENTRAL_BACKUP_KEY'] = key.decode()
    connection = sqlite3.connect((source / 'central.sqlite3').resolve().as_uri() + '?mode=ro', uri=True)
    try:
        db = SimpleNamespace(conn=connection, lock=threading.RLock())
        archive = destination / 'data.fernet'
        print(create(db, source, archive))
        print(verify(archive))
    finally:
        connection.close()


if __name__ == '__main__':
    main()
