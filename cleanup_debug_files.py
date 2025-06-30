#!/usr/bin/env python3
"""
Debug Files Cleanup Script for Strike Finance Monitor
Implements tiered retention policy for debug screenshots and HTML files
"""

import os
import time
import logging
import glob
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict
import re

class DebugFileManager:
    def __init__(self, logs_dir: str = "logs"):
        self.logs_dir = Path(logs_dir)
        self.retention_policy = {
            'keep_all_days': 3,      # Keep all files for 3 days
            'hourly_days': 14,       # Keep hourly files for 14 days total
            'daily_days': 365,       # Keep daily files for 1 year total
        }
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
    def parse_filename_timestamp(self, filename: str) -> datetime:
        """Parse timestamp from debug filename like debug_screenshot_20250627_013045.png"""
        match = re.search(r'debug_\w+_(\d{8})_(\d{6})', filename)
        if match:
            date_str, time_str = match.groups()
            return datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
        return None
        
    def get_debug_files(self) -> List[Dict]:
        """Get all debug files with metadata"""
        files = []
        
        for pattern in ['debug_screenshot_*.png', 'debug_source_*.html']:
            for file_path in self.logs_dir.glob(pattern):
                try:
                    timestamp = self.parse_filename_timestamp(file_path.name)
                    if timestamp:
                        files.append({
                            'path': file_path,
                            'name': file_path.name,
                            'timestamp': timestamp,
                            'age_hours': (datetime.now() - timestamp).total_seconds() / 3600,
                            'age_days': (datetime.now() - timestamp).days,
                            'size': file_path.stat().st_size,
                            'type': 'screenshot' if file_path.suffix == '.png' else 'html'
                        })
                except Exception as e:
                    self.logger.warning(f"Could not process file {file_path}: {e}")
                    
        # Sort by timestamp
        files.sort(key=lambda x: x['timestamp'])
        return files
        
    def group_files_by_time_period(self, files: List[Dict]) -> Dict:
        """Group files by retention periods"""
        now = datetime.now()
        groups = {
            'keep_all': [],        # 0-3 days: keep all
            'hourly_zone': [],     # 3-14 days: keep hourly
            'daily_zone': [],      # 14-365 days: keep daily  
            'weekly_zone': [],     # 365+ days: keep weekly (for deletion)
            'expired': []          # >1 year: delete
        }
        
        for file_info in files:
            age_days = file_info['age_days']
            
            if age_days <= self.retention_policy['keep_all_days']:
                groups['keep_all'].append(file_info)
            elif age_days <= self.retention_policy['hourly_days']:
                groups['hourly_zone'].append(file_info)
            elif age_days <= self.retention_policy['daily_days']:
                groups['daily_zone'].append(file_info)
            else:
                groups['expired'].append(file_info)
                
        return groups
        
    def select_representative_files(self, files: List[Dict], interval_hours: int) -> List[Dict]:
        """Select representative files based on time interval"""
        if not files:
            return []
            
        selected = []
        last_selected_time = None
        
        for file_info in files:
            current_time = file_info['timestamp']
            
            if (last_selected_time is None or 
                (current_time - last_selected_time).total_seconds() >= interval_hours * 3600):
                selected.append(file_info)
                last_selected_time = current_time
                
        return selected
        
    def cleanup_files(self, dry_run: bool = False) -> Dict:
        """Execute cleanup with retention policy"""
        files = self.get_debug_files()
        
        if not files:
            self.logger.info("No debug files found")
            return {'kept': 0, 'deleted': 0, 'errors': 0}
            
        groups = self.group_files_by_time_period(files)
        
        stats = {'kept': 0, 'deleted': 0, 'errors': 0, 'size_freed': 0}
        
        self.logger.info(f"Processing {len(files)} debug files...")
        
        # Keep all files in keep_all zone (0-3 days)
        keep_all_count = len(groups['keep_all'])
        stats['kept'] += keep_all_count
        if keep_all_count > 0:
            self.logger.info(f"Keeping all {keep_all_count} files from last 3 days")
            
        # Process hourly zone (3-14 days)
        if groups['hourly_zone']:
            hourly_selected = self.select_representative_files(groups['hourly_zone'], interval_hours=1)
            hourly_to_delete = [f for f in groups['hourly_zone'] if f not in hourly_selected]
            
            stats['kept'] += len(hourly_selected)
            self.logger.info(f"Hourly zone: keeping {len(hourly_selected)}, deleting {len(hourly_to_delete)} files")
            
            for file_info in hourly_to_delete:
                if self._delete_file(file_info, dry_run):
                    stats['deleted'] += 1
                    stats['size_freed'] += file_info['size']
                else:
                    stats['errors'] += 1
                    
        # Process daily zone (14-365 days)  
        if groups['daily_zone']:
            daily_selected = self.select_representative_files(groups['daily_zone'], interval_hours=24)
            daily_to_delete = [f for f in groups['daily_zone'] if f not in daily_selected]
            
            stats['kept'] += len(daily_selected)
            self.logger.info(f"Daily zone: keeping {len(daily_selected)}, deleting {len(daily_to_delete)} files")
            
            for file_info in daily_to_delete:
                if self._delete_file(file_info, dry_run):
                    stats['deleted'] += 1
                    stats['size_freed'] += file_info['size']
                else:
                    stats['errors'] += 1
                    
        # Delete all expired files (>1 year)
        if groups['expired']:
            self.logger.info(f"Deleting {len(groups['expired'])} expired files (>1 year old)")
            
            for file_info in groups['expired']:
                if self._delete_file(file_info, dry_run):
                    stats['deleted'] += 1
                    stats['size_freed'] += file_info['size']
                else:
                    stats['errors'] += 1
                    
        return stats
        
    def _delete_file(self, file_info: Dict, dry_run: bool = False) -> bool:
        """Delete a single file"""
        try:
            if dry_run:
                self.logger.info(f"[DRY RUN] Would delete: {file_info['name']}")
                return True
            else:
                file_info['path'].unlink()
                self.logger.debug(f"Deleted: {file_info['name']}")
                return True
        except Exception as e:
            self.logger.error(f"Failed to delete {file_info['name']}: {e}")
            return False
            
    def get_retention_summary(self) -> str:
        """Get human-readable retention policy summary"""
        return f"""
Debug Files Retention Policy:
• 0-{self.retention_policy['keep_all_days']} days: Keep ALL screenshots
• {self.retention_policy['keep_all_days']}-{self.retention_policy['hourly_days']} days: Keep HOURLY screenshots  
• {self.retention_policy['hourly_days']}-{self.retention_policy['daily_days']} days: Keep DAILY screenshots
• >{self.retention_policy['daily_days']} days: DELETE all files
        """.strip()
        
    def show_status(self) -> None:
        """Show current debug files status"""
        files = self.get_debug_files()
        
        if not files:
            print("No debug files found")
            return
            
        groups = self.group_files_by_time_period(files)
        
        total_size = sum(f['size'] for f in files)
        
        print(f"\nDebug Files Status:")
        print(f"Total files: {len(files)} ({total_size / 1024 / 1024:.1f} MB)")
        print(f"")
        print(f"By retention zone:")
        print(f"• Keep all (0-3 days): {len(groups['keep_all'])} files")
        print(f"• Hourly zone (3-14 days): {len(groups['hourly_zone'])} files")  
        print(f"• Daily zone (14-365 days): {len(groups['daily_zone'])} files")
        print(f"• Expired (>1 year): {len(groups['expired'])} files")
        
        if files:
            oldest = min(files, key=lambda x: x['timestamp'])
            newest = max(files, key=lambda x: x['timestamp'])
            print(f"")
            print(f"Date range: {oldest['timestamp'].strftime('%Y-%m-%d')} to {newest['timestamp'].strftime('%Y-%m-%d')}")

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Cleanup debug files with retention policy')
    parser.add_argument('--logs-dir', default='logs', help='Directory containing debug files')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted without deleting')
    parser.add_argument('--status', action='store_true', help='Show current debug files status')
    parser.add_argument('--quiet', action='store_true', help='Reduce logging output')
    
    args = parser.parse_args()
    
    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)
    
    manager = DebugFileManager(args.logs_dir)
    
    if args.status:
        print(manager.get_retention_summary())
        manager.show_status()
        return
        
    print(manager.get_retention_summary())
    print()
    
    stats = manager.cleanup_files(dry_run=args.dry_run)
    
    action = "Would delete" if args.dry_run else "Deleted"
    print(f"\nCleanup Summary:")
    print(f"• Kept: {stats['kept']} files")
    print(f"• {action}: {stats['deleted']} files")
    print(f"• Errors: {stats['errors']} files")
    if not args.dry_run and stats['size_freed'] > 0:
        print(f"• Space freed: {stats['size_freed'] / 1024 / 1024:.1f} MB")
    
    if args.dry_run and stats['deleted'] > 0:
        print(f"\nRun without --dry-run to actually delete files")

if __name__ == '__main__':
    main()
