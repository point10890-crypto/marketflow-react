#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Market Snapshot - Daily snapshot upload to xAI Collections
"""
from __future__ import annotations
import os
from datetime import datetime
from typing import Optional

from market_gate import MarketGateResult
from grok_collections import upload_market_snapshot, get_or_create_collection


# Default collection names
SNAPSHOTS_COLLECTION_NAME = "Crypto_Daily_Snapshots"
PLAYBOOK_COLLECTION_NAME = "Crypto_Playbook"


def upload_daily_snapshot(result: MarketGateResult, date_str: Optional[str] = None) -> Optional[str]:
    """
    Upload daily market snapshot to Collections.
    
    Returns file_id if successful, None otherwise.
    """
    if date_str is None:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
    
    # Get or create collection with metadata fields
    collection_id = get_or_create_collection(
        name=SNAPSHOTS_COLLECTION_NAME,
        field_defs=[
            {"key": "gate", "required": True},
            {"key": "score", "required": True},
            {"key": "date", "required": True, "unique": True},
        ]
    )
    
    if not collection_id:
        print("⚠️ Snapshots collection not available (xAI keys missing?)")
        return None
    
    return upload_market_snapshot(
        collection_id=collection_id,
        gate=result.gate,
        score=result.score,
        metrics=result.metrics,
        reasons=result.reasons,
        date_str=date_str,
    )


def get_snapshots_collection_id() -> Optional[str]:
    """Get snapshots collection ID"""
    return get_or_create_collection(SNAPSHOTS_COLLECTION_NAME)


def get_playbook_collection_id() -> Optional[str]:
    """Get playbook collection ID"""
    return get_or_create_collection(PLAYBOOK_COLLECTION_NAME)
