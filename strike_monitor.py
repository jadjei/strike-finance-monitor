#!/usr/bin/env python3
"""
Strike Finance Liquidity Monitor - Simplified Single Check
Only looks for "Liquidity Currently Capped" text
"""

import requests
import time
import json
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
from dataclasses import dataclass
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import asyncio
import aiohttp
from pathlib import Path

@dataclass
class MonitorConfig:
    url: str = "https://app.strikefinance.org/liquidity"
    check_interval: int = 60
    timeout: int = 15
    alert_cooldown: int = 180
    
    # Single indicator to check for
    capped_text: str = "Liquidity Currently Capped"

class AlertManager:
    def __init__(self, config: Dict):
        self.config = config
        self.last_alerts = {}
        
    async def send_alert(self, message: str, alert_type: str = "LIQUIDITY_AVAILABLE"):
        """Send alerts through multiple channels"""
        now = datetime.now()
        
        cooldown = 180 if alert_type == "LIQUIDITY_AVAILABLE" else 300
        
        if alert_type in self.last_alerts:
            if now - self.last_alerts[alert_type] < timedelta(seconds=cooldown):
                return
        
        self.last_alerts[alert_type] = now
        
        # Send through all configured channels
        tasks = []
        
        if self.config.get('email'):
            tasks.append(self._send_email(message))
        
        if self.config.get('discord_webhook'):
            tasks.append(self._send_discord(message))
        
        if self.config.get('pushover'):
            tasks.append(self._send_pushover(message))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _send_email(self, message: str):
        """Send email alert"""
        try:
            msg = MIMEMultipart()
            msg['From'] = self.config['email']['from']
            msg['To'] = ', '.join(self.config['email']['to'])
            msg['Subject'] = "🚨 Strike Finance Liquidity Alert"
            
            body = f"""
            LIQUIDITY DEPLOYMENT AVAILABLE!
            
            {message}
            
            URL: https://app.strikefinance.org/liquidity
            Time: {datetime.now().isoformat()}
            """
            
            msg.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP(self.config['email']['smtp_server'], 587)
            server.starttls()
            server.login(self.config['email']['username'], self.config['email']['password'])
            server.send_message(msg)
            server.quit()
            
        except Exception as e:
            logging.error(f"Email alert failed: {e}")
    
    async def _send_discord(self, message: str):
        """Send Discord webhook alert"""
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "embeds": [{
                        "title": "🚨 Strike Finance Liquidity Alert",
                        "description": message,
                        "color": 65280,  # Green
                        "timestamp": datetime.utcnow().isoformat(),
                        "url": "https://app.strikefinance.org/liquidity"
                    }]
                }
                
                async with session.post(
                    self.config['discord_webhook'],
                    json=payload
                ) as response:
                    if response.status != 204:
                        logging.error(f"Discord webhook failed: {response.status}")
                        
        except Exception as e:
            logging.error(f"Discord alert failed: {e}")
    
    async def _send_pushover(self, message: str):
        """Send Pushover notification"""
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "token": self.config['pushover']['app_token'],
                    "user": self.config['pushover']['user_key'],
                    "message": message,
                    "title": "Strike Finance Alert",
                    "priority": 2,  # Emergency priority
                    "retry": 30,
                    "expire": 3600,
                    "url": "https://app.strikefinance.org/liquidity"
                }
                
                async with session.post(
                    "https://api.pushover.net/1/messages.json",
                    data=payload
                ) as response:
                    if response.status != 200:
                        logging.error(f"Pushover failed: {response.status}")
                        
        except Exception as e:
            logging.error(f"Pushover alert failed: {e}")

class SimpleMonitor:
    def __init__(self, config: MonitorConfig, alert_manager: AlertManager):
        self.config = config
        self.alert_manager = alert_manager
        self.db_path = "strike_monitor.db"
        self.setup_database()
        self.setup_logging()
        
    def setup_database(self):
        """Initialize SQLite database for state tracking"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS monitor_state (
                id INTEGER PRIMARY KEY,
                timestamp DATETIME,
                method TEXT,
                state_hash TEXT,
                raw_content TEXT,
                liquidity_available BOOLEAN,
                success BOOLEAN,
                error_message TEXT,
                capped_text_found BOOLEAN
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def setup_logging(self):
        """Configure comprehensive logging"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('strike_monitor.log'),
                logging.StreamHandler()
            ]
        )
    
    def log_state(self, method: str, state_hash: str, content: str, 
                  available: bool, success: bool, error: str = None,
                  capped_text_found: bool = False):
        """Log monitoring state to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO monitor_state 
            (timestamp, method, state_hash, raw_content, liquidity_available, 
             success, error_message, capped_text_found)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (datetime.now(), method, state_hash, content, available, 
              success, error, capped_text_found))
        
        conn.commit()
        conn.close()
    
    async def check_liquidity_status(self) -> Optional[bool]:
        """Single check: Look for 'Liquidity Currently Capped' text"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.config.url, 
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.config.timeout)
                ) as response:
                    
                    if response.status != 200:
                        raise Exception(f"HTTP {response.status}")
                    
                    content = await response.text()
                    
                    # Simple check: Look for the capped text
                    capped_text_found = self.config.capped_text in content
                    
                    # If "Liquidity Currently Capped" is found = NOT available
                    # If "Liquidity Currently Capped" is NOT found = available
                    available = not capped_text_found
                    
                    state_hash = hashlib.md5(content.encode()).hexdigest()
                    
                    logging.info(f"Single check - '{self.config.capped_text}' found: {capped_text_found}, Available: {available}")
                    
                    self.log_state("http_simple", state_hash, content[:1000], available, True,
                                 capped_text_found=capped_text_found)
                    return available
                    
        except Exception as e:
            self.log_state("http_simple", "", "", False, False, str(e))
            logging.error(f"Simple check failed: {e}")
            return None
    
    async def run_monitor(self):
        """Main monitoring loop - simplified"""
        logging.info("Starting Strike Finance liquidity monitor (SIMPLE MODE)...")
        logging.info(f"Checking for text: '{self.config.capped_text}'")
        
        last_state = None
        consecutive_failures = 0
        last_cleanup = datetime.now()
        
        while True:
            try:
                current_state = await self.check_liquidity_status()
                
                if current_state is None:
                    consecutive_failures += 1
                    logging.error(f"Check failed ({consecutive_failures})")
                    
                    if consecutive_failures >= 5:
                        await self.alert_manager.send_alert(
                            f"Monitor has failed {consecutive_failures} consecutive times",
                            "MONITOR_FAILURE"
                        )
                else:
                    consecutive_failures = 0
                    
                    # Alert on state change from CAPPED to AVAILABLE
                    if current_state and last_state is False:
                        message = f"""
                        🚨 LIQUIDITY DEPLOYMENT NOW AVAILABLE! 🚨
                        
                        The "Liquidity Currently Capped" text is no longer present.
                        Liquidity deployment may now be possible.
                        
                        Detected at: {datetime.now().isoformat()}
                        """
                        
                        await self.alert_manager.send_alert(message, "LIQUIDITY_AVAILABLE")
                        logging.info("🚨 LIQUIDITY AVAILABLE - Alerts sent!")
                    
                    elif not current_state and last_state is True:
                        logging.info("Liquidity is now capped again")
                    
                    last_state = current_state
                    
                    # Log current status
                    status = "AVAILABLE" if current_state else "CAPPED"
                    logging.info(f"Status: {status}")
                
                # Daily cleanup
                if (datetime.now() - last_cleanup).days >= 1:
                    await self._cleanup_debug_files()
                    last_cleanup = datetime.now()
                
            except Exception as e:
                consecutive_failures += 1
                logging.error(f"Monitor cycle failed ({consecutive_failures}): {e}")
            
            await asyncio.sleep(self.config.check_interval)
    
    async def _cleanup_debug_files(self):
        """Run debug files cleanup"""
        try:
            logs_dir = Path("logs")
            if logs_dir.exists():
                # Simple cleanup: delete files older than 7 days
                import os
                import time
                
                now = time.time()
                for file_path in logs_dir.glob("debug_*"):
                    if now - file_path.stat().st_mtime > 7 * 24 * 3600:  # 7 days
                        file_path.unlink()
                        logging.debug(f"Cleaned up old debug file: {file_path.name}")
            
        except Exception as e:
            logging.error(f"Debug files cleanup failed: {e}")

async def main():
    """Main entry point"""
    try:
        with open('config.json', 'r') as f:
            config_data = json.load(f)
    except FileNotFoundError:
        print("config.json not found, using default config")
        config_data = {}
    
    alert_config = {
        'email': config_data.get('email'),
        'discord_webhook': config_data.get('discord_webhook'),
        'pushover': config_data.get('pushover')
    }
    
    # Simple configuration
    config = MonitorConfig(
        check_interval=config_data.get('check_interval', 60),
        timeout=config_data.get('timeout', 15)
    )
    
    alert_manager = AlertManager(alert_config)
    monitor = SimpleMonitor(config, alert_manager)
    
    logging.info(f"SIMPLE MODE - Single check for: '{config.capped_text}'")
    logging.info(f"Check interval: {config.check_interval}s")
    
    await monitor.run_monitor()

if __name__ == "__main__":
    asyncio.run(main())
