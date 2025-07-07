#!/bin/bash
set -e

echo "🚀 Starting Strike Finance Monitor..."

# Create config.json if it doesn't exist
if [[ ! -f /app/config.json ]]; then
    echo "📝 Creating config.json from template..."
    cp /app/config.json.template /app/config.json
    echo "⚠️  Edit config.json with your credentials!"
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
