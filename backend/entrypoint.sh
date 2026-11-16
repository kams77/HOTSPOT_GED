#!/bin/sh
set -e

case "$1" in
  web)
    python manage.py migrate --noinput
    if [ "${LOAD_DEMO:-0}" = "1" ]; then
      python manage.py bootstrap --demo
    else
      python manage.py bootstrap
    fi
    python manage.py collectstatic --noinput >/dev/null
    exec gunicorn hotspot.wsgi:application --bind 0.0.0.0:8000 --workers "${WEB_WORKERS:-3}" --access-logfile -
    ;;
  worker)
    exec celery -A hotspot worker -l info
    ;;
  beat)
    exec celery -A hotspot beat -l info --schedule /tmp/celerybeat-schedule
    ;;
  *)
    exec "$@"
    ;;
esac
