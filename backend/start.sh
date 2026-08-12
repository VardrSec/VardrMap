#!/bin/bash
set -e

# Railway boots this container and Postgres at the same time. Without this gate
# alembic hits "FATAL: the database system is starting up", set -e kills the
# container, and the deploy crash-loops. See wait_for_db.py.
echo "Waiting for database..."
python wait_for_db.py

echo "Running Alembic migrations..."
alembic upgrade head

echo "Starting server..."
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
