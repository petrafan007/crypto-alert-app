from flask import Blueprint, request, jsonify, session, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash

from core.extensions import db
from credentials import User, Credential, UserSetting
from models import DefaultAIPrompt, AIPrompt
from log import logger
from services.credential_service import get_user_credentials

# Import extensions if needed

# Create Blueprint
auth_bp = Blueprint('auth', __name__)

@auth_bp.route("/api/login", methods=["POST"])
def api_login():
    """API endpoint for logging in. Returns JSON only."""
    data = request.get_json() or request.form
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return jsonify({"success": False, "error": "Username and password required."}), 400
    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
        login_user(user, remember=True)
        session.permanent = True
        return jsonify({"success": True, "user": {"username": user.username, "id": user.id}})
    return jsonify({"success": False, "error": "Invalid username or password."}), 401

@auth_bp.route("/api/logout", methods=["POST"])
@login_required
def api_logout():
    """API endpoint for logging out. Returns JSON only."""
    logger.info(f"Logging out user via API: {current_user.username if current_user.is_authenticated else 'Anonymous'}")
    logger.info(f"Session before logout: {dict(session)}")
    logout_user()
    session.clear()
    session.pop('_flashes', None)
    session.pop('user_id', None)  
    session.pop('username', None)
    session.modified = True
    logger.info(f"Session after logout: {dict(session)}")
    logger.info("User logged out successfully via API")
    return jsonify({"success": True})

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if request.is_json:
            data = request.get_json()
            username = data.get('username')
            password = data.get('password')
        else:
            username = request.form.get('username')
            password = request.form.get('password')
        
        if not username or not password:
            return jsonify({"error": "Username and password are required"}), 400
        try:
            # Check if user exists
            user = db.session.query(User).filter_by(username=username).first()
            if user:
                return jsonify({"error": "Username already exists"}), 400
            
            # Create new user
            new_user = User(username=username)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            
            # Create empty Credential record for the new user
            new_cred = Credential(user_id=new_user.id, username=new_user.username)
            db.session.add(new_cred)
            db.session.commit()

            # Create default UserSetting record
            new_settings = UserSetting(user_id=new_user.id)
            db.session.add(new_settings)
            db.session.commit()
            
            # Seed all 10 AI prompts from defaults
            try:
                defaults = DefaultAIPrompt.query.first()
                if defaults:
                    new_prompts = AIPrompt(
                        user_id=new_user.id,
                        market_analysis_pre=defaults.market_analysis_pre,
                        market_analysis_post=defaults.market_analysis_post,
                        risk_assessment_pre=defaults.risk_assessment_pre,
                        risk_assessment_post=defaults.risk_assessment_post,
                        portfolio_review_pre=defaults.portfolio_review_pre,
                        portfolio_review_post=defaults.portfolio_review_post,
                        coin_analysis_pre=defaults.coin_analysis_pre,
                        coin_analysis_post=defaults.coin_analysis_post,
                        sentiment_prompt_pre=defaults.sentiment_prompt_pre,
                        sentiment_prompt_post=defaults.sentiment_prompt_post,
                        news_analysis_pre=getattr(defaults, 'news_analysis_pre', ''),
                        news_analysis_post=getattr(defaults, 'news_analysis_post', '')
                    )
                    db.session.add(new_prompts)
                    db.session.commit()
                    logger.info(f"Seeded 10 AI prompts for new user {new_user.id}")
            except Exception as prompt_err:
                logger.warning(f"Failed to seed prompts for new user: {prompt_err}")
            
            login_user(new_user)
            return jsonify({"success": True, "redirect": "/settings?new_user=true", "user_id": new_user.id}), 200
            
        except Exception as e:
            logger.error(f"Registration error: {str(e)}")
            db.session.rollback()
            return jsonify({"error": f"Registration failed: {str(e)}"}), 500
    return jsonify({"error": "GET method not supported"}), 405

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    logger.info(f"Login request: method={request.method}")
    if request.method == "POST":
        logger.info("Login POST request received")
        try:
            username = request.form["username"]
            password = request.form["password"]
            logger.info(f"Login attempt for username: {username}")
            
            user = User.query.filter_by(username=username).first()
            logger.info(f"User found: {user is not None}")
                
            if user and user.check_password(password):
                logger.info(f"Password check successful for user: {username}")
                login_user(user, remember=True)
                session.permanent = True
                logger.info("Login successful, redirecting to dashboard")
                return redirect(url_for("dashboard"))
            else:
                logger.error(f"Login failed: invalid username or password for {username}")
                return jsonify({"error": "Invalid username or password"}), 401
        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            return jsonify({"error": str(e)}), 500
    
    # For GET requests, serve the React app by importing the shared helper
    from main import serve_react_app
    logger.info("Login GET request, serving React app")
    return serve_react_app()

@auth_bp.route("/logout")
def logout():
    logger.info(f"Logging out user via GET: {current_user.username if current_user.is_authenticated else 'Anonymous'}")
    logger.info(f"Session before logout: {dict(session)}")
    logout_user()
    session.clear()
    session.pop('_flashes', None)
    session.pop('user_id', None)  
    session.pop('username', None)
    session.modified = True
    logger.info(f"Session after logout: {dict(session)}")
    logger.info("User logged out successfully via GET")
    return redirect(url_for("auth.login"))

@auth_bp.route("/reset-password", methods=["GET", "POST"])
@login_required
def reset_password():
    if request.method == "POST":
        password = request.form.get("password")
        if not password or len(password) < 6:
            return jsonify({"error": "Password must be at least 6 characters"}), 400
        user = db.session.get(User, current_user.id)
        user.pwd_hash = generate_password_hash(password)
        db.session.commit()
        return jsonify({"success": True, "message": "Password updated"})
    
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Reset Password</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            .form-group { margin-bottom: 15px; }
            input[type="password"] { padding: 8px; width: 200px; }
            button { padding: 10px 20px; background: #007bff; color: white; border: none; cursor: pointer; }
            button:hover { background: #0056b3; }
        </style>
    </head>
    <body>
        <h2>Reset Password</h2>
        <form method="POST">
            <div class="form-group">
                <label for="password">New Password:</label><br>
                <input type="password" id="password" name="password" required minlength="6">
            </div>
            <button type="submit">Update Password</button>
        </form>
    </body>
    </html>
    '''
