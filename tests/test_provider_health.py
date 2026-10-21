"""Teste do circuito de proteção usando SQLite temporário, sem APIs externas."""
from pathlib import Path
from tempfile import TemporaryDirectory
from central.database import Database
from central.health import ProviderHealth
from central.providers import ProviderError


def make_db(path):
    db = Database(path)
    db.execute('INSERT INTO users VALUES(?,?,?,?)',('u','test@example.com','pass','now'))
    db.execute('''INSERT INTO providers(id,user_id,name,kind,base_url,model,priority,created_at)
       VALUES(?,?,?,?,?,?,?,?)''',('p','u','Test','compatible','https://example.com','m',1,'now'))
    return db


def test_suspend_on_503_and_recover_after_cooldown():
    with TemporaryDirectory() as tmp:
        path=Path(tmp)/'db.sqlite3'
        db=make_db(path)
        t=[1000.0]
        health=ProviderHealth(db,clock=lambda:t[0])
        err=ProviderError('unavailable','HTTP 503',True,http_status=503)
        assert not health.record('p','m',success=False,latency_ms=10,error=err)['opened']
        assert health.record('p','m',success=False,latency_ms=10,error=err)['opened']
        assert health.acquire('p','m')==(False,False)
        db.close()
        db=Database(path)
        health=ProviderHealth(db,clock=lambda:t[0])
        assert health.detail('p','m')['state']=='suspended'
        t[0]+=61
        assert health.acquire('p','m')==(True,True)
        assert health.acquire('p','m')==(False,False)
        assert health.record('p','m',success=True,latency_ms=150)['recovered']
        assert health.detail('p','m')['suspended_until'] is None
        assert health.detail('p','m')['samples']==3
        assert health.detail('p','m')['last_http_status'] is None
        db.close()


def test_429_triggers_immediate_cooldown():
    with TemporaryDirectory() as tmp:
        db=make_db(Path(tmp)/'db.sqlite3')
        health=ProviderHealth(db,clock=lambda:2000.0)
        err=ProviderError('rate_limit','429',True,http_status=429)
        assert health.record('p','m',success=False,latency_ms=7,error=err)['opened']
        assert health.detail('p','m')['remaining_seconds']==120
        assert health.detail('p','m')['last_http_status']==429
        assert health.acquire('p','m')==(False,False)
        db.close()
