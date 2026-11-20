"""Persistence for the Muse-placed orders channel (v4.19.15).

Three tables:

- ``claude_agent_configs``: one row per user holding the feature master
  switch, the Fernet-encrypted spoken PIN and its lifecycle, the hashed
  agent API key, the failed-attempt lockout state, and the per-account
  enable switchboard (accounts default to enabled; the JSON lists the
  DISABLED account keys).
- ``claude_order_drafts``: short-lived pending order drafts Muse creates
  before the user confirms with the PIN.
- ``claude_order_audit``: one row per agent action (place / replace /
  cancel) — the authoritative record of Muse-placed orders shown in
  Settings.
"""

from datetime import datetime

from core.extensions import db


class ClaudeAgentConfig(db.Model):
    __tablename__ = 'claude_agent_configs'

    user_id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    # ONE Muse PIN for every environment (Joseph's correction, Nov 20,
    # 2026 — there is deliberately no per-environment PIN). The order's
    # environment is recorded on each draft, never bound to the PIN.
    pin_encrypted = db.Column(db.Text, nullable=True)
    pin_set_at = db.Column(db.DateTime, nullable=True)
    pin_expires_at = db.Column(db.DateTime, nullable=True)
    auto_generate_enabled = db.Column(db.Boolean, nullable=False, default=True)
    agent_key_hash = db.Column(db.String(64), nullable=True, index=True)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked = db.Column(db.Boolean, nullable=False, default=False)
    disabled_accounts_json = db.Column(db.Text, nullable=False, default='[]')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ClaudeOrderDraft(db.Model):
    __tablename__ = 'claude_order_drafts'

    id = db.Column(db.String(32), primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    kind = db.Column(db.String(30), nullable=False)
    # 'real' or 'paper' — derived from the target account's mode at draft
    # creation and named in the read-back. Informational only: the single
    # Muse PIN verifies for either environment.
    environment = db.Column(db.String(10), nullable=False, default='real')
    spec_json = db.Column(db.Text, nullable=False)
    readback_json = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='PENDING')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    confirmed_at = db.Column(db.DateTime, nullable=True)
    result_json = db.Column(db.Text, nullable=True)

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'kind': self.kind,
            'environment': self.environment,
            'status': self.status,
            'spec': json.loads(self.spec_json) if self.spec_json else {},
            'readback': json.loads(self.readback_json) if self.readback_json else {},
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'confirmed_at': self.confirmed_at.isoformat() if self.confirmed_at else None,
        }


class ClaudeOrderAudit(db.Model):
    __tablename__ = 'claude_order_audit'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    action = db.Column(db.String(20), nullable=False)  # place / replace / cancel
    draft_id = db.Column(db.String(32), nullable=True)
    kind = db.Column(db.String(30), nullable=True)
    environment = db.Column(db.String(10), nullable=True)
    broker = db.Column(db.String(20), nullable=True)
    account_id = db.Column(db.String(80), nullable=True)
    symbol = db.Column(db.String(40), nullable=True)
    spec_json = db.Column(db.Text, nullable=True)
    request_text = db.Column(db.Text, nullable=True)
    result_status = db.Column(db.String(20), nullable=False, default='SUCCESS')
    broker_order_id = db.Column(db.String(120), nullable=True)
    ladder_order_id = db.Column(db.Integer, nullable=True)
    message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'action': self.action,
            'draft_id': self.draft_id,
            'kind': self.kind,
            'environment': self.environment,
            'broker': self.broker,
            'account_id': self.account_id,
            'symbol': self.symbol,
            'spec': json.loads(self.spec_json) if self.spec_json else None,
            'request_text': self.request_text,
            'result_status': self.result_status,
            'broker_order_id': self.broker_order_id,
            'ladder_order_id': self.ladder_order_id,
            'message': self.message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
