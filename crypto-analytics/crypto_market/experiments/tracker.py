#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Experiment Tracker - Reproducible Backtest Results
Tracks all backtest runs with full parameter snapshots for reproducibility.

Features:
1. Git hash + timestamp + run_id
2. Full parameter serialization
3. Trade log + equity curve storage
4. Reproduce CLI
"""
import os
import json
import uuid
import hashlib
import subprocess
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Tuple, Any, Optional
import logging

logger = logging.getLogger(__name__)

EXPERIMENTS_DIR = os.path.join(os.path.dirname(__file__), 'runs')


def get_git_hash() -> str:
    """Get current git commit hash"""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            capture_output=True, text=True, encoding='utf-8', timeout=5
        )
        return result.stdout.strip()[:8] if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def get_git_branch() -> str:
    """Get current git branch"""
    try:
        result = subprocess.run(
            ['git', 'branch', '--show-current'],
            capture_output=True, text=True, encoding='utf-8', timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def compute_data_hash(file_path: str) -> str:
    """Compute MD5 hash of data file for reproducibility check"""
    if not os.path.exists(file_path):
        return "none"
    
    hasher = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            hasher.update(chunk)
    return hasher.hexdigest()[:12]


@dataclass
class ExperimentRun:
    """A single experiment run with full tracking"""
    
    # Identity
    run_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    description: str = ""
    
    # Metadata
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    git_hash: str = field(default_factory=get_git_hash)
    git_branch: str = field(default_factory=get_git_branch)
    
    # Parameters
    config: Dict[str, Any] = field(default_factory=dict)
    universe: List[str] = field(default_factory=list)
    date_range: Tuple[str, str] = ("", "")
    timeframe: str = "4h"
    market_gate_enabled: bool = True
    data_hash: str = ""
    
    # Results
    metrics: Dict[str, float] = field(default_factory=dict)
    trades: List[Dict] = field(default_factory=list)
    equity_curve: List[Dict] = field(default_factory=list)
    regime_stats: Dict[str, Dict] = field(default_factory=dict)
    
    # Status
    status: str = "created"  # created, running, completed, failed
    error: str = ""
    duration_seconds: float = 0.0
    
    @property
    def run_dir(self) -> str:
        """Directory for this run's artifacts"""
        return os.path.join(EXPERIMENTS_DIR, self.run_id)
    
    def save(self) -> str:
        """Save experiment to disk"""
        os.makedirs(self.run_dir, exist_ok=True)
        
        # Save main config
        config_path = os.path.join(self.run_dir, 'config.json')
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump({
                'run_id': self.run_id,
                'name': self.name,
                'description': self.description,
                'timestamp': self.timestamp,
                'git_hash': self.git_hash,
                'git_branch': self.git_branch,
                'config': self.config,
                'universe': self.universe,
                'date_range': list(self.date_range),
                'timeframe': self.timeframe,
                'market_gate_enabled': self.market_gate_enabled,
                'data_hash': self.data_hash,
                'status': self.status,
                'error': self.error,
                'duration_seconds': self.duration_seconds,
            }, f, indent=2, ensure_ascii=False)
        
        # Save metrics summary
        if self.metrics:
            metrics_path = os.path.join(self.run_dir, 'metrics.json')
            with open(metrics_path, 'w', encoding='utf-8') as f:
                json.dump(self.metrics, f, indent=2)
        
        # Save trades
        if self.trades:
            trades_path = os.path.join(self.run_dir, 'trades.json')
            with open(trades_path, 'w', encoding='utf-8') as f:
                json.dump(self.trades, f, indent=2, ensure_ascii=False)
        
        # Save equity curve
        if self.equity_curve:
            equity_path = os.path.join(self.run_dir, 'equity_curve.json')
            with open(equity_path, 'w', encoding='utf-8') as f:
                json.dump(self.equity_curve, f)
        
        # Save regime stats
        if self.regime_stats:
            regime_path = os.path.join(self.run_dir, 'regime_stats.json')
            with open(regime_path, 'w', encoding='utf-8') as f:
                json.dump(self.regime_stats, f, indent=2)
        
        logger.info(f"Saved experiment {self.run_id} to {self.run_dir}")
        return self.run_dir
    
    @classmethod
    def load(cls, run_id: str) -> "ExperimentRun":
        """Load experiment from disk"""
        run_dir = os.path.join(EXPERIMENTS_DIR, run_id)
        
        if not os.path.exists(run_dir):
            raise FileNotFoundError(f"Experiment {run_id} not found")
        
        config_path = os.path.join(run_dir, 'config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        run = cls(
            run_id=data['run_id'],
            name=data.get('name', ''),
            description=data.get('description', ''),
            timestamp=data['timestamp'],
            git_hash=data['git_hash'],
            git_branch=data.get('git_branch', ''),
            config=data['config'],
            universe=data['universe'],
            date_range=tuple(data['date_range']),
            timeframe=data.get('timeframe', '4h'),
            market_gate_enabled=data['market_gate_enabled'],
            data_hash=data.get('data_hash', ''),
            status=data.get('status', 'completed'),
            error=data.get('error', ''),
            duration_seconds=data.get('duration_seconds', 0),
        )
        
        # Load optional files
        metrics_path = os.path.join(run_dir, 'metrics.json')
        if os.path.exists(metrics_path):
            with open(metrics_path, 'r', encoding='utf-8') as f:
                run.metrics = json.load(f)
        
        trades_path = os.path.join(run_dir, 'trades.json')
        if os.path.exists(trades_path):
            with open(trades_path, 'r', encoding='utf-8') as f:
                run.trades = json.load(f)
        
        return run


class ExperimentTracker:
    """Main tracker for managing experiments"""
    
    def __init__(self):
        os.makedirs(EXPERIMENTS_DIR, exist_ok=True)
        self._current_run: Optional[ExperimentRun] = None
    
    def start_run(
        self,
        name: str = "",
        description: str = "",
        config: Dict = None,
        universe: List[str] = None,
        date_range: Tuple[str, str] = None,
        **kwargs
    ) -> ExperimentRun:
        """Start a new experiment run"""
        run = ExperimentRun(
            name=name or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            description=description,
            config=config or {},
            universe=universe or [],
            date_range=date_range or ("", ""),
            status="running",
            **kwargs
        )
        
        self._current_run = run
        run.save()
        
        logger.info(f"Started experiment: {run.run_id}")
        return run
    
    def log_metrics(self, metrics: Dict[str, float]) -> None:
        """Log metrics to current run"""
        if self._current_run:
            self._current_run.metrics.update(metrics)
    
    def log_trades(self, trades: List) -> None:
        """Log trades to current run"""
        if self._current_run:
            # Convert Trade objects to dicts if needed
            self._current_run.trades = [
                t if isinstance(t, dict) else asdict(t) if hasattr(t, '__dataclass_fields__') else vars(t)
                for t in trades
            ]
    
    def log_equity_curve(self, curve: List[Tuple[int, float]]) -> None:
        """Log equity curve to current run"""
        if self._current_run:
            self._current_run.equity_curve = [
                {'timestamp': ts, 'equity': eq} for ts, eq in curve
            ]
    
    def end_run(self, status: str = "completed", error: str = "") -> ExperimentRun:
        """End current run and save"""
        if not self._current_run:
            raise RuntimeError("No active run to end")
        
        self._current_run.status = status
        self._current_run.error = error
        
        # Calculate duration
        start = datetime.fromisoformat(self._current_run.timestamp)
        self._current_run.duration_seconds = (datetime.now() - start).total_seconds()
        
        self._current_run.save()
        
        run = self._current_run
        self._current_run = None
        
        logger.info(f"Ended experiment: {run.run_id} ({status})")
        return run
    
    def list_runs(self, limit: int = 20) -> List[Dict]:
        """List recent experiment runs"""
        runs = []
        
        if not os.path.exists(EXPERIMENTS_DIR):
            return runs
        
        for run_id in os.listdir(EXPERIMENTS_DIR):
            config_path = os.path.join(EXPERIMENTS_DIR, run_id, 'config.json')
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    runs.append({
                        'run_id': run_id,
                        'name': data.get('name', ''),
                        'timestamp': data.get('timestamp', ''),
                        'status': data.get('status', ''),
                        'git_hash': data.get('git_hash', ''),
                    })
        
        # Sort by timestamp descending
        runs.sort(key=lambda x: x['timestamp'], reverse=True)
        return runs[:limit]
    
    def get_run(self, run_id: str) -> ExperimentRun:
        """Get a specific run"""
        return ExperimentRun.load(run_id)
    
    def compare_runs(self, run_ids: List[str]) -> Dict:
        """Compare multiple runs"""
        comparison = {'runs': []}
        
        for run_id in run_ids:
            run = self.get_run(run_id)
            comparison['runs'].append({
                'run_id': run_id,
                'name': run.name,
                'timestamp': run.timestamp,
                'git_hash': run.git_hash,
                'config': run.config,
                'metrics': run.metrics,
            })
        
        return comparison


def print_run_summary(run: ExperimentRun):
    """Pretty print run summary"""
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                    EXPERIMENT RUN: {run.run_id:<10}               ║
╠══════════════════════════════════════════════════════════════╣
║ Name:      {run.name[:50]:<50} ║
║ Status:    {run.status:<50} ║
║ Timestamp: {run.timestamp[:25]:<50} ║
║ Git:       {run.git_hash} ({run.git_branch})                         ║
╠══════════════════════════════════════════════════════════════╣
║ Date Range: {run.date_range[0]} → {run.date_range[1]:<25} ║
║ Universe:   {len(run.universe)} symbols                                     ║
║ Gate:       {'ON' if run.market_gate_enabled else 'OFF'}                                              ║
╠══════════════════════════════════════════════════════════════╣
║ METRICS:                                                     ║""")
    
    for key, value in run.metrics.items():
        if isinstance(value, float):
            print(f"║   {key:<20}: {value:>10.2f}                         ║")
        else:
            print(f"║   {key:<20}: {str(value):>10}                         ║")
    
    print("╚══════════════════════════════════════════════════════════════╝")


# CLI for reproduction
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Experiment Tracker CLI')
    subparsers = parser.add_subparsers(dest='command')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List experiments')
    list_parser.add_argument('--limit', type=int, default=10)
    
    # Show command
    show_parser = subparsers.add_parser('show', help='Show experiment details')
    show_parser.add_argument('run_id', help='Run ID')
    
    # Compare command
    compare_parser = subparsers.add_parser('compare', help='Compare experiments')
    compare_parser.add_argument('run_ids', nargs='+', help='Run IDs to compare')
    
    args = parser.parse_args()
    tracker = ExperimentTracker()
    
    if args.command == 'list':
        runs = tracker.list_runs(limit=args.limit)
        print(f"\n📋 Recent Experiments ({len(runs)}):")
        print("-" * 60)
        for r in runs:
            status_icon = "✅" if r['status'] == 'completed' else "❌"
            print(f"  {status_icon} {r['run_id']} | {r['name'][:30]:<30} | {r['timestamp'][:16]}")
    
    elif args.command == 'show':
        run = tracker.get_run(args.run_id)
        print_run_summary(run)
    
    elif args.command == 'compare':
        comparison = tracker.compare_runs(args.run_ids)
        print("\n📊 Experiment Comparison:")
        for r in comparison['runs']:
            print(f"\n  {r['run_id']} ({r['git_hash']}):")
            for k, v in r['metrics'].items():
                print(f"    {k}: {v}")
    
    else:
        parser.print_help()
