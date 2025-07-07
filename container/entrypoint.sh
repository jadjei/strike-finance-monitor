#!/bin/bash
set -e

echo "🚀 Starting Strike Finance Monitor..."

# Create config.json if it doesn't exist or if mounted file has permission issues
if [[ ! -f /app/config.json ]] || [[ ! -r /app/config.json ]]; then
    echo "📝 Creating config.json from template..."
    cp /app/config.json.template /app/config.json
    chmod 644 /app/config.json
    echo "⚠️  Edit config.json with your credentials!"
fi

# Ensure config.json is readable
if [[ ! -r /app/config.json ]]; then
    echo "⚠️  Fixing config.json permissions..."
    chmod 644 /app/config.json
fi

# Create necessary directories
mkdir -p /app/logs /app/db

echo "🎬 Starting services..."

# Start both monitor and debug server
python /app/strike_monitor.py &
python /app/debug_server.py &

# Wait for any process to exit
wait -n

# Exit with status of process that exited first
exit $?
