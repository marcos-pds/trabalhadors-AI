"""Keep app database bootstrap isolated from operator data during pytest."""
import atexit
import os
from pathlib import Path
import shutil
import tempfile

# Pytest imports this before modules that import central.main. Keep the isolated
# SQLite data under the writable checkout (the host temp folder may be denied).
_TEST_ROOT = Path(__file__).resolve().parents[1]
_TEST_DATA = Path(tempfile.mkdtemp(prefix='.pytest-data-', dir=_TEST_ROOT))
atexit.register(shutil.rmtree, _TEST_DATA, ignore_errors=True)
os.environ['CENTRAL_DATA_DIR'] = str(_TEST_DATA)
