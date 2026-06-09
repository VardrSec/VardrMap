#!/bin/bash
set -e

echo "Running Alembic migrations..."
alembic upgrade head

echo "Starting server..."
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
