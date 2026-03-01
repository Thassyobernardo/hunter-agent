import os

# Read PORT from environment — works on Railway, Heroku, Render, etc.
# Avoids relying on shell variable expansion in the Procfile.
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
workers = 1
threads = 4
timeout = 120
loglevel = "info"
accesslog = "-"   # log requests to stdout
errorlog = "-"    # log errors to stdout
