from datetime import datetime, timedelta
import pytz
from flask import current_app
from models import db, User, AIAnalysisSchedule, UserSetting
from services.helpers import get_user_ai_settings
import logging

logger = logging.getLogger(__name__)

def get_eastern_now():
    """Get current time in US/Eastern timezone"""
    return datetime.now(pytz.timezone('US/Eastern'))

def _parse_iso(value, default=None):
    """
    Safely parse a datetime or ISO string into an Eastern-aware datetime.
    Returns `default` when parsing fails.
    """
    try:
        if value is None:
            return default

        # Accept already-materialized datetimes
        if isinstance(value, datetime):
            dt_obj = value
        else:
            dt_obj = datetime.fromisoformat(str(value))

        # Assume UTC when tzinfo is missing, then convert to Eastern
        if dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=pytz.utc)

        return dt_obj.astimezone(pytz.timezone('US/Eastern'))
    except Exception as e:
        logger.error(f"Failed to parse datetime value '{value}': {e}")
        return default

def _get_analysis_window_bounds(settings, now):
    """Get the window start and end times for today based on settings"""
    window_start_hour = settings.get('ai_analysis_window_start', 9)
    window_end_hour = settings.get('ai_analysis_window_end', 21)
    
    window_start = now.replace(hour=window_start_hour, minute=0, second=0, microsecond=0)
    window_end = now.replace(hour=window_end_hour, minute=0, second=0, microsecond=0)
    
    return window_start, window_end

def is_user_analysis_window_active(user_id):
    """Check if the current time is within the user's analysis window"""
    user = User.query.filter_by(id=user_id).first()
    if not user:
        return False
        
    settings = get_user_ai_settings(user.username)
    now = get_eastern_now()
    
    window_start, window_end = _get_analysis_window_bounds(settings, now)
    return window_start <= now <= window_end

def should_run_ai_analysis(user_id):
    """Check if AI analysis should run based on schedule and frequency settings"""
    try:
        schedule = AIAnalysisSchedule.query.filter_by(user_id=user_id).first()
        
        user = User.query.filter_by(id=user_id).first()
        if not user:
            return False

        settings = get_user_ai_settings(user.username)
        frequency = settings.get('ai_analysis_frequency', 'daily').lower()
        now = get_eastern_now()
        
        # Helper to get window bounds for today
        window_start, window_end = _get_analysis_window_bounds(settings, now)

        # Initialize schedule if not exists
        if not schedule:
            # If no previous run, we should run now (or at window start if hourly)
            initial_next_run = now
            if frequency == 'hourly':
                # For hourly, if we are before window, wait for window
                if now < window_start:
                    initial_next_run = window_start
                elif now > window_end:
                     # If after window, wait for next day window
                    initial_next_run = window_start + timedelta(days=1)
            
            schedule = AIAnalysisSchedule(
                user_id=user_id,
                last_analysis=None,
                next_analysis=initial_next_run
            )
            db.session.add(schedule)
            db.session.commit()
            
            # If we are ready to run
            return now >= initial_next_run

        last_run = schedule.last_analysis
        
        # If never ran, logic is simpler: check if we hit next_analysis
        if not last_run:
            # Sanity check if we missed the next_analysis by a lot, just run now
            next_analysis_dt = _parse_iso(schedule.next_analysis, default=now)
            if next_analysis_dt and now >= next_analysis_dt:
                return True
            return False

        # Calculate when we SHOULD run next based on last_run
        last_run_local = _parse_iso(last_run, default=now - timedelta(days=1))
        
        if frequency == 'hourly':
            # HOURLY: Must respect Window AND 1 hour interval
            # 1. Check Window
            if not (window_start <= now <= window_end):
                return False
            
            # 2. Check 1 hour interval
            next_run_time = last_run_local + timedelta(hours=1)
            return now >= next_run_time

        elif frequency == 'weekly':
            # WEEKLY: Simple 7 day interval, ignore window
            next_run_time = last_run_local + timedelta(days=7)
            return now >= next_run_time
        
        else: # Default 'daily'
            # DAILY: Simple 24 hour interval, ignore window
            next_run_time = last_run_local + timedelta(days=1)
            return now >= next_run_time

    except Exception as e:
        logger.error(f"Error checking AI analysis schedule: {e}")
        return True

def update_ai_analysis_schedule(user_id):
    """Update AI analysis schedule"""
    try:
        # Get user to get username
        user = User.query.filter_by(id=user_id).first()
        if not user:
            return

        # Get user settings for cache duration
        user_settings = get_user_ai_settings(user.username)
        cache_duration_hours = user_settings.get('ai_cache_duration_hours', 4)

        now = get_eastern_now()
        window_start, window_end = _get_analysis_window_bounds(user_settings, now)

        next_candidate = now + timedelta(hours=cache_duration_hours)
        if next_candidate < window_start:
            next_run = window_start
        elif next_candidate <= window_end:
            next_run = next_candidate
        else:
            # Schedule for next day start
            next_run = window_start + timedelta(days=1)

        schedule = AIAnalysisSchedule.query.filter_by(user_id=user_id).first()
        if schedule:
            schedule.last_analysis = now
            schedule.next_analysis = next_run
        else:
            schedule = AIAnalysisSchedule(
                user_id=user_id,
                last_analysis=now,
                next_analysis=next_run
            )
            db.session.add(schedule)
        
        db.session.commit()
    except Exception as e:
        logger.error(f"Error updating AI analysis schedule for user {user_id}: {e}")
        db.session.rollback()
