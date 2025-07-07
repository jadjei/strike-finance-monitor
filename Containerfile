FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create monitor user
RUN useradd -m -u 1000 monitor

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY strike_monitor.py .
COPY debug_server.py .
COPY cleanup_debug_files.py .
COPY config.json.template .

# Create necessary directories
RUN mkdir -p logs db && chown -R monitor:monitor /app

# Switch to monitor user
USER monitor

# Expose debug server port
EXPOSE 5000

# Use supervisor to run both services
COPY --chown=monitor:monitor container/supervisord.conf /etc/supervisor/conf.d/
COPY --chown=monitor:monitor container/entrypoint.sh /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
