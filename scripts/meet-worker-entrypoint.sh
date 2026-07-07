#!/bin/sh
set -e
rm -f /tmp/.X99-lock 2>/dev/null || true
mkdir -p /tmp/.X11-unix

export XDG_RUNTIME_DIR=/tmp/pulse-runtime
mkdir -p "$XDG_RUNTIME_DIR"
export PULSE_SERVER="unix:${XDG_RUNTIME_DIR}/pulse/native"
export MEET_PULSE_MONITOR_SOURCE="${MEET_PULSE_MONITOR_SOURCE:-meet_sink.monitor}"

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
  PULSE_SERVER="$PULSE_SERVER" pactl load-module module-null-sink \
    sink_name=meet_sink sink_properties=device.description=MeetCapture >/dev/null 2>&1 || true
  PULSE_SERVER="$PULSE_SERVER" pactl set-default-sink meet_sink 2>/dev/null || true
  PULSE_SERVER="$PULSE_SERVER" pactl set-default-source meet_sink.monitor 2>/dev/null || true
  echo "meet-worker: PulseAudio ready (monitor=${MEET_PULSE_MONITOR_SOURCE})"
}

start_pulse

if [ -f /app/config/assets/animated_tempa.mp4 ]; then
  ffmpeg -y -nostdin -loglevel error -i /app/config/assets/animated_tempa.mp4 \
    -an -vf scale=640:360 -c:v mjpeg -q:v 5 -f mjpeg /app/config/assets/animated_tempa.mjpeg
  echo "meet-worker: virtual camera MJPEG ready"
fi

Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp &
export DISPLAY=:99
sleep 2

exec env \
  PULSE_SERVER="$PULSE_SERVER" \
  XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
  DISPLAY="$DISPLAY" \
  MEET_PULSE_MONITOR_SOURCE="$MEET_PULSE_MONITOR_SOURCE" \
  python -u -m tempa.meet.worker_main
