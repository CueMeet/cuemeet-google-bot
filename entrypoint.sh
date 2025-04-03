#!/bin/bash
set -e

# Start PulseAudio server in the background
pulseaudio --start --log-target=syslog --system=false --disallow-exit

# Create a virtual audio sink
pacmd load-module module-null-sink sink_name=virtual-sink sink_properties=device.description="Virtual_Sink"

# Wait for PulseAudio to fully initialize
sleep 2

# Execute the passed command
exec "$@"