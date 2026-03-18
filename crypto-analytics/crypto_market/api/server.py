#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API Layer (FastAPI)
Lightweight REST API for dashboard integration.

Endpoints:
- GET /status - System status
- GET /health - Health check
- GET /signals - Recent signals
- POST /scan - Trigger manual scan
"""
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional
import json

# Add parent path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


if FASTAPI_AVAILABLE:
    app = FastAPI(
        title="Crypto VCP System API",
        description="REST API for VCP analysis and monitoring",
        version="4.0"
    )
    
    # CORS for dashboard
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Response models
    class StatusResponse(BaseModel):
        gate: str
        gate_score: int
        signal_count: int
        is_halted: bool
        last_update: str
        tasks: Dict
    
    class HealthResponse(BaseModel):
        healthy: bool
        data_fetch_rate: float
        signal_drought_hours: float
        api_error_rate: float
    
    class SignalResponse(BaseModel):
        symbol: str
        score: int
        signal_type: str
        gate: str
        timestamp: str
    
    # In-memory state (would be shared with orchestrator)
    _state = {
        'gate': 'YELLOW',
        'gate_score': 50,
        'signals': [],
        'is_halted': False,
        'last_update': datetime.now().isoformat()
    }
    
    @app.get("/", tags=["Root"])
    async def root():
        return {"message": "Crypto VCP System API v4.0", "status": "running"}
    
    @app.get("/status", response_model=StatusResponse, tags=["Status"])
    async def get_status():
        """Get current system status"""
        return StatusResponse(
            gate=_state['gate'],
            gate_score=_state['gate_score'],
            signal_count=len(_state['signals']),
            is_halted=_state['is_halted'],
            last_update=_state['last_update'],
            tasks={}
        )
    
    @app.get("/health", response_model=HealthResponse, tags=["Health"])
    async def get_health():
        """Get system health metrics"""
        from operations.production_utils import HealthMetrics
        health = HealthMetrics()
        
        return HealthResponse(
            healthy=health.is_healthy(),
            data_fetch_rate=health.data_fetch_success_rate,
            signal_drought_hours=health.signal_drought_hours,
            api_error_rate=health.api_error_rate
        )
    
    @app.get("/signals", response_model=List[SignalResponse], tags=["Signals"])
    async def get_signals(limit: int = 10):
        """Get recent signals"""
        signals = []
        for s in _state['signals'][:limit]:
            signals.append(SignalResponse(
                symbol=s.get('symbol', 'UNKNOWN'),
                score=s.get('score', 0),
                signal_type=s.get('type', 'BREAKOUT'),
                gate=_state['gate'],
                timestamp=s.get('timestamp', datetime.now().isoformat())
            ))
        return signals
    
    @app.get("/gate", tags=["Market"])
    async def get_gate():
        """Get current market gate status"""
        return {
            'gate': _state['gate'],
            'score': _state['gate_score'],
            'timestamp': _state['last_update']
        }
    
    @app.post("/scan", tags=["Actions"])
    async def trigger_scan(background_tasks: BackgroundTasks):
        """Trigger manual VCP scan (async)"""
        def run_scan():
            try:
                from orchestrator import Orchestrator
                orch = Orchestrator()
                result = orch._task_vcp_scan()
                _state['signals'] = result.get('signals', [])
                _state['last_update'] = datetime.now().isoformat()
            except Exception as e:
                pass
        
        background_tasks.add_task(run_scan)
        return {"status": "scan_triggered", "message": "Scan started in background"}
    
    @app.post("/gate/check", tags=["Actions"])
    async def trigger_gate_check(background_tasks: BackgroundTasks):
        """Trigger manual gate check (async)"""
        def run_gate():
            try:
                from orchestrator import Orchestrator
                orch = Orchestrator()
                result = orch._task_gate_check()
                _state['gate'] = result.get('gate', 'YELLOW')
                _state['gate_score'] = result.get('score', 50)
                _state['last_update'] = datetime.now().isoformat()
            except Exception as e:
                pass
        
        background_tasks.add_task(run_gate)
        return {"status": "gate_check_triggered"}


def run_api(host: str = "0.0.0.0", port: int = 8001):
    """Run FastAPI server"""
    if not FASTAPI_AVAILABLE:
        print("FastAPI not installed. Run: pip install fastapi uvicorn")
        return
    
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Crypto API Server')
    parser.add_argument('--host', default='0.0.0.0', help='Host')
    parser.add_argument('--port', type=int, default=8001, help='Port')
    
    args = parser.parse_args()
    
    if FASTAPI_AVAILABLE:
        print(f"\n🚀 Starting API server on http://{args.host}:{args.port}")
        print("   Docs: http://localhost:8001/docs")
        run_api(args.host, args.port)
    else:
        print("❌ FastAPI not installed")
        print("   Run: pip install fastapi uvicorn")
