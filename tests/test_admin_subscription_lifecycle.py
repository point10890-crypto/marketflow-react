"""Admin expiry and deletion use isolated SQLite, real auth, and no transports."""
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest
from flask import Flask
from sqlalchemy import event, text

from app.auth.decorators import generate_token
from app.models import db
from app.models.community import Board, Comment, Post, PostImage, PurchaseRequest
from app.models.user import AdminAuditLog, SubscriptionRequest, User
import app.routes.admin as admin_routes
import app.routes.auth as auth_routes


def _member(**values):
    user = User(**{
        'email': f'member-{User.query.count()}@example.com', 'name': 'Fixture member',
        'password_hash': 'unused', 'status': 'approved', 'tier': 'pro',
        'pro_expires_at': datetime.now(timezone.utc) + timedelta(days=10),
        **values,
    })
    db.session.add(user)
    db.session.commit()
    return user


def _headers(user):
    return {'Authorization': 'Bearer ' + generate_token(user.id)}


@pytest.fixture
def lifecycle(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config.update(
        TESTING=True, SECRET_KEY='isolated-lifecycle-test',
        SQLALCHEMY_DATABASE_URI='sqlite:///' + (tmp_path / 'members.db').as_posix(),
    )
    db.init_app(app)
    app.register_blueprint(admin_routes.admin_bp, url_prefix='/api/admin')
    app.register_blueprint(auth_routes.auth_bp, url_prefix='/api/auth')
    notifications = []

    def no_network(*args, **kwargs):
        raise AssertionError('Lifecycle tests must not call external providers')

    monkeypatch.setattr('requests.sessions.Session.request', no_network)
    monkeypatch.setattr(auth_routes, '_notify_admin_telegram', lambda *args, **kwargs: None)
    monkeypatch.setattr(admin_routes, '_notify_member', lambda *args, **kwargs: None)

    with app.app_context():
        engine = db.engine

        @event.listens_for(engine, 'connect')
        def foreign_keys_on(connection, _record):
            connection.execute('PRAGMA foreign_keys=ON')

        db.create_all()
        admin = _member(email='admin@example.com', role='admin', tier='premium')

        def notify_after_commit(action, target, detail=''):
            # A separate connection must already see both mutation and audit.
            with engine.connect() as connection:
                status = connection.execute(text('SELECT status FROM users WHERE id=:id'), {'id': target.id}).scalar()
                audits = connection.execute(text('SELECT COUNT(*) FROM admin_audit_log WHERE target_user_id=:id'), {'id': target.id}).scalar()
            notifications.append({'action': action, 'status': status, 'audits': audits})

        monkeypatch.setattr(admin_routes, '_notify_admin', notify_after_commit)
        yield SimpleNamespace(app=app, client=app.test_client(), admin=admin,
                              headers=_headers(admin), notifications=notifications, engine=engine)
        db.session.remove()
        engine.dispose()


@pytest.mark.parametrize('tier', ['pro', 'premium'])
def test_expire_ends_base_and_addon_without_removing_history(lifecycle, tier):
    ctx = lifecycle
    target = _member(tier=tier, aibain_enabled=True,
                     aibain_expires_at=datetime.now(timezone.utc) + timedelta(days=20),
                     kongming_expires_at=datetime.now(timezone.utc) + timedelta(days=25),
                     pro_paused_at=datetime.now(timezone.utc) - timedelta(days=2),
                     requested_tier=tier)
    target_id = target.id
    token = _headers(target)
    pending = SubscriptionRequest(user_id=target_id, request_type='renewal',
                                  from_tier=tier, to_tier=tier, status='pending', amount='history amount')
    approved = SubscriptionRequest(user_id=target_id, request_type='upgrade',
                                   from_tier='none', to_tier=tier, status='approved')
    board = Board(slug='history', name='History')
    db.session.add_all([pending, approved, board])
    db.session.flush()
    post = Post(board_id=board.id, author_id=target_id, title='Keep', content='Keep')
    db.session.add(post)
    db.session.flush()
    purchase = PurchaseRequest(post_id=post.id, user_id=target_id, buyer_name='Fixture', status='approved')
    db.session.add(purchase)
    db.session.commit()
    pending_id, approved_id, post_id, purchase_id = pending.id, approved.id, post.id, purchase.id

    response = ctx.client.post(f'/api/admin/users/{target_id}/expire', headers=ctx.headers,
                               json={'note': '  operator expiry  '})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['message']
    assert payload['user']['status'] == 'expired'
    assert payload['user']['tier'] == tier
    assert payload['user']['aibain_enabled'] is False
    assert payload['user']['is_aibain_active'] is False
    assert payload['user']['is_kongming_active'] is False
    assert payload['user']['pro_paused_at'] is None
    db.session.expire_all()
    target = db.session.get(User, target_id)
    assert target.pro_expires_at < datetime.now(timezone.utc).replace(tzinfo=None)
    assert target.aibain_expires_at < datetime.now(timezone.utc).replace(tzinfo=None)
    assert target.kongming_expires_at < datetime.now(timezone.utc).replace(tzinfo=None)
    assert target.pro_expiry_alert_stage == target.aibain_alert_stage == 'expired'
    assert db.session.get(SubscriptionRequest, pending_id).status == 'pending'
    assert db.session.get(SubscriptionRequest, pending_id).amount == 'history amount'
    assert db.session.get(SubscriptionRequest, approved_id).status == 'approved'
    assert db.session.get(Post, post_id) is not None
    assert db.session.get(PurchaseRequest, purchase_id) is not None
    assert target.requested_tier == tier
    audit = AdminAuditLog.query.filter_by(action='expire_subscription', target_user_id=target_id).one()
    assert audit.note == 'operator expiry'
    assert json.loads(audit.before)['status'] == 'approved'
    assert json.loads(audit.after)['status'] == 'expired'
    assert ctx.notifications == [{'action': '구독 전체 만료 처리', 'status': 'expired', 'audits': 1}]
    me = ctx.client.get('/api/auth/me', headers=token)
    assert me.status_code == 200
    assert me.get_json()['user']['status'] == 'expired'
    assert me.get_json()['user']['has_pending_subscription'] is True


@pytest.mark.parametrize('tier', ['pro', 'premium'])
def test_expired_member_can_request_renewal_and_regain_base_and_addon(lifecycle, tier):
    ctx = lifecycle
    target = _member(tier=tier, aibain_enabled=True, aibain_expires_at=None,
                     pro_paused_at=datetime.now(timezone.utc))
    target_id, token = target.id, _headers(target)
    assert ctx.client.post(f'/api/admin/users/{target_id}/expire', headers=ctx.headers).status_code == 200
    renewal = ctx.client.post('/api/auth/subscription/request', headers=token,
                              json={'to_tier': tier})
    assert renewal.status_code == 201
    assert renewal.get_json()['request']['request_type'] == 'renewal'
    request_id = renewal.get_json()['request']['id']
    approved = ctx.client.put(f'/api/admin/subscriptions/{request_id}/approve', headers=ctx.headers)
    assert approved.status_code == 200
    assert approved.get_json()['user']['status'] == 'approved'
    assert approved.get_json()['user']['is_pro_expired'] is False
    assert approved.get_json()['user']['aibain_enabled'] is False
    addon = ctx.client.post(f'/api/admin/users/{target_id}/aibain/enable', headers=ctx.headers,
                            json={'days': 30})
    assert addon.status_code == 200
    assert addon.get_json()['user']['is_aibain_active'] is True


def test_forced_expiry_does_not_restore_bundle_after_account_was_moved_to_pending(lifecycle):
    user = _member(tier=None, pro_expires_at=None,
                   kongming_expires_at=datetime.now(timezone.utc) + timedelta(days=10))
    url = f'/api/admin/users/{user.id}'
    pending = lifecycle.client.put(f'{url}/status', headers=lifecycle.headers, json={'status': 'pending'})
    assert pending.status_code == 200
    assert pending.get_json()['user']['is_kongming_active'] is False

    expired = lifecycle.client.post(f'{url}/expire', headers=lifecycle.headers, json={})
    assert expired.status_code == 200
    payload = expired.get_json()['user']
    assert payload['status'] == 'expired'
    assert payload['is_kongming_active'] is False
    expired_at = datetime.fromisoformat(payload['kongming_expires_at'])
    if expired_at.tzinfo is None:
        expired_at = expired_at.replace(tzinfo=timezone.utc)
    assert expired_at < datetime.now(timezone.utc)


@pytest.mark.parametrize('status', ['suspended', 'rejected'])
def test_expire_cannot_unlock_a_blocked_account(lifecycle, status):
    target = _member(status=status, aibain_enabled=True)
    response = lifecycle.client.post(f'/api/admin/users/{target.id}/expire', headers=lifecycle.headers)
    assert response.status_code == 409
    db.session.expire_all()
    assert db.session.get(User, target.id).status == status
    assert db.session.get(User, target.id).aibain_enabled is True
    assert AdminAuditLog.query.count() == 0
    assert lifecycle.notifications == []


@pytest.mark.parametrize('self_target', [False, True])
def test_expire_protects_every_admin_account(lifecycle, self_target):
    target = lifecycle.admin if self_target else _member(role='admin', tier='premium')
    response = lifecycle.client.post(f'/api/admin/users/{target.id}/expire', headers=lifecycle.headers)
    assert response.status_code == 400
    assert db.session.get(User, target.id).status == 'approved'


@pytest.mark.parametrize('note', [123, None, 'x' * 501])
def test_expire_rejects_invalid_notes_without_mutation(lifecycle, note):
    target = _member()
    response = lifecycle.client.post(f'/api/admin/users/{target.id}/expire', headers=lifecycle.headers,
                                     json={'note': note})
    assert response.status_code == 400
    assert db.session.get(User, target.id).status == 'approved'
    assert AdminAuditLog.query.count() == 0


@pytest.mark.parametrize('body,content_type', [
    ('{', 'application/json'),
    ('null', 'application/json'),
    ('[]', 'application/json'),
    ('   ', 'application/json'),
    ('{}', 'text/plain'),
])
def test_expire_rejects_supplied_body_unless_it_is_a_json_object(lifecycle, body, content_type):
    target = _member()
    response = lifecycle.client.post(f'/api/admin/users/{target.id}/expire', headers=lifecycle.headers,
                                     data=body, content_type=content_type)
    assert response.status_code == 400
    db.session.expire_all()
    assert db.session.get(User, target.id).status == 'approved'
    assert AdminAuditLog.query.count() == 0
    assert lifecycle.notifications == []


@pytest.mark.parametrize('operation', ['expire', 'delete'])
@pytest.mark.parametrize('actor', ['anonymous', 'member', 'suspended_admin'])
def test_lifecycle_actions_require_an_active_admin(lifecycle, operation, actor):
    target = _member()
    headers = {} if actor == 'anonymous' else _headers(_member(
        role='admin' if actor == 'suspended_admin' else 'user',
        status='suspended' if actor == 'suspended_admin' else 'approved',
    ))
    if operation == 'expire':
        response = lifecycle.client.post(f'/api/admin/users/{target.id}/expire', headers=headers)
    else:
        response = lifecycle.client.delete(f'/api/admin/users/{target.id}', headers=headers)
    assert response.status_code == (401 if actor == 'anonymous' else 403)
    assert db.session.get(User, target.id) is not None
    assert AdminAuditLog.query.count() == 0


def _conversation(target, other):
    board = Board(slug='discussion', name='Discussion')
    db.session.add(board)
    db.session.flush()
    retained_post = Post(board_id=board.id, author_id=other.id, title='Retained', content='Retained')
    removed_post = Post(board_id=board.id, author_id=target.id, title='Removed', content='Removed')
    db.session.add_all([retained_post, removed_post])
    db.session.flush()
    parent = Comment(post_id=retained_post.id, author_id=target.id, content='Removed parent')
    db.session.add(parent)
    db.session.flush()
    reply = Comment(post_id=retained_post.id, author_id=other.id, parent_id=parent.id, content='Keep reply')
    image = PostImage(post_id=removed_post.id, filename='fixture-only.png')
    comment_on_removed_post = Comment(post_id=removed_post.id, author_id=other.id, content='Remove with post')
    purchase = PurchaseRequest(post_id=removed_post.id, user_id=other.id, buyer_name='Fixture')
    subscription = SubscriptionRequest(user_id=target.id, request_type='renewal', from_tier='pro', to_tier='pro')
    db.session.add_all([reply, image, comment_on_removed_post, purchase, subscription])
    db.session.commit()
    return {'parent': parent.id, 'reply': reply.id, 'retained_post': retained_post.id,
            'removed_post': removed_post.id, 'image': image.id, 'purchase': purchase.id,
            'subscription': subscription.id}


def test_delete_preserves_other_authors_reply_with_foreign_keys_enabled(lifecycle):
    ctx = lifecycle
    target, other = _member(), _member()
    target_id, token = target.id, _headers(target)
    ids = _conversation(target, other)
    prior_audit = AdminAuditLog(action='set_tier', target_user_id=target_id, target_email=target.email)
    db.session.add(prior_audit)
    db.session.commit()
    prior_id = prior_audit.id
    assert db.session.execute(text('PRAGMA foreign_keys')).scalar() == 1
    response = ctx.client.delete(f'/api/admin/users/{target_id}', headers=ctx.headers)
    assert response.status_code == 200
    db.session.expire_all()
    assert db.session.get(User, target_id) is None
    assert db.session.get(Comment, ids['parent']) is None
    reply = db.session.get(Comment, ids['reply'])
    assert reply.parent_id is None
    assert reply.content == 'Keep reply'
    assert db.session.get(Post, ids['retained_post']) is not None
    assert db.session.get(Post, ids['removed_post']) is None
    assert db.session.get(PostImage, ids['image']) is None
    assert db.session.get(PurchaseRequest, ids['purchase']) is None
    assert db.session.get(SubscriptionRequest, ids['subscription']) is None
    assert db.session.get(AdminAuditLog, prior_id) is not None
    assert AdminAuditLog.query.filter_by(action='delete_user', target_user_id=target_id).count() == 1
    assert db.session.execute(text('PRAGMA foreign_key_check')).all() == []
    assert ctx.client.get('/api/auth/me', headers=token).status_code == 401


@pytest.mark.parametrize('operation', ['expire', 'delete'])
def test_audit_insert_failure_rolls_back_entire_lifecycle_change(lifecycle, operation, caplog):
    ctx = lifecycle
    target, other = _member(aibain_enabled=True), _member()
    target_id = target.id
    ids = _conversation(target, other)
    audit_attempted = []

    def reject_audit(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith('INSERT INTO ADMIN_AUDIT_LOG'):
            audit_attempted.append(True)
            raise RuntimeError('private database detail must never reach client or log')

    event.listen(ctx.engine, 'before_cursor_execute', reject_audit)
    try:
        if operation == 'expire':
            response = ctx.client.post(f'/api/admin/users/{target_id}/expire', headers=ctx.headers)
        else:
            response = ctx.client.delete(f'/api/admin/users/{target_id}', headers=ctx.headers)
    finally:
        event.remove(ctx.engine, 'before_cursor_execute', reject_audit)
    assert response.status_code == 500
    assert audit_attempted, 'The failure must occur at the audit insert, after source changes.'
    assert 'private database detail' not in response.get_data(as_text=True)
    assert 'private database detail' not in caplog.text
    db.session.expire_all()
    target = db.session.get(User, target_id)
    assert target.status == 'approved'
    assert target.aibain_enabled is True
    assert db.session.get(Comment, ids['parent']) is not None
    assert db.session.get(Comment, ids['reply']).parent_id == ids['parent']
    assert db.session.get(Post, ids['removed_post']) is not None
    assert db.session.get(SubscriptionRequest, ids['subscription']) is not None
    assert AdminAuditLog.query.count() == 0
    assert ctx.notifications == []


def test_delete_self_stays_protected(lifecycle):
    response = lifecycle.client.delete(f'/api/admin/users/{lifecycle.admin.id}', headers=lifecycle.headers)
    assert response.status_code == 400
    assert db.session.get(User, lifecycle.admin.id) is not None


def test_legacy_revoke_keeps_pro_only_and_does_not_disable_addon(lifecycle):
    premium = _member(tier='premium')
    assert lifecycle.client.post(f'/api/admin/users/{premium.id}/revoke', headers=lifecycle.headers,
                                  json={}).status_code == 400
    pro = _member(aibain_enabled=True, pro_paused_at=datetime.now(timezone.utc),
                  kongming_expires_at=datetime.now(timezone.utc) + timedelta(days=10))
    response = lifecycle.client.post(f'/api/admin/users/{pro.id}/revoke', headers=lifecycle.headers, json={})
    assert response.status_code == 200
    assert response.get_json()['user']['status'] == 'approved'
    assert response.get_json()['user']['is_pro_expired'] is True
    assert response.get_json()['user']['aibain_enabled'] is True
    assert response.get_json()['user']['is_kongming_active'] is True


def test_reject_cannot_overwrite_an_approval_after_a_stale_pending_read(lifecycle, monkeypatch):
    ctx = lifecycle
    target = _member(status='pending', tier=None, pro_expires_at=None, requested_tier='pro')
    target_id = target.id
    pending = SubscriptionRequest(user_id=target_id, request_type='upgrade',
                                  from_tier='none', to_tier='pro', status='pending')
    db.session.add(pending)
    db.session.commit()
    request_id = pending.id
    real_get = db.session.get
    stale_read = []

    def approval_after_read(model, key, *args, **kwargs):
        result = real_get(model, key, *args, **kwargs)
        if model is SubscriptionRequest and key == request_id and not stale_read:
            stale_read.append(True)
            result.to_dict()  # Keep the stale snapshot's relationship loaded.
            db.session.expunge(result)
            # Preserve a pending ORM snapshot while the committed row advances.
            db.session.execute(text('UPDATE subscription_requests SET status=:status WHERE id=:id'),
                               {'status': 'approved', 'id': request_id})
            db.session.commit()
        return result

    monkeypatch.setattr(db.session, 'get', approval_after_read)
    response = ctx.client.put(f'/api/admin/subscriptions/{request_id}/reject', headers=ctx.headers,
                               json={'note': 'late rejection'})
    assert response.status_code == 400
    db.session.expire_all()
    assert real_get(SubscriptionRequest, request_id).status == 'approved'
    assert real_get(User, target_id).requested_tier == 'pro'
    assert AdminAuditLog.query.count() == 0


def test_pending_rejection_still_records_note_and_clears_initial_plan_marker(lifecycle):
    ctx = lifecycle
    target = _member(status='pending', tier=None, pro_expires_at=None, requested_tier='pro')
    pending = SubscriptionRequest(user_id=target.id, request_type='upgrade',
                                  from_tier='none', to_tier='pro', status='pending')
    db.session.add(pending)
    db.session.commit()
    request_id, target_id = pending.id, target.id
    response = ctx.client.put(f'/api/admin/subscriptions/{request_id}/reject', headers=ctx.headers,
                               json={'admin_note': 'check payment'})
    assert response.status_code == 200
    assert response.get_json()['request']['status'] == 'rejected'
    assert response.get_json()['request']['admin_note'] == 'check payment'
    db.session.expire_all()
    assert db.session.get(User, target_id).requested_tier is None


@pytest.mark.parametrize('operation', ['expire', 'delete'])
def test_lifecycle_missing_target_returns_404(lifecycle, operation):
    if operation == 'expire':
        response = lifecycle.client.post('/api/admin/users/99999/expire', headers=lifecycle.headers)
    else:
        response = lifecycle.client.delete('/api/admin/users/99999', headers=lifecycle.headers)
    assert response.status_code == 404


def test_expire_accepts_maximum_note_and_repeated_expiry_keeps_access_closed(lifecycle):
    target = _member(tier='premium', aibain_enabled=True)
    target_id = target.id
    for _ in range(2):
        response = lifecycle.client.post(f'/api/admin/users/{target_id}/expire', headers=lifecycle.headers,
                                         json={'note': 'x' * 500})
        assert response.status_code == 200
        assert response.get_json()['user']['status'] == 'expired'
        assert response.get_json()['user']['aibain_enabled'] is False
        assert response.get_json()['user']['tier'] == 'premium'
