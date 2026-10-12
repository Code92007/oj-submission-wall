#!/bin/sh
set -eu
umask 077
mkdir -p /data/browser-profile
Xvfb :99 -screen 0 1280x900x24 -nolisten tcp &
xvfb_pid=$!
vnc_pid=''
web_pid=''
proxy_pid=''
cleanup() {
  for task_pid in "$proxy_pid" "$web_pid" "$vnc_pid" "$xvfb_pid"; do
    if [ -n "$task_pid" ]; then kill "$task_pid" 2>/dev/null || true; fi
  done
}
trap cleanup EXIT
stop() {
  if [ -n "$proxy_pid" ]; then
    kill "$proxy_pid" 2>/dev/null || true
    wait "$proxy_pid" 2>/dev/null || true
  fi
  exit 0
}
trap stop INT TERM
# The display socket is ready before starting the browser and VNC server.
attempt=0
while [ ! -S /tmp/.X11-unix/X99 ]; do
  attempt=$((attempt + 1))
  [ "$attempt" -lt 30 ] || exit 1
  sleep 1
done
x11vnc -display :99 -localhost -forever -shared -nopw -rfbport 5900 -quiet &
vnc_pid=$!
websockify --web=/usr/share/novnc 6080 localhost:5900 &
web_pid=$!
python /app/luogu_proxy.py &
proxy_pid=$!
wait "$proxy_pid"
