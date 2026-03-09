#!/bin/bash

# Start Xvfb
Xvfb :1 -screen 0 1280x720x16 &> /tmp/xvfb.log &
export DISPLAY=:1

# Start a window manager (optional, but good for handling the window)
openbox-session &> /tmp/openbox.log &

# Start VNC server
x11vnc -display :1 -nopw -listen localhost -xkb &> /tmp/x11vnc.log &

# Start noVNC
/usr/share/novnc/utils/launch.sh --vnc localhost:5900 --listen 6080 &> /tmp/novnc.log &

# Get URL from environment variable or use a default
URL=${URL:-"https://www.google.com"}

# Kill other processes to ensure kiosk mode
killall xfce4-panel &> /dev/null
killall xfdesktop &> /dev/null

# Start Firefox in kiosk mode
firefox --kiosk "$URL" &> /tmp/firefox.log &

# Keep the script running
wait
