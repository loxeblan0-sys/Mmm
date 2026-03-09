FROM debian:12-slim

# Install necessary packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    firefox-esr \
    xserver-xorg-core \
    xserver-xorg-video-dummy \
    x11vnc \
    xvfb \
    xfce4 \
    xfce4-terminal \
    novnc \
    dbus-x11 \
    libx11-6 \
    libxrandr2 \
    libxext6 \
    libxrender1 \
    libxfixes3 \
    libxss1 \
    libxtst6 \
    libxi6 \
    # Add proxy support tools
    socat \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Create a startup script
COPY start.sh /start.sh
RUN chmod +x /start.sh

# Expose VNC port
EXPOSE 6080

# Set the entrypoint
ENTRYPOINT ["/start.sh"]
