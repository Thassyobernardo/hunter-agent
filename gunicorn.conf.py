# Non-port gunicorn settings.
# Port binding is handled exclusively by start.py to keep it explicit
# and visible in Railway logs.
workers = 1
threads = 4
timeout = 120
loglevel = "info"
accesslog = "-"
errorlog = "-"
