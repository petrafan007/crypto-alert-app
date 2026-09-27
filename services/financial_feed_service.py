import feedparser
import requests
import urllib.parse
from datetime import datetime, timezone
from typing import List, Dict

from log import logger

RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://finance.yahoo.com/news/rssindex"
]

def fetch_rss_feeds(symbol: str, max_results=5) -> List[Dict]:
    """Fetch matching news from standard RSS feeds"""
    results = []
    symbol_lower = symbol.lower()
    
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url, request_headers={'User-Agent': 'Mozilla/5.0'})
            for entry in feed.entries:
                title = getattr(entry, 'title', '').lower()
                summary = getattr(entry, 'summary', '').lower()
                
                # Basic matching logic
                match_terms = [symbol_lower]
                base_symbol = symbol_lower.replace('usd', '').replace('usdt', '')
                if base_symbol and base_symbol != symbol_lower:
                    match_terms.append(base_symbol)
                    
                if base_symbol in ['btc']:
                    match_terms.append('bitcoin')
                elif base_symbol in ['eth']:
                    match_terms.append('ethereum')
                elif base_symbol in ['sol']:
                    match_terms.append('solana')

                if any(term in title or term in summary for term in match_terms):
                    results.append({
                        'title': getattr(entry, 'title', ''),
                        'url': getattr(entry, 'link', ''),
                        'snippet': getattr(entry, 'summary', '')[:200],
                        'source': 'RSS'
                    })
                    
                if len(results) >= max_results:
                    return results
        except Exception as e:
            logger.warning(f"Failed to fetch RSS feed {feed_url}: {e}")
            
    return results

import time

_cc_news_cache = {}
_CC_CACHE_TTL = 8 * 3600  # 8 hours = max 3 calls per day (90/month)

def fetch_cryptocurrency_cv_news(symbol: str, max_results=5) -> List[Dict]:
    """Fetch keyless news from Cryptocurrency.cv aggregator"""
    try:
        url = "https://cryptocurrency.cv/api/news"
        resp = requests.get(url, timeout=10)
        
        # If their API doesn't have a direct /news endpoint yet, we fallback to RSS
        if resp.status_code != 200:
            return []
            
        data = resp.json().get('data', [])
        results = []
        symbol_lower = symbol.lower()
        base_symbol = symbol_lower.replace('usd', '').replace('usdt', '')
        
        for item in data:
            title = item.get('title', '').lower()
            summary = item.get('summary', '').lower()
            if base_symbol in title or base_symbol in summary:
                results.append({
                    'title': item.get('title', ''),
                    'url': item.get('url', ''),
                    'snippet': item.get('summary', '')[:200],
                    'source': 'Cryptocurrency.cv'
                })
            if len(results) >= max_results:
                break
        return results
    except Exception as e:
        logger.warning(f"Failed to fetch Cryptocurrency.cv news: {e}")
        return []

def fetch_coinstats_news(symbol: str, api_key: str = None, max_results=5) -> List[Dict]:
    """Fetch curated news from CoinStats API"""
    if not api_key:
        return []
    
    try:
        url = f"https://openapiv1.coinstats.app/news/type/latest?limit={max_results * 5}"
        headers = {'X-API-KEY': api_key}
        
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        results = []
        symbol_lower = symbol.lower()
        base_symbol = symbol_lower.replace('usd', '').replace('usdt', '')
        
        for item in data:
            title = item.get('title', '').lower()
            description = item.get('description', '').lower()
            
            if base_symbol in title or base_symbol in description:
                results.append({
                    'title': item.get('title', ''),
                    'url': item.get('link', ''),
                    'snippet': item.get('description', '')[:200],
                    'source': f"CoinStats ({item.get('source', 'News')})"
                })
                
            if len(results) >= max_results:
                break
                
        return results
    except Exception as e:
        logger.warning(f"Failed to fetch CoinStats news for {symbol}: {e}")
        return []

def fetch_financial_feeds(symbol: str, cred=None, max_results=5, system_caller=None) -> List[Dict]:
    """Unified entrypoint to fetch news from RSS and Crypto APIs"""
    results = []
    
    # Try Cryptocurrency.cv first (Free, Keyless)
    cv_news = fetch_cryptocurrency_cv_news(symbol, max_results=max_results)
    results.extend(cv_news)
    
    # Try CoinStats if we have an API key and the caller is the quant engine
    if len(results) < max_results:
        api_key = cred.coinstats_api_key if (cred and system_caller in ['quant_engine', 'sentiment']) else None
        cs_news = fetch_coinstats_news(symbol, api_key, max_results=max_results - len(results))
        results.extend(cs_news)
    
    # If not enough results, backfill with RSS
    if len(results) < max_results:
        rss_news = fetch_rss_feeds(symbol, max_results=max_results - len(results))
        results.extend(rss_news)
        
    return results
