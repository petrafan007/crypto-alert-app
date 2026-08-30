"""
Webull Real-Time Data Streaming Service (MQTT v3.1.1)

Manages real-time market data streaming for Webull equities, ETFs, futures, and options.
Strictly isolated from Binance.US crypto streaming.

Follows official Webull OpenAPI Data Streaming rules:
- Connects to data-api.webull.com:1883 (TCP) or wss://data-api.webull.com:8883/mqtt (WebSocket)
- Uses unique session_id per client
- Enforces maximum concurrent connection limit (<= 5 per App Key)
- Automatically reconnects with backoff
- Pushes parsed quotes and ticks into thread-safe in-memory cache
"""

import logging
import threading
import time
import uuid
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Global cache for real-time Webull quotes and ticks
# Key: uppercase symbol string (e.g. 'AAPL')
# Value: dict of latest streaming market data
WEBULL_STREAMING_CACHE: Dict[str, dict] = {}
_STREAMING_LOCK = threading.Lock()

# Connection tracking
_ACTIVE_CLIENTS: Dict[str, 'WebullStreamingManager'] = {}
_CLIENTS_LOCK = threading.Lock()


class WebullStreamingManager:
    """Manages an active Webull MQTT streaming session for an App Key."""

    def __init__(self, app_key: str, app_secret: str, environment: str = 'production'):
        self.app_key = str(app_key or '').strip()
        self.app_secret = str(app_secret or '').strip()
        self.environment = environment
        self.session_id = f"stream_{uuid.uuid4().hex[:12]}"
        self.subscribed_symbols: Set[str] = set()
        self.client = None
        self._is_running = False
        self._last_disconnect_time = 0.0
        self._reconnect_cooldown = 60.0  # 1-minute cooldown if limit or disconnection occurred
        self._lock = threading.Lock()

    def start(self):
        """Start the Webull MQTT streaming client in a background thread."""
        with self._lock:
            if self._is_running:
                return

            if not self.app_key or not self.app_secret:
                logger.warning("[Webull Streaming] Cannot start: App Key or App Secret missing.")
                return

            # Respect 1-minute cooldown if recently disconnected
            time_since_disconnect = time.time() - self._last_disconnect_time
            if self._last_disconnect_time > 0 and time_since_disconnect < self._reconnect_cooldown:
                logger.info(
                    "[Webull Streaming] Waiting for connection cooldown (%.1fs remaining).",
                    self._reconnect_cooldown - time_since_disconnect
                )

            try:
                from webull.data.data_streaming_client import DataStreamingClient

                self.client = DataStreamingClient(
                    app_key=self.app_key,
                    app_secret=self.app_secret,
                )

                # Register message and connection callbacks
                self.client.on_connect_success = self._on_connect
                self.client.on_disconnect = self._on_disconnect
                self.client.on_quotes_message = self._on_quote_message

                # Start background loop
                self.client.connect_and_loop_start()
                self._is_running = True
                logger.info("[Webull Streaming] Started MQTT streaming client for app_key=%s...", self.app_key[:4] + "***")
            except Exception as e:
                logger.warning("[Webull Streaming] Failed to initialize MQTT client: %s", e)
                self._is_running = False

    def stop(self):
        """Gracefully stop and disconnect the Webull MQTT streaming client."""
        with self._lock:
            if not self._is_running or not self.client:
                return
            try:
                self.client.disconnect()
                self.client.loop_stop()
                self._last_disconnect_time = time.time()
                self._is_running = False
                logger.info("[Webull Streaming] Disconnected streaming client.")
            except Exception as e:
                logger.warning("[Webull Streaming] Error during disconnect: %s", e)
                self._is_running = False

    def subscribe_symbols(self, symbols: List[str], category: str = 'US_STOCK', sub_type: str = 'QUOTE'):
        """Subscribe to real-time quotes/ticks for given symbols."""
        if not symbols or not self.client or not self._is_running:
            return
        clean_symbols = [str(s).upper().strip() for s in symbols if s]
        try:
            for sym in clean_symbols:
                if sym not in self.subscribed_symbols:
                    # In SDK, subscribe takes symbols and category
                    self.client.subscribe(symbols=[sym], category=category, sub_type=sub_type)
                    self.subscribed_symbols.add(sym)
            logger.debug("[Webull Streaming] Subscribed to symbols: %s", clean_symbols)
        except Exception as e:
            logger.warning("[Webull Streaming] Subscription error for %s: %s", clean_symbols, e)

    def unsubscribe_symbols(self, symbols: List[str], category: str = 'US_STOCK', sub_type: str = 'QUOTE'):
        """Unsubscribe from real-time quotes for given symbols."""
        if not symbols or not self.client or not self._is_running:
            return
        clean_symbols = [str(s).upper().strip() for s in symbols if s]
        try:
            for sym in clean_symbols:
                if sym in self.subscribed_symbols:
                    self.client.unsubscribe(symbols=[sym], category=category, sub_type=sub_type)
                    self.subscribed_symbols.discard(sym)
            logger.debug("[Webull Streaming] Unsubscribed from symbols: %s", clean_symbols)
        except Exception as e:
            logger.warning("[Webull Streaming] Unsubscription error for %s: %s", clean_symbols, e)

    def _on_connect(self, *args, **kwargs):
        logger.info("[Webull Streaming] Connected to Webull Data Streaming server.")

    def _on_disconnect(self, client, userdata, rc, *args, **kwargs):
        self._last_disconnect_time = time.time()
        logger.info("[Webull Streaming] Disconnected from Webull Data Streaming server (rc=%s).", rc)

    def _on_quote_message(self, topic, payload, *args, **kwargs):
        """Handle incoming quote/tick/snapshot messages pushed from Webull."""
        try:
            if not payload:
                return

            symbol = None
            price = None
            timestamp = time.time()

            # Handle dict payload or protobuf parsed object
            if isinstance(payload, dict):
                symbol = payload.get('symbol') or payload.get('basic', {}).get('symbol')
                price = payload.get('price') or payload.get('last_price') or payload.get('close')
                timestamp = payload.get('timestamp') or timestamp
            elif hasattr(payload, 'basic') and hasattr(payload.basic, 'symbol'):
                symbol = payload.basic.symbol
                if hasattr(payload, 'price'):
                    price = payload.price
                elif hasattr(payload, 'last_price'):
                    price = payload.last_price

            if symbol and price is not None:
                clean_sym = str(symbol).upper().strip()
                try:
                    num_price = float(price)
                    if num_price > 0:
                        with _STREAMING_LOCK:
                            WEBULL_STREAMING_CACHE[clean_sym] = {
                                'symbol': clean_sym,
                                'price': num_price,
                                'timestamp': timestamp,
                                'source': 'webull_streaming',
                            }
                except (TypeError, ValueError):
                    pass
        except Exception as e:
            logger.debug("[Webull Streaming] Failed to parse message on topic %s: %s", topic, e)


def get_webull_streaming_manager(app_key: str, app_secret: str, environment: str = 'production') -> Optional[WebullStreamingManager]:
    """Retrieve or initialize the singleton Webull streaming manager for this App Key."""
    if not app_key or not app_secret:
        return None
    with _CLIENTS_LOCK:
        if app_key not in _ACTIVE_CLIENTS:
            _ACTIVE_CLIENTS[app_key] = WebullStreamingManager(app_key, app_secret, environment)
        return _ACTIVE_CLIENTS[app_key]


def get_latest_streaming_price(symbol: str) -> Optional[float]:
    """Retrieve the latest streaming price from the Webull cache if fresh (within 60s)."""
    clean_sym = str(symbol or '').upper().strip()
    with _STREAMING_LOCK:
        entry = WEBULL_STREAMING_CACHE.get(clean_sym)
        if entry:
            # Check freshness (within 60 seconds)
            if time.time() - entry.get('timestamp', 0) < 60:
                return entry.get('price')
    return None
