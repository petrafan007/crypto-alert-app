import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import './ToastNotifications.css';

const AUTO_DISMISS_MS = 7500;
const POLL_INTERVAL_MS = 4000;

export default function ToastNotifications({ isLightMode }) {
  const [toasts, setToasts] = useState([]);
  const [isEnabled, setIsEnabled] = useState(() => {
    const stored = localStorage.getItem('crypto_toast_notifications_enabled');
    return stored !== 'false';
  });

  const seenNotificationIds = useRef(new Set());
  const isInitialFetch = useRef(true);
  const closingToasts = useRef(new Set());

  // Listen to settings changes
  useEffect(() => {
    const handleSettingChange = (e) => {
      if (e?.detail?.enabled !== undefined) {
        setIsEnabled(!!e.detail.enabled);
      }
    };
    window.addEventListener('app:toast-setting-changed', handleSettingChange);
    return () => window.removeEventListener('app:toast-setting-changed', handleSettingChange);
  }, []);

  // Fetch initial setting from server
  useEffect(() => {
    let isMounted = true;
    axios.get('/api/settings', { withCredentials: true })
      .then(res => {
        if (!isMounted || !res.data) return;
        const enabled = res.data.browser_notifications_enabled ?? res.data.toast_notifications_enabled;
        if (enabled !== undefined) {
          setIsEnabled(!!enabled);
          localStorage.setItem('crypto_toast_notifications_enabled', enabled ? 'true' : 'false');
        }
      })
      .catch(() => {});
    return () => { isMounted = false; };
  }, []);

  // Dismiss a toast
  const dismissToast = useCallback((id) => {
    closingToasts.current.add(id);
    // Trigger closing animation
    setToasts(prev => prev.map(t => t.id === id ? { ...t, isClosing: true } : t));
    setTimeout(() => {
      closingToasts.current.delete(id);
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 260);
  }, []);

  // Add a toast
  const addToast = useCallback((toastData) => {
    if (!isEnabled) return;
    const id = toastData.id || `toast-${Date.now()}-${Math.random().toString(36).substr(2, 6)}`;
    
    setToasts(prev => {
      // Prevent duplicate active toasts
      if (prev.some(t => t.id === id)) return prev;
      const newToast = {
        ...toastData,
        id,
        createdAt: Date.now(),
        expiresAt: Date.now() + AUTO_DISMISS_MS,
        isPaused: false,
        isClosing: false,
      };
      // Keep up to 5 visible toasts
      const updated = [...prev, newToast];
      if (updated.length > 5) {
        return updated.slice(updated.length - 5);
      }
      return updated;
    });
  }, [isEnabled]);

  // Listen to manual dispatch events from anywhere in the app
  useEffect(() => {
    const handleCustomToast = (e) => {
      if (e?.detail) {
        addToast(e.detail);
      }
    };
    window.addEventListener('app:new-toast', handleCustomToast);
    return () => window.removeEventListener('app:new-toast', handleCustomToast);
  }, [addToast]);

  // Poll backend notifications
  useEffect(() => {
    let isMounted = true;
    let timerId;

    async function pollNotifications() {
      try {
        const res = await axios.get('/api/notifications?limit=25', { withCredentials: true });
        if (!isMounted) return;
        const notifs = res.data || [];

        if (isInitialFetch.current) {
          // On first load, record all existing IDs so we don't spam old notifications
          notifs.forEach(n => seenNotificationIds.current.add(n.id));
          isInitialFetch.current = false;
          return;
        }

        // Identify new notifications that haven't been seen
        const incoming = [];
        for (const n of notifs) {
          if (!seenNotificationIds.current.has(n.id)) {
            seenNotificationIds.current.add(n.id);
            incoming.push(n);
          }
        }

        // Limit seenNotificationIds set size to prevent memory leaks
        if (seenNotificationIds.current.size > 500) {
          const arr = Array.from(seenNotificationIds.current);
          seenNotificationIds.current = new Set(arr.slice(arr.length - 300));
        }

        if (incoming.length > 0 && isEnabled) {
          incoming.forEach(n => {
            addToast({
              id: `notif-${n.id}`,
              category: n.category || 'price_alert',
              symbol: n.symbol,
              direction: n.direction,
              crossing_price: n.crossing_price,
              current_price: n.current_price,
              percent_value: n.percent_value,
              threshold_type: n.threshold_type,
              message: n.message,
              time: n.time || 'Just now',
            });
          });
        }
      } catch (err) {
        // Suppress auth/network polling errors
      }
    }

    pollNotifications();
    timerId = setInterval(pollNotifications, POLL_INTERVAL_MS);

    return () => {
      isMounted = false;
      clearInterval(timerId);
    };
  }, [isEnabled, addToast]);

  // Auto-dismiss countdown timer
  useEffect(() => {
    if (toasts.length === 0) return;
    const interval = setInterval(() => {
      const now = Date.now();
      toasts.forEach(t => {
        if (!t.isPaused && !t.isClosing && t.expiresAt && now >= t.expiresAt) {
          dismissToast(t.id);
        }
      });
    }, 200);

    return () => clearInterval(interval);
  }, [toasts, dismissToast]);

  // Pause on hover
  const handleMouseEnter = (id) => {
    setToasts(prev => prev.map(t => {
      if (t.id === id) {
        return { ...t, isPaused: true };
      }
      return t;
    }));
  };

  const handleMouseLeave = (id) => {
    setToasts(prev => prev.map(t => {
      if (t.id === id) {
        return {
          ...t,
          isPaused: false,
          expiresAt: Date.now() + 3500 // give 3.5s after unhovering
        };
      }
      return t;
    }));
  };

  if (!isEnabled || toasts.length === 0) {
    return null;
  }

  return (
    <div className="toast-notifications-container">
      {toasts.map(toast => {
        const cat = (toast.category || 'price_alert').toLowerCase();
        const config = getToastConfig(cat, toast);

        return (
          <div
            key={toast.id}
            className={`toast-card type-${cat} ${toast.isClosing ? 'toast-closing' : ''}`}
            onMouseEnter={() => handleMouseEnter(toast.id)}
            onMouseLeave={() => handleMouseLeave(toast.id)}
            role="alert"
          >
            <div className="toast-header">
              <div className="toast-header-left">
                <span className="toast-icon">{config.icon}</span>
                <span className="toast-badge">{config.badge}</span>
              </div>
              <span className="toast-time">{toast.time || 'Just now'}</span>
              <button
                type="button"
                className="toast-close-btn"
                onClick={() => dismissToast(toast.id)}
                title="Close"
              >
                ✕
              </button>
            </div>

            <div className="toast-body">
              {toast.symbol && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span className="toast-symbol-tag">{toast.symbol}</span>
                  {config.subTitle && (
                    <span style={{ fontSize: '0.78rem', color: '#94a3b8' }}>
                      {config.subTitle}
                    </span>
                  )}
                </div>
              )}
              <div className="toast-message-text">
                {toast.message || config.defaultMessage}
              </div>
            </div>

            <div className="toast-progress-container">
              <div
                className="toast-progress-bar"
                style={{
                  width: toast.isPaused ? '100%' : '0%',
                  transitionDuration: toast.isPaused ? '0s' : `${AUTO_DISMISS_MS}ms`
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function getToastConfig(category, toast) {
  switch (category) {
    case 'order_filled':
    case 'trade':
      return {
        badge: 'Order Filled',
        icon: '✅',
        defaultMessage: `Transaction completed for ${toast.symbol || 'asset'}.`,
        subTitle: toast.direction ? toast.direction.toUpperCase() : ''
      };
    case 'order_canceled':
      return {
        badge: 'Order Canceled',
        icon: '🚫',
        defaultMessage: `Order for ${toast.symbol || 'asset'} has been canceled.`,
        subTitle: 'CANCELED'
      };
    case 'order_placed':
      return {
        badge: 'Order Placed',
        icon: '📝',
        defaultMessage: `New order submitted for ${toast.symbol || 'asset'}.`,
        subTitle: 'OPEN'
      };
    case 'sentiment_alert':
    case 'ai_sentiment':
      return {
        badge: 'AI Sentiment Signal',
        icon: '🤖',
        defaultMessage: `New sentiment signal detected for ${toast.symbol || 'asset'}.`,
        subTitle: 'AI SIGNAL'
      };
    case 'auto_sell':
      return {
        badge: 'Auto-Sell Executed',
        icon: '⚡',
        defaultMessage: `Auto-sell triggered for ${toast.symbol || 'asset'}.`,
        subTitle: 'AUTO-TRADE'
      };
    case 'auto_buy':
      return {
        badge: 'Auto-Buy Executed',
        icon: '🚀',
        defaultMessage: `Auto-buy triggered for ${toast.symbol || 'asset'}.`,
        subTitle: 'AUTO-TRADE'
      };
    case 'volatility_alert':
    case 'volatility':
      return {
        badge: 'Volatility Alert',
        icon: '⚠️',
        defaultMessage: `High volatility detected on ${toast.symbol || 'asset'}.`,
        subTitle: toast.direction ? `${toast.direction.toUpperCase()} ALERT` : 'ALERT'
      };
    case 'price_alert':
    default:
      return {
        badge: 'Price Alert',
        icon: '🔔',
        defaultMessage: toast.crossing_price
          ? `Price ${toast.direction === 'down' ? 'fell below' : 'rose above'} $${toast.crossing_price}`
          : `Price alert triggered for ${toast.symbol || 'asset'}.`,
        subTitle: toast.direction ? `${toast.direction.toUpperCase()} ALERT` : 'ALERT'
      };
  }
}
