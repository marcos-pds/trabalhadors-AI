# Build locally; do not pull executable images dynamically during agent runs.
# The image contains Node.js 22 and Python 3 for offline build/pytest.
FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pytest git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
ENV HOME=/tmp \
    CI=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Individual docker run invocations override UID/GID with the current host uid
# (or a fixed unprivileged UID when called through Docker Desktop on Windows).
USER 10001:10001

CMD ["python3", "--version"]
