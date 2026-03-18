#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xAI Collections Integration (Official API Spec)

Based on: https://docs.x.ai/docs/guides/collections

Collections:
1. Crypto_Playbook - 사이클/기준서/리서치 문서
2. Daily_Snapshots - 매일 시장 스냅샷

Required env vars:
- XAI_API_KEY: For search operations
- XAI_MANAGEMENT_API_KEY: For upload/create operations (optional)
"""
from __future__ import annotations
import os
from typing import Optional, Dict, Any, List
from dataclasses import dataclass


@dataclass
class SearchResult:
    """검색 결과 아이템"""
    name: str
    snippet: str
    score: float = 0.0


def _get_client():
    """Initialize xAI SDK client"""
    try:
        from xai_sdk import Client
        api_key = os.getenv("XAI_API_KEY", "").strip()
        mgmt_key = os.getenv("XAI_MANAGEMENT_API_KEY", "").strip()
        
        if not api_key:
            return None
            
        return Client(
            api_key=api_key,
            management_api_key=mgmt_key if mgmt_key else None,
            timeout=3600,
        )
    except ImportError:
        print("⚠️ xai_sdk not installed. Run: pip install xai-sdk")
        return None
    except Exception as e:
        print(f"⚠️ Failed to create xAI client: {e}")
        return None


# ============================================================
# Collection Management
# ============================================================

def create_collection(
    name: str,
    field_definitions: Optional[List[Dict]] = None
) -> Optional[str]:
    """
    Create a new collection.
    
    Args:
        name: Collection name (e.g., "Crypto_Playbook", "Daily_Snapshots")
        field_definitions: Optional metadata field definitions
            Example: [
                {"key": "gate", "required": True},
                {"key": "score", "required": True},
                {"key": "date", "required": True, "unique": True},
            ]
    
    Returns:
        collection_id or None
    """
    client = _get_client()
    if not client:
        return None
    
    try:
        kwargs = {"name": name}
        if field_definitions:
            kwargs["field_definitions"] = field_definitions
            
        collection = client.collections.create(**kwargs)
        cid = getattr(collection, "collection_id", None) or getattr(collection, "id", None)
        print(f"✅ Created collection: {name} (ID: {cid})")
        return cid
    except Exception as e:
        print(f"❌ Failed to create collection '{name}': {e}")
        return None


def list_collections() -> List[Dict]:
    """List all collections"""
    client = _get_client()
    if not client:
        return []
    
    try:
        collections = client.collections.list()
        result = []
        for c in collections:
            result.append({
                "id": getattr(c, "collection_id", None) or getattr(c, "id", None),
                "name": getattr(c, "name", "unknown"),
            })
        return result
    except Exception as e:
        print(f"❌ Failed to list collections: {e}")
        return []


def get_or_create_collection(name: str, field_defs: Optional[List[Dict]] = None) -> Optional[str]:
    """Get existing collection ID or create new one"""
    # First check env var for explicit ID
    env_key = f"XAI_COLLECTION_{name.upper()}_ID"
    cid = os.getenv(env_key, "").strip()
    if cid:
        return cid
    
    # Try to find by name
    for c in list_collections():
        if c.get("name") == name:
            return c.get("id")
    
    # Create new
    return create_collection(name, field_defs)


# ============================================================
# Document Upload
# ============================================================

def upload_document(
    collection_id: str,
    name: str,
    content: bytes | str,
    content_type: str = "text/markdown",
    fields: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """
    Upload a document to a collection.
    
    Args:
        collection_id: Target collection ID
        name: Document name (e.g., "snapshot_2025-12-25.md")
        content: Document content (bytes or str)
        content_type: MIME type (text/markdown, text/html, application/pdf, etc.)
        fields: Metadata fields (must match collection's field_definitions)
    
    Returns:
        file_id or None
    """
    client = _get_client()
    if not client:
        return None
    
    try:
        data = content if isinstance(content, bytes) else content.encode("utf-8")
        
        doc = client.collections.upload_document(
            collection_id=collection_id,
            name=name,
            data=data,
            content_type=content_type,
            fields=fields or {},
        )
        
        file_id = getattr(doc, "file_id", None) or getattr(doc, "id", None)
        print(f"✅ Uploaded: {name} → {collection_id[:20]}...")
        return file_id
    except Exception as e:
        print(f"❌ Failed to upload '{name}': {e}")
        return None


# ============================================================
# Search
# ============================================================

def search_collections(
    query: str,
    collection_ids: List[str],
    retrieval_mode: str = "hybrid",  # "keyword" | "semantic" | "hybrid"
    filter_str: Optional[str] = None,  # AIP-160 syntax: 'gate="RED" AND score>=40'
    top_k: int = 5,
) -> List[SearchResult]:
    """
    Search documents in collections.
    
    Args:
        query: Natural language search query
        collection_ids: List of collection IDs to search
        retrieval_mode: "hybrid" (recommended), "keyword", or "semantic"
        filter_str: Optional metadata filter (AIP-160 syntax)
        top_k: Number of results to return
    
    Returns:
        List of SearchResult
    """
    client = _get_client()
    if not client:
        return []
    
    try:
        kwargs = {
            "query": query,
            "collection_ids": collection_ids,
        }
        
        # SDK may or may not support all params
        try:
            response = client.collections.search(**kwargs)
        except TypeError:
            # Fallback without unsupported params
            response = client.collections.search(query=query, collection_ids=collection_ids)
        
        # Parse response
        results = []
        items = response if isinstance(response, list) else (
            getattr(response, "results", None) or 
            getattr(response, "documents", None) or 
            getattr(response, "items", None) or
            []
        )
        
        for item in items[:top_k]:
            name = getattr(item, "name", None) or getattr(item, "document_name", None) or "document"
            snippet = str(
                getattr(item, "snippet", None) or 
                getattr(item, "text", None) or 
                getattr(item, "content", None) or 
                ""
            ).strip().replace("\n", " ")
            
            if len(snippet) > 300:
                snippet = snippet[:300] + "…"
            
            score = float(getattr(item, "score", 0) or 0)
            
            results.append(SearchResult(name=name, snippet=snippet, score=score))
        
        return results
    except Exception as e:
        print(f"❌ Search failed: {e}")
        return []


# ============================================================
# Convenience: Market Snapshot Upload
# ============================================================

def upload_market_snapshot(
    collection_id: str,
    gate: str,
    score: int,
    metrics: Dict[str, Any],
    reasons: List[str],
    date_str: str,  # "2025-12-25"
) -> Optional[str]:
    """
    Upload daily market snapshot to Collections.
    
    Designed for filtered retrieval:
    - Search by gate color: filter='gate="RED"'
    - Search by score range: filter='score>=60'
    - Search by date: filter='date="2025-12-25"'
    """
    content = f"""# Market Snapshot: {date_str}

## Gate Status
- **Gate**: {gate}
- **Score**: {score}/100

## Metrics
- BTC Price: ${metrics.get('btc_price', 'N/A'):,.2f}
- BTC EMA50: ${metrics.get('btc_ema50', 'N/A'):,.2f}  
- BTC EMA200: ${metrics.get('btc_ema200', 'N/A'):,.2f}
- EMA200 Slope (20d): {metrics.get('btc_ema200_slope_pct_20', 'N/A'):.2f}%
- Volume Z-Score: {metrics.get('btc_volume_z_50', 'N/A'):.2f}
- ATR%: {metrics.get('btc_atrp_14_pct', 'N/A'):.2f}%
- Alt Breadth (>EMA50): {metrics.get('alt_breadth_above_ema50', 'N/A'):.1%}

## Reasons
{chr(10).join(f'- {r}' for r in reasons)}

## Score Components
{chr(10).join(f'- {k}: {v:.1f}' for k, v in metrics.get('gate_score_components', {}).items())}
"""
    
    return upload_document(
        collection_id=collection_id,
        name=f"snapshot_{date_str}.md",
        content=content,
        content_type="text/markdown",
        fields={
            "gate": gate,
            "score": str(score),
            "date": date_str,
        },
    )


# ============================================================
# Test / CLI
# ============================================================

if __name__ == "__main__":
    print("🔍 Testing xAI Collections Integration...\n")
    
    # Check API key
    if not os.getenv("XAI_API_KEY"):
        print("❌ XAI_API_KEY not set. Add to .env file.")
        exit(1)
    
    # List collections
    print("📚 Existing Collections:")
    for c in list_collections():
        print(f"  - {c['name']} (ID: {c['id'][:30]}...)")
    
    # Test search (if collections exist)
    collections = list_collections()
    if collections:
        cid = collections[0]["id"]
        print(f"\n🔎 Test search in '{collections[0]['name']}':")
        results = search_collections(
            query="market conditions for crypto uptrend",
            collection_ids=[cid],
        )
        for r in results[:3]:
            print(f"  - {r.name}: {r.snippet[:100]}...")
