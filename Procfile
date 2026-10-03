web: flask --app wsgi seed && gunicorn wsgi:app --workers 1 --threads 8 --timeout 60 --bind 0.0.0.0:$PORT
