"""Execute: python run.py (localhost only by default)."""
import os
import uvicorn

if __name__ == '__main__':
    uvicorn.run('central.main:app',host=os.environ.get('CENTRAL_HOST','127.0.0.1'),
                port=int(os.environ.get('CENTRAL_PORT','8765')),reload=False,access_log=False)
