#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Production Utilities
Core stability utilities for enterprise-grade operations.

Features:
1. FileLock - 동시 실행 방지
2. Idempotency - 재실행 안전
3. Structured Logging - JSON 로그
4. Config Schema - Pydantic 검증
5. Retry with Backoff - 실패 복구
6. Notification Dedup - 알림 중복 방지
"""
import os
import sys
import json
import time
import hashlib
import logging
import tempfile

try:
    import fcntl
except ImportError:
    fcntl = None
    import msvcrt
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Callable
from functools import wraps
import pytz

# Timezone
KST = pytz.timezone('Asia/Seoul')


# =============================================================================
# 1. FILE LOCK (동시 실행 방지)
# =============================================================================

class FileLock:
    """
    File-based lock to prevent concurrent execution.
    Stale locks (>10 min) are automatically released.
    """
    
    def __init__(self, lock_file: str = None, stale_timeout: int = 600):
        self.lock_file = lock_file or os.path.join(tempfile.gettempdir(), "crypto_orchestrator.lock")
        self.stale_timeout = stale_timeout
        self._fd = None
    
    def acquire(self) -> bool:
        """Acquire lock, return True if successful"""
        # Check for stale lock
        if os.path.exists(self.lock_file):
            try:
                mtime = os.path.getmtime(self.lock_file)
                if time.time() - mtime > self.stale_timeout:
                    os.remove(self.lock_file)
                    logging.warning(f"Removed stale lock file: {self.lock_file}")
            except Exception:
                pass
        
        try:
            self._fd = open(self.lock_file, 'w', encoding='utf-8')
            if fcntl:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                msvcrt.locking(self._fd.fileno(), msvcrt.LK_NBLCK, 1)
            self._fd.write(f"{os.getpid()}\n{datetime.now(KST).isoformat()}")
            self._fd.flush()
            return True
        except (IOError, OSError):
            if self._fd:
                self._fd.close()
                self._fd = None
            return False
    
    def release(self) -> None:
        """Release the lock"""
        if self._fd:
            try:
                if fcntl:
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
                else:
                    self._fd.seek(0)
                    msvcrt.locking(self._fd.fileno(), msvcrt.LK_UNLCK, 1)
                self._fd.close()
            except Exception:
                pass
            finally:
                self._fd = None
        
        try:
            os.remove(self.lock_file)
        except Exception:
            pass
    
    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("Could not acquire lock - another instance running?")
        return self
    
    def __exit__(self, *args):
        self.release()


# =============================================================================
# 2. IDEMPOTENCY (재실행 안전)
# =============================================================================

class IdempotencyStore:
    """
    Track processed items to ensure idempotent execution.
    Uses a JSON file per task type.
    """
    
    def __init__(self, store_dir: str = None):
        self.store_dir = store_dir or os.path.join(
            os.path.dirname(__file__), 'processed'
        )
        os.makedirs(self.store_dir, exist_ok=True)
    
    def _get_store_path(self, task_name: str) -> str:
        return os.path.join(self.store_dir, f"{task_name}.json")
    
    def _load_store(self, task_name: str) -> Dict:
        path = self._get_store_path(task_name)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def _save_store(self, task_name: str, data: Dict) -> None:
        path = self._get_store_path(task_name)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
    
    def is_processed(self, task_name: str, key: str) -> bool:
        """Check if an item was already processed"""
        store = self._load_store(task_name)
        return key in store
    
    def mark_processed(self, task_name: str, key: str, result: Any = None) -> None:
        """Mark an item as processed"""
        store = self._load_store(task_name)
        store[key] = {
            'processed_at': datetime.now(KST).isoformat(),
            'result': result
        }
        self._save_store(task_name, store)
    
    def get_daily_key(self, suffix: str = "") -> str:
        """Get today's key (KST)"""
        date = datetime.now(KST).strftime('%Y-%m-%d')
        return f"{date}_{suffix}" if suffix else date
    
    def cleanup_old(self, task_name: str, days: int = 7) -> int:
        """Remove entries older than N days"""
        store = self._load_store(task_name)
        cutoff = datetime.now(KST) - timedelta(days=days)
        
        original_count = len(store)
        store = {
            k: v for k, v in store.items()
            if datetime.fromisoformat(v['processed_at'].replace('Z', '+00:00')) > cutoff
        }
        
        self._save_store(task_name, store)
        return original_count - len(store)


# =============================================================================
# 3. STRUCTURED LOGGING (JSON 로그)
# =============================================================================

class StructuredLogger:
    """
    JSON structured logging with run_id tagging.
    """
    
    def __init__(self, name: str, run_id: str = None, log_file: str = None):
        self.name = name
        self.run_id = run_id or self._generate_run_id()
        self.log_file = log_file
        
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        
        # Add file handler if specified
        if log_file:
            handler = logging.FileHandler(log_file)
            handler.setFormatter(logging.Formatter('%(message)s'))
            self.logger.addHandler(handler)
    
    def _generate_run_id(self) -> str:
        import uuid
        return str(uuid.uuid4())[:8]
    
    def _format_message(self, level: str, message: str, **extra) -> str:
        log_entry = {
            'timestamp': datetime.now(KST).isoformat(),
            'level': level,
            'run_id': self.run_id,
            'logger': self.name,
            'message': message,
            **extra
        }
        return json.dumps(log_entry, ensure_ascii=False, default=str)
    
    def info(self, message: str, **extra):
        self.logger.info(self._format_message('INFO', message, **extra))
    
    def warning(self, message: str, **extra):
        self.logger.warning(self._format_message('WARNING', message, **extra))
    
    def error(self, message: str, **extra):
        self.logger.error(self._format_message('ERROR', message, **extra))
    
    def debug(self, message: str, **extra):
        self.logger.debug(self._format_message('DEBUG', message, **extra))


# =============================================================================
# 4. CONFIG SCHEMA (Pydantic 검증)
# =============================================================================

try:
    from pydantic import BaseModel, Field, validator
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False
    BaseModel = object


if PYDANTIC_AVAILABLE:
    class OrchestratorConfig(BaseModel):
        """Configuration with validation"""
        
        # API Keys (required)
        google_api_key: str = Field(..., min_length=10)
        
        # Optional keys
        telegram_bot_token: Optional[str] = None
        telegram_chat_id: Optional[str] = None
        
        # Orchestrator settings
        check_interval_seconds: int = Field(default=120, ge=30, le=3600)
        timezone: str = Field(default="Asia/Seoul")
        
        # Risk limits
        max_daily_loss_pct: float = Field(default=3.0, ge=0, le=100)
        max_positions: int = Field(default=5, ge=1, le=20)
        
        @classmethod
        def from_env(cls) -> "OrchestratorConfig":
            """Load from environment variables"""
            from dotenv import load_dotenv
            load_dotenv()
            
            return cls(
                google_api_key=os.environ.get('GOOGLE_API_KEY', ''),
                telegram_bot_token=os.environ.get('TELEGRAM_BOT_TOKEN'),
                telegram_chat_id=os.environ.get('TELEGRAM_CHAT_ID'),
            )
else:
    @dataclass
    class OrchestratorConfig:
        """Fallback config without Pydantic"""
        google_api_key: str = ""
        telegram_bot_token: str = ""
        telegram_chat_id: str = ""
        check_interval_seconds: int = 120
        timezone: str = "Asia/Seoul"
        max_daily_loss_pct: float = 3.0
        max_positions: int = 5


# =============================================================================
# 5. RETRY WITH BACKOFF
# =============================================================================

def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential: bool = True,
    exceptions: tuple = (Exception,)
):
    """
    Decorator for retry with exponential backoff.
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt < max_attempts - 1:
                        if exponential:
                            delay = min(base_delay * (2 ** attempt), max_delay)
                        else:
                            delay = base_delay
                        
                        logging.warning(
                            f"Retry {attempt + 1}/{max_attempts} for {func.__name__} "
                            f"after {delay:.1f}s: {e}"
                        )
                        time.sleep(delay)
            
            raise last_exception
        
        return wrapper
    return decorator


# =============================================================================
# 6. NOTIFICATION DEDUP (알림 중복 방지)
# =============================================================================

class NotificationDedup:
    """
    Prevent duplicate notifications within cooldown period.
    """
    
    def __init__(self, cooldown_hours: float = 4.0, store_path: str = None):
        self.cooldown_hours = cooldown_hours
        self.store_path = store_path or os.path.join(
            os.path.dirname(__file__), 'notification_history.json'
        )
    
    def _load_history(self) -> Dict:
        if os.path.exists(self.store_path):
            with open(self.store_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def _save_history(self, history: Dict) -> None:
        with open(self.store_path, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2)
    
    def _make_key(self, symbol: str, notification_type: str) -> str:
        return f"{symbol}_{notification_type}"
    
    def should_notify(self, symbol: str, notification_type: str) -> bool:
        """Check if notification should be sent (not in cooldown)"""
        history = self._load_history()
        key = self._make_key(symbol, notification_type)
        
        if key not in history:
            return True
        
        last_sent = datetime.fromisoformat(history[key])
        cooldown_end = last_sent + timedelta(hours=self.cooldown_hours)
        
        return datetime.now(KST) > cooldown_end
    
    def mark_sent(self, symbol: str, notification_type: str) -> None:
        """Mark notification as sent"""
        history = self._load_history()
        key = self._make_key(symbol, notification_type)
        history[key] = datetime.now(KST).isoformat()
        self._save_history(history)
    
    def notify_if_allowed(
        self, 
        symbol: str, 
        notification_type: str,
        send_func: Callable
    ) -> bool:
        """
        Send notification only if not in cooldown.
        Returns True if sent.
        """
        if self.should_notify(symbol, notification_type):
            send_func()
            self.mark_sent(symbol, notification_type)
            return True
        return False


# =============================================================================
# 7. HEALTHCHECK METRICS
# =============================================================================

@dataclass
class HealthMetrics:
    """Concrete healthcheck metrics"""
    
    # Data fetch metrics
    data_fetch_success_count: int = 0
    data_fetch_failure_count: int = 0
    
    # Candle metrics
    candle_total_count: int = 0
    candle_missing_count: int = 0
    
    # Signal metrics
    last_signal_time: Optional[datetime] = None
    signal_drought_hours: float = 0.0
    
    # API metrics
    api_success_count: int = 0
    api_error_count: int = 0
    
    # Timestamps
    last_check: Optional[datetime] = None
    
    @property
    def data_fetch_success_rate(self) -> float:
        total = self.data_fetch_success_count + self.data_fetch_failure_count
        return self.data_fetch_success_count / total * 100 if total > 0 else 100.0
    
    @property
    def candle_missing_rate(self) -> float:
        return self.candle_missing_count / self.candle_total_count * 100 if self.candle_total_count > 0 else 0.0
    
    @property
    def api_error_rate(self) -> float:
        total = self.api_success_count + self.api_error_count
        return self.api_error_count / total * 100 if total > 0 else 0.0
    
    def is_healthy(self) -> bool:
        """Overall health check"""
        return (
            self.data_fetch_success_rate >= 90 and
            self.candle_missing_rate <= 5 and
            self.signal_drought_hours <= 48 and
            self.api_error_rate <= 10
        )
    
    def update_signal_drought(self) -> None:
        """Update signal drought hours"""
        if self.last_signal_time:
            delta = datetime.now(KST) - self.last_signal_time
            self.signal_drought_hours = delta.total_seconds() / 3600


# =============================================================================
# CLI TEST
# =============================================================================

if __name__ == "__main__":
    print("\n🔧 PRODUCTION UTILITIES TEST")
    print("=" * 50)
    
    # 1. Lock test
    print("\n1️⃣ FileLock test:")
    lock = FileLock()
    if lock.acquire():
        print("   ✅ Lock acquired")
        lock.release()
        print("   ✅ Lock released")
    
    # 2. Idempotency test
    print("\n2️⃣ Idempotency test:")
    idem = IdempotencyStore()
    key = idem.get_daily_key("test")
    print(f"   Key: {key}")
    print(f"   Already processed: {idem.is_processed('test_task', key)}")
    idem.mark_processed('test_task', key, {'status': 'ok'})
    print(f"   After mark: {idem.is_processed('test_task', key)}")
    
    # 3. Structured logging test
    print("\n3️⃣ Structured logging test:")
    logger = StructuredLogger("test", run_id="abc123")
    logger.info("Test message", extra_field="value")
    
    # 4. Retry test
    print("\n4️⃣ Retry test:")
    
    @retry_with_backoff(max_attempts=2, base_delay=0.1)
    def flaky_function():
        if not hasattr(flaky_function, 'called'):
            flaky_function.called = True
            raise ValueError("First call fails")
        return "Success on retry"
    
    try:
        result = flaky_function()
        print(f"   ✅ {result}")
    except Exception as e:
        print(f"   ❌ {e}")
    
    # 5. Notification dedup test
    print("\n5️⃣ Notification dedup test:")
    dedup = NotificationDedup(cooldown_hours=0.01)  # 36 seconds for test
    print(f"   Should notify: {dedup.should_notify('BTC', 'SIGNAL')}")
    dedup.mark_sent('BTC', 'SIGNAL')
    print(f"   After mark: {dedup.should_notify('BTC', 'SIGNAL')}")
    
    # 6. Health metrics test
    print("\n6️⃣ Health metrics test:")
    health = HealthMetrics(
        data_fetch_success_count=95,
        data_fetch_failure_count=5,
        candle_total_count=1000,
        candle_missing_count=10,
        last_signal_time=datetime.now(KST) - timedelta(hours=12)
    )
    health.update_signal_drought()
    print(f"   Fetch success rate: {health.data_fetch_success_rate:.1f}%")
    print(f"   Signal drought: {health.signal_drought_hours:.1f}h")
    print(f"   Is healthy: {health.is_healthy()}")
    
    print("\n✅ All tests complete!")
