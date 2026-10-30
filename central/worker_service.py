"""Optional dedicated worker process for the same local SQLite task queue.

Usage (PowerShell, separate terminal):
  $env:CENTRAL_JOB_MODE = "worker"
  python -m central.worker_service

Start API independently with CENTRAL_JOB_MODE=api. Both MUST share
CENTRAL_DATA_DIR and use the same filesystem, security key and workspace.
Not a multi-host distributed queue.
"""
import asyncio
import os
import signal

os.environ['CENTRAL_JOB_MODE'] = 'worker'


async def serve():
    from .main import ENGINE, DB
    from .observability import log_event
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stopped.set)
        except (NotImplementedError, RuntimeError):
            pass
    log_event('worker_started', status='worker')
    ENGINE.shutting_down = False
    ENGINE.resume_pending()
    ENGINE.start_dispatcher()
    try:
        await stopped.wait()
    except KeyboardInterrupt:
        pass
    finally:
        ENGINE.shutting_down = True
        if ENGINE.dispatch_task:
            ENGINE.dispatch_task.cancel()
            await asyncio.gather(ENGINE.dispatch_task, return_exceptions=True)
        running = list(ENGINE.running.values())
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        log_event('worker_stopped', status='stopped')
        DB.close()


if __name__ == '__main__':
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass
