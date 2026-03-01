"""
Railway-safe gunicorn launcher.

Reads PORT from the environment in Python (no shell expansion needed),
logs the exact value so it's visible in Railway's log stream, then
exec-replaces itself with gunicorn bound to that port.
"""
import os
import sys


def main():
    port = os.environ.get("PORT", "").strip()

    # Log every PORT-related var so Railway logs show exactly what we see
    print(f"[start] PORT          = {port!r}", flush=True)
    print(f"[start] all PORT vars = { {k: v for k, v in os.environ.items() if 'port' in k.lower()} }",
          flush=True)

    if not port:
        print("[start] WARNING: PORT not set by Railway — defaulting to 5000", flush=True)
        port = "5000"

    bind = f"0.0.0.0:{port}"
    print(f"[start] binding gunicorn to {bind}", flush=True)

    cmd = [
        "gunicorn", "main:app",
        "--bind", bind,
        "--workers", "1",
        "--threads", "4",
        "--timeout", "120",
        "--log-level", "info",
        "--access-logfile", "-",
        "--error-logfile", "-",
    ]

    print(f"[start] exec: {' '.join(cmd)}", flush=True)

    # exec-replace this process with gunicorn — same PID, no subprocess wrapper
    os.execvp("gunicorn", cmd)


if __name__ == "__main__":
    main()
