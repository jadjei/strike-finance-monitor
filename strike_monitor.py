#!/usr/bin/env python3
"""
Strike Finance Liquidity Monitor - Enhanced Sensitivity
Prioritizes avoiding false negatives over false positives
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
    check_interval: int = 60  # 60 seconds to avoid server spam
    timeout: int = 15
    max_retries: int = 3
    alert_cooldown: int = 180  # Reduced from 300 to 180 seconds (3 minutes)
    use_selenium: bool = True
    
    # More lenient detection - look for POSITIVE indicators of availability
    availability_indicators: List[str] = None
    capped_indicators: List[str] = None
    
    def __post_init__(self):
        if self.availability_indicators is None:
            # Look for signs that liquidity IS available
            self.availability_indicators = [
                "Provide Liquidity",  # Button text when available
                "Deposit",            # Deposit functionality
                "Available:",         # Available balance indicators
                "MAX",               # MAX button for deposits
                "Expected Receive",   # Shows when deposits are possible
                "Conversion Rate",    # Rate shown when deposits work
            ]
        
        if self.capped_indicators is None:
            # Only consider it capped if we see STRONG indicators
            self.capped_indicators = [
                "Liquidity Currently Capped",
                "cursor-not-allowed",
                "disabled",
                "bg-[#636363]",     # Gray background
                "Liquidity providers cannot",  # Explanatory text
            ]

class AlertManager:
    def __init__(self, config: Dict):
        self.config = config
        self.last_alerts = {}
        
    async def send_alert(self, message: str, alert_type: str = "LIQUIDITY_AVAILABLE"):
        """Send alerts through multiple channels"""
        now = datetime.now()
        
        # Reduced cooldown for availability alerts
        cooldown = 120 if alert_type == "LIQUIDITY_AVAILABLE" else 300
        
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
                error_message TEXT,
                availability_score INTEGER,
                capped_score INTEGER
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
                  availability_score: int = 0, capped_score: int = 0):
        """Log monitoring state to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO monitor_state 
            (timestamp, method, state_hash, raw_content, liquidity_available, 
             success, error_message, availability_score, capped_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (datetime.now(), method, state_hash, content, available, 
              success, error, availability_score, capped_score))
        
        conn.commit()
        conn.close()
    
    async def check_with_requests(self) -> Optional[bool]:
        """Method 1: HTTP requests with positive detection logic"""
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
                    
                    # Count positive indicators of availability
                    availability_count = sum(1 for indicator in self.config.availability_indicators 
                                           if indicator in content)
                    
                    # Count strong capped indicators
                    capped_count = sum(1 for indicator in self.config.capped_indicators 
                                     if indicator in content)
                    
                    # NEW LOGIC: Default to AVAILABLE unless strong capped indicators
                    # This reduces false negatives
                    if availability_count >= 3:  # Strong positive signals
                        available = True
                    elif capped_count >= 2:     # Strong capped signals
                        available = False
                    else:
                        # When unsure, lean toward available (anti-false-negative)
                        available = availability_count > capped_count
                    
                    state_hash = hashlib.md5(content.encode()).hexdigest()
                    
                    logging.info(f"HTTP check - Availability indicators: {availability_count}, "
                               f"Capped indicators: {capped_count}, Available: {available}")
                    
                    self.log_state("requests", state_hash, content[:1000], available, True,
                                 availability_score=availability_count, capped_score=capped_count)
                    return available
                    
        except Exception as e:
            self.log_state("requests", "", "", False, False, str(e))
            logging.error(f"Requests method failed: {e}")
            return None
    
    def check_with_selenium(self) -> Optional[bool]:
        """Method 2: Selenium with enhanced detection"""
        driver = None
        try:
            options = Options()
            options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')
            
            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(self.config.timeout)
            
            driver.get(self.config.url)
            
            # Wait for page to load completely
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "button"))
            )
            
            # Additional wait for dynamic content
            time.sleep(3)
            
            page_source = driver.page_source
            
            # Look for the "Provide Liquidity" button specifically
            try:
                provide_button = driver.find_element(By.XPATH, "//button[contains(text(), 'Provide Liquidity')]")
                # If button exists and is not disabled, liquidity is available
                available = not (provide_button.get_attribute("disabled") or 
                               "cursor-not-allowed" in provide_button.get_attribute("class") or "")
            except:
                # If "Provide Liquidity" button not found, check for other indicators
                availability_count = sum(1 for indicator in self.config.availability_indicators 
                                       if indicator in page_source)
                capped_count = sum(1 for indicator in self.config.capped_indicators 
                                 if indicator in page_source)
                
                # Same logic as HTTP method
                if availability_count >= 3:
                    available = True
                elif capped_count >= 2:
                    available = False
                else:
                    available = availability_count > capped_count
            
            state_hash = hashlib.md5(page_source.encode()).hexdigest()
            
            logging.info(f"Selenium check - Available: {available}")
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
        """Run multiple monitoring methods with availability bias"""
        results = []
        
        # Method 1: HTTP check
        result1 = await self.check_with_requests()
        if result1 is not None:
            results.append(("HTTP", result1))
        
        # Method 2: Selenium check
        if self.config.use_selenium:
            def selenium_wrapper():
                return self.check_with_selenium()
            
            loop = asyncio.get_event_loop()
            result2 = await loop.run_in_executor(None, selenium_wrapper)
            if result2 is not None:
                results.append(("Selenium", result2))
        
        if not results:
            logging.error("All monitoring methods failed")
            return False
        
        # NEW CONSENSUS LOGIC: Bias toward availability
        http_result = next((result for method, result in results if method == "HTTP"), None)
        selenium_result = next((result for method, result in results if method == "Selenium"), None)
        
        if http_result is not None and selenium_result is not None:
            # If either method says available, consider it available
            if http_result or selenium_result:
                if http_result != selenium_result:
                    logging.info(f"Methods disagree - HTTP: {http_result}, Selenium: {selenium_result} - CHOOSING AVAILABLE")
                    await self._save_debug_info(http_result, selenium_result)
                return True
            else:
                # Both say capped
                return False
        
        # Single method result
        return http_result if http_result is not None else selenium_result
    
    async def _save_debug_info(self, http_result: bool, selenium_result: bool):
        """Save debug information when methods disagree"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            logs_dir = Path("logs")
            logs_dir.mkdir(exist_ok=True)
            
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
            
            source_path = logs_dir / f"debug_source_{timestamp}.html"
            with open(source_path, 'w') as f:
                f.write(driver.page_source)
            
            logging.info(f"Debug files saved: {screenshot_path.name} and {source_path.name}")
            driver.quit()
            
        except Exception as e:
            logging.error(f"Failed to save debug info: {e}")
    
    async def run_monitor(self):
        """Main monitoring loop with enhanced alerting"""
        logging.info("Starting Strike Finance liquidity monitor (SENSITIVE MODE)...")
        
        last_state = None  # Start with None to force initial state detection
        consecutive_failures = 0
        last_cleanup = datetime.now()
        
        while True:
            try:
                current_state = await self.consensus_check()
                
                consecutive_failures = 0
                
                # Alert on state changes OR if we're uncertain and lean available
                if current_state and (last_state is False or last_state is None):
                    message = f"""
                    🚨 LIQUIDITY DEPLOYMENT DETECTED AS AVAILABLE! 🚨
                    
                    Strike Finance liquidity monitoring indicates deployment is possible.
                    Check the interface immediately: https://app.strikefinance.org/liquidity
                    
                    Detected at: {datetime.now().isoformat()}
                    Previous state: {last_state}
                    """
                    
                    await self.alert_manager.send_alert(message, "LIQUIDITY_AVAILABLE")
                    logging.info("🚨 LIQUIDITY AVAILABLE - Alerts sent!")
                
                elif not current_state and last_state is True:
                    logging.info("Liquidity appears capped again")
                
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
                
                if consecutive_failures >= 3:  # Reduced from 5 to 3
                    await self.alert_manager.send_alert(
                        f"Monitor has failed {consecutive_failures} times. Last error: {e}",
                        "MONITOR_FAILURE"
                    )
            
            await asyncio.sleep(self.config.check_interval)
    
    async def _cleanup_debug_files(self):
        """Run debug files cleanup"""
        try:
            from cleanup_debug_files import DebugFileManager
            
            logs_dir = Path("logs")
            if logs_dir.exists():
                manager = DebugFileManager(str(logs_dir))
                stats = manager.cleanup_files(dry_run=False)
                
                if stats['deleted'] > 0:
                    logging.info(f"Cleanup: Kept {stats['kept']}, deleted {stats['deleted']} debug files")
            
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
    
    # More sensitive configuration
    config = MonitorConfig(
        use_selenium=config_data.get('use_selenium', True),
        check_interval=config_data.get('check_interval', 60),  # Respectful 60s interval
        timeout=config_data.get('timeout', 15)
    )
    
    alert_manager = AlertManager(alert_config)
    monitor = MultiLayerMonitor(config, alert_manager)
    
    logging.info(f"SENSITIVE MODE - Selenium: {config.use_selenium}, Interval: {config.check_interval}s")
    logging.info("Bias: Prefer availability alerts over false negatives")
    
    await monitor.run_monitor()

if __name__ == "__main__":
    asyncio.run(main())
