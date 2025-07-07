# Strike Finance Liquidity Monitor

Simple, reliable monitoring for Strike Finance liquidity deployment availability. Sends instant alerts when liquidity becomes available for deployment.

## 🚨 What It Does

Monitors [Strike Finance Liquidity](https://app.strikefinance.org/liquidity) by checking for the text "Liquidity Currently Capped". When this text disappears, liquidity deployment is available and alerts are sent.

## ✨ Features

- **Simple Detection**: Single HTTP check for "Liquidity Currently Capped" text
- **Multi-Channel Alerts**: Email, Discord, Pushover notifications
- **Web Dashboard**: Real-time status at `http://YOUR_IP:5000`
- **Container Deployment**: Clean, isolated environment
- **Automatic Restart**: Systemd integration for reliability

## 🚀 Quick Start

### Prerequisites
- Podman installed
- Port 5000 available for web dashboard

### 1. Deploy with Podman

```bash
# Clone the repository
git clone <repository-url>
cd strike-finance-monitor

# One-command deployment
chmod +x deploy-podman.sh
./deploy-podman.sh
```

### 2. Configure Alerts

Edit the configuration file:
```bash
# Edit config (container will restart automatically)
podman exec -it strike-finance-monitor nano /app/config.json
```

Required configuration:
```json
{
    "email": {
        "from": "your-email@gmail.com",
        "to": ["your-phone@carrier-sms-gateway.com"],
        "smtp_server": "smtp.gmail.com", 
        "username": "your-email@gmail.com",
        "password": "your-gmail-app-password"
    },
    "discord_webhook": "https://discord.com/api/webhooks/...",
    "pushover": {
        "app_token": "YOUR_APP_TOKEN",
        "user_key": "YOUR_USER_KEY"
    }
}
```

### 3. Access Dashboard

Open `http://YOUR_SERVER_IP:5000` to view:
- Real-time liquidity status
- Monitor statistics and logs
- Historical state changes

## 📱 Alert Setup

### Email + SMS
1. **Gmail App Password**: Enable 2FA, generate app password in Security settings
2. **SMS via Email** (UK carriers):
   - **O2**: `447123456789@email.o2.co.uk`
   - **EE**: `447123456789@mms.ee.co.uk` 
   - **Three**: `447123456789@email.three.co.uk`
   - **Vodafone**: `447123456789@vodafone.net`

### Discord
1. Server Settings → Integrations → Webhooks
2. Create New Webhook → Copy URL

### Pushover (Recommended)
1. Create account at [pushover.net](https://pushover.net)
2. Create application ($5 one-time fee)
3. Get app token and user key

## 🐋 Container Management

```bash
# View status
podman ps
podman logs strike-finance-monitor

# Restart after config changes
podman restart strike-finance-monitor

# Stop/start
podman stop strike-finance-monitor
podman start strike-finance-monitor

# Systemd user service (auto-configured)
systemctl --user status strike-monitor
systemctl --user restart strike-monitor
```

## 📊 How It Works

### Detection Logic
```
1. HTTP GET → https://app.strikefinance.org/liquidity
2. Search page content for "Liquidity Currently Capped"
3. If found → Status: CAPPED
4. If NOT found → Status: AVAILABLE
5. Alert on CAPPED → AVAILABLE transition
```

### Alert Behavior
- **Triggers**: Only when status changes from CAPPED to AVAILABLE
- **Cooldown**: 3 minutes between duplicate alerts
- **Multi-Channel**: All configured channels receive alerts simultaneously

## ⚙️ Configuration Options

```json
{
    "check_interval": 60,     // Seconds between checks
    "timeout": 15,            // HTTP request timeout
    "alert_cooldown": 180     // Seconds between duplicate alerts
}
```

## 🔧 Troubleshooting

### Monitor Not Working
```bash
# Check container logs
podman logs strike-finance-monitor

# Check if running
podman ps

# Restart container
podman restart strike-finance-monitor
```

### No Alerts Received
1. Check email credentials (Gmail app password)
2. Verify Discord webhook URL
3. Test Pushover credentials
4. Check dashboard for error messages

### False State Detection
- Dashboard shows current detection logic
- Monitor logs show exactly what text was found
- Simple single-check approach minimizes errors

## 📁 Project Structure

```
strike-finance-monitor/
├── strike_monitor.py          # Main monitoring service
├── debug_server.py            # Web dashboard  
├── cleanup_debug_files.py     # Log cleanup utility
├── config.json.template       # Configuration template
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Container definition
├── podman-compose.yml         # Container orchestration
├── deploy-podman.sh           # Deployment script
└── README.md                  # This file
```

## 🔒 Security

- **Rootless containers**: Runs as non-root user
- **No sensitive data in logs**: Passwords masked
- **Local operation**: All monitoring runs on your server
- **HTTPS only**: All external communications encrypted

## 📈 Performance

- **Check frequency**: Every 60 seconds (configurable)
- **Response time**: ~2 seconds per check
- **Resource usage**: <30MB RAM, minimal CPU
- **Reliability**: Simple single-check approach for maximum uptime

---

**⚠️ Important**: This monitor detects availability but does not automatically deploy capital. You must manually execute trades when alerts are received.
