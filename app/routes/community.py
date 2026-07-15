"""Community bulletin board routes"""

import os
import re
import uuid
import threading
import requests as http_requests
from flask import Blueprint, request, jsonify, send_from_directory, current_app
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from app.models import db
from app.models.community import Board, Post, PostImage, Comment, PurchaseRequest
from app.auth.decorators import approved_required, admin_required, _get_current_user


def _notify_admin_telegram(message: str):
    """관리자 텔레그램으로 알림 전송 (비동기, 실패는 경고 로그).

    Previously silently swallowed all exceptions. Now logs HTTP failures
    and exceptions so we can detect bad tokens/network outages.
    """
    import logging as _logging
    _logger = _logging.getLogger("marketflow.telegram")

    def _send():
        try:
            token = os.getenv('TELEGRAM_BOT_TOKEN')
            chat_id = os.getenv('TELEGRAM_CHAT_ID')
            if not token or not chat_id:
                _logger.info("telegram[community] skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID unset")
                return
            resp = http_requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'},
                timeout=10,
            )
            if resp.status_code != 200:
                _logger.warning(
                    f"telegram[community] HTTP {resp.status_code} body={resp.text[:200]}"
                )
        except Exception as e:
            _logger.warning(f"telegram[community] exception: {type(e).__name__}: {e}")
    threading.Thread(target=_send, daemon=True).start()

community_bp = Blueprint('community', __name__)

TIER_ORDER = {'pro': 1, 'premium': 2}  # 'free' 플랜 폐지 — 미구독자(None)는 TIER_ORDER.get() 기본값 0으로 접근 불가
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
FORMULA_FILE_EXTENSIONS = {'txt', 'csv', 'xlsx', 'xls', 'pdf', 'zip', 'hwp', 'docx'}
VIDEO_EXTENSIONS = {'mp4', 'mov', 'webm'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_FORMULA_FILE_SIZE = 20 * 1024 * 1024  # 20MB
MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100MB
MAX_POST_TITLE_LENGTH = 200
MAX_POST_CONTENT_LENGTH = 200_000
MAX_COMMENT_LENGTH = 10_000

UPLOAD_DIR = os.path.join(os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                          'data', 'uploads', 'community')


def _save_upload_verified(file_data: bytes, filename: str) -> tuple[bool, str]:
    """업로드 파일 저장 + fsync + 존재/크기 검증.

    dual-tunnel 사고처럼 업로드 요청이 다른 호스트로 라우팅돼 응답은 200 이지만
    실제 디스크에는 파일이 없는 상황을 방지. 저장 후 동일 프로세스 디스크에
    실제로 기록됐는지 확인하고 불일치 시 False 반환.
    """
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        filepath = os.path.join(UPLOAD_DIR, filename)
        with open(filepath, 'wb') as f:
            f.write(file_data)
            f.flush()
            os.fsync(f.fileno())
        if not os.path.exists(filepath):
            return False, 'file missing after write'
        actual = os.path.getsize(filepath)
        if actual != len(file_data):
            try:
                os.remove(filepath)
            except OSError:
                pass
            return False, f'size mismatch (expected {len(file_data)}, got {actual})'
        return True, ''
    except OSError as e:
        return False, f'{type(e).__name__}: {e}'


def _read_upload_limited(file_storage, max_bytes: int) -> bytes | None:
    """Read at most ``max_bytes + 1`` so oversized uploads cannot exhaust RAM."""
    data = file_storage.read(max_bytes + 1)
    return None if len(data) > max_bytes else data


def _check_tier(user_tier, required_tier):
    if required_tier == 'admin':
        return False  # Only admin role can pass, checked separately
    return TIER_ORDER.get(user_tier, 0) >= TIER_ORDER.get(required_tier, 0)


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# Magic bytes for image MIME validation
_IMAGE_SIGNATURES = {
    b'\xff\xd8\xff': 'jpg',       # JPEG
    b'\x89PNG\r\n\x1a\n': 'png',  # PNG
    b'GIF87a': 'gif',             # GIF87a
    b'GIF89a': 'gif',             # GIF89a
    b'RIFF': 'webp',             # WebP (RIFF....WEBP)
}


def _validate_image_content(file_data: bytes, claimed_ext: str) -> bool:
    """Verify file content matches claimed extension using magic bytes.
    Returns True if content is a valid image matching the claimed extension."""
    if len(file_data) < 12:
        return False

    detected_type = None
    for sig, img_type in _IMAGE_SIGNATURES.items():
        if file_data[:len(sig)] == sig:
            detected_type = img_type
            break

    if detected_type is None:
        return False

    # WebP needs extra check: bytes 8-12 must be 'WEBP'
    if detected_type == 'webp' and file_data[8:12] != b'WEBP':
        return False

    # Map claimed extension to type for comparison
    ext_to_type = {'jpg': 'jpg', 'jpeg': 'jpg', 'png': 'png', 'gif': 'gif', 'webp': 'webp'}
    claimed_type = ext_to_type.get(claimed_ext.lower())

    return detected_type == claimed_type


def _validate_video_content(file_data: bytes, claimed_ext: str) -> bool:
    """Perform a small container-signature check before public video serving."""
    if claimed_ext in {'mp4', 'mov'}:
        return len(file_data) >= 12 and file_data[4:8] == b'ftyp'
    if claimed_ext == 'webm':
        return len(file_data) >= 4 and file_data[:4] == b'\x1aE\xdf\xa3'
    return False


# ── Boards ──

@community_bp.route('/boards', methods=['GET'])
@approved_required
def list_boards():
    user = _get_current_user()
    boards = Board.query.filter_by(is_active=True).order_by(Board.sort_order).all()
    board_ids = [board.id for board in boards]
    post_counts = {}
    latest_posts = {}
    if board_ids:
        # Keep response work proportional to the number of boards, not posts.
        # The previous implementation materialized every visible post merely to
        # count rows and select one latest row.  On the production SQLite DB this
        # made /api/community/boards increasingly slow and prone to proxy timeout.
        post_counts = dict(
            db.session.query(Post.board_id, func.count(Post.id))
            .filter(Post.board_id.in_(board_ids), Post.is_hidden.is_(False))
            .group_by(Post.board_id)
            .all()
        )

        visible_at = func.coalesce(Post.updated_at, Post.created_at)
        latest_at = (
            db.session.query(
                Post.board_id.label('board_id'),
                func.max(visible_at).label('latest_at'),
            )
            .filter(Post.board_id.in_(board_ids), Post.is_hidden.is_(False))
            .group_by(Post.board_id)
            .subquery()
        )
        latest_rows = (
            db.session.query(
                Post.id,
                Post.board_id,
                Post.title,
                Post.created_at,
                Post.updated_at,
            )
            .join(
                latest_at,
                (Post.board_id == latest_at.c.board_id)
                & (visible_at == latest_at.c.latest_at),
            )
            .filter(Post.is_hidden.is_(False))
            .order_by(Post.board_id, Post.id.desc())
            .all()
        )
        # A timestamp tie can return multiple rows; the deterministic id order
        # above makes setdefault select exactly one row per board.
        for post in latest_rows:
            latest_posts.setdefault(post.board_id, post)

    result = []
    for b in boards:
        can_read = (user.role == 'admin') or _check_tier(user.tier, b.min_tier)
        latest_post = latest_posts.get(b.id) if can_read else None
        d = {
            'id': b.id,
            'slug': b.slug,
            'name': b.name,
            'description': b.description,
            'icon': b.icon,
            'sort_order': b.sort_order,
            'min_tier': b.min_tier,
            'write_tier': b.write_tier,
            'is_active': b.is_active,
            'post_count': post_counts.get(b.id, 0) if can_read else 0,
            'latest_post_id': latest_post.id if latest_post else None,
            'latest_post_title': latest_post.title if latest_post else None,
            'latest_post_at': (
                latest_post.updated_at.isoformat()
                if latest_post and latest_post.updated_at else None
            ),
            'created_at': b.created_at.isoformat() if b.created_at else None,
        }
        d['can_read'] = can_read
        d['can_write'] = (user.role == 'admin') or _check_tier(user.tier, b.write_tier)
        result.append(d)
    return jsonify(result)


@community_bp.route('/boards', methods=['POST'])
@admin_required
def create_board():
    data = request.get_json() or {}
    slug = data.get('slug', '').strip()
    name = data.get('name', '').strip()
    if not slug or not name:
        return jsonify({'error': 'slug and name required'}), 400
    if Board.query.filter_by(slug=slug).first():
        return jsonify({'error': 'slug already exists'}), 409
    board = Board(
        slug=slug, name=name,
        description=data.get('description', ''),
        icon=data.get('icon', 'fa-comments'),
        sort_order=data.get('sort_order', 0),
        min_tier=data.get('min_tier', 'pro'),
        write_tier=data.get('write_tier', 'pro'),
    )
    db.session.add(board)
    db.session.commit()
    return jsonify(board.to_dict()), 201


@community_bp.route('/boards/<int:board_id>', methods=['PUT'])
@admin_required
def update_board(board_id):
    board = Board.query.get_or_404(board_id)
    data = request.get_json() or {}
    for key in ('name', 'description', 'icon', 'sort_order', 'min_tier', 'write_tier'):
        if key in data:
            setattr(board, key, data[key])
    db.session.commit()
    return jsonify(board.to_dict())


@community_bp.route('/boards/<int:board_id>', methods=['DELETE'])
@admin_required
def deactivate_board(board_id):
    board = Board.query.get_or_404(board_id)
    board.is_active = False
    db.session.commit()
    return jsonify({'ok': True})


# ── Posts ──

@community_bp.route('/boards/<slug>/posts', methods=['GET'])
@approved_required
def list_posts(slug):
    user = _get_current_user()
    board = Board.query.filter_by(slug=slug, is_active=True).first()
    if not board:
        return jsonify({'error': 'Board not found'}), 404
    if user.role != 'admin' and not _check_tier(user.tier, board.min_tier):
        return jsonify({'error': 'Tier upgrade required'}), 403

    page = max(1, request.args.get('page', 1, type=int) or 1)
    per_page = request.args.get('per_page', 20, type=int) or 20
    per_page = max(1, min(per_page, 50))

    # Notices (only page 1)
    notices = []
    if page == 1:
        notice_q = Post.query.options(joinedload(Post.author))\
            .filter_by(board_id=board.id, is_hidden=False, is_notice=True)\
            .order_by(Post.created_at.desc()).limit(50).all()
        notices = [p.to_dict() for p in notice_q]

    # Regular posts
    query = Post.query.options(joinedload(Post.author))\
        .filter_by(board_id=board.id, is_hidden=False, is_notice=False)\
        .order_by(Post.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'posts': [p.to_dict() for p in pagination.items],
        'notices': notices,
        'total': pagination.total,
        'page': page,
        'per_page': per_page,
        'total_pages': pagination.pages,
        'board': board.to_dict(),
    })


@community_bp.route('/posts/<int:post_id>', methods=['GET'])
@approved_required
def get_post(post_id):
    user = _get_current_user()
    post = Post.query.get_or_404(post_id)
    if post.is_hidden and user.role != 'admin':
        return jsonify({'error': 'Post not found'}), 404
    board = post.board
    if user.role != 'admin' and not _check_tier(user.tier, board.min_tier):
        return jsonify({'error': 'Tier upgrade required'}), 403

    post.view_count += 1
    db.session.commit()

    post_data = post.to_dict(include_content=True, user_id=user.id)

    # Include purchase status for formula-market posts
    if board.slug == 'formula-market' and user.role != 'admin':
        pr = PurchaseRequest.query.filter_by(post_id=post.id, user_id=user.id)\
            .order_by(PurchaseRequest.created_at.desc()).first()
        if pr:
            post_data['purchase_status'] = pr.status
            post_data['purchase_id'] = pr.id
        else:
            post_data['purchase_status'] = None
        # Hide file info unless purchase is approved
        if not pr or pr.status != 'approved':
            post_data.pop('file_url', None)
            post_data.pop('file_name', None)
    elif board.slug == 'formula-market' and user.role == 'admin':
        post_data['purchase_status'] = 'approved'

    return jsonify({'post': post_data})


@community_bp.route('/boards/<slug>/posts', methods=['POST'])
@approved_required
def create_post(slug):
    user = _get_current_user()
    board = Board.query.filter_by(slug=slug, is_active=True).first()
    if not board:
        return jsonify({'error': 'Board not found'}), 404
    if user.role != 'admin' and not _check_tier(user.tier, board.write_tier):
        return jsonify({'error': 'Tier upgrade required'}), 403

    data = request.get_json() or {}
    title = data.get('title', '').strip()
    content = data.get('content', '').strip()
    if not title or not content:
        return jsonify({'error': 'Title and content required'}), 400
    if len(title) > MAX_POST_TITLE_LENGTH:
        return jsonify({'error': f'Title too long (max {MAX_POST_TITLE_LENGTH} characters)'}), 400
    if len(content) > MAX_POST_CONTENT_LENGTH:
        return jsonify({'error': f'Content too long (max {MAX_POST_CONTENT_LENGTH} characters)'}), 400

    post = Post(board_id=board.id, author_id=user.id, title=title, content=content)

    # Formula market fields
    if board.slug == 'formula-market':
        post.price = data.get('price', '').strip() or None
        post.is_public = data.get('is_public', False)
        post.file_url = data.get('file_url') or None
        post.file_name = data.get('file_name') or None

    db.session.add(post)
    db.session.flush()

    # Link uploaded images
    for fn in data.get('image_filenames', []):
        img = PostImage.query.filter_by(filename=fn).first()
        if img and not img.post_id:
            img.post_id = post.id

    db.session.commit()
    return jsonify(post.to_dict(include_content=True, user_id=user.id)), 201


@community_bp.route('/posts/<int:post_id>', methods=['PUT'])
@approved_required
def update_post(post_id):
    user = _get_current_user()
    post = Post.query.get_or_404(post_id)
    if user.role != 'admin' and post.author_id != user.id:
        return jsonify({'error': 'Permission denied'}), 403

    data = request.get_json() or {}
    if 'title' in data:
        title = str(data['title'] or '').strip()
        if not title:
            return jsonify({'error': 'Title required'}), 400
        if len(title) > MAX_POST_TITLE_LENGTH:
            return jsonify({'error': f'Title too long (max {MAX_POST_TITLE_LENGTH} characters)'}), 400
        post.title = title
    if 'content' in data:
        content = str(data['content'] or '').strip()
        if not content:
            return jsonify({'error': 'Content required'}), 400
        if len(content) > MAX_POST_CONTENT_LENGTH:
            return jsonify({'error': f'Content too long (max {MAX_POST_CONTENT_LENGTH} characters)'}), 400
        post.content = content

    # Formula market: allow editing price (포인트 금액) + 식파일
    if post.board and post.board.slug == 'formula-market':
        if 'price' in data:
            raw = data.get('price')
            post.price = (raw.strip() or None) if isinstance(raw, str) else (str(raw) if raw is not None else None)
        if 'file_url' in data:
            post.file_url = data.get('file_url') or None
        if 'file_name' in data:
            post.file_name = data.get('file_name') or None
        if 'is_public' in data:
            post.is_public = bool(data.get('is_public'))

    db.session.commit()
    return jsonify(post.to_dict(include_content=True, user_id=user.id))


@community_bp.route('/posts/<int:post_id>', methods=['DELETE'])
@approved_required
def delete_post(post_id):
    user = _get_current_user()
    post = Post.query.get_or_404(post_id)
    if user.role != 'admin' and post.author_id != user.id:
        return jsonify({'error': 'Permission denied'}), 403
    post.is_hidden = True
    db.session.commit()
    return jsonify({'ok': True})


@community_bp.route('/posts/<int:post_id>/notice', methods=['PUT'])
@admin_required
def toggle_notice(post_id):
    post = Post.query.get_or_404(post_id)
    data = request.get_json(silent=True) or {}
    if 'is_notice' in data:
        post.is_notice = bool(data.get('is_notice'))
    else:
        post.is_notice = not post.is_notice
    db.session.commit()
    return jsonify({'is_notice': post.is_notice})


# ── Purchase Requests ──

@community_bp.route('/posts/<int:post_id>/purchase', methods=['POST'])
@approved_required
def create_purchase(post_id):
    user = _get_current_user()
    post = Post.query.get_or_404(post_id)
    data = request.get_json() or {}
    buyer_name = data.get('buyer_name', '').strip()
    if not buyer_name:
        return jsonify({'error': '입금자명을 입력하세요.'}), 400

    # Check if already requested
    existing = PurchaseRequest.query.filter_by(post_id=post.id, user_id=user.id, status='pending').first()
    if existing:
        return jsonify({'error': '이미 구매신청이 접수되었습니다.'}), 400

    pr = PurchaseRequest(post_id=post.id, user_id=user.id, buyer_name=buyer_name)
    db.session.add(pr)
    db.session.commit()

    # 관리자 텔레그램 알림
    price = post.price or '가격 미정'
    _notify_admin_telegram(
        f"🔔 <b>수식마켓 구매 요청</b>\n\n"
        f"📌 수식: {post.title}\n"
        f"👤 구매자: {user.name} ({buyer_name})\n"
        f"💰 금액: {price}\n\n"
        f"👉 관리자 페이지에서 승인해주세요."
    )

    # 인앱 알림
    from app.routes.admin import create_admin_notification
    create_admin_notification(
        'purchase_request',
        '수식마켓 구매 요청',
        f'{user.name} ({buyer_name}) — {post.title} ({price})',
        related_id=pr.id,
    )

    return jsonify(pr.to_dict()), 201


@community_bp.route('/purchases/summary', methods=['GET'])
@admin_required
def purchases_summary():
    """승인된 구매의 매출 합산 — 오늘/이번달/전체.

    post.price 는 숫자 문자열('30000', '50000' 등). PurchaseRequest.status='approved'
    에 해당하는 post.price 합산. 가격 파싱 실패 시 0 처리.
    """
    from sqlalchemy import func
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    # KST 기준 오늘/이번달 (approved_at/created_at 은 UTC)
    kst_offset = timedelta(hours=9)
    kst_today_start = (now + kst_offset).replace(hour=0, minute=0, second=0, microsecond=0) - kst_offset
    kst_month_start = (now + kst_offset).replace(day=1, hour=0, minute=0, second=0, microsecond=0) - kst_offset

    def _sum(since=None):
        q = db.session.query(Post.price).join(
            PurchaseRequest, PurchaseRequest.post_id == Post.id
        ).filter(PurchaseRequest.status == 'approved')
        if since is not None:
            # approved_at 은 nullable — null 인 경우 created_at 을 쓴다
            q = q.filter(db.func.coalesce(PurchaseRequest.approved_at, PurchaseRequest.created_at) >= since)
        total = 0
        count = 0
        for (p,) in q.all():
            count += 1
            if not p:
                continue
            try:
                total += int(str(p).replace(',', '').replace('원', '').strip() or 0)
            except (ValueError, TypeError):
                pass
        return {'count': count, 'total': total}

    all_sum = _sum()
    month_sum = _sum(kst_month_start.replace(tzinfo=None))
    today_sum = _sum(kst_today_start.replace(tzinfo=None))

    # pending 건수
    pending_count = PurchaseRequest.query.filter_by(status='pending').count()

    return jsonify({
        'today': today_sum,
        'month': month_sum,
        'all': all_sum,
        'pending_count': pending_count,
    })


@community_bp.route('/purchases', methods=['GET'])
@admin_required
def list_purchases():
    """Admin: list all purchase requests with pagination"""
    status_filter = request.args.get('status', '')
    search = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 10

    query = PurchaseRequest.query

    if status_filter:
        query = query.filter(PurchaseRequest.status == status_filter)
    if search:
        query = query.join(PurchaseRequest.user).filter(
            db.or_(
                PurchaseRequest.buyer_name.ilike(f'%{search}%'),
            )
        )

    query = query.order_by(PurchaseRequest.created_at.desc())
    total = query.count()
    purchases = query.offset((page - 1) * per_page).limit(per_page).all()

    return jsonify({
        'purchases': [p.to_dict() for p in purchases],
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': max(1, (total + per_page - 1) // per_page),
    })


@community_bp.route('/purchases/<int:purchase_id>', methods=['PUT'])
@admin_required
def update_purchase(purchase_id):
    """Admin: approve/reject purchase"""
    pr = PurchaseRequest.query.get_or_404(purchase_id)
    data = request.get_json() or {}
    new_status = data.get('status', '')
    if new_status not in ('approved', 'rejected'):
        return jsonify({'error': 'Invalid status'}), 400
    pr.status = new_status
    if new_status == 'approved':
        from datetime import datetime, timezone
        pr.approved_at = datetime.now(timezone.utc)
    else:
        pr.approved_at = None
    db.session.commit()
    return jsonify(pr.to_dict())


@community_bp.route('/purchases/<int:purchase_id>', methods=['DELETE'])
@admin_required
def delete_purchase(purchase_id):
    """Admin: delete purchase record"""
    pr = PurchaseRequest.query.get_or_404(purchase_id)
    db.session.delete(pr)
    db.session.commit()
    return jsonify({'success': True})


# ── Comments ──

@community_bp.route('/posts/<int:post_id>/comments', methods=['GET'])
@approved_required
def list_comments(post_id):
    user = _get_current_user()
    post = Post.query.get_or_404(post_id)
    if post.is_hidden and user.role != 'admin':
        return jsonify({'error': 'Post not found'}), 404
    board = post.board
    if user.role != 'admin' and not _check_tier(user.tier, board.min_tier):
        return jsonify({'error': 'Tier upgrade required'}), 403
    limit = request.args.get('limit', 200, type=int) or 200
    limit = max(1, min(limit, 500))
    comments = Comment.query.options(joinedload(Comment.author))\
        .filter_by(post_id=post.id, is_hidden=False)\
        .order_by(Comment.created_at.asc()).limit(limit).all()
    return jsonify([c.to_dict() for c in comments])


@community_bp.route('/posts/<int:post_id>/comments', methods=['POST'])
@approved_required
def create_comment(post_id):
    user = _get_current_user()
    post = Post.query.get_or_404(post_id)
    board = post.board
    if user.role != 'admin' and not _check_tier(user.tier, board.min_tier):
        return jsonify({'error': 'Tier upgrade required'}), 403

    data = request.get_json() or {}
    content = data.get('content', '').strip()
    if not content:
        return jsonify({'error': 'Content required'}), 400
    if len(content) > MAX_COMMENT_LENGTH:
        return jsonify({'error': f'Content too long (max {MAX_COMMENT_LENGTH} characters)'}), 400

    parent_id = data.get('parent_id')
    if parent_id:
        parent = Comment.query.get(parent_id)
        if not parent or parent.post_id != post.id:
            return jsonify({'error': 'Invalid parent comment'}), 400

    comment = Comment(post_id=post.id, author_id=user.id, content=content, parent_id=parent_id)
    db.session.add(comment)
    post.comment_count = Comment.query.filter_by(post_id=post.id, is_hidden=False).count() + 1
    db.session.commit()
    return jsonify(comment.to_dict()), 201


@community_bp.route('/comments/<int:comment_id>', methods=['PUT'])
@approved_required
def update_comment(comment_id):
    user = _get_current_user()
    comment = Comment.query.get_or_404(comment_id)
    if comment.is_hidden and user.role != 'admin':
        return jsonify({'error': 'Comment not found'}), 404
    post = Post.query.get_or_404(comment.post_id)
    if post.is_hidden and user.role != 'admin':
        return jsonify({'error': 'Post not found'}), 404
    board = post.board
    if user.role != 'admin' and not _check_tier(user.tier, board.min_tier):
        return jsonify({'error': 'Tier upgrade required'}), 403
    if user.role != 'admin' and comment.author_id != user.id:
        return jsonify({'error': 'Permission denied'}), 403

    data = request.get_json() or {}
    content = data.get('content', '').strip()
    if not content:
        return jsonify({'error': 'Content required'}), 400
    if len(content) > MAX_COMMENT_LENGTH:
        return jsonify({'error': f'Content too long (max {MAX_COMMENT_LENGTH} characters)'}), 400
    comment.content = content
    db.session.commit()
    return jsonify(comment.to_dict())


@community_bp.route('/comments/<int:comment_id>', methods=['DELETE'])
@approved_required
def delete_comment(comment_id):
    user = _get_current_user()
    comment = Comment.query.get_or_404(comment_id)
    if comment.is_hidden and user.role != 'admin':
        return jsonify({'error': 'Comment not found'}), 404
    post = Post.query.get_or_404(comment.post_id)
    if post.is_hidden and user.role != 'admin':
        return jsonify({'error': 'Post not found'}), 404
    board = post.board
    if user.role != 'admin' and not _check_tier(user.tier, board.min_tier):
        return jsonify({'error': 'Tier upgrade required'}), 403
    if user.role != 'admin' and comment.author_id != user.id:
        return jsonify({'error': 'Permission denied'}), 403
    comment.is_hidden = True
    post.comment_count = Comment.query.filter_by(post_id=post.id, is_hidden=False).count()
    db.session.commit()
    return jsonify({'ok': True})


# ── Image Upload ──

@community_bp.route('/upload', methods=['POST'])
@approved_required
def upload_image():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if not file.filename or not _allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Allowed: jpg, png, gif, webp'}), 400

    # Read and check size
    file_data = _read_upload_limited(file, MAX_FILE_SIZE)
    if file_data is None:
        return jsonify({'error': 'File too large (max 5MB)'}), 400

    ext = file.filename.rsplit('.', 1)[1].lower()

    # MIME validation: verify actual content matches claimed extension
    if not _validate_image_content(file_data, ext):
        return jsonify({'error': 'File content does not match extension. Upload rejected.'}), 400
    filename = f"{uuid.uuid4().hex}.{ext}"

    ok, err = _save_upload_verified(file_data, filename)
    if not ok:
        return jsonify({'error': f'파일 저장에 실패했습니다: {err}'}), 500

    # Save record (post_id will be linked when post is created)
    img = PostImage(post_id=0, filename=filename, original_name=file.filename, file_size=len(file_data))
    db.session.add(img)
    db.session.commit()

    return jsonify({
        'url': f'/api/community/uploads/{filename}',
        'filename': filename,
    })


@community_bp.route('/upload-file', methods=['POST'])
@approved_required
def upload_formula_file():
    """Upload formula file (txt, csv, xlsx, pdf, zip, hwp, docx)"""
    user = _get_current_user()
    if user.role != 'admin':
        return jsonify({'error': 'Admin only'}), 403
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No filename'}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in FORMULA_FILE_EXTENSIONS:
        return jsonify({'error': f'Invalid file type. Allowed: {", ".join(sorted(FORMULA_FILE_EXTENSIONS))}'}), 400

    file_data = _read_upload_limited(file, MAX_FORMULA_FILE_SIZE)
    if file_data is None:
        return jsonify({'error': 'File too large (max 20MB)'}), 400

    filename = f"{uuid.uuid4().hex}.{ext}"
    ok, err = _save_upload_verified(file_data, filename)
    if not ok:
        return jsonify({'error': f'파일 저장에 실패했습니다: {err}'}), 500

    return jsonify({
        'url': f'/api/community/uploads/{filename}',
        'filename': filename,
        'original_name': file.filename,
    })


@community_bp.route('/upload-video', methods=['POST'])
@approved_required
def upload_video():
    """Upload video file (mp4, mov, webm) — max 100MB"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No filename'}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in VIDEO_EXTENSIONS:
        return jsonify({'error': f'Invalid file type. Allowed: {", ".join(sorted(VIDEO_EXTENSIONS))}'}), 400

    file_data = _read_upload_limited(file, MAX_VIDEO_SIZE)
    if file_data is None:
        return jsonify({'error': 'File too large (max 100MB)'}), 400

    if not _validate_video_content(file_data, ext):
        return jsonify({'error': 'File content does not match extension. Upload rejected.'}), 400

    filename = f"{uuid.uuid4().hex}.{ext}"
    ok, err = _save_upload_verified(file_data, filename)
    if not ok:
        return jsonify({'error': f'파일 저장에 실패했습니다: {err}'}), 500

    return jsonify({
        'url': f'/api/community/uploads/{filename}',
        'filename': filename,
        'original_name': file.filename,
    })


@community_bp.route('/uploads/<filename>', methods=['GET'])
def serve_upload(filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext in FORMULA_FILE_EXTENSIONS:
        return jsonify({'error': 'Use the protected download endpoint'}), 403
    if (
        ext not in ALLOWED_EXTENSIONS | VIDEO_EXTENSIONS
        or not re.fullmatch(r'[0-9a-f]{32}\.[a-z0-9]+', filename or '')
    ):
        return jsonify({'error': 'Not found'}), 404
    response = send_from_directory(UPLOAD_DIR, filename)
    response.headers['Cache-Control'] = 'public, max-age=86400'
    return response


@community_bp.route('/posts/<int:post_id>/download', methods=['GET'])
@approved_required
def download_formula_file(post_id):
    """Download formula file — requires approved purchase or admin"""
    user = _get_current_user()
    post = Post.query.get_or_404(post_id)

    if not post.file_url:
        return jsonify({'error': '파일이 없습니다.'}), 404

    # Admin can always download
    if user.role != 'admin':
        pr = PurchaseRequest.query.filter_by(
            post_id=post.id, user_id=user.id, status='approved'
        ).first()
        if not pr:
            return jsonify({'error': '구매 승인 후 다운로드할 수 있습니다.'}), 403

    # Extract stored filename from url like /api/community/uploads/xxxx.ext
    stored_filename = post.file_url.rsplit('/', 1)[-1]
    ext = stored_filename.rsplit('.', 1)[-1].lower() if '.' in stored_filename else ''
    if (
        ext not in FORMULA_FILE_EXTENSIONS
        or not re.fullmatch(r'[0-9a-f]{32}\.[a-z0-9]+', stored_filename or '')
    ):
        return jsonify({'error': 'Invalid stored file reference'}), 400
    filepath = os.path.join(UPLOAD_DIR, stored_filename)
    if not os.path.exists(filepath):
        return jsonify({'error': '파일을 찾을 수 없습니다.'}), 404

    download_name = post.file_name or stored_filename
    return send_from_directory(
        UPLOAD_DIR, stored_filename,
        as_attachment=True,
        download_name=download_name
    )


# ── Search ──

@community_bp.route('/summary', methods=['GET'])
@approved_required
def community_summary():
    """Summary stats limited to boards the authenticated member can read."""
    from datetime import datetime

    user = _get_current_user()
    boards = Board.query.filter_by(is_active=True).all()
    accessible_board_ids = [
        board.id for board in boards
        if user.role == 'admin' or _check_tier(user.tier, board.min_tier)
    ]
    visible_posts = Post.query.filter(
        Post.board_id.in_(accessible_board_ids),
        Post.is_hidden.is_(False),
    )
    total_posts = visible_posts.count()
    total_comments = (
        Comment.query.join(Post, Comment.post_id == Post.id)
        .filter(
            Post.board_id.in_(accessible_board_ids),
            Post.is_hidden.is_(False),
            Comment.is_hidden.is_(False),
        )
        .count()
    )

    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_posts = visible_posts.filter(Post.created_at >= today).count()

    # Recent posts (latest 3)
    recent = visible_posts.options(joinedload(Post.board))\
        .order_by(Post.created_at.desc()).limit(3).all()
    recent_posts = [{
        'id': p.id,
        'title': p.title[:40],
        'board_name': p.board.name if p.board else '',
        'created_at': p.created_at.isoformat() if p.created_at else '',
        'comment_count': p.comment_count,
    } for p in recent]

    # Formula market stats
    formula_count = Post.query.join(Board).filter(
        Board.id.in_(accessible_board_ids),
        Board.slug == 'formula-market',
        Post.is_hidden.is_(False),
    ).count()
    pending_purchases = (
        PurchaseRequest.query.filter_by(status='pending').count()
        if user.role == 'admin' else 0
    )

    return jsonify({
        'total_posts': total_posts,
        'total_comments': total_comments,
        'today_posts': today_posts,
        'recent_posts': recent_posts,
        'formula_count': formula_count,
        'pending_purchases': pending_purchases,
    })


@community_bp.route('/search', methods=['GET'])
@approved_required
def search_posts():
    user = _get_current_user()
    q = request.args.get('q', '').strip()
    board_slug = request.args.get('board', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20

    if not q or len(q) < 2:
        return jsonify({'posts': [], 'notices': [], 'total': 0, 'page': 1, 'per_page': per_page, 'total_pages': 0})

    query = Post.query.join(Board).filter(
        Post.is_hidden == False,
        Board.is_active == True,
    )

    if board_slug:
        query = query.filter(Board.slug == board_slug)

    # Tier filter: exclude boards user can't access
    if user.role != 'admin':
        user_tier_val = TIER_ORDER.get(user.tier, 0)
        accessible_tiers = [t for t, v in TIER_ORDER.items() if v <= user_tier_val]
        query = query.filter(Board.min_tier.in_(accessible_tiers))

    query = query.filter(
        db.or_(Post.title.ilike(f'%{q}%'), Post.content.ilike(f'%{q}%'))
    )
    query = query.order_by(Post.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'posts': [p.to_dict() for p in pagination.items],
        'notices': [],
        'total': pagination.total,
        'page': page,
        'per_page': per_page,
        'total_pages': pagination.pages,
    })
