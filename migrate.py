import sys
sys.path.append('.')
from main import app
from core.extensions import db
from credentials import Credential, UserSetting
from database import init_db

with app.app_context():
    init_db()
    # Data is now copied by init_db? No, init_db just creates columns.
    
    # Copy credentials
    creds = Credential.query.all()
    for c in creds:
        # We need to use raw SQL since the model properties changed to quaternary
        pass
    
    # Actually raw SQL is easier
    try:
        db.session.execute("UPDATE credentials SET inception_key_quaternary = inception_key_quartan WHERE inception_key_quartan IS NOT NULL")
        db.session.execute("UPDATE credentials SET gemini_key_quaternary = gemini_key_quartan WHERE gemini_key_quartan IS NOT NULL")
        db.session.execute("UPDATE credentials SET zai_key_quaternary = zai_key_quartan WHERE zai_key_quartan IS NOT NULL")
        db.session.execute("UPDATE credentials SET openai_key_quaternary = openai_key_quartan WHERE openai_key_quartan IS NOT NULL")
        db.session.execute("UPDATE credentials SET perplexity_key_quaternary = perplexity_key_quartan WHERE perplexity_key_quartan IS NOT NULL")
        
        db.session.execute("UPDATE user_settings SET ai_provider_quaternary = ai_provider_quartan WHERE ai_provider_quartan IS NOT NULL")
        db.session.execute("UPDATE user_settings SET ai_model_quaternary = ai_model_quartan WHERE ai_model_quartan IS NOT NULL")
        db.session.execute("UPDATE user_settings SET ai_reasoning_level_quaternary = ai_reasoning_level_quartan WHERE ai_reasoning_level_quartan IS NOT NULL")
        db.session.commit()
        print("Data migration successful")
    except Exception as e:
        print("Migration error (might be normal if columns don't exist):", e)
        db.session.rollback()
