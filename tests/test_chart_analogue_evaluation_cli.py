"""Offline operator boundaries: isolated output and no backdated ingestion."""
import json
from pathlib import Path
import subprocess
import sys

SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'evaluate_chart_analogue_shadow.py'


def test_empty_offline_evaluation_writes_only_requested_report(tmp_path):
    root=tmp_path/'evaluation'
    result=subprocess.run([sys.executable,str(SCRIPT),'--root',str(root),
                           '--index-root',str(tmp_path/'missing-index')],
                          capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    saved=json.loads((root/'report.json').read_text(encoding='utf-8'))
    assert saved['status']=='collecting'
    assert saved['counts']['recorded']==0
    assert all(row['excess_return_pct'] is None for row in saved['horizons'])
    summary=json.loads(result.stdout)
    assert summary['status']=='collecting'
    assert summary['counts']['recorded']==0


def test_cli_rejects_backdated_ingestion_before_writing(tmp_path):
    root=tmp_path/'evaluation'
    result=subprocess.run([sys.executable,str(SCRIPT),'--root',str(root),
                           '--ingest-latest','--as-of','2025-01-01T00:00:00Z'],
                          capture_output=True,text=True,timeout=30)
    assert result.returncode==2
    assert 'ingest' in result.stderr.lower()
    assert not root.exists()
