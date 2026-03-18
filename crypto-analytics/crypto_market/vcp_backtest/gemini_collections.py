#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini File Search Collections (Playbook QA)
Uses Gemini's native File Search API for RAG-based trading playbook Q&A.

Features:
1. Playbook QA - Query trading rules with native Gemini RAG
2. Post-mortem Archive - Store and search trade outcomes
3. Pattern Discovery - Search for common failure cases

Pricing: Storage FREE, Embeddings $0.15/1M tokens at indexing
Supports: gemini-3-pro-preview, gemini-2.5-flash, gemini-2.5-pro
"""
import os
import json
import logging
import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


def load_api_key():
    """Load Google API key from environment or .env file"""
    try:
        from dotenv import load_dotenv
        env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
        if os.path.exists(env_path):
            load_dotenv(env_path)
        else:
            load_dotenv()
    except ImportError:
        pass
    
    return os.environ.get('GOOGLE_API_KEY')


@dataclass
class SearchResult:
    """A single search result"""
    content: str
    source: str
    score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlaybookAnswer:
    """Answer from Playbook QA"""
    question: str
    answer: str
    sources: List[str]
    citations: List[Dict]
    confidence: str
    generated_at: str


class GeminiFileSearchClient:
    """
    Gemini File Search API client for native RAG.
    """
    
    def __init__(self, store_name: str = "vcp_playbook"):
        self.api_key = load_api_key()
        self.store_display_name = store_name
        self._client = None
        self._store = None
        self._store_name = None
    
    def _get_client(self):
        """Initialize Gemini client"""
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        return self._client
    
    def is_available(self) -> bool:
        """Check if API is available"""
        return bool(self.api_key)
    
    # ===== FILE SEARCH STORE MANAGEMENT =====
    
    def create_store(self, display_name: str = None) -> str:
        """Create a new file search store"""
        client = self._get_client()
        
        name = display_name or self.store_display_name
        
        store = client.file_search_stores.create(
            config={'display_name': name}
        )
        
        self._store = store
        self._store_name = store.name
        
        logger.info(f"Created File Search Store: {store.name}")
        return store.name
    
    def get_or_create_store(self) -> str:
        """Get existing store or create new one"""
        if self._store_name:
            return self._store_name
        
        client = self._get_client()
        
        # List existing stores
        try:
            stores = list(client.file_search_stores.list())
            for store in stores:
                if hasattr(store, 'display_name') and store.display_name == self.store_display_name:
                    self._store_name = store.name
                    logger.info(f"Found existing store: {store.name}")
                    return store.name
        except Exception as e:
            logger.warning(f"Error listing stores: {e}")
        
        # Create new store
        return self.create_store()
    
    def list_stores(self) -> List[Dict]:
        """List all file search stores"""
        client = self._get_client()
        stores = []
        
        for store in client.file_search_stores.list():
            stores.append({
                'name': store.name,
                'display_name': getattr(store, 'display_name', 'N/A')
            })
        
        return stores
    
    def delete_store(self, store_name: str) -> bool:
        """Delete a file search store"""
        client = self._get_client()
        
        try:
            client.file_search_stores.delete(name=store_name, config={'force': True})
            logger.info(f"Deleted store: {store_name}")
            return True
        except Exception as e:
            logger.error(f"Delete failed: {e}")
            return False
    
    # ===== FILE UPLOAD =====
    
    def upload_file(
        self, 
        file_path: str,
        display_name: str = None,
        wait: bool = True
    ) -> bool:
        """Upload a file to the file search store"""
        client = self._get_client()
        store_name = self.get_or_create_store()
        
        display = display_name or os.path.basename(file_path)
        
        logger.info(f"Uploading {file_path} to {store_name}...")
        
        operation = client.file_search_stores.upload_to_file_search_store(
            file=file_path,
            file_search_store_name=store_name,
            config={'display_name': display}
        )
        
        if wait:
            while not operation.done:
                time.sleep(2)
                operation = client.operations.get(operation)
            logger.info(f"Upload complete: {display}")
        
        return True
    
    def upload_text(
        self,
        content: str,
        filename: str = "document.txt"
    ) -> bool:
        """Upload text content by creating a temp file"""
        import tempfile
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write(content)
            temp_path = f.name
        
        try:
            result = self.upload_file(temp_path, display_name=filename)
            return result
        finally:
            os.unlink(temp_path)
    
    # ===== QUERY WITH FILE SEARCH =====
    
    def query(
        self,
        question: str,
        model: str = "gemini-2.5-flash",
        system_prompt: str = None
    ) -> Dict:
        """Query with File Search RAG"""
        from google.genai import types
        
        client = self._get_client()
        store_name = self.get_or_create_store()
        
        # Build content
        contents = question
        if system_prompt:
            contents = f"{system_prompt}\n\nQuestion: {question}"
        
        # Call with File Search tool
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                tools=[
                    types.Tool(
                        file_search=types.FileSearch(
                            file_search_store_names=[store_name]
                        )
                    )
                ]
            )
        )
        
        # Extract citations
        citations = []
        grounding_metadata = None
        
        if response.candidates and len(response.candidates) > 0:
            grounding_metadata = getattr(response.candidates[0], 'grounding_metadata', None)
        
        return {
            'answer': response.text,
            'grounding_metadata': grounding_metadata,
            'model': model
        }


class PlaybookQA:
    """
    Playbook Question & Answer system using Gemini File Search.
    """
    
    SYSTEM_PROMPT = """You are a trading assistant helping to interpret a trading playbook.
Answer questions based ONLY on the provided context from the file search.
If the answer is not in the documents, say "이 정보는 플레이북에 없습니다."

Focus on:
- Trading rules and conditions
- Risk management guidelines
- Entry/exit criteria
- Market regime considerations

Respond in Korean unless asked otherwise. Be specific and actionable."""
    
    def __init__(self, store_name: str = "vcp_playbook"):
        self.client = GeminiFileSearchClient(store_name)
    
    def load_playbook_file(self, file_path: str) -> bool:
        """Load a playbook file into the store"""
        return self.client.upload_file(file_path)
    
    def load_playbook_dir(self, dir_path: str) -> int:
        """Load all markdown/text files from a directory"""
        count = 0
        for filename in os.listdir(dir_path):
            if filename.endswith(('.md', '.txt', '.pdf')):
                file_path = os.path.join(dir_path, filename)
                if self.client.upload_file(file_path):
                    count += 1
        return count
    
    def ask(self, question: str) -> PlaybookAnswer:
        """Ask a question about the playbook"""
        
        result = self.client.query(
            question=question,
            model="gemini-2.5-flash",
            system_prompt=self.SYSTEM_PROMPT
        )
        
        # Extract sources from grounding metadata
        sources = []
        citations = []
        
        if result.get('grounding_metadata'):
            meta = result['grounding_metadata']
            # Parse grounding metadata for sources
            # This structure depends on the API response format
        
        return PlaybookAnswer(
            question=question,
            answer=result['answer'],
            sources=sources,
            citations=citations,
            confidence="high" if sources else "medium",
            generated_at=datetime.now().isoformat()
        )


class PostMortemArchive:
    """
    Post-mortem trade archive using Gemini File Search.
    """
    
    def __init__(self, store_name: str = "trade_postmortem"):
        self.client = GeminiFileSearchClient(store_name)
        self.local_archive_path = os.path.join(
            os.path.dirname(__file__), 'postmortem_archive.json'
        )
    
    def record_trade(
        self,
        symbol: str,
        entry_time: str,
        entry_price: float,
        exit_time: str = None,
        exit_price: float = None,
        return_pct: float = None,
        max_adverse_excursion: float = None,
        signal_type: str = "",
        market_regime: str = "",
        notes: str = ""
    ) -> bool:
        """Record a trade outcome"""
        
        outcome = "WIN" if return_pct and return_pct > 0 else "LOSS"
        
        record = {
            "symbol": symbol,
            "entry_time": entry_time,
            "entry_price": entry_price,
            "exit_time": exit_time,
            "exit_price": exit_price,
            "return_pct": return_pct,
            "max_adverse_excursion": max_adverse_excursion,
            "signal_type": signal_type,
            "market_regime": market_regime,
            "notes": notes,
            "recorded_at": datetime.now().isoformat(),
            "outcome": outcome
        }
        
        # Build content for file search
        content = f"""
# Trade Post-Mortem: {symbol}
Date: {entry_time}
Entry: ${entry_price}
Exit: ${exit_price}
Return: {return_pct:.2f}%
Max Drawdown: {max_adverse_excursion}%
Signal Type: {signal_type}
Market Regime: {market_regime}
Outcome: {outcome}

Notes: {notes}
"""
        
        # Upload to file search store
        filename = f"trade_{symbol}_{entry_time.replace(' ', '_').replace(':', '-')}.txt"
        self.client.upload_text(content, filename)
        
        # Save to local archive
        self._save_local(record)
        
        return True
    
    def _save_local(self, record: Dict) -> None:
        """Save to local JSON archive"""
        archive = []
        if os.path.exists(self.local_archive_path):
            with open(self.local_archive_path, 'r', encoding='utf-8') as f:
                archive = json.load(f)

        archive.append(record)

        with open(self.local_archive_path, 'w', encoding='utf-8') as f:
            json.dump(archive, f, indent=2, ensure_ascii=False)
    
    def search_patterns(self, query: str = "실패한 트레이드의 공통점은?") -> str:
        """Search for patterns in trades"""
        result = self.client.query(query)
        return result['answer']
    
    def get_stats(self) -> Dict:
        """Get archive statistics"""
        if not os.path.exists(self.local_archive_path):
            return {"total": 0, "wins": 0, "losses": 0}
        
        with open(self.local_archive_path, 'r', encoding='utf-8') as f:
            archive = json.load(f)

        wins = len([t for t in archive if t.get('outcome') == 'WIN'])
        losses = len([t for t in archive if t.get('outcome') == 'LOSS'])
        
        return {
            "total": len(archive),
            "wins": wins,
            "losses": losses,
            "win_rate": wins / len(archive) * 100 if archive else 0
        }


# ===== CLI Testing =====
if __name__ == "__main__":
    print("\n🔗 GEMINI FILE SEARCH CLIENT TEST")
    print("=" * 60)
    
    client = GeminiFileSearchClient()
    
    if client.is_available():
        print("✅ Google API Key found")
        
        # List stores
        print("\n📁 Listing File Search Stores...")
        stores = client.list_stores()
        print(f"   Found {len(stores)} stores")
        for s in stores:
            print(f"   - {s['name']}: {s['display_name']}")
        
        # Create or get store
        print("\n📦 Getting/Creating store...")
        store_name = client.get_or_create_store()
        print(f"   Store: {store_name}")
        
        # Upload test content
        print("\n📄 Uploading test document...")
        test_content = """
# VCP Trading Playbook

## Market Gate Rules
- GREEN (score >= 72): 적극 진입 가능, min_score=45
- YELLOW (48-71): 선별적 진입, min_score=60  
- RED (< 48): RETEST만 허용, min_score=75

## Entry Triggers
- BREAKOUT: 피봇 고점 돌파 시 진입
- RETEST: 돌파 후 지지 확인 시 진입

## Risk Management
- Stop Loss: 피봇 기준 2% 아래
- Take Profit: 8-12%
- Max Hold: 15-25 bars
"""
        client.upload_text(test_content, "playbook_rules.txt")
        print("   ✅ Uploaded!")
        
        # Query test
        print("\n💬 Testing query with File Search...")
        result = client.query("Gate가 YELLOW일 때 min_score는?")
        print(f"   Answer: {result['answer'][:200]}...")
        
    else:
        print("⚠️ Google API Key not set")
    
    print("\n✅ Gemini File Search test complete!")
