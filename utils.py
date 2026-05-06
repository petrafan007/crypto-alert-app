import os, requests, json, time
from log import logger

def get_access_token(username):
    # Get credentials directly using db session
    from core.extensions import db
    from sqlalchemy import text
    try:
        result = db.session.execute(
            text('SELECT oauth_client_id, oauth_secret, oauth_callback_url FROM credentials WHERE username = :username'), 
            {'username': username}
        ).fetchone()
        
        if not result:
            cred = None
        else:
            # Create a simple object with the needed properties
            class SimpleCredential:
                def __init__(self, oauth_client_id, oauth_secret, oauth_callback_url):
                    self.oauth_client_id = oauth_client_id
                    self.oauth_secret = oauth_secret
                    self.oauth_callback_url = oauth_callback_url
            cred = SimpleCredential(result[0], result[1], result[2])
    except Exception as e:
        logger.error(f"Error fetching credentials: {e}")
        cred = None
    if not cred:
        msg = f"OAuth error: No credentials found for user {username}."
        logger.error(msg)
        print(msg, flush=True)
        raise Exception("OAuth error: No credentials found for user. Please re-link your Coinbase account.")
    if not cred.oauth_client_id or not cred.oauth_secret or not cred.oauth_callback_url:
        msg = f"OAuth error: Missing OAuth client_id, secret, or callback_url for user {username}."
        logger.error(msg)
        print(msg, flush=True)
        raise Exception("OAuth error: Missing OAuth client_id, secret, or callback_url. Please re-link your Coinbase account.")
    token_file = os.path.expanduser(f"~/crypto_alert_app/{username}_access_token.json")
    logger.info(f"Looking for token file at: {token_file}")
    if not os.path.exists(token_file):
        msg = f"OAuth error: No token file found for user {username}. Please run OAuth login."
        logger.error(msg)
        print(msg, flush=True)
        raise Exception("OAuth error: No token file found. Please run OAuth login.")
    try:
        with open(token_file) as f:
            tokens = json.load(f)
    except Exception as e:
        msg = f"OAuth error: Failed to load token file for {username}: {e}"
        logger.error(msg)
        print(msg, flush=True)
        raise Exception("OAuth error: Failed to load token file. Please re-authenticate.")
    expires_at = tokens.get("expired_at") or 0
    now = int(time.time())
    if expires_at <= now:
        logger.info(f"🔄 Refreshing access token for {username}...")
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            msg = f"OAuth error: No refresh token found for {username}. User must re-authenticate."
            logger.error(msg)
            print(msg, flush=True)
            raise Exception("OAuth error: No refresh token found. Please re-authenticate with Coinbase.")
        url = "https://api.coinbase.com/oauth/token"
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": cred.oauth_client_id,
            "client_secret": cred.oauth_secret,
            "redirect_uri": cred.oauth_callback_url
        }
        try:
            resp = requests.post(url, data=data)
        except Exception as e:
            msg = f"OAuth error: Exception during token refresh for {username}: {e}"
            logger.error(msg)
            print(msg, flush=True)
            raise Exception("OAuth error: Exception during token refresh. Please check your network and try again.")
        if resp.status_code != 200:
            msg = f"OAuth error: Failed to refresh access token for {username}: {resp.text}"
            logger.error(msg)
            print(msg, flush=True)
            raise Exception(f"OAuth error: Failed to refresh access token: {resp.text}")
        new_tokens = resp.json()
        if "access_token" not in new_tokens:
            msg = f"OAuth error: No access_token in refresh response for {username}: {new_tokens}"
            logger.error(msg)
            print(msg, flush=True)
            raise Exception("OAuth error: No access_token in refresh response. Please re-authenticate.")
        tokens["access_token"] = new_tokens["access_token"]
        tokens["refresh_token"] = new_tokens.get("refresh_token", refresh_token)
        tokens["expires_in"] = new_tokens.get("expires_in", 3600)
        tokens["expired_at"] = int(time.time()) + int(tokens["expires_in"])
        with open(token_file, "w") as f2:
            json.dump(tokens, f2)
        return tokens["access_token"]
    if "access_token" not in tokens:
        msg = f"OAuth error: No access_token in token file for {username}."
        logger.error(msg)
        print(msg, flush=True)
        raise Exception("OAuth error: No access_token in token file. Please re-authenticate.")
    return tokens["access_token"]

def get_live_coinbase_holdings(access_token):
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    url = "https://api.coinbase.com/api/v3/brokerage/accounts"
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        logger.error(f"Failed to fetch Coinbase holdings: " + resp.text)
        raise Exception("Failed to fetch Coinbase holdings: " + resp.text)
    data = resp.json()
    holdings = []
    for acc in data.get("accounts", []):
        try:
            symbol = acc.get("currency", "")
            amount = float(acc["available_balance"]["value"])
            holdings.append({
                "symbol": symbol,
                "amount": amount
            })
        except Exception as e:
            logger.error(f"Skipping account: {acc} Error: {e}", exc_info=True)
            continue
    return holdings