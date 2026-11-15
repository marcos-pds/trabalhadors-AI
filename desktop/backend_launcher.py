"""Bundled local Python server entry point for the Windows desktop shell.

The web entrypoint stays unchanged. Listening only on 127.0.0.1 using a
pre-bound, dynamically allocated port avoids conflict with the web server.
"""
import asyncio
import os
import socket
import sys

READY_PREFIX = "CENTRAL_DESKTOP_READY="


def reserve_loopback():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        return sock, sock.getsockname()[1]
    except BaseException:
        sock.close()
        raise


async def serve_desktop():
    os.environ["CENTRAL_DEPLOYMENT_MODE"] = "local"
    os.environ["CENTRAL_HOST"] = "127.0.0.1"
    os.environ["CENTRAL_JOB_MODE"] = "embedded"
    import uvicorn
    from central.main import app

    sock, port = reserve_loopback()
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port,
        access_log=False, log_level="warning"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(1200):
            if server.started:
                print(f"{READY_PREFIX}http://127.0.0.1:{port}/", flush=True)
                await task
                return
            if task.done():
                await task
                raise RuntimeError("Desktop server exited before startup")
            await asyncio.sleep(0.05)
        server.should_exit = True
        await task
        raise RuntimeError("Desktop startup timed out")
    finally:
        sock.close()


def main():
    try:
        asyncio.run(serve_desktop())
        return 0
    except KeyboardInterrupt:
        return 0
    except BaseException as exc:
        print("CENTRAL_DESKTOP_ERROR=" + type(exc).__name__,
              file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
