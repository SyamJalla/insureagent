#!/bin/sh
# Container entrypoint: seed the data volume, converge the schema, serve.
#
# 1) Volume-occlusion fix: user-memory embeddings live on a volume mounted
#    at $DATA_DIR — but a volume mounts OVER the image path, hiding the FAQ
#    store baked at build time. First boot with an empty volume copies the
#    baked store in; later boots leave the volume (real user data) alone.
# 2) Migrations run BEFORE the server: a fresh database converges on the
#    schema ledger automatically (idempotent; seeds are NOT run here —
#    seed_enterprise wipes tables and must stay an explicit human act).
# 3) --workers 2: the agent graph is synchronous; one worker would
#    serialize every user behind a single LLM call. `exec` makes uvicorn
#    PID 1 so Docker's stop signal reaches it.
#
# DATA_DIR/BAKED_DIR are overridable so the script is testable outside
# Docker (see tests in the deployment doc); container defaults are used
# as-is in the image.
set -e

DATA_DIR="${DATA_DIR:-/data}"
BAKED_DIR="${BAKED_DIR:-/app/datasources}"

if [ ! -d "$DATA_DIR/vector_database" ]; then
    echo "entrypoint: seeding $DATA_DIR/vector_database from baked image copy"
    mkdir -p "$DATA_DIR"
    cp -r "$BAKED_DIR/vector_database" "$DATA_DIR/"
fi

python scripts/db/migrate.py

# Standard entrypoint convention: run whatever command was passed (e.g.
# `docker compose run app python scripts/seed_users.py`); the server is
# only the DEFAULT command (CMD in the Dockerfile).
exec "$@"
