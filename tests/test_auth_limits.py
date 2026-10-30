"""Rate-limit tests without logging credentials or polluting user records."""
import uuid

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

from central.database import Database
from central.auth_limits import ensure_allowed, failed, succeeded, WINDOW
from central.main import app


def test_login_fingerprint_limit_expires_and_success_clears(tmp_path):
    db=Database(tmp_path / 'auth.db')
    email='test@example.org'
    try:
        for n in range(6):
            ensure_allowed(db,email,now=1000+n)
            failed(db,email,now=1000+n)
        with pytest.raises(HTTPException) as e:
            ensure_allowed(db,email,now=1007)
        assert e.value.status_code == 429
        assert int(e.value.headers['Retry-After']) > 0
        row=db.one('SELECT identity_hash FROM login_failures LIMIT 1')
        assert '@' not in row['identity_hash']
        ensure_allowed(db,email,now=1000+WINDOW+7)
        succeeded(db,email)
        assert db.one('SELECT COUNT(*) AS n FROM login_failures')['n']==0
    finally:
        db.close()


def test_integration_login_lockout_has_generic_failure_and_retry_header():
    headers={'X-Central-Request':'1'}
    email=uuid.uuid4().hex+'@example.org'
    with TestClient(app) as client:
        created=client.post('/api/register',headers=headers,json={
            'email':email, 'password':'myverystrongpassword'})
        assert created.status_code==200
        client.post('/api/logout',headers=headers)
        for _ in range(6):
            res=client.post('/api/login',headers=headers,json={
                'email':email,'password':'wrongpassword'})
            assert res.status_code==401
            assert 'senha incorretos' in res.json()['detail']
        blocked=client.post('/api/login',headers=headers,json={
            'email':email,'password':'myverystrongpassword'})
        assert blocked.status_code==429
        assert int(blocked.headers['retry-after'])>0
