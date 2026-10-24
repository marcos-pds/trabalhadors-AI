"""Reproducible operator checks; unknown external validation is never passed."""
import os
import shutil
import subprocess
from .runtime_config import validate_runtime


def report(db=None, probe_docker=False):
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
    checks.extend({'name': name, 'status': 'requires_external_validation'} for name in (
        'docker_real_workloads', 'ollama_embedding_model', 'postgresql_migration',
        'distributed_queue', 'sso_identity_provider', 'tls_public_endpoint',
        'load_test', 'independent_security_review', 'offsite_disaster_recovery'))
    return {'production_ready': False, 'checks': checks,
            'scope': 'local MVP; external gates remain open'}
