"""Reproducible operator checks; unknown external validation is never passed."""
import os
import shutil
import subprocess
from .runtime_config import validate_runtime


def report(db=None, probe_docker=False, backup_file=None):
    checks = []
    try:
        mode = validate_runtime()
        checks.append({'name': 'runtime_configuration', 'status': 'passed', 'mode': mode})
    except ValueError as exc:
        checks.append({'name': 'runtime_configuration', 'status': 'failed', 'detail': str(exc)})
    if db is not None:
        row = db.one('PRAGMA integrity_check')
        checks.append({'name': 'database_integrity',
                       'status': 'passed' if row and list(row.values()) == ['ok'] else 'failed'})
        checks.append({'name': 'schema_migrations', 'status': 'passed',
                       'versions': [r['version'] for r in db.all('SELECT version FROM schema_migrations')]})
    if db is not None:
        from .worker_liveness import snapshot as worker_snapshot
        workers = worker_snapshot(db)
        job_mode = os.environ.get('CENTRAL_JOB_MODE', 'embedded')
        checks.append({
            'name':'dedicated_worker_liveness',
            'status': ('passed' if workers['active_dedicated_workers'] > 0 else 'failed')
                      if job_mode == 'api' else 'not_checked',
            'active_workers':workers['active_workers'],
            'active_dedicated_workers':workers['active_dedicated_workers'],
            'job_mode':job_mode,
            'scope':workers['scope'],
        })
    docker = shutil.which('docker.exe' if os.name == 'nt' else 'docker')
    status = 'not_checked'
    if probe_docker:
        try:
            result = subprocess.run([docker or 'docker', 'info', '--format', '{{.ServerVersion}}'],
                                    capture_output=True, timeout=8, check=False)
            status = 'passed' if result.returncode == 0 else 'failed'
        except (OSError, subprocess.SubprocessError):
            status = 'failed'
    checks.append({'name': 'docker_daemon', 'status': status, 'cli_found': bool(docker)})
    if backup_file:
        from .backups import verify
        try:
            verified = verify(backup_file)
            checks.append({'name': 'encrypted_backup_recovery_point',
                           'status': 'passed', 'verified': verified['verified'],
                           'database_bytes': verified['database_bytes']})
        except Exception:
            # Do not include paths, key material or encrypted payload in logs.
            checks.append({'name': 'encrypted_backup_recovery_point',
                           'status': 'failed',
                           'detail': 'Backup inválido, chave incorreta ou integridade comprometida.'})
    else:
        checks.append({'name': 'encrypted_backup_recovery_point', 'status': 'not_checked'})
    checks.extend({'name': name, 'status': 'requires_external_validation'} for name in (
        'docker_real_workloads', 'ollama_embedding_model', 'postgresql_migration',
        'distributed_queue', 'sso_identity_provider', 'tls_public_endpoint',
        'load_test', 'independent_security_review', 'offsite_disaster_recovery'))
    return {'production_ready': False, 'checks': checks,
            'scope': 'local MVP; external gates remain open'}
