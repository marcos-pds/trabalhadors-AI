import httpx
import pytest
from central.database import Database
from central.release_checks import report
from central.load_probe import run


def test_readiness_never_passes_unperformed_external_validation(monkeypatch):
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE', 'local')
    db = Database(':memory:')
    result = report(db)
    assert result['production_ready'] is False
    checks = {row['name']: row['status'] for row in result['checks']}
    assert checks['database_integrity'] == 'passed'
    assert checks['docker_daemon'] == 'not_checked'
    assert checks['independent_security_review'] == 'requires_external_validation'
    db.close()


def test_load_probe_counts_errors_and_restricts_target_and_work():
    responses = []
    def respond(request):
        assert request.url.path == '/api/health'
        responses.append(request)
        return httpx.Response(503)
    result = run('https://central.example.com', requests=3, workers=1,
                 transport=httpx.MockTransport(respond))
    assert result['failed'] == 3 and result['successful'] == 0 and result['p95_ms'] >= 0
    assert len(responses) == 3
    with pytest.raises(ValueError):
        run('https://user:password@example.com')
    with pytest.raises(ValueError):
        run('https://example.com', requests=100000)


def test_release_cli_fails_gate_when_external_checks_are_pending(tmp_path, capsys, monkeypatch):
    from central.cli import main
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE', 'local')
    db = Database(tmp_path / 'central.sqlite3'); db.close()
    assert main(['--data-dir', str(tmp_path), 'release-check']) == 2
    assert 'production_ready' in capsys.readouterr().out



def test_api_only_release_gate_requires_live_dedicated_worker(monkeypatch):
    from central.worker_liveness import beat, forget
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE','local')
    monkeypatch.setenv('CENTRAL_JOB_MODE','api')
    db=Database(':memory:')
    try:
        checks={x['name']:x for x in report(db)['checks']}
        assert checks['dedicated_worker_liveness']['status']=='failed'
        assert report(db)['production_ready'] is False
        beat(db,'dedicated-process','worker')
        checks={x['name']:x for x in report(db)['checks']}
        assert checks['dedicated_worker_liveness']['status']=='passed'
        assert checks['dedicated_worker_liveness']['active_workers']==1
        forget(db,'dedicated-process')
        assert next(x for x in report(db)['checks']
                    if x['name']=='dedicated_worker_liveness')['status']=='failed'
    finally:
        db.close()


def test_api_only_does_not_accept_embedded_worker(monkeypatch):
    from central.worker_liveness import beat
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE', 'local')
    monkeypatch.setenv('CENTRAL_JOB_MODE', 'api')
    db = Database(':memory:')
    try:
        beat(db, 'embedded-process', 'embedded')
        checks = {item['name']: item for item in report(db)['checks']}
        assert checks['dedicated_worker_liveness']['active_workers'] == 1
        assert checks['dedicated_worker_liveness']['active_dedicated_workers'] == 0
        assert checks['dedicated_worker_liveness']['status'] == 'failed'
        beat(db, 'dedicated-process', 'worker')
        checks = {item['name']: item for item in report(db)['checks']}
        assert checks['dedicated_worker_liveness']['active_dedicated_workers'] == 1
        assert checks['dedicated_worker_liveness']['status'] == 'passed'
    finally:
        db.close()
