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

def fetch_cryptocompare_news(symbol: str, api_key: str = None, max_results=5) -> List[Dict]:
    """Fetch news from CryptoCompare API"""
    try:
        url = "https://min-api.cryptocompare.com/data/v2/news/?lang=EN"
        headers = {}
        if api_key:
            headers['authorization'] = f"Apikey {api_key}"
            
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json().get('Data', [])
        
        results = []
        symbol_lower = symbol.lower()
        base_symbol = symbol_lower.replace('usd', '').replace('usdt', '')
        
        for item in data:
            categories = item.get('categories', '').lower()
            title = item.get('title', '').lower()
            
            if base_symbol in categories or base_symbol in title:
                results.append({
                    'title': item.get('title', ''),
                    'url': item.get('url', ''),
                    'snippet': item.get('body', '')[:200],
                    'source': f"CryptoCompare ({item.get('source_info', {}).get('name', 'News')})"
                })
                
            if len(results) >= max_results:
                break
                
        return results
    except Exception as e:
        logger.warning(f"Failed to fetch CryptoCompare news for {symbol}: {e}")
        return []

def fetch_financial_feeds(symbol: str, cred=None, max_results=5) -> List[Dict]:
    """Unified entrypoint to fetch news from RSS and Crypto APIs"""
    results = []
    
    # Try CryptoCompare first for crypto tickers
    api_key = cred.cryptocompare_api_key if cred else None
    cc_news = fetch_cryptocompare_news(symbol, api_key, max_results=max_results)
    results.extend(cc_news)
    
    # If not enough results, backfill with RSS
    if len(results) < max_results:
        rss_news = fetch_rss_feeds(symbol, max_results=max_results - len(results))
        results.extend(rss_news)
        
    return results
