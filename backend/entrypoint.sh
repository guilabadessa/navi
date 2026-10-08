#!/bin/sh
set -e
cd /app
export PYTHONPATH=/app
if [ "$1" = "api" ]; then
  alembic upgrade head
  python -m app.seed
  exec uvicorn app.main:app --host 0.0.0.0 --port 8100 --proxy-headers --forwarded-allow-ips='*' --no-server-header
elif [ "$1" = "worker" ]; then
  sleep 8   # aguarda migrations da API
  exec python -c "from app import jobs; jobs.start()"
fi
exec "$@"
