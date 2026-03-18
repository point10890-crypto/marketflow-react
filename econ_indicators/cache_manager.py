#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
통합 캐시 관리자 (SQLite 기반)
API 응답 캐싱으로 반복 호출 방지
"""

import sqlite3
import json
import pandas as pd
from datetime import datetime, timedelta
from typing import Any, Optional
from pathlib import Path


class CacheManager:
    """SQLite 기반 캐시 관리"""
    
    def __init__(self, db_name: str = 'cache.db'):
        self.db_path = Path(__file__).parent.parent / 'data' / db_name
        self.db_path.parent.mkdir(exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """데이터베이스 초기화"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT,
                expires_at TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
    
    def get(self, key: str) -> Optional[Any]:
        """캐시에서 값 조회"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT value, expires_at FROM cache WHERE key = ?
        """, (key,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row is None:
            return None
        
        value, expires_at = row
        if datetime.fromisoformat(expires_at) < datetime.now():
            self.delete(key)
            return None
        
        # DataFrame 복원 시도
        data = json.loads(value)
        if isinstance(data, dict) and '_dataframe' in data:
            return pd.DataFrame(data['data'])
        
        return data
    
    def set(self, key: str, value: Any, ttl: int = 3600):
        """캐시에 값 저장 (기본 TTL: 1시간)"""
        expires_at = datetime.now() + timedelta(seconds=ttl)
        
        # DataFrame 처리
        if isinstance(value, pd.DataFrame):
            value = {'_dataframe': True, 'data': value.to_dict()}
        
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO cache (key, value, expires_at)
            VALUES (?, ?, ?)
        """, (key, json.dumps(value, default=str), expires_at.isoformat()))
        
        conn.commit()
        conn.close()
    
    def delete(self, key: str):
        """캐시에서 삭제"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cache WHERE key = ?", (key,))
        conn.commit()
        conn.close()
    
    def clear_expired(self):
        """만료된 캐시 정리"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cache WHERE expires_at < ?", 
                      (datetime.now().isoformat(),))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        return deleted
    
    def clear_all(self):
        """전체 캐시 삭제"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cache")
        conn.commit()
        conn.close()


if __name__ == "__main__":
    # 테스트
    cache = CacheManager("test_cache.db")
    
    # 단순 값 저장
    cache.set("test_key", {"value": 123}, ttl=60)
    print(f"Get test_key: {cache.get('test_key')}")
    
    # DataFrame 저장
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    cache.set("test_df", df, ttl=60)
    result = cache.get("test_df")
    print(f"Get test_df:\n{result}")
    
    print("✅ CacheManager test passed!")
