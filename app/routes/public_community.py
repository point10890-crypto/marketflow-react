# -*- coding: utf-8 -*-
"""공개 커뮤니티 읽기 API — 인증 없음 (AdSense 심사용 공개 콘텐츠).

로그인 게이트 뒤에 있던 커뮤니티 중 화이트리스트 보드만 읽기 전용으로 연다.
자동 게시 파이프라인(일일분석·로또·공지)이 매일 쌓는 글이 "지속 갱신되는
고유 콘텐츠"로 심사 크롤러에 보이게 하는 것이 목적이다.

경계 (tests/test_public_community.py 로 고정):
- 화이트리스트 밖 보드는 존재 자체를 숨긴다 (404) — 수식마켓·Pro 라운지 등
- 읽기 전용: GET 외 메서드 미등록
- 작성자는 표시 이름만. 이메일/author_id/구매정보 비노출
- per_page 상한 30
"""
from __future__ import annotations

import os

from flask import Blueprint, jsonify, request
from sqlalchemy.orm import joinedload

from app.models.community import Board, Comment, Post

public_community_bp = Blueprint('public_community', __name__)

_DEFAULT_PUBLIC_BOARDS = 'notice,lotto-ai,analysis,free-talk'
_PER_PAGE_MAX = 30


def _public_board_slugs() -> set[str]:
    raw = os.getenv('PUBLIC_COMMUNITY_BOARDS', _DEFAULT_PUBLIC_BOARDS)
    return {s.strip() for s in raw.split(',') if s.strip()}


def _public_post_dict(post: Post) -> dict:
    """공개용 축약 — Post.to_dict() 는 author_id 등을 포함하므로 쓰지 않는다."""
    return {
        'id': post.id,
        'title': post.title,
        'author_name': post.author.name if post.author else '익명',
        'is_notice': bool(post.is_notice),
        'view_count': post.view_count or 0,
        'comment_count': post.comment_count or 0,
        'created_at': post.created_at.isoformat() if post.created_at else None,
    }


@public_community_bp.route('/boards', methods=['GET'])
def public_boards():
    slugs = _public_board_slugs()
    boards = Board.query.filter(Board.is_active.is_(True)).order_by(Board.sort_order).all()
    out = []
    for b in boards:
        if b.slug not in slugs:
            continue
        post_count = Post.query.filter_by(board_id=b.id, is_hidden=False).count()
        out.append({
            'slug': b.slug,
            'name': b.name,
            'description': getattr(b, 'description', None),
            'post_count': post_count,
        })
    return jsonify({'boards': out})


@public_community_bp.route('/boards/<slug>/posts', methods=['GET'])
def public_posts(slug):
    if slug not in _public_board_slugs():
        return jsonify({'error': 'Board not found'}), 404
    board = Board.query.filter_by(slug=slug, is_active=True).first()
    if not board:
        return jsonify({'error': 'Board not found'}), 404

    page = max(1, request.args.get('page', 1, type=int) or 1)
    per_page = request.args.get('per_page', 20, type=int) or 20
    per_page = max(1, min(per_page, _PER_PAGE_MAX))

    notices = []
    if page == 1:
        notice_q = (
            Post.query.options(joinedload(Post.author))
            .filter_by(board_id=board.id, is_hidden=False, is_notice=True)
            .order_by(Post.created_at.desc()).limit(20).all()
        )
        notices = [_public_post_dict(p) for p in notice_q]

    query = (
        Post.query.options(joinedload(Post.author))
        .filter_by(board_id=board.id, is_hidden=False, is_notice=False)
        .order_by(Post.created_at.desc())
    )
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'board': {'slug': board.slug, 'name': board.name},
        'posts': [_public_post_dict(p) for p in pagination.items],
        'notices': notices,
        'total': pagination.total,
        'page': page,
        'per_page': per_page,
        'total_pages': pagination.pages,
    })


@public_community_bp.route('/posts/<int:post_id>', methods=['GET'])
def public_post_detail(post_id):
    post = (
        Post.query.options(joinedload(Post.author), joinedload(Post.board))
        .filter_by(id=post_id, is_hidden=False)
        .first()
    )
    if not post or not post.board or not post.board.is_active:
        return jsonify({'error': 'Post not found'}), 404
    if post.board.slug not in _public_board_slugs():
        return jsonify({'error': 'Post not found'}), 404

    comments = (
        Comment.query.options(joinedload(Comment.author))
        .filter_by(post_id=post.id, is_hidden=False)
        .order_by(Comment.created_at.asc()).limit(100).all()
    )

    detail = _public_post_dict(post)
    detail['content'] = post.content
    detail['board'] = {'slug': post.board.slug, 'name': post.board.name}
    return jsonify({
        'post': detail,
        'comments': [
            {
                'id': c.id,
                'author_name': c.author.name if c.author else '익명',
                'content': c.content,
                'created_at': c.created_at.isoformat() if c.created_at else None,
            } for c in comments
        ],
    })
