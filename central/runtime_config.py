"""Validate explicit server deployment settings before opening data or listeners."""
import os
from urllib.parse import urlsplit
from cryptography.fernet import Fernet


def validate_runtime():
    mode = os.environ.get('CENTRAL_DEPLOYMENT_MODE', 'local')
    if mode not in ('local', 'server'):
        raise ValueError('CENTRAL_DEPLOYMENT_MODE must be local or server')
    if mode == 'server':
        origin = urlsplit(os.environ.get('CENTRAL_PUBLIC_ORIGIN', ''))
        if (origin.scheme != 'https' or not origin.hostname or origin.username
                or origin.password or origin.path not in ('', '/') or origin.query
                or origin.fragment):
            raise ValueError('Server mode requires an HTTPS CENTRAL_PUBLIC_ORIGIN')
        if os.environ.get('CENTRAL_COMMAND_RUNNER') != 'docker':
            raise ValueError('Server mode requires Docker command isolation')
        if not os.environ.get('CENTRAL_SECRET_KEY'):
            raise ValueError('Server mode requires an externally managed CENTRAL_SECRET_KEY')
        Fernet(os.environ['CENTRAL_SECRET_KEY'].encode())
    return mode


def registration_allowed():
    return (os.environ.get('CENTRAL_DEPLOYMENT_MODE', 'local') == 'local'
            or os.environ.get('CENTRAL_ALLOW_REGISTRATION', '').lower() == 'true')
