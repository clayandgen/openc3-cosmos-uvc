#!/usr/bin/env bash
# Push the camera into MediaMTX as RTSP.
# Run `mediamtx` in another terminal first.
#
# Usage: ./stream.sh [device] [path]
set -euo pipefail

DEVICE="${1:-Insta360 Link 2}"
PATH_NAME="${2:-insta360}"
SIZE="${SIZE:-1280x720}"
FPS="${FPS:-30}"

OS="$(uname -s)"
case "$OS" in
  Darwin) INPUT_FMT="avfoundation" ;;
  Linux)  INPUT_FMT="v4l2"; DEVICE="${DEVICE/Insta360 Link 2//dev/video0}" ;;
  *)      echo "Unsupported OS: $OS" >&2; exit 1 ;;
esac

# Keyframe interval (in frames). Short GOP = short HLS parts = low latency.
# 6 frames @ 30fps = 200ms — matches mediamtx.yml hlsPartDuration.
GOP="${GOP:-6}"

exec ffmpeg \
  -f "$INPUT_FMT" -framerate "$FPS" -video_size "$SIZE" -i "$DEVICE" \
  -c:v libx264 -preset ultrafast -tune zerolatency \
  -profile:v baseline -level 4.0 -pix_fmt yuv420p \
  -g "$GOP" -keyint_min "$GOP" -sc_threshold 0 \
  -f rtsp -rtsp_transport tcp \
  "rtsp://localhost:8554/${PATH_NAME}"
