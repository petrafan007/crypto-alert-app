"""Separate, append-only market research archive; never a trading ledger."""
from datetime import datetime, timezone
from core.extensions import db


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ResearchCollectionConfig(db.Model):
    __tablename__ = 'research_collection_configs'
    user_id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    settings_json = db.Column(db.Text, nullable=False, default='{}')
    stored_bytes = db.Column(db.BigInteger, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class ResearchCollectionState(db.Model):
    __tablename__ = 'research_collection_states'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    lane = db.Column(db.String(24), nullable=False)
    status = db.Column(db.String(32), nullable=False, default='WAITING')
    heartbeat_at = db.Column(db.DateTime)
    next_run_at = db.Column(db.DateTime)
    details_json = db.Column(db.Text, nullable=False, default='{}')
    __table_args__ = (db.UniqueConstraint('user_id', 'lane', name='uq_research_collection_lane'),)


class ResearchCapture(db.Model):
    __tablename__ = 'research_captures'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    lane = db.Column(db.String(24), nullable=False)
    source = db.Column(db.String(48), nullable=False)
    kind = db.Column(db.String(48), nullable=False)
    symbol = db.Column(db.String(160), nullable=False)
    started_at = db.Column(db.DateTime, nullable=False)
    received_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    sha256 = db.Column(db.String(64), nullable=False)
    compressed_bytes = db.Column(db.Integer, nullable=False)
    raw_bytes = db.Column(db.Integer, nullable=False)
    payload_gzip = db.Column(db.LargeBinary, nullable=False)
    metadata_json = db.Column(db.Text, nullable=False, default='{}')
    __table_args__ = (
        db.Index('ix_research_capture_user_id', 'user_id', 'id'),
        db.Index('ix_research_capture_user_lane_received', 'user_id', 'lane', 'received_at'),
    )


class ResearchDataset(db.Model):
    __tablename__ = 'research_datasets'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    sha256 = db.Column(db.String(64), nullable=False)
    payload_gzip = db.Column(db.LargeBinary, nullable=False)
    summary_json = db.Column(db.Text, nullable=False)
    __table_args__ = (db.UniqueConstraint('user_id', 'sha256', name='uq_research_dataset_hash'),)


class ResearchJob(db.Model):
    __tablename__ = 'research_jobs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    kind = db.Column(db.String(24), nullable=False)
    status = db.Column(db.String(24), nullable=False, default='QUEUED')
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    request_json = db.Column(db.Text, nullable=False)
    result_gzip = db.Column(db.LargeBinary)
    summary_json = db.Column(db.Text)
    message = db.Column(db.Text)
