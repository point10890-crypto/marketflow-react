"""Community models — Board, Post, PostImage, Comment"""

from datetime import datetime, timezone
from app.models import db


class Board(db.Model):
    __tablename__ = 'boards'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, default='')
    icon = db.Column(db.String(50), default='fa-comments')
    sort_order = db.Column(db.Integer, default=0)
    min_tier = db.Column(db.String(20), default='pro')
    write_tier = db.Column(db.String(20), default='pro')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    posts = db.relationship('Post', backref='board', lazy='dynamic')

    def to_dict(self):
        latest_post = (
            self.posts.filter_by(is_hidden=False)
            .order_by(Post.updated_at.desc(), Post.created_at.desc())
            .first()
        )
        return {
            'id': self.id, 'slug': self.slug, 'name': self.name,
            'description': self.description, 'icon': self.icon,
            'sort_order': self.sort_order, 'min_tier': self.min_tier,
            'write_tier': self.write_tier, 'is_active': self.is_active,
            'post_count': self.posts.filter_by(is_hidden=False).count(),
            'latest_post_id': latest_post.id if latest_post else None,
            'latest_post_title': latest_post.title if latest_post else None,
            'latest_post_at': latest_post.updated_at.isoformat() if latest_post and latest_post.updated_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Post(db.Model):
    __tablename__ = 'posts'

    id = db.Column(db.Integer, primary_key=True)
    board_id = db.Column(db.Integer, db.ForeignKey('boards.id'), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_notice = db.Column(db.Boolean, default=False)
    is_hidden = db.Column(db.Boolean, default=False)
    view_count = db.Column(db.Integer, default=0)
    comment_count = db.Column(db.Integer, default=0)
    like_count = db.Column(db.Integer, default=0)
    # Formula market fields
    price = db.Column(db.String(50), nullable=True)
    file_url = db.Column(db.String(500), nullable=True)
    file_name = db.Column(db.String(255), nullable=True)
    is_public = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    author = db.relationship('User', backref=db.backref('posts', lazy='dynamic'))
    images = db.relationship('PostImage', backref='post', lazy='select',
                             order_by='PostImage.sort_order')
    comments = db.relationship('Comment', backref='post', lazy='dynamic')

    __table_args__ = (
        db.Index('ix_posts_board_created', 'board_id', 'is_hidden', 'created_at'),
    )

    def to_dict(self, include_content=False, user_id=None):
        d = {
            'id': self.id, 'board_id': self.board_id,
            'author': {
                'id': self.author.id, 'name': self.author.name, 'tier': self.author.tier
            } if self.author else None,
            'title': self.title,
            'is_notice': self.is_notice,
            'view_count': self.view_count,
            'comment_count': self.comment_count,
            'like_count': self.like_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_content:
            d['content'] = self.content
            d['images'] = [img.to_dict() for img in self.images]
            if self.board:
                d['board'] = {'id': self.board.id, 'slug': self.board.slug, 'name': self.board.name}
            if user_id:
                d['is_mine'] = (self.author_id == user_id)
        # Formula market fields
        if self.price is not None:
            d['price'] = self.price
        if self.file_url:
            d['file_url'] = self.file_url
            d['file_name'] = self.file_name
        d['is_public'] = self.is_public if self.is_public is not None else True
        return d


class PostImage(db.Model):
    __tablename__ = 'post_images'

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255))
    file_size = db.Column(db.Integer, default=0)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id, 'filename': self.filename,
            'original_name': self.original_name, 'file_size': self.file_size,
            'url': f'/api/community/uploads/{self.filename}',
        }


class Comment(db.Model):
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('comments.id'), nullable=True, index=True)
    content = db.Column(db.Text, nullable=False)
    is_hidden = db.Column(db.Boolean, default=False)
    like_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    author = db.relationship('User', backref=db.backref('comments', lazy='dynamic'))
    replies = db.relationship('Comment', backref=db.backref('parent', remote_side=[id]), lazy='select')

    __table_args__ = (
        db.Index('ix_comments_post_created', 'post_id', 'created_at'),
    )

    def to_dict(self):
        return {
            'id': self.id, 'post_id': self.post_id,
            'author': {
                'id': self.author.id, 'name': self.author.name, 'tier': self.author.tier
            } if self.author else None,
            'parent_id': self.parent_id,
            'content': self.content,
            'is_hidden': self.is_hidden,
            'like_count': self.like_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class PurchaseRequest(db.Model):
    __tablename__ = 'purchase_requests'

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    buyer_name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    approved_at = db.Column(db.DateTime, nullable=True)

    post = db.relationship('Post', backref=db.backref('purchases', lazy='dynamic'))
    user = db.relationship('User', backref=db.backref('purchases', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id, 'post_id': self.post_id,
            'user_id': self.user_id,
            'buyer_name': self.buyer_name,
            'status': self.status,
            'user_name': self.user.name if self.user else None,
            'post_title': self.post.title if self.post else None,
            'post_price': self.post.price if self.post else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
        }
