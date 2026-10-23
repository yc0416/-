#!/bin/sh
set -eu
mkdir -p "$GALLERY_DATA_DIR"
chown gallery:gallery "$GALLERY_DATA_DIR"
exec gunicorn --bind "0.0.0.0:${PORT:-8000}" --workers 1 --threads 4 --timeout 60 --no-control-socket --user gallery --group gallery --access-logfile - server.wsgi:application
