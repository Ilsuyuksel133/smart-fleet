#!/bin/sh
# Bring the database schema up to date, then start the API.
# exec replaces the shell, so uvicorn gets the container's stop signal directly.
set -e
alembic upgrade head
exec uvicorn main:app --host 0.0.0.0 --port 8000 --no-access-log
