#!/usr/bin/env python3
"""
Robust Strike Finance Liquidity Monitor
Multi-layered monitoring with redundancy and comprehensive alerting
"""

import requests
import time
import json
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import threading
import queue
import asyncio
import aiohttp
from pathlib import Path

@dataclass
class MonitorConfig:
    url: str = "https://app.strikefinance.org/liquidity"
    check_interval: int = 30  # seconds
    timeout: int = 15
    max_retries: int = 3
    alert_cooldown: int = 300  # 5 minutes between same alerts
    use_selenium: bool = True  # Set to False to disable Selenium
    
    # Target elements to monitor
    button_selectors: List[str] = None
    disabled_text: str = "Liquidity Currently Capped"
    
    def __post_init__(self):
        if self.button_selectors is None:
            self.button_selectors = [
                'button:contains("Liquidity Currently Capped")',
                'button[disabled*=""]',
                '.bg-\\[\\#636363\\]',
                'button.cursor-not-allowed'
            ]

class AlertManager:
    def __init__(self, config: Dict):
        self.config = config
        self.last_alerts = {}
        
    async def send_alert(self, message: str, alert_type: str = "LIQUIDITY_AVAILABLE"):
        """Send alerts through multiple channels"""
        now = datetime.now()
        
        # Cooldown check
        if alert_type in self.last_alerts:
            if now - self.last_alerts[alert_type] < timedelta(seconds=300):
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
        
        # Execute all alerts concurrently (only if we have tasks)
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

class MultiLayerMonitor:
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
                error_message TEXT
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
                  available: bool, success: bool, error: str = None):
        """Log monitoring state to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO monitor_state 
            (timestamp, method, state_hash, raw_content, liquidity_available, success, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (datetime.now(), method, state_hash, content, available, success, error))
        
        conn.commit()
        conn.close()
    
    async def check_with_requests(self) -> Optional[bool]:
        """Method 1: Simple HTTP requests with BeautifulSoup"""
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
                    
                    # Check multiple indicators that liquidity is capped
                    capped_indicators = [
                        "Liquidity Currently Capped" in content,
                        "cursor-not-allowed" in content,
                        'disabled=""' in content,
                        "bg-[#636363]" in content,
                        "text-[#a0a0a0]" in content
                    ]
                    
                    # If ANY indicator shows it's capped, then it's capped
                    is_capped = any(capped_indicators)
                    available = not is_capped
                    
                    state_hash = hashlib.md5(content.encode()).hexdigest()
                    
                    logging.info(f"HTTP check - Capped indicators: {sum(capped_indicators)}/5, Available: {available}")
                    self.log_state("requests", state_hash, content[:1000], available, True)
                    return available
                    
        except Exception as e:
            self.log_state("requests", "", "", False, False, str(e))
            logging.error(f"Requests method failed: {e}")
            return None
    
    def check_with_selenium(self) -> Optional[bool]:
        """Method 2: Selenium for JavaScript-heavy content"""
        driver = None
        try:
            options = Options()
            options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            
            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(self.config.timeout)
            
            driver.get(self.config.url)
            
            # Wait for page to load
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "button"))
            )
            
            # Check for disabled state
            try:
                disabled_button = driver.find_element(
                    By.CSS_SELECTOR, 
                    'button[disabled], button.cursor-not-allowed'
                )
                button_text = disabled_button.text
                
                available = self.config.disabled_text not in button_text
                
            except:
                # If no disabled button found, liquidity might be available
                available = True
            
            page_source = driver.page_source
            state_hash = hashlib.md5(page_source.encode()).hexdigest()
            
            self.log_state("selenium", state_hash, page_source[:1000], available, True)
            return available
            
        except Exception as e:
            self.log_state("selenium", "", "", False, False, str(e))
            logging.error(f"Selenium method failed: {e}")
            return None
            
        finally:
            if driver:
                driver.quit()
    
    async def consensus_check(self) -> bool:
        """Run multiple monitoring methods and use consensus"""
        results = []
        
        # Method 1: Async HTTP + BeautifulSoup (primary method - most reliable)
        result1 = await self.check_with_requests()
        if result1 is not None:
            results.append(("HTTP", result1))
        
        # Method 2: Selenium (backup method) - only if enabled
        if self.config.use_selenium:
            def selenium_wrapper():
                return self.check_with_selenium()
            
            loop = asyncio.get_event_loop()
            result2 = await loop.run_in_executor(None, selenium_wrapper)
            if result2 is not None:
                results.append(("Selenium", result2))
        
        # Consensus logic - prioritize HTTP method
        if not results:
            logging.error("All monitoring methods failed")
            return False
        
        # If we have HTTP result, trust it more
        http_result = next((result for method, result in results if method == "HTTP"), None)
        selenium_result = next((result for method, result in results if method == "Selenium"), None)
        
        if http_result is not None:
            if selenium_result is not None and http_result != selenium_result:
                logging.warning(f"Methods disagree - HTTP: {http_result}, Selenium: {selenium_result} - Using HTTP result")
                # Save debug info when methods disagree
                await self._save_debug_info(http_result, selenium_result)
            return http_result
        else:
            # Fallback to Selenium if HTTP failed
            logging.warning("HTTP method failed, using Selenium result")
            return selenium_result if selenium_result is not None else False
    
    async def _save_debug_info(self, http_result: bool, selenium_result: bool):
        """Save debug information when methods disagree"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Create logs directory if it doesn't exist
            logs_dir = Path("logs")
            logs_dir.mkdir(exist_ok=True)
            
            # Save a screenshot with Selenium for debugging
            options = Options()
            options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--window-size=1920,1080')
            
            driver = webdriver.Chrome(options=options)
            driver.get(self.config.url)
            time.sleep(5)
            
            screenshot_path = logs_dir / f"debug_screenshot_{timestamp}.png"
            driver.save_screenshot(str(screenshot_path))
            
            # Save page source
            source_path = logs_dir / f"debug_source_{timestamp}.html"
            with open(source_path, 'w') as f:
                f.write(driver.page_source)
            
            logging.info(f"Debug files saved: {screenshot_path.name} and {source_path.name}")
            driver.quit()
            
        except Exception as e:
            logging.error(f"Failed to save debug info: {e}")
    
    async def run_monitor(self):
        """Main monitoring loop"""
        logging.info("Starting Strike Finance liquidity monitor...")
        
        last_state = False
        consecutive_failures = 0
        last_cleanup = datetime.now()
        
        while True:
            try:
                current_state = await self.consensus_check()
                
                # Reset failure counter on success
                consecutive_failures = 0
                
                # State change detection
                if current_state and not last_state:
                    message = f"""
                    🚨 LIQUIDITY DEPLOYMENT NOW AVAILABLE! 🚨
                    
                    The Strike Finance liquidity cap has been lifted.
                    You can now deploy capital.
                    
                    Detected at: {datetime.now().isoformat()}
                    """
                    
                    await self.alert_manager.send_alert(message, "LIQUIDITY_AVAILABLE")
                    logging.info("🚨 LIQUIDITY AVAILABLE - Alerts sent!")
                
                elif not current_state and last_state:
                    logging.info("Liquidity capped again")
                
                last_state = current_state
                
                # Log current status
                status = "AVAILABLE" if current_state else "CAPPED"
                logging.info(f"Status: {status}")
                
                # Run daily cleanup of debug files (once per day)
                if (datetime.now() - last_cleanup).days >= 1:
                    await self._cleanup_debug_files()
                    last_cleanup = datetime.now()
                
            except Exception as e:
                consecutive_failures += 1
                logging.error(f"Monitor cycle failed ({consecutive_failures}): {e}")
                
                # Send failure alert after multiple failures
                if consecutive_failures >= 5:
                    await self.alert_manager.send_alert(
                        f"Monitor has failed {consecutive_failures} times. Last error: {e}",
                        "MONITOR_FAILURE"
                    )
            
            # Wait before next check
            await asyncio.sleep(self.config.check_interval)
    
    async def _cleanup_debug_files(self):
        """Run debug files cleanup in background"""
        try:
            # Import cleanup functionality
            from cleanup_debug_files import DebugFileManager
            
            logs_dir = Path("logs")
            if logs_dir.exists():
                manager = DebugFileManager(str(logs_dir))
                stats = manager.cleanup_files(dry_run=False)
                
                if stats['deleted'] > 0:
                    logging.info(f"Cleanup: Kept {stats['kept']}, deleted {stats['deleted']} debug files, freed {stats['size_freed'] / 1024 / 1024:.1f} MB")
                else:
                    logging.debug("Cleanup: No files needed deletion")
            
        except Exception as e:
            logging.error(f"Debug files cleanup failed: {e}")

# Configuration template
ALERT_CONFIG = {
    "email": {
        "from": "your-email@gmail.com",
        "to": ["447123456789@email.o2.co.uk", "backup@email.com"],
        "smtp_server": "smtp.gmail.com",
        "username": "your-email@gmail.com",
        "password": "your-app-password"
    },
    "discord_webhook": "https://discord.com/api/webhooks/YOUR_WEBHOOK_URL",
    "pushover": {
        "app_token": "YOUR_PUSHOVER_APP_TOKEN",
        "user_key": "YOUR_PUSHOVER_USER_KEY"
    }
}

async def main():
    """Main entry point"""
    # Load configuration from file
    try:
        with open('config.json', 'r') as f:
            config_data = json.load(f)
    except FileNotFoundError:
        print("config.json not found, using default config")
        config_data = {}
    
    # Extract alert config and monitor config
    alert_config = {
        'email': config_data.get('email'),
        'discord_webhook': config_data.get('discord_webhook'),
        'pushover': config_data.get('pushover')
    }
    
    # Create monitor config with settings from JSON
    config = MonitorConfig(
        use_selenium=config_data.get('use_selenium', True),
        check_interval=config_data.get('check_interval', 30),
        timeout=config_data.get('timeout', 15)
    )
    
    alert_manager = AlertManager(alert_config)
    
    # Create monitor
    monitor = MultiLayerMonitor(config, alert_manager)
    
    # Log configuration
    logging.info(f"Monitor config - Selenium: {config.use_selenium}, Interval: {config.check_interval}s")
    
    # Start monitoring directly (no startup notification)
    logging.info("Monitor initialized, starting monitoring loop...")
    await monitor.run_monitor()

if __name__ == "__main__":
    asyncio.run(main())
