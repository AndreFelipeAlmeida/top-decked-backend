#!/bin/sh
set -e

echo "Aplicando migrations (alembic upgrade head)..."
alembic upgrade head

echo "Subindo aplicação..."
exec fastapi run app/main.py --host 0.0.0.0 --port 8000
