"""Enable one Ollama connection per account, preserving other saved providers."""
import argparse
import os
from pathlib import Path

from central.database import Database, uid, utcnow


def configure(db, model):
    with db.lock:
        db.conn.execute('BEGIN IMMEDIATE')
        try:
            for user in db.all('SELECT id FROM users'):
                user_id = user['id']
                existing = db.one(
                    "SELECT id FROM providers WHERE user_id=? AND kind='ollama' "
                    'ORDER BY (model=?) DESC, enabled DESC, created_at LIMIT 1',
                    (user_id, model),
                )
                db.execute('UPDATE providers SET enabled=0 WHERE user_id=?', (user_id,))
                pid = existing['id'] if existing else uid()
                if not existing:
                    db.execute(
                        'INSERT INTO providers(id,user_id,name,kind,base_url,model,created_at) '
                        'VALUES(?,?,?,?,?,?,?)',
                        (pid, user_id, 'Ollama local', 'ollama',
                         'http://127.0.0.1:11434/v1', model, utcnow()),
                    )
                db.execute(
                    'UPDATE providers SET enabled=1,priority=1,model=?,base_url=?,'
                    'api_key_enc=NULL,input_price=0,output_price=0,last_error=NULL WHERE id=?',
                    (model, 'http://127.0.0.1:11434/v1', pid),
                )
                db.execute('DELETE FROM provider_health WHERE provider_id=?', (pid,))
                db.execute('UPDATE agents SET provider_id=?,model=NULL WHERE user_id=?', (pid, user_id))
            db.conn.commit()
        except Exception:
            db.conn.rollback()
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='qwen2.5-coder:3b')
    args = parser.parse_args()
    if not args.model.strip():
        parser.error('Informe um modelo.')
    root = Path(__file__).resolve().parent
    db = Database(Path(os.environ.get('CENTRAL_DATA_DIR', root / 'data')) / 'central.sqlite3')
    try:
        configure(db, args.model.strip())
        print(f'Configurado: somente Ollama ativo ({args.model}). Demais cadastros preservados.')
    finally:
        db.close()
