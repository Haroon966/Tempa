#!/bin/sh
set -e
rm -f /tmp/.X99-lock 2>/dev/null || true
mkdir -p /tmp/.X11-unix
Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp &
export DISPLAY=:99
sleep 2
exec python -u -m tempa.meet.worker_main
