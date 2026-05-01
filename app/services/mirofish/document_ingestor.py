"""Document ingestor — PDF/MD/TXT/CSV 청킹 + entity 추출.

청킹: 슬라이딩 윈도우 1500자, overlap 200자 (MD 명세).
청크별 GraphRAG 호출 후 EKG 병합.
"""
from __future__ import annotations

import csv
import io
import os
from typing import Any

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50MB (MD 명세)
DEFAULT_CHUNK_SIZE = 1500
DEFAULT_OVERLAP = 200


# ─── Public API ────────────────────────────────────────────

def ingest_document(filename: str, file_bytes: bytes) -> dict[str, Any]:
    """파일 → 텍스트 → 청크 분할.

    Returns:
        {
            'filename': str,
            'format': 'pdf' | 'md' | 'txt' | 'csv' | 'unknown',
            'size_bytes': int,
            'text_length': int,
            'chunks': [str, ...],
            'metadata': {...},
            'error': str?,  # 실패 시
        }
    """
    if not filename:
        return _err('empty filename', filename)
    size = len(file_bytes or b'')
    if size == 0:
        return _err('empty file', filename, format=_detect_format(filename))
    if size > MAX_FILE_SIZE_BYTES:
        return _err(f'file too large ({size} > {MAX_FILE_SIZE_BYTES})', filename)

    fmt = _detect_format(filename)
    try:
        if fmt == 'pdf':
            text = _parse_pdf(file_bytes)
        elif fmt == 'md':
            text = _parse_text(file_bytes)
        elif fmt == 'txt':
            text = _parse_text(file_bytes)
        elif fmt == 'csv':
            text = _parse_csv(file_bytes)
        else:
            return _err(f'unsupported format: {fmt}', filename, format=fmt)
    except Exception as e:
        return _err(f'parse failed: {type(e).__name__}: {e}', filename, format=fmt)

    chunks = chunk_text(text, chunk_size=DEFAULT_CHUNK_SIZE, overlap=DEFAULT_OVERLAP)

    return {
        'filename': filename,
        'format': fmt,
        'size_bytes': size,
        'text_length': len(text),
        'chunks': chunks,
        'chunk_count': len(chunks),
        'metadata': {
            'chunk_size': DEFAULT_CHUNK_SIZE,
            'overlap': DEFAULT_OVERLAP,
        },
    }


def chunk_text(text: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE,
               overlap: int = DEFAULT_OVERLAP) -> list[str]:
    """슬라이딩 윈도우 청킹. 무한루프 방지 가드 포함."""
    text = (text or '').strip()
    if not text:
        return []
    chunk_size = max(100, chunk_size)
    overlap = max(0, min(overlap, chunk_size - 50))
    step = chunk_size - overlap

    chunks: list[str] = []
    pos = 0
    text_len = len(text)
    while pos < text_len:
        end = min(pos + chunk_size, text_len)
        chunk = text[pos:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= text_len:
            break
        pos += step
        if step <= 0:  # safety
            break
    return chunks


def ingest_and_extract(filename: str, file_bytes: bytes,
                       *, use_llm: bool = True) -> dict[str, Any]:
    """ingest + 청크별 GraphRAG 추출 + EKG 병합 한 번에."""
    from app.services.mirofish import graphrag_extractor as gr

    ingested = ingest_document(filename, file_bytes)
    if 'error' in ingested:
        return ingested

    chunks = ingested.get('chunks', [])
    # 비용 통제: 너무 많은 청크는 max_calls 까지만 처리
    max_chunks = gr.MAX_CALLS_PER_RUN if use_llm else len(chunks)
    chunks_to_process = chunks[:max_chunks]

    total_entities = 0
    total_relations = 0
    extraction_methods: set[str] = set()

    for chunk in chunks_to_process:
        graph = gr.extract_graph(chunk, use_llm=use_llm)
        extraction_methods.add(graph.get('method', 'unknown'))
        stats = gr.merge_into_ekg(graph)
        total_entities += stats['new_entities']
        total_relations += stats['new_relations']

    return {
        **ingested,
        'extraction': {
            'chunks_processed': len(chunks_to_process),
            'chunks_skipped': max(0, len(chunks) - len(chunks_to_process)),
            'new_entities': total_entities,
            'new_relations': total_relations,
            'methods': sorted(extraction_methods),
        },
    }


# ─── Format parsers ────────────────────────────────────────

def _detect_format(filename: str) -> str:
    fn = (filename or '').lower()
    if fn.endswith('.pdf'):
        return 'pdf'
    if fn.endswith('.md') or fn.endswith('.markdown'):
        return 'md'
    if fn.endswith('.txt'):
        return 'txt'
    if fn.endswith('.csv'):
        return 'csv'
    return 'unknown'


def _parse_text(file_bytes: bytes) -> str:
    # UTF-8 우선, 실패 시 CP949 (한국어 윈도우)
    for encoding in ('utf-8', 'utf-8-sig', 'cp949', 'euc-kr'):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode('utf-8', errors='replace')


def _parse_csv(file_bytes: bytes) -> str:
    """CSV → 행별 텍스트 (헤더 + 값 결합). Top 100 row 만."""
    text = _parse_text(file_bytes)
    lines = []
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return ''
    headers = rows[0] if rows else []
    for i, row in enumerate(rows[1:101]):  # max 100 rows
        items = [f"{h}={v}" for h, v in zip(headers, row) if v]
        lines.append(' | '.join(items))
    return '\n'.join(lines)


def _parse_pdf(file_bytes: bytes) -> str:
    """PDF → text. PyPDF2 또는 pdfplumber 시도, 모두 실패 시 ImportError."""
    # 1) PyPDF2
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        pages_text = []
        for page in reader.pages:
            try:
                pages_text.append(page.extract_text() or '')
            except Exception:
                continue
        text = '\n'.join(pages_text)
        if text.strip():
            return text
    except ImportError:
        pass

    # 2) pdfplumber
    try:
        import pdfplumber
        pages_text = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                pages_text.append(page.extract_text() or '')
        text = '\n'.join(pages_text)
        if text.strip():
            return text
    except ImportError:
        pass

    raise ImportError('Neither PyPDF2 nor pdfplumber available — install one of them')


def _err(msg: str, filename: str, *, format: str = 'unknown') -> dict[str, Any]:
    return {
        'filename': filename or 'unknown',
        'format': format,
        'size_bytes': 0,
        'text_length': 0,
        'chunks': [],
        'chunk_count': 0,
        'error': msg,
    }
