#!/usr/bin/env python3
"""
Debug Web Server for Strike Finance Monitor
Serves debug logs, screenshots, and monitoring status
"""

import os
import json
import sqlite3
from datetime import datetime
from flask import Flask, render_template_string, send_file, jsonify, request
import glob
from pathlib import Path

app = Flask(__name__)

# HTML template for the debug dashboard
DEBUG_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Strike Finance Monitor Debug</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; 
            margin: 20px; 
            background: #1a1a1a; 
            color: #e0e0e0; 
        }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { 
            background: #2d2d2d; 
            padding: 20px; 
            border-radius: 8px; 
            margin-bottom: 20px; 
            border-left: 4px solid #00d4aa; 
        }
        .status { 
            display: inline-block; 
            padding: 6px 12px; 
            border-radius: 4px; 
            font-weight: bold; 
            margin-left: 10px; 
        }
        .status.capped { background: #ff4444; color: white; }
        .status.available { background: #00d4aa; color: white; }
        .status.unknown { background: #666; color: white; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
        .card { 
            background: #2d2d2d; 
            padding: 20px; 
            border-radius: 8px; 
            border: 1px solid #444; 
        }
        .card h3 { margin-top: 0; color: #00d4aa; }
        .logs { background: #1e1e1e; padding: 15px; border-radius: 4px; overflow-x: auto; }
        .log-entry { 
            padding: 8px; 
            margin: 4px 0; 
            border-radius: 4px; 
            font-family: 'Courier New', monospace; 
            font-size: 12px; 
        }
        .log-info { background: #0d4377; }
        .log-warning { background: #8b4000; }
        .log-error { background: #8b0000; }
        .debug-files { margin-top: 20px; }
        .file-item { 
            background: #333; 
            padding: 15px; 
            margin: 10px 0; 
            border-radius: 4px; 
            border-left: 3px solid #00d4aa; 
        }
        .file-item a { color: #00d4aa; text-decoration: none; }
        .file-item a:hover { text-decoration: underline; }
        .screenshot { max-width: 100%; height: auto; border: 1px solid #444; border-radius: 4px; }
        .stats { display: flex; gap: 20px; flex-wrap: wrap; }
        .stat-box { 
            background: #333; 
            padding: 15px; 
            border-radius: 4px; 
            text-align: center; 
            min-width: 120px; 
        }
        .stat-number { font-size: 24px; font-weight: bold; color: #00d4aa; }
        .stat-label { font-size: 12px; color: #999; margin-top: 5px; }
        .refresh-btn { 
            background: #00d4aa; 
            color: white; 
            border: none; 
            padding: 10px 20px; 
            border-radius: 4px; 
            cursor: pointer; 
            margin-bottom: 20px; 
        }
        .refresh-btn:hover { background: #00b892; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { padding: 8px; text-align: left; border-bottom: 1px solid #444; }
        th { background: #333; color: #00d4aa; }
        .timestamp { color: #999; font-size: 11px; }
    </style>
    <script>
        function refreshPage() { location.reload(); }
        setInterval(refreshPage, 30000); // Auto-refresh every 30 seconds
    </script>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 Strike Finance Monitor Debug Dashboard</h1>
            <p>Monitor URL: <a href="{{ monitor_url }}" target="_blank" style="color: #00d4aa;">{{ monitor_url }}</a></p>
            <p>Last Updated: {{ last_updated }}
                <span class="status {{ status_class }}">{{ current_status }}</span>
            </p>
            <button class="refresh-btn" onclick="refreshPage()">🔄 Refresh</button>
        </div>

        <div class="grid">
            <div class="card">
                <h3>📊 Monitor Statistics</h3>
                <div class="stats">
                    <div class="stat-box">
                        <div class="stat-number">{{ stats.total_checks }}</div>
                        <div class="stat-label">Total Checks</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-number">{{ stats.successful_checks }}</div>
                        <div class="stat-label">Successful</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-number">{{ stats.failed_checks }}</div>
                        <div class="stat-label">Failed</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-number">{{ stats.disagreements }}</div>
                        <div class="stat-label">Disagreements</div>
                    </div>
                </div>
            </div>

            <div class="card">
                <h3>🔍 Recent Activity</h3>
                <div class="logs">
                    {% for log in recent_logs %}
                    <div class="log-entry log-{{ log.level }}">
                        <span class="timestamp">{{ log.timestamp }}</span> - {{ log.message }}
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>

        <div class="card">
            <h3>📋 Recent Monitor States</h3>
            <table>
                <thead>
                    <tr>
                        <th>Timestamp</th>
                        <th>Method</th>
                        <th>Available</th>
                        <th>Success</th>
                        <th>Error</th>
                    </tr>
                </thead>
                <tbody>
                    {% for state in recent_states %}
                    <tr>
                        <td class="timestamp">{{ state.timestamp }}</td>
                        <td>{{ state.method }}</td>
                        <td>
                            {% if state.liquidity_available %}
                                <span class="status available">Available</span>
                            {% else %}
                                <span class="status capped">Capped</span>
                            {% endif %}
                        </td>
                        <td>{{ '✅' if state.success else '❌' }}</td>
                        <td>{{ state.error_message or '-' }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        {% if debug_files %}
        <div class="card debug-files">
            <h3>🐛 Debug Files</h3>
            <p>Files generated when monitoring methods disagree:</p>
            {% for file in debug_files %}
            <div class="file-item">
                <strong>{{ file.display_name }}</strong> - {{ file.size }} - 
                <span class="timestamp">{{ file.timestamp }}</span><br>
                {% if file.type == 'screenshot' %}
                    <a href="/debug/{{ file.name }}" target="_blank">View Screenshot</a> | 
                    <a href="/debug/{{ file.name }}" download>Download</a>
                {% elif file.type == 'html' %}
                    <a href="/debug/{{ file.name }}" target="_blank">View HTML Source</a> | 
                    <a href="/debug/{{ file.name }}" download>Download</a>
                {% endif %}
            </div>
            {% endfor %}
        </div>
        {% endif %}

        {% if latest_screenshot %}
        <div class="card">
            <h3>📸 Latest Screenshot</h3>
            <img src="/debug/{{ latest_screenshot }}" alt="Latest Screenshot" class="screenshot">
        </div>
        {% endif %}
    </div>
</body>
</html>
'''

class DebugServer:
    def __init__(self, monitor_dir="/app"):
        self.monitor_dir = Path(monitor_dir)
        self.db_path = self.monitor_dir / "strike_monitor.db"
        self.log_path = self.monitor_dir / "strike_monitor.log"
    
    def get_stats(self):
        """Get monitoring statistics from database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Total checks
            cursor.execute("SELECT COUNT(*) FROM monitor_state")
            total_checks = cursor.fetchone()[0]
            
            # Successful checks
            cursor.execute("SELECT COUNT(*) FROM monitor_state WHERE success = 1")
            successful_checks = cursor.fetchone()[0]
            
            # Failed checks
            cursor.execute("SELECT COUNT(*) FROM monitor_state WHERE success = 0")
            failed_checks = cursor.fetchone()[0]
            
            # Method disagreements (approximate)
            cursor.execute("""
                SELECT COUNT(*) FROM (
                    SELECT timestamp, COUNT(DISTINCT liquidity_available) as methods
                    FROM monitor_state 
                    WHERE timestamp > datetime('now', '-1 hour')
                    GROUP BY timestamp 
                    HAVING methods > 1
                )
            """)
            disagreements = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                'total_checks': total_checks,
                'successful_checks': successful_checks,
                'failed_checks': failed_checks,
                'disagreements': disagreements
            }
        except:
            return {
                'total_checks': 0,
                'successful_checks': 0,
                'failed_checks': 0,
                'disagreements': 0
            }
    
    def get_recent_states(self, limit=10):
        """Get recent monitor states from database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT timestamp, method, liquidity_available, success, error_message
                FROM monitor_state 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (limit,))
            
            states = []
            for row in cursor.fetchall():
                states.append({
                    'timestamp': row[0],
                    'method': row[1],
                    'liquidity_available': bool(row[2]),
                    'success': bool(row[3]),
                    'error_message': row[4]
                })
            
            conn.close()
            return states
        except:
            return []
    
    def get_recent_logs(self, limit=20):
        """Parse recent log entries"""
        logs = []
        try:
            with open(self.log_path, 'r') as f:
                lines = f.readlines()
                
            for line in lines[-limit:]:
                line = line.strip()
                if ' - ' in line:
                    parts = line.split(' - ', 2)
                    if len(parts) >= 3:
                        timestamp = parts[0]
                        level = parts[1].lower()
                        message = parts[2]
                        
                        logs.append({
                            'timestamp': timestamp,
                            'level': level,
                            'message': message
                        })
            
            return logs[::-1]  # Reverse to show newest first
        except:
            return []
    
    def get_debug_files(self):
        """Get list of debug files (screenshots and HTML) from logs directory"""
        files = []
        
        # Check both main directory and logs subdirectory
        search_paths = [self.monitor_dir, self.monitor_dir / "logs"]
        
        for search_path in search_paths:
            if not search_path.exists():
                continue
                
            # Find debug files
            for pattern in ['debug_screenshot_*.png', 'debug_source_*.html']:
                for file_path in search_path.glob(pattern):
                    try:
                        stat = file_path.stat()
                        file_type = 'screenshot' if file_path.suffix == '.png' else 'html'
                        
                        # Use relative path for serving
                        relative_path = file_path.relative_to(self.monitor_dir)
                        
                        files.append({
                            'name': str(relative_path),
                            'display_name': file_path.name,
                            'size': f"{stat.st_size / 1024:.1f} KB",
                            'timestamp': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                            'type': file_type,
                            'path': file_path
                        })
                    except:
                        continue
        
        # Sort by timestamp (newest first)
        files.sort(key=lambda x: x['timestamp'], reverse=True)
        return files
    
    def get_current_status(self):
        """Get current monitoring status"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT liquidity_available, success, timestamp
                FROM monitor_state 
                WHERE method = 'requests'
                ORDER BY timestamp DESC 
                LIMIT 1
            """)
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                available, success, timestamp = result
                if success:
                    return "AVAILABLE" if available else "CAPPED", "available" if available else "capped"
                else:
                    return "ERROR", "unknown"
            else:
                return "UNKNOWN", "unknown"
        except:
            return "ERROR", "unknown"

# Initialize server
debug_server = DebugServer()

@app.route('/')
def dashboard():
    """Main dashboard"""
    stats = debug_server.get_stats()
    recent_logs = debug_server.get_recent_logs()
    recent_states = debug_server.get_recent_states()
    debug_files = debug_server.get_debug_files()
    current_status, status_class = debug_server.get_current_status()
    
    # Get latest screenshot
    latest_screenshot = None
    for file in debug_files:
        if file['type'] == 'screenshot':
            latest_screenshot = file['name']
            break
    
    return render_template_string(DEBUG_TEMPLATE,
        stats=stats,
        recent_logs=recent_logs,
        recent_states=recent_states,
        debug_files=debug_files,
        latest_screenshot=latest_screenshot,
        current_status=current_status,
        status_class=status_class,
        monitor_url="https://app.strikefinance.org/liquidity",
        last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )

@app.route('/debug/<path:filename>')
def serve_debug_file(filename):
    """Serve debug files (screenshots, HTML) from main dir or logs subdir"""
    # Try main directory first, then logs subdirectory
    possible_paths = [
        debug_server.monitor_dir / filename,
        debug_server.monitor_dir / "logs" / filename
    ]
    
    for file_path in possible_paths:
        if file_path.exists() and (filename.startswith('debug_') or filename.startswith('logs/')):
            return send_file(file_path)
    
    return "File not found", 404

@app.route('/api/status')
def api_status():
    """JSON API for current status"""
    current_status, status_class = debug_server.get_current_status()
    stats = debug_server.get_stats()
    
    return jsonify({
        'status': current_status,
        'status_class': status_class,
        'stats': stats,
        'timestamp': datetime.now().isoformat()
    })

if __name__ == '__main__':
    print("Starting Strike Finance Monitor Debug Server...")
    print("Dashboard: http://localhost:5000")
    print("API: http://localhost:5000/api/status")
    app.run(host='0.0.0.0', port=5000, debug=False)
