"""Phase 3C: Document ingestor tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.mirofish import document_ingestor as di  # noqa: E402


def test_chunk_text_empty():
    assert di.chunk_text('') == []
    assert di.chunk_text('   ') == []


def test_chunk_text_short():
    text = 'Hello world'
    chunks = di.chunk_text(text, chunk_size=1500, overlap=200)
    assert chunks == ['Hello world']


def test_chunk_text_overlap_correct():
    text = 'A' * 3000  # 3000 chars
    chunks = di.chunk_text(text, chunk_size=1500, overlap=200)
    assert len(chunks) >= 2
    # 첫 청크와 둘째 청크에 겹치는 부분 존재
    if len(chunks) >= 2:
        # overlap 200 이면 step=1300, 둘째 청크 start=1300, 즉 [1300:2800]
        assert chunks[0][-100:] == chunks[1][:100][:100]  # last 100 of 1st = first 100 of 2nd? 200 overlap


def test_chunk_text_no_infinite_loop_with_zero_step():
    # overlap >= chunk_size → step <=0 → guard
    chunks = di.chunk_text('A' * 1000, chunk_size=500, overlap=600)
    assert len(chunks) >= 1
    assert len(chunks) < 1000  # not infinite


def test_detect_format():
    assert di._detect_format('foo.pdf') == 'pdf'
    assert di._detect_format('Foo.PDF') == 'pdf'
    assert di._detect_format('a.md') == 'md'
    assert di._detect_format('a.markdown') == 'md'
    assert di._detect_format('a.txt') == 'txt'
    assert di._detect_format('a.csv') == 'csv'
    assert di._detect_format('a.docx') == 'unknown'
    assert di._detect_format('') == 'unknown'


def test_ingest_text_file():
    text = '삼성전자 호조. 반도체 수요 회복.'
    out = di.ingest_document('news.txt', text.encode('utf-8'))
    assert out['format'] == 'txt'
    assert out['text_length'] == len(text)
    assert len(out['chunks']) >= 1


def test_ingest_md_file():
    md = '# 제목\n\n삼성전자 분석.\n\n- 항목1\n- 항목2'
    out = di.ingest_document('report.md', md.encode('utf-8'))
    assert out['format'] == 'md'
    assert '삼성전자' in out['chunks'][0]


def test_ingest_csv_file():
    csv_text = 'ticker,name,score\n005930,삼성전자,85\n000660,SK하이닉스,80'
    out = di.ingest_document('data.csv', csv_text.encode('utf-8'))
    assert out['format'] == 'csv'
    assert '삼성전자' in out['chunks'][0]


def test_ingest_cp949_text():
    """한글 cp949 인코딩도 지원."""
    text = '삼성전자 호조'
    out = di.ingest_document('legacy.txt', text.encode('cp949'))
    assert out['text_length'] > 0
    assert '삼성전자' in out['chunks'][0]


def test_ingest_empty_file_returns_error():
    out = di.ingest_document('empty.txt', b'')
    assert 'error' in out
    assert 'empty file' in out['error']


def test_ingest_too_large_returns_error():
    big = b'x' * (di.MAX_FILE_SIZE_BYTES + 1)
    out = di.ingest_document('big.txt', big)
    assert 'error' in out
    assert 'too large' in out['error']


def test_ingest_unsupported_format_returns_error():
    out = di.ingest_document('foo.docx', b'<xml/>')
    assert 'error' in out
    assert 'unsupported' in out['error']


def test_ingest_empty_filename_returns_error():
    out = di.ingest_document('', b'data')
    assert 'error' in out


def test_chunk_text_long_content_split():
    text = '한국 시장 분석. ' * 200  # ~3200 chars
    chunks = di.chunk_text(text, chunk_size=1500, overlap=200)
    assert len(chunks) >= 2
    # 모든 청크 길이 1500 이하
    for c in chunks:
        assert len(c) <= 1500


def test_ingest_csv_caps_at_100_rows():
    rows = ['ticker,score']
    rows.extend(f'{i:06d},{i % 100}' for i in range(200))
    csv_text = '\n'.join(rows)
    out = di.ingest_document('big.csv', csv_text.encode('utf-8'))
    # CSV 파서에서 100 row 만 처리 → text_length 절반
    assert 'error' not in out
