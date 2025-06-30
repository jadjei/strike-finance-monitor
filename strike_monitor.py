#!/usr/bin/env python3
"""
Enhanced Strike Finance Liquidity Monitor
Optimized to be more afraid of missing changes than false positives
"""

import requests
import time
import json
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
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
    check_interval: int = 60
    timeout: int = 15  # Slightly reduced timeout for faster cycles
    max_retries: int = 2  # Fewer retries to cycle faster
    alert_cooldown: int = 300
    use_selenium: bool = True
    
    # More aggressive detection thresholds
    uncertainty_threshold: float = 0.3  # If >30% uncertainty, assume available
    
    # Target elements to monitor (expanded list)
    button_selectors: List[str] = None
    disabled_text: str = "Liquidity Currently Capped"
    
    def __post_init__(self):
        if self.button_selectors is None:
            self.button_selectors = [
                'button:contains("Liquidity Currently Capped")',
                'button[disabled*=""]',
                '.bg-\\[\\#636363\\]',
                'button.cursor-not-allowed',
                'button[aria-disabled="true"]',
                '.opacity-50'
            ]

class AlertManager:
    def __init__(self, config: Dict):
        self.config = config
        self.last_alerts = {}
        
    async def send_alert(self, message: str, alert_type: str = "LIQUIDITY_AVAILABLE", confidence: str = "HIGH"):
        """Send alerts through multiple channels with confidence level"""
        now = datetime.now()
        
        # Reduced cooldown for uncertain alerts
        cooldown_seconds = 120 if confidence == "UNCERTAIN" else 180
        
        # Cooldown check
        if alert_type in self.last_alerts:
            if now - self.last_alerts[alert_type] < timedelta(seconds=cooldown_seconds):
                return
        
        self.last_alerts[alert_type] = now
        
        # Send through all configured channels
        tasks = []
        
        if self.config.get('email'):
            tasks.append(self._send_email(message, confidence))
        
        if self.config.get('discord_webhook'):
            tasks.append(self._send_discord(message, confidence))
        
        if self.config.get('pushover'):
            tasks.append(self._send_pushover(message, confidence))
        
        # Execute all alerts concurrently
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _send_email(self, message: str, confidence: str):
        """Send email alert with confidence indicator"""
        try:
            msg = MIMEMultipart()
            msg['From'] = self.config['email']['from']
            msg['To'] = ', '.join(self.config['email']['to'])
            
            confidence_prefix = "🔍 POSSIBLE" if confidence == "UNCERTAIN" else "🚨"
            msg['Subject'] = f"{confidence_prefix} Strike Finance Liquidity Alert"
            
            body = f"""
            LIQUIDITY DEPLOYMENT DETECTED!
            Confidence: {confidence}
            
            {message}
            
            URL: https://app.strikefinance.org/liquidity
            Time: {datetime.now().isoformat()}
            
            Note: This monitor is tuned to avoid missing opportunities.
            """
            
            msg.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP(self.config['email']['smtp_server'], 587)
            server.starttls()
            server.login(self.config['email']['username'], self.config['email']['password'])
            server.send_message(msg)
            server.quit()
            
        except Exception as e:
            logging.error(f"Email alert failed: {e}")
    
    async def _send_discord(self, message: str, confidence: str):
        """Send Discord webhook alert with confidence level"""
        try:
            async with aiohttp.ClientSession() as session:
                color = 16776960 if confidence == "UNCERTAIN" else 65280  # Yellow or Green
                emoji = "🔍" if confidence == "UNCERTAIN" else "🚨"
                
                payload = {
                    "embeds": [{
                        "title": f"{emoji} Strike Finance Liquidity Alert",
                        "description": f"**Confidence: {confidence}**\n\n{message}",
                        "color": color,
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
    
    async def _send_pushover(self, message: str, confidence: str):
        """Send Pushover notification with appropriate priority"""
        try:
            async with aiohttp.ClientSession() as session:
                # Lower priority for uncertain alerts
                priority = 1 if confidence == "UNCERTAIN" else 2
                title_prefix = "POSSIBLE" if confidence == "UNCERTAIN" else "CONFIRMED"
                
                payload = {
                    "token": self.config['pushover']['app_token'],
                    "user": self.config['pushover']['user_key'],
                    "message": f"{message}\n\nConfidence: {confidence}",
                    "title": f"{title_prefix} Strike Alert",
                    "priority": priority,
                    "url": "https://app.strikefinance.org/liquidity"
                }
                
                if priority == 2:  # Emergency for high confidence
                    payload.update({"retry": 30, "expire": 3600})
                
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
        
        # State tracking for enhanced change detection
        self.historical_states = []
        self.max_history = 10
        
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
                confidence_score REAL,
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
                  available: bool, confidence: float, success: bool, error: str = None):
        """Log monitoring state to database with confidence score"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO monitor_state 
            (timestamp, method, state_hash, raw_content, liquidity_available, confidence_score, success, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (datetime.now(), method, state_hash, content, available, confidence, success, error))
        
        conn.commit()
        conn.close()
    
    def calculate_confidence(self, capped_indicators: List[bool], method: str) -> float:
        """Calculate confidence score for the detection"""
        if method == "requests":
            # For HTTP method, high confidence if all indicators agree
            if all(capped_indicators) or not any(capped_indicators):
                return 0.95  # High confidence
            else:
                return 0.4  # Mixed signals = low confidence
        else:
            # Selenium generally less reliable for this site
            return 0.7
    
    async def check_with_requests(self) -> Tuple[Optional[bool], float]:
        """Method 1: HTTP requests with enhanced sensitivity"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
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
                    
                    # Expanded list of capped indicators (more sensitive)
                    capped_indicators = [
                        "Liquidity Currently Capped" in content,
                        "cursor-not-allowed" in content,
                        'disabled=""' in content or 'disabled="disabled"' in content,
                        "bg-[#636363]" in content,
                        "text-[#a0a0a0]" in content,
                        "opacity-50" in content,
                        'aria-disabled="true"' in content,
                        "pointer-events-none" in content
                    ]
                    
                    confidence = self.calculate_confidence(capped_indicators, "requests")
                    
                    # CHANGED: More aggressive logic - if confidence is low, assume available
                    capped_count = sum(capped_indicators)
                    total_indicators = len(capped_indicators)
                    
                    if confidence < 0.5:
                        # Low confidence = assume available (err on side of not missing opportunities)
                        available = True
                        logging.warning(f"HTTP check - LOW CONFIDENCE ({confidence:.2f}), assuming AVAILABLE")
                    else:
                        # High confidence = trust the indicators
                        available = capped_count < (total_indicators * 0.5)  # If <50% indicators show capped, assume available
                    
                    state_hash = hashlib.md5(content.encode()).hexdigest()
                    
                    logging.info(f"HTTP check - Capped indicators: {capped_count}/{total_indicators}, Confidence: {confidence:.2f}, Available: {available}")
                    self.log_state("requests", state_hash, content[:1000], available, confidence, True)
                    return available, confidence
                    
        except Exception as e:
            self.log_state("requests", "", "", False, 0.0, False, str(e))
            logging.error(f"Requests method failed: {e}")
            return None, 0.0
    
    def check_with_selenium(self) -> Tuple[Optional[bool], float]:
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
            
            # Wait for page to load
            WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.TAG_NAME, "button"))
            )
            
            # Multiple approaches to detect state
            detection_methods = []
            
            # Method 1: Look for disabled buttons
            try:
                disabled_buttons = driver.find_elements(
                    By.CSS_SELECTOR, 
                    'button[disabled], button.cursor-not-allowed, button[aria-disabled="true"]'
                )
                
                has_capped_button = any(
                    self.config.disabled_text in btn.text 
                    for btn in disabled_buttons
                )
                detection_methods.append(has_capped_button)
                
            except Exception as e:
                logging.debug(f"Selenium disabled button check failed: {e}")
                detection_methods.append(False)  # Assume available if check fails
            
            # Method 2: Look for specific text patterns
            try:
                page_text = driver.find_element(By.TAG_NAME, "body").text
                has_capped_text = "Liquidity Currently Capped" in page_text
                detection_methods.append(has_capped_text)
                
            except Exception as e:
                logging.debug(f"Selenium text check failed: {e}")
                detection_methods.append(False)
            
            # Method 3: Check button classes/styles
            try:
                buttons = driver.find_elements(By.TAG_NAME, "button")
                has_disabled_styles = any(
                    "cursor-not-allowed" in btn.get_attribute("class") or
                    "opacity-50" in btn.get_attribute("class") or
                    btn.get_attribute("disabled") == "true"
                    for btn in buttons
                )
                detection_methods.append(has_disabled_styles)
                
            except Exception as e:
                logging.debug(f"Selenium style check failed: {e}")
                detection_methods.append(False)
            
            # Calculate result - if any method fails to detect capping, assume available
            capped_votes = sum(detection_methods)
            total_methods = len(detection_methods)
            
            # CHANGED: If <75% of methods agree it's capped, assume available
            is_capped = capped_votes >= (total_methods * 0.75)
            available = not is_capped
            
            confidence = 0.8 if capped_votes in [0, total_methods] else 0.4  # High confidence if all agree
            
            page_source = driver.page_source
            state_hash = hashlib.md5(page_source.encode()).hexdigest()
            
            logging.info(f"Selenium check - Capped votes: {capped_votes}/{total_methods}, Confidence: {confidence:.2f}, Available: {available}")
            self.log_state("selenium", state_hash, page_source[:1000], available, confidence, True)
            return available, confidence
            
        except Exception as e:
            self.log_state("selenium", "", "", False, 0.0, False, str(e))
            logging.error(f"Selenium method failed: {e}")
            return None, 0.0
            
        finally:
            if driver:
                driver.quit()
    
    def analyze_trend(self, current_state: bool) -> str:
        """Analyze recent trends to improve confidence"""
        self.historical_states.append(current_state)
        if len(self.historical_states) > self.max_history:
            self.historical_states.pop(0)
        
        if len(self.historical_states) < 3:
            return "INSUFFICIENT_DATA"
        
        recent_states = self.historical_states[-3:]
        
        if all(recent_states):
            return "CONSISTENTLY_AVAILABLE"
        elif not any(recent_states):
            return "CONSISTENTLY_CAPPED"
        else:
            return "FLUCTUATING"
    
    async def consensus_check(self) -> Tuple[bool, str]:
        """Enhanced consensus with bias toward detecting availability"""
        results = []
        
        # Method 1: HTTP (primary)
        result1, conf1 = await self.check_with_requests()
        if result1 is not None:
            results.append(("HTTP", result1, conf1))
        
        # Method 2: Selenium (if enabled)
        if self.config.use_selenium:
            def selenium_wrapper():
                return self.check_with_selenium()
            
            loop = asyncio.get_event_loop()
            result2, conf2 = await loop.run_in_executor(None, selenium_wrapper)
            if result2 is not None:
                results.append(("Selenium", result2, conf2))
        
        if not results:
            logging.error("All monitoring methods failed")
            return False, "ERROR"
        
        # CHANGED: Enhanced consensus logic biased toward availability
        available_votes = sum(1 for _, available, _ in results if available)
        total_votes = len(results)
        
        # Calculate weighted confidence
        total_confidence = sum(conf for _, _, conf in results)
        avg_confidence = total_confidence / len(results)
        
        # Decision logic - biased toward availability
        if available_votes >= (total_votes * 0.5):
            # If 50%+ vote available, go with available
            final_state = True
            confidence_level = "HIGH" if avg_confidence > 0.7 else "UNCERTAIN"
        else:
            # Only declare capped if strong consensus
            if avg_confidence > 0.8 and available_votes == 0:
                final_state = False
                confidence_level = "HIGH"
            else:
                # When in doubt, assume available
                final_state = True
                confidence_level = "UNCERTAIN"
                logging.warning("Uncertain state - defaulting to AVAILABLE to avoid missing opportunities")
        
        # Log method disagreements
        if len(results) > 1 and len(set(result for _, result, _ in results)) > 1:
            method_results = [(method, result) for method, result, _ in results]
            logging.warning(f"Methods disagree: {method_results} - Final: {final_state} ({confidence_level})")
            await self._save_debug_info(results)
        
        return final_state, confidence_level
    
    async def _save_debug_info(self, results: List[Tuple[str, bool, float]]):
        """Save debug information when methods disagree"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            logs_dir = Path("logs")
            logs_dir.mkdir(exist_ok=True)
            
            # Save detailed analysis
            analysis_path = logs_dir / f"debug_analysis_{timestamp}.txt"
            with open(analysis_path, 'w') as f:
                f.write(f"Method Disagreement Analysis - {datetime.now()}\n")
                f.write("=" * 50 + "\n\n")
                for method, result, confidence in results:
                    f.write(f"{method}: {result} (confidence: {confidence:.2f})\n")
                f.write(f"\nHistorical states: {self.historical_states}\n")
            
            # Save screenshot for visual confirmation
            options = Options()
            options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--window-size=1920,1080')
            
            driver = webdriver.Chrome(options=options)
            driver.get(self.config.url)
            time.sleep(3)
            
            screenshot_path = logs_dir / f"debug_screenshot_{timestamp}.png"
            driver.save_screenshot(str(screenshot_path))
            
            source_path = logs_dir / f"debug_source_{timestamp}.html"
            with open(source_path, 'w') as f:
                f.write(driver.page_source)
            
            logging.info(f"Debug files saved: {analysis_path.name}, {screenshot_path.name}, {source_path.name}")
            driver.quit()
            
        except Exception as e:
            logging.error(f"Failed to save debug info: {e}")
    
    async def run_monitor(self):
        """Main monitoring loop with enhanced change detection"""
        logging.info("Starting enhanced Strike Finance liquidity monitor...")
        logging.info("Configuration: Biased toward detecting availability (fewer missed opportunities)")
        
        last_state = False
        last_confidence = "HIGH"
        consecutive_failures = 0
        last_cleanup = datetime.now()
        
        while True:
            try:
                current_state, confidence_level = await self.consensus_check()
                
                # Reset failure counter on success
                consecutive_failures = 0
                
                # Analyze trends
                trend = self.analyze_trend(current_state)
                
                # Enhanced state change detection
                state_changed = current_state != last_state
                confidence_changed = confidence_level != last_confidence
                
                if state_changed and current_state:
                    # Liquidity became available
                    message = f"""
                    🚨 LIQUIDITY DEPLOYMENT DETECTED! 🚨
                    
                    The Strike Finance liquidity appears to be available for deployment.
                    Confidence Level: {confidence_level}
                    Trend: {trend}
                    
                    Detected at: {datetime.now().isoformat()}
                    
                    Please verify manually before deploying capital.
                    """
                    
                    await self.alert_manager.send_alert(message, "LIQUIDITY_AVAILABLE", confidence_level)
                    logging.info(f"🚨 LIQUIDITY AVAILABLE ({confidence_level}) - Alerts sent!")
                
                elif current_state and confidence_changed and confidence_level == "UNCERTAIN":
                    # Send uncertain alert if we're unsure but think it might be available
                    message = f"""
                    🔍 POSSIBLE LIQUIDITY OPPORTUNITY
                    
                    Detection methods are uncertain, but liquidity may be available.
                    This alert is sent to avoid missing opportunities.
                    
                    Trend: {trend}
                    Time: {datetime.now().isoformat()}
                    
                    Please check manually: https://app.strikefinance.org/liquidity
                    """
                    
                    await self.alert_manager.send_alert(message, "UNCERTAIN_AVAILABLE", confidence_level)
                    logging.info(f"🔍 UNCERTAIN AVAILABILITY - Precautionary alert sent!")
                
                elif not current_state and last_state:
                    logging.info(f"Liquidity capped again ({confidence_level})")
                
                # Update state tracking
                last_state = current_state
                last_confidence = confidence_level
                
                # Enhanced status logging
                status = "AVAILABLE" if current_state else "CAPPED"
                logging.info(f"Status: {status} ({confidence_level}) | Trend: {trend}")
                
                # Daily cleanup
                if (datetime.now() - last_cleanup).days >= 1:
                    await self._cleanup_debug_files()
                    last_cleanup = datetime.now()
                
            except Exception as e:
                consecutive_failures += 1
                logging.error(f"Monitor cycle failed ({consecutive_failures}): {e}")
                
                # Send failure alert after fewer failures (more sensitive)
                if consecutive_failures >= 3:
                    await self.alert_manager.send_alert(
                        f"Monitor has failed {consecutive_failures} times. Last error: {e}",
                        "MONITOR_FAILURE"
                    )
            
            # Wait before next check
            await asyncio.sleep(self.config.check_interval)
    
    async def _cleanup_debug_files(self):
        """Run debug files cleanup in background"""
        try:
            from cleanup_debug_files import DebugFileManager
            
            logs_dir = Path("logs")
            if logs_dir.exists():
                manager = DebugFileManager(str(logs_dir))
                stats = manager.cleanup_files(dry_run=False)
                
                if stats['deleted'] > 0:
                    logging.info(f"Cleanup: Kept {stats['kept']}, deleted {stats['deleted']} debug files, freed {stats['size_freed'] / 1024 / 1024:.1f} MB")
            
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
    
    # Extract alert config
    alert_config = {
        'email': config_data.get('email'),
        'discord_webhook': config_data.get('discord_webhook'),
        'pushover': config_data.get('pushover')
    }
    
    # Create enhanced monitor config
    config = MonitorConfig(
        use_selenium=config_data.get('use_selenium', True),
        check_interval=config_data.get('check_interval', 15),  # More frequent by default
        timeout=config_data.get('timeout', 12),
        alert_cooldown=config_data.get('alert_cooldown', 180),  # Shorter cooldown
        uncertainty_threshold=config_data.get('uncertainty_threshold', 0.3)
    )
    
    alert_manager = AlertManager(alert_config)
    monitor = MultiLayerMonitor(config, alert_manager)
    
    # Log enhanced configuration
    logging.info("=" * 60)
    logging.info("ENHANCED STRIKE FINANCE MONITOR")
    logging.info("Configuration: BIASED TOWARD DETECTING AVAILABILITY")
    logging.info(f"• Check interval: {config.check_interval}s (frequent)")
    logging.info(f"• Alert cooldown: {config.alert_cooldown}s (short)")
    logging.info(f"• Uncertainty threshold: {config.uncertainty_threshold}")
    logging.info(f"• Selenium enabled: {config.use_selenium}")
    logging.info("• Logic: When in doubt, assume AVAILABLE")
    logging.info("=" * 60)
    
    await monitor.run_monitor()

if __name__ == "__main__":
    asyncio.run(main())
