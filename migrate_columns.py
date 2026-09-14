import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv("/home/jcavallarojr/crypto_alert_app/.env")
db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost/cryptoalertapp")
print(f"Connecting to {db_url}")
engine = create_engine(db_url)
with engine.begin() as conn:
    try:
        conn.execute(text("ALTER TABLE default_ai_prompts ADD COLUMN copilot_title_prompt TEXT;"))
        print("Added to default_ai_prompts")
    except Exception as e:
        print("Error on default_ai_prompts:", e)
    
    try:
        conn.execute(text("ALTER TABLE ai_prompts ADD COLUMN copilot_title_prompt TEXT;"))
        print("Added to ai_prompts")
    except Exception as e:
        print("Error on ai_prompts:", e)
        
    try:
        conn.execute(text("ALTER TABLE user_settings ADD COLUMN copilot_title_prompt TEXT;"))
        print("Added to user_settings")
    except Exception as e:
        print("Error on user_settings:", e)
