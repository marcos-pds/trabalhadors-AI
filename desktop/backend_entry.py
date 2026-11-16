"""Packaged localhost-only FastAPI backend for the Windows desktop."""
import os
import uvicorn
from central.main import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["CENTRAL_PORT"]),
                reload=False, access_log=False, log_level="warning")
