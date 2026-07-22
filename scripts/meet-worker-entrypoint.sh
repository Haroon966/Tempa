#!/bin/sh
set -e
mkdir -p /tmp/.X11-unix

export XDG_RUNTIME_DIR=/tmp/pulse-runtime
mkdir -p "$XDG_RUNTIME_DIR"
export PULSE_SERVER="unix:${XDG_RUNTIME_DIR}/pulse/native"

# Concurrent Meet sessions: one Xvfb + Pulse null-sink per slot (1–16).
N="${MEET_MAX_CONCURRENT:-10}"
case "$N" in
  ''|*[!0-9]*) N=10 ;;
esac
if [ "$N" -lt 1 ]; then N=1; fi
if [ "$N" -gt 16 ]; then N=16; fi

start_pulse() {
  rm -rf "${XDG_RUNTIME_DIR}/pulse" "${XDG_RUNTIME_DIR}/pid" 2>/dev/null || true
  if PULSE_SERVER="$PULSE_SERVER" pactl info >/dev/null 2>&1; then
    return 0
  fi
  pulseaudio --daemonize --exit-idle-time=-1 --disallow-exit 2>/dev/null || true
  i=0
  while [ "$i" -lt 20 ]; do
    i=$((i + 1))
    sleep 0.25
    if PULSE_SERVER="$PULSE_SERVER" pactl info >/dev/null 2>&1; then
      break
    fi
  done
  if ! PULSE_SERVER="$PULSE_SERVER" pactl info >/dev/null 2>&1; then
    echo "meet-worker: PulseAudio failed to start" >&2
    return 1
  fi

  i=0
  while [ "$i" -lt "$N" ]; do
    PULSE_SERVER="$PULSE_SERVER" pactl load-module module-null-sink \
      sink_name="meet_sink_$i" \
      sink_properties=device.description="MeetCapture$i" >/dev/null 2>&1 || true
    i=$((i + 1))
  done
  PULSE_SERVER="$PULSE_SERVER" pactl set-default-sink meet_sink_0 2>/dev/null || true
  PULSE_SERVER="$PULSE_SERVER" pactl set-default-source meet_sink_0.monitor 2>/dev/null || true
  echo "meet-worker: PulseAudio ready (slots=$N, default=meet_sink_0.monitor)"
}

start_pulse

if [ -f /app/config/assets/animated_tempa.mp4 ]; then
  ffmpeg -y -nostdin -loglevel error -i /app/config/assets/animated_tempa.mp4 \
    -an -vf scale=640:360 -c:v mjpeg -q:v 5 -f mjpeg /app/config/assets/animated_tempa.mjpeg
  echo "meet-worker: virtual camera MJPEG ready"
fi

i=0
while [ "$i" -lt "$N" ]; do
  DISP=$((99 + i))
  rm -f "/tmp/.X${DISP}-lock" 2>/dev/null || true
  Xvfb ":$DISP" -screen 0 1280x1024x24 -nolisten tcp &
  i=$((i + 1))
done
export DISPLAY=:99
export MEET_PULSE_MONITOR_SOURCE="${MEET_PULSE_MONITOR_SOURCE:-meet_sink_0.monitor}"
export MEET_MAX_CONCURRENT="$N"
sleep 2

exec env \
  PULSE_SERVER="$PULSE_SERVER" \
  XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
  DISPLAY="$DISPLAY" \
  MEET_PULSE_MONITOR_SOURCE="$MEET_PULSE_MONITOR_SOURCE" \
  MEET_MAX_CONCURRENT="$MEET_MAX_CONCURRENT" \
  python -u -m tempa.meet.worker_main
