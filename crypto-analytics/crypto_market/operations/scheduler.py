#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Operations Scheduler
APScheduler-based task scheduling for automated VCP scanning and reporting.

Features:
1. Periodic VCP scans (4h intervals)
2. Daily reports
3. Gate-aware operation policies
"""
import os
import sys
import logging
from datetime import datetime
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Add parent path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class OperationPolicy:
    """Gate-dependent operation policies"""
    
    POLICIES = {
        "GREEN": {
            "scan_enabled": True,
            "scan_interval_hours": 4,
            "notify_all_signals": True,
            "min_score_override": None,
        },
        "YELLOW": {
            "scan_enabled": True,
            "scan_interval_hours": 4,
            "notify_all_signals": False,  # Only high score
            "min_score_override": 60,
        },
        "RED": {
            "scan_enabled": False,  # Skip scanning
            "scan_interval_hours": 8,
            "notify_all_signals": False,
            "min_score_override": 75,
        },
    }
    
    @classmethod
    def get_policy(cls, gate: str) -> Dict:
        return cls.POLICIES.get(gate.upper(), cls.POLICIES["YELLOW"])


class Scheduler:
    """
    Operations scheduler using APScheduler.
    """
    
    def __init__(self):
        self._scheduler = None
        self._jobs = {}
        self._current_gate = "YELLOW"
    
    def _get_scheduler(self):
        """Lazy init scheduler"""
        if self._scheduler is None:
            try:
                from apscheduler.schedulers.background import BackgroundScheduler
                self._scheduler = BackgroundScheduler()
            except ImportError:
                logger.error("APScheduler not installed. Run: pip install apscheduler")
                return None
        return self._scheduler
    
    def set_gate(self, gate: str) -> None:
        """Update current gate status"""
        old_gate = self._current_gate
        self._current_gate = gate.upper()
        
        if old_gate != self._current_gate:
            logger.info(f"Gate changed: {old_gate} → {self._current_gate}")
            self._apply_policy()
    
    def _apply_policy(self) -> None:
        """Apply operation policy based on gate"""
        policy = OperationPolicy.get_policy(self._current_gate)
        
        if not policy['scan_enabled']:
            logger.info(f"Scanning disabled for gate={self._current_gate}")
    
    def add_job(
        self,
        func: Callable,
        job_id: str,
        trigger: str = 'cron',
        **kwargs
    ) -> bool:
        """Add a scheduled job"""
        scheduler = self._get_scheduler()
        if not scheduler:
            return False
        
        try:
            job = scheduler.add_job(func, trigger, id=job_id, **kwargs)
            self._jobs[job_id] = job
            logger.info(f"Added job: {job_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to add job {job_id}: {e}")
            return False
    
    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job"""
        scheduler = self._get_scheduler()
        if not scheduler:
            return False
        
        try:
            scheduler.remove_job(job_id)
            self._jobs.pop(job_id, None)
            return True
        except Exception as e:
            logger.error(f"Failed to remove job {job_id}: {e}")
            return False
    
    def start(self) -> None:
        """Start the scheduler"""
        scheduler = self._get_scheduler()
        if scheduler and not scheduler.running:
            scheduler.start()
            logger.info("Scheduler started")
    
    def stop(self) -> None:
        """Stop the scheduler"""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown()
            logger.info("Scheduler stopped")
    
    def list_jobs(self) -> list:
        """List all scheduled jobs"""
        scheduler = self._get_scheduler()
        if not scheduler:
            return []
        
        return [
            {
                'id': job.id,
                'next_run': str(job.next_run_time),
                'trigger': str(job.trigger)
            }
            for job in scheduler.get_jobs()
        ]


# Example job functions
def scan_vcp_job():
    """VCP scan job"""
    logger.info(f"[{datetime.now()}] Running VCP scan...")
    # Import and run scan
    try:
        from run_scan import main as run_scan
        # run_scan()
        logger.info("VCP scan completed")
    except Exception as e:
        logger.error(f"VCP scan failed: {e}")


def daily_report_job():
    """Daily report job"""
    logger.info(f"[{datetime.now()}] Generating daily report...")


def gate_check_job():
    """Check and update gate status"""
    logger.info(f"[{datetime.now()}] Checking gate status...")
    try:
        from market_gate import run_market_gate_sync
        result = run_market_gate_sync()
        logger.info(f"Gate status: {result.get('signal', 'UNKNOWN')}")
        return result
    except Exception as e:
        logger.error(f"Gate check failed: {e}")
        return None


if __name__ == "__main__":
    print("\n⏰ SCHEDULER TEST")
    print("=" * 50)
    
    scheduler = Scheduler()
    
    # Test policy
    print("\n📋 Operation Policies:")
    for gate in ["GREEN", "YELLOW", "RED"]:
        policy = OperationPolicy.get_policy(gate)
        print(f"  {gate}: scan={policy['scan_enabled']}, min_score={policy['min_score_override']}")
    
    # Test gate change
    print("\n🚦 Testing gate change:")
    scheduler.set_gate("GREEN")
    scheduler.set_gate("RED")
    
    print("\n✅ Scheduler test complete!")
    print("   Note: Full scheduler requires 'pip install apscheduler'")
