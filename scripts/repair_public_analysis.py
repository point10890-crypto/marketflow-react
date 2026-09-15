"""Prepare/replay narrowly scoped corrections to legacy public analysis posts.

Dry-run is the default. The plan is also the backup; apply never overwrites a
post changed since planning. All reads/writes use the deployed public/API host.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from datetime import datetime, timezone

import requests

ORIGIN = 'https://marketflow-api.bit-man.net'
MARKER = 'data-editorial-correction="2026-09-15"'
NOTE = f'''<section {MARKER}>
<h2>기록 정정 · 2026-09-15</h2>
<p>이 글은 과거 자동 생성된 관찰 기록입니다. 당시 기록된 종목·가격·등락률·점수는 보존했습니다.
원문 링크가 없는 뉴스 제목과 모든 종목에 일괄 적용하던 매매 지시를 제거했습니다.
원천 시각, 당시 모델 호출 성공 여부, 뉴스의 종목 관련성을 이 글만으로 검증할 수 없습니다.
등급과 점수는 실제 계좌 수익이나 투자 성과가 아닙니다.</p>
<p>이미지는 AI 생성 삽화이며 실제 차트·수익 증빙이 아닙니다. 투자 결정 전 현재의 공식 자료를 확인해 주세요.</p>
<p><a href="https://bit-man.net/guide/signal-verification-worked-example">관찰 기록을 검증하는 방법</a> ·
<a href="https://bit-man.net/contact">자료 오류 신고</a></p></section>'''


def correct_content(title: str, html: str) -> str:
    # Never touch arbitrary member posts or unknown generators.
    if not title.startswith('[종가베팅]') or '종가베팅 V2' not in html or MARKER in html:
        return html
    original = html
    html = re.sub(r'<p>📰\s*(?![^<]*<a\b)(?:(?!</p>).)*</p>',
                  lambda m: m[0] if re.search(r'<a\b', m[0], re.I) else '', html, flags=re.S)
    html = re.sub(r'<h[12]>💵 매매 규칙</h[12]>.*?(?=<h[12]>⚠️ 주의</h[12]>)', '', html, flags=re.S)
    for paragraph in (
        '손절선 깨지면 즉시 정리 — 반등 기다리지 말 것.',
        'AI Consensus 태그는 Gemini+GPT-4o 교차검증 통과.',
    ):
        html = html.replace(f'<p>{paragraph}</p>', '')
    html = html.replace('종가베팅 V2 · 17점 체크리스트 · Gemini + GPT-4o 교차검증',
                        '종가베팅 V2 · 17점 체크리스트 · 과거 자동 생성 기록')
    html = html.replace('장마감 · 자동 생성', '기준 자료 · 자동 생성 (장 마감 확정 여부 미검증)')
    # Keep old model tags as historical values, explicitly not verification.
    html = re.sub(r'AI Consensus #(\d+)', r'원본 합의 태그 #\1 (호출 성공 미검증)', html)
    if html == original:
        return original
    return html.rstrip() + '\n' + NOTE


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def prepare(session):
    summaries = {}
    page = 1
    while True:
        response = session.get(f'{ORIGIN}/api/public/community/boards/analysis/posts',
                               params={'page': page, 'per_page': 30}, timeout=30)
        response.raise_for_status()
        batch = response.json()
        for post in batch['posts'] + batch.get('notices', []):
            summaries[post['id']] = post
        if page >= batch['total_pages']:
            break
        page += 1
    changes = []
    for post in summaries.values():
        if not post['title'].startswith('[종가베팅]'):
            continue
        response = session.get(f"{ORIGIN}/api/public/community/posts/{post['id']}", timeout=30)
        response.raise_for_status()
        detail = response.json()['post']
        assert detail['board']['slug'] == 'analysis'
        revised = correct_content(detail['title'], detail['content'])
        if revised != detail['content']:
            changes.append({'id': detail['id'], 'title': detail['title'],
                            'before': detail['content'], 'after': revised,
                            'before_sha256': digest(detail['content'])})
    return {'origin': ORIGIN, 'created_at': datetime.now(timezone.utc).isoformat(),
            'scanned': len(summaries), 'changes': changes}


def apply_plan(session, plan, receipt_path):
    assert plan['origin'] == ORIGIN
    receipt = {'verified': [], 'conflicts': []}
    for change in plan['changes']:
        response = session.get(f"{ORIGIN}/api/public/community/posts/{change['id']}", timeout=30)
        response.raise_for_status()
        current = response.json()['post']
        assert current['board']['slug'] == 'analysis'
        if current['content'] == change['after']:
            receipt['verified'].append(change['id'])
            save(receipt_path, receipt)
            continue
        if current['title'] != change['title'] or digest(current['content']) != change['before_sha256']:
            receipt['conflicts'].append(change['id'])
            save(receipt_path, receipt)
            continue
        response = session.put(f"{ORIGIN}/api/community/posts/{change['id']}",
                               json={'content': change['after']}, timeout=30)
        response.raise_for_status()
        response = session.get(f"{ORIGIN}/api/public/community/posts/{change['id']}", timeout=30)
        response.raise_for_status()
        assert response.json()['post']['content'] == change['after']
        receipt['verified'].append(change['id'])
        save(receipt_path, receipt)
    print(json.dumps({'verified': len(receipt['verified']), 'conflicts': receipt['conflicts']}))
    return 1 if receipt['conflicts'] else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    with requests.Session() as session:
        if not args.apply:
            if args.plan.exists():
                raise SystemExit('Plan already exists; use a new filename to preserve the backup.')
            plan = prepare(session)
            save(args.plan, plan)
            print(json.dumps({'scanned': plan['scanned'], 'proposed': len(plan['changes'])}))
            return 0
        token = os.environ.get('MARKETFLOW_ADMIN_TOKEN', '').strip()
        if not token:
            raise SystemExit('MARKETFLOW_ADMIN_TOKEN is required; no changes applied.')
        plan = json.loads(args.plan.read_text(encoding='utf-8'))
        session.headers['Authorization'] = f'Bearer {token}'
        return apply_plan(session, plan, args.plan.with_suffix('.receipt.json'))


if __name__ == '__main__':
    raise SystemExit(main())
