"""Snapshot one user's non-secret defaults for future registrations."""

import argparse

from main import app
from core.extensions import db
from credentials import User
from services.onboarding_service import snapshot_defaults


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--username', required=True)
    args = parser.parse_args()
    with app.app_context():
        user = User.query.filter_by(username=args.username).first()
        if not user:
            raise SystemExit(f'User not found: {args.username}')
        snapshot_defaults(user.id)
        db.session.commit()
        print(f'Onboarding defaults snapshotted from user id {user.id}.')


if __name__ == '__main__':
    main()
