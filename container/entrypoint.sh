#!/bin/bash
set -e

echo "🚀 Starting Strike Finance Monitor container..."

# Create config.json if it doesn't exist
if [[ ! -f /app/config.json ]]; then
    echo "📝 Creating config.json from template..."
    cp /app/config.json.template /app/config.json
    echo "⚠️  IMPORTANT: Edit /app/config.json with your credentials!"
fi

# Set up cron job for cleanup (as monitor user)
if [[ ! -f /var/spool/cron/crontabs/monitor ]]; then
    echo "⏰ Setting up cleanup cron job..."
    # Create crontab directory if it doesn't exist
    mkdir -p /tmp/cron
    echo "0 2 * * * cd /app && python cleanup_debug_files.py --quiet" > /tmp/cron/monitor-crontab
    
    # Note: In rootless container, we'll handle cleanup via the monitor app instead
    echo "📅 Cleanup will be handled by the monitor application"
fi

echo "🎬 Starting supervisor as monitor user..."

# Start supervisor with correct user permissions
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
