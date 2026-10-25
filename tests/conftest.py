"""Never bootstrap the ASGI app against an operator's existing data during tests."""
import os
import tempfile

# Must run before test-module imports (several import central.main directly).
os.environ['CENTRAL_DATA_DIR'] = tempfile.mkdtemp(prefix='central-pytest-isolated-')
