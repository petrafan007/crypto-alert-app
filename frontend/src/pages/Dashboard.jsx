import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import useNotificationPoller from '../hooks/useNotificationPoller';
import axios from 'axios';
import { PortfolioPie, PortfolioTrend } from '../components/DashboardCharts';
import PriceHistoryPopup from '../components/PriceHistoryPopup';
import { getTradeUrl } from '../utils/exchangeUtils';
import AIAnalysisModal from '../components/AIAnalysisModal';
import { useAuth } from '../components/AuthContext';
import FearGreedWidget from '../components/FearGreedWidget';
import CBBIWidget from '../components/CBBIWidget';
import StakingSummaryWidget from '../components/StakingSummaryWidget';

const TREND_RANGES = [
  { key: '4H', label: '4H' },
  { key: '12H', label: '12H' },
  { key: '1D', label: '1D' },
  { key: '3D', label: '3D' },
  { key: '7D', label: '7D' },
  { key: '4W', label: '4W' },
  { key: '3M', label: '3M' },
  { key: '6M', label: '6M' },
  { key: '1Y', label: '1Y' },
];

function Dashboard({ isLightMode }) {
  const { isLoggingOut, user } = useAuth();
  const navigate = useNavigate();
  const [totalValue, setTotalValue] = useState(null);
  const [portfolio, setPortfolio] = useState([]);
  const [watchlist, setWatchlist] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [trendHistory, setTrendHistory] = useState([]);
  const [pendingOrders, setPendingOrders] = useState([]);
  const [orderTooltip, setOrderTooltip] = useState({ isVisible: false, text: '', position: { x: 0, y: 0 } });
  const [trendRange, setTrendRange] = useState('7D');
  const [trendLoading, setTrendLoading] = useState(true);

  // Sorting state
  const [sortConfig, setSortConfig] = useState(() => {
    if (typeof window === 'undefined') {
      return { key: null, direction: 'asc' };
    }
    try {
      const stored = window.localStorage.getItem('dashboardSortConfig');
      if (stored) {
        const parsed = JSON.parse(stored);
        if (parsed && typeof parsed === 'object') {
          return {
            key: parsed.key ?? null,
            direction: parsed.direction === 'desc' ? 'desc' : 'asc'
          };
        }
      }
    } catch (err) {
      console.warn('Failed to read saved sort config:', err);
    }
    return { key: null, direction: 'asc' };
  });

  // Note modal state
  const [showNoteModal, setShowNoteModal] = useState(false);
  const [editingNote, setEditingNote] = useState(null);
  const [noteText, setNoteText] = useState('');

  // Authentication state
  const [needsLogin, setNeedsLogin] = useState(false);

  // Add to watchlist state
  const [watchlistSymbol, setWatchlistSymbol] = useState('');
  const [addingToWatchlist, setAddingToWatchlist] = useState(false);

  // Staking state
  const [stakeableCoins, setStakeableCoins] = useState([]);
  const [showStakeModal, setShowStakeModal] = useState(false);
  const [stakingCoin, setStakingCoin] = useState(null);
  const [stakeAmount, setStakeAmount] = useState('');

  // Hover popup state
  const [hoverPopup, setHoverPopup] = useState({
    isVisible: false,
    symbol: null,
    position: { x: 0, y: 0 }
  });

  const [notification, setNotification] = useState({ show: false, message: '', type: 'info' });
  const [isMobile, setIsMobile] = useState(false);
  const [openActionMenu, setOpenActionMenu] = useState({ type: null, key: null, payload: null });

  // Toast for backend notifications
  useNotificationPoller(user && user.id, notif => {
    setNotification({
      show: true,
      message: notif.symbol ? `ALERT: ${notif.symbol} ${notif.direction} at ${notif.crossing_price} (current: ${notif.current_price})` : notif.message || 'New notification',
      type: 'success'
    });
    setTimeout(() => {
      setNotification({ show: false, message: '', type: 'info' });
    }, 4000);
  });



  // News analysis modal state
  const [showNewsModal, setShowNewsModal] = useState(false);
  const [newsAnalysisSymbol, setNewsAnalysisSymbol] = useState(null);
  const [newsAnalysisData, setNewsAnalysisData] = useState(null);
  const [newsLoading, setNewsLoading] = useState(false);

  // Mobile detection for responsive-only behaviors
  useEffect(() => {
    const handleResize = () => {
      if (typeof window !== 'undefined') {
        setIsMobile(window.innerWidth <= 960);
      }
    };
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const closeActionMenu = () => setOpenActionMenu({ type: null, key: null, payload: null });

  const toggleActionMenu = (type, key, event, payload = null) => {
    if (!isMobile) return;
    setOpenActionMenu(prev =>
      prev.type === type && prev.key === key
        ? { type: null, key: null, payload: null }
        : { type, key, payload }
    );
  };


  // Hover popup functions
  const handleSymbolHover = (symbol, event) => {
    const rect = event.currentTarget.getBoundingClientRect();
    setHoverPopup({
      isVisible: true,
      symbol: symbol,
      position: {
        x: rect.left + rect.width / 2 - 150, // Center above symbol (popup width is ~300px)
        y: rect.top - 250 // Position above symbol
      }
    });
  };

  const handleSymbolLeave = () => {
    setHoverPopup({
      isVisible: false,
      symbol: null,
      position: { x: 0, y: 0 }
    });
  };

  const handleChartClick = (symbol) => {
    // Open the exchange in a new tab
    window.open(getTradeUrl(symbol), '_blank');
  };

  // Get pending orders for a specific coin
  const getPendingOrdersForCoin = (symbol) => {
    if (!pendingOrders || !Array.isArray(pendingOrders)) return [];
    return pendingOrders.filter(order => order.asset === symbol);
  };

  const formatOrderQuantity = (amount) => {
    if (amount === null || amount === undefined) return null;
    const absVal = Math.abs(amount);
    if (absVal === 0) return '0.0000';
    if (absVal >= 1) return amount.toFixed(4);
    if (absVal >= 0.01) return amount.toFixed(6);
    return amount.toFixed(8);
  };

  const formatOrderUsd = (amount) => {
    if (amount === null || amount === undefined) return null;
    return amount.toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  };

  // Generate tooltip text for pending orders
  const generateOrderTooltipText = (orders) => {
    if (orders.length === 0) return '';

    const describeOrder = (order) => {
      const orderTypeName = (order.type || 'LIMIT').replace(/_/g, ' ').toLowerCase();
      const side = (order.side || '').toLowerCase();
      const trigger = order.trigger_price
        ? order.trigger_price.toFixed(4)
        : order.price
          ? Number(order.price).toFixed(4)
          : 'N/A';
      const orderQuantity = Number(order.quantity ?? 0);
      const quantityText = formatOrderQuantity(orderQuantity);
      const assetSymbol = (order.asset || '').toUpperCase();
      const priceReference = Number(order.trigger_price || order.price || 0);
      const quoteValue = order.quantity_usdt !== undefined && order.quantity_usdt !== null
        ? Number(order.quantity_usdt)
        : orderQuantity * priceReference;
      const usdText = formatOrderUsd(quoteValue);
      const sizeDescription = quantityText
        ? `${quantityText} ${assetSymbol}${usdText ? ` (~${usdText} USDT)` : ''}`
        : assetSymbol || 'this asset';

      return `Pending ${orderTypeName} ${side} for ${sizeDescription} when price ${order.direction} ${trigger} USDT`;
    };

    return orders.map(describeOrder).join('\n');
  };

  // Handle hover on row for pending order tooltip
  const handleRowHover = (coin, event) => {
    // Check if hovering over excluded elements: symbol-cell, buttons, inputs, selects
    const target = event.target;
    const isExcluded = target.closest('.symbol-cell') ||
      target.tagName === 'BUTTON' ||
      target.tagName === 'INPUT' ||
      target.tagName === 'SELECT' ||
      target.closest('button') ||
      target.closest('input') ||
      target.closest('select');

    if (isExcluded) {
      handleRowLeave();
      return;
    }

    const orders = getPendingOrdersForCoin(coin.symbol);
    if (orders.length > 0) {
      const rect = event.currentTarget.getBoundingClientRect();
      setOrderTooltip({
        visible: true,
        text: generateOrderTooltipText(orders),
        x: event.clientX + 15,
        y: rect.top - 60
      });
    }
  };

  const handleRowLeave = () => {
    setOrderTooltip({
      visible: false,
      text: '',
      x: 0,
      y: 0
    });
  };

  useEffect(() => {
    let refreshInterval;

    async function fetchData(isInitialLoad = true) {
      try {
        // Don't make any API calls if we're logging out
        if (isLoggingOut || window.globalIsLoggingOut) {
          return;
        }

        // Background refresh - no longer need to check for actively editing since portfolio alert fields are now uncontrolled

        if (isInitialLoad) {
          setNeedsLogin(false);
          // Don't set loading true - it clears the table!
        }

        // First, fetch portfolio data (most important) - use database for instant load
        try {
          const portfolioResponse = await axios.get('/api/coin-data');
          // Also fetch open orders to flag rows
          let pendingSymbols = new Set();
          let pendingOrdersData = [];
          try {
            const ordersRes = await axios.get('/api/pending-orders', { withCredentials: true });
            pendingOrdersData = ordersRes.data.pending_orders || [];
            setPendingOrders(pendingOrdersData);
            pendingOrdersData.forEach(order => {
              if (order.asset) {
                pendingSymbols.add(order.asset.toUpperCase());
              }
            });
          } catch (e) {
            console.error('Error fetching pending orders:', e);
            // ignore if not authed yet; we still render portfolio
          }
          const rawPortfolio = Array.isArray(portfolioResponse.data.portfolio)
            ? portfolioResponse.data.portfolio
            : [];

          const withFlags = rawPortfolio.map((c) => ({
            ...c,
            hasPendingOrder: pendingSymbols.has((c.symbol || '').toUpperCase()),
            pendingPlaceholder: false
          }));

          const existingSymbols = new Set(
            withFlags.map((coin) => (coin.symbol || '').toUpperCase())
          );
          const placeholderMap = {};

          pendingOrdersData.forEach((order) => {
            const assetSymbol = (order.asset || '').toUpperCase();
            if (!assetSymbol || existingSymbols.has(assetSymbol)) {
              return;
            }
            if (!placeholderMap[assetSymbol]) {
              const referencePrice = Number(order.trigger_price || order.price || 0);
              placeholderMap[assetSymbol] = {
                id: `pending-${assetSymbol}`,
                symbol: assetSymbol,
                initial_price: referencePrice,
                avg_entry: referencePrice,
                initial_value: 0,
                purchase_date: null,
                current_price: referencePrice,
                amount: 0,
                cost_basis: 0,
                current_value: 0,
                pct_change: 0,
                custom_lower_pct: null,
                custom_upper_pct: null,
                custom_lower_type: '#',
                custom_upper_type: '#',
                custom_lower_val: null,
                custom_upper_val: null,
                down_alert: null,
                up_alert: null,
                alert_enabled: true,
                favorite: false,
                hidden: false,
                has_note: false,
                hasPendingOrder: true,
                sentiment: 'Pending Order',
                force_visible: true,
                pendingPlaceholder: true
              };
              existingSymbols.add(assetSymbol);
            }
          });

          const placeholderCoins = Object.values(placeholderMap);
          const combinedPortfolio = [...withFlags, ...placeholderCoins];
          if (combinedPortfolio.length > 0 || isInitialLoad) {
            setPortfolio(combinedPortfolio);
          }
          if (isInitialLoad) {
            setLoading(false);
          }
        } catch (error) {
          console.error('Error fetching portfolio:', error);
          // Check if it's an authentication error (302 redirect or 401)
          if (error.response && (error.response.status === 302 || error.response.status === 401)) {
            setNeedsLogin(true);
            return;
          }
          // Also check for network errors that might indicate redirects
          if (error.code === 'ERR_NETWORK' || error.message.includes('redirect')) {
            setNeedsLogin(true);
            return;
          }
          // Check for any error that might indicate authentication issues
          if (error.message && (error.message.includes('login') || error.message.includes('auth'))) {
            setNeedsLogin(true);
            return;
          }
        }

        // Then fetch other data in parallel (background refresh) - don't wait for this
        if (isInitialLoad) {
          // For initial load, fetch other data in background without blocking
          // Use setTimeout to make it truly non-blocking
          setTimeout(() => {
            Promise.allSettled([
              axios.get('/api/watchlist'),
              axios.get(`/api/true-portfolio-value?ts=${Date.now()}`)
              // Don't fetch trend history here - let the useEffect handle it
            ]).then(([watchlistResponse, portfolioValueResponse]) => {
              // Handle watchlist
              if (watchlistResponse.status === 'fulfilled') {
                console.log('Watchlist response:', watchlistResponse.value.data);
                setWatchlist(watchlistResponse.value.data || []);
              }

              // Handle portfolio value
              if (portfolioValueResponse.status === 'fulfilled') {
                const totalVal = portfolioValueResponse.value.data.total_value;
                console.log(`[DEBUG] Received Total Portfolio Value: ${totalVal}`, portfolioValueResponse.value.data);
                setTotalValue(totalVal || 0);
              }
            });
          }, 100); // Small delay to ensure portfolio loads first
        } else {
          // For background refresh, wait for all data including live portfolio data
          const [watchlistResponse, portfolioValueResponse, livePortfolioResponse, ordersResponse] = await Promise.allSettled([
            axios.get('/api/watchlist-live'),
            axios.get(`/api/true-portfolio-value?ts=${Date.now()}`),
            axios.get('/api/coin-data-live'),
            axios.get('/api/pending-orders', { withCredentials: true })
            // Don't fetch trend history in background refresh - it's handled by useEffect
          ]);

          // Also check for recent filled orders
          await checkForFilledOrders();

          // Check for authentication errors in any response
          const hasAuthError = [watchlistResponse, portfolioValueResponse, livePortfolioResponse, ordersResponse].some(
            response => response.status === 'rejected' &&
              response.reason.response &&
              (response.reason.response.status === 302 || response.reason.response.status === 401)
          );

          // Also check for network errors that might indicate redirects
          const hasNetworkError = [watchlistResponse, portfolioValueResponse, livePortfolioResponse, ordersResponse].some(
            response => response.status === 'rejected' &&
              (response.reason.code === 'ERR_NETWORK' || response.reason.message.includes('redirect'))
          );

          if (hasAuthError || hasNetworkError) {
            setNeedsLogin(true);
            return;
          }

          // Handle watchlist
          if (watchlistResponse.status === 'fulfilled') {
            setWatchlist(watchlistResponse.value.data || []);
          }

          // Handle portfolio value
          if (portfolioValueResponse.status === 'fulfilled') {
            setTotalValue(portfolioValueResponse.value.data.total_value || 0);
          }

          // Build pending symbols set from orders
          let pendingSymbolsLive = new Set();
          if (ordersResponse.status === 'fulfilled' && ordersResponse.value?.data?.pending_orders) {
            (ordersResponse.value.data.pending_orders || []).forEach(order => {
              if (order.asset) {
                pendingSymbolsLive.add(order.asset.toUpperCase());
              }
            });
          }

          // Handle live portfolio data (update with fresh prices) – merge into existing state
          if (livePortfolioResponse.status === 'fulfilled' && livePortfolioResponse.value.data.portfolio && livePortfolioResponse.value.data.portfolio.length > 0) {
            const incoming = livePortfolioResponse.value.data.portfolio;
            const incomingMap = new Map();
            incoming.forEach(c => {
              const sym = (c.symbol || '').toUpperCase();
              incomingMap.set(sym, {
                ...c,
                hasPendingOrder: pendingSymbolsLive.has(sym),
                pendingPlaceholder: false
              });
            });

            setPortfolio(prev => {
              const prevMap = new Map();
              prev.forEach(p => prevMap.set((p.symbol || '').toUpperCase(), p));
              // Update or add incoming coins
              incomingMap.forEach((val, key) => {
                prevMap.set(key, { ...(prevMap.get(key) || {}), ...val });
              });
              // Return stable array preserving previous order, append any new ones
              const updated = [];
              const seen = new Set();
              prev.forEach(p => {
                const key = (p.symbol || '').toUpperCase();
                updated.push(prevMap.get(key));
                seen.add(key);
              });
              // Append any new symbols not in previous
              incoming.forEach(c => {
                const key = (c.symbol || '').toUpperCase();
                if (!seen.has(key)) {
                  updated.push(prevMap.get(key));
                }
              });
              return updated;
            });
          }
        }

      } catch (error) {
        console.error('Error fetching data:', error);
        if (isInitialLoad) {
          setError('Failed to load dashboard data');
        }
      } finally {
        if (isInitialLoad) {
          setLoading(false);
        }
      }
    }

    // Initial load - show data immediately
    fetchData(true);

    // Set up background refresh every 10 seconds for faster updates
    refreshInterval = setInterval(() => {
      fetchData(false);
    }, 10000);

    // Cleanup interval on unmount
    return () => {
      if (refreshInterval) {
        clearInterval(refreshInterval);
      }
    };
  }, []);

  useEffect(() => {
    async function fetchTrend() {
      setTrendLoading(true);
      try {
        const res = await axios.get(`/api/true-portfolio-history?range=${trendRange}`, { withCredentials: true });
        setTrendHistory(res.data || []);
      } catch (err) {
        console.error('Trend fetch error:', err);
        // Check for authentication error
        if (err.response && (err.response.status === 302 || err.response.status === 401)) {
          setNeedsLogin(true);
        } else {
          setTrendHistory([]);
        }
      }
      setTrendLoading(false);
    }
    fetchTrend();
  }, [trendRange]);

  // Fetch stakeable coins
  useEffect(() => {
    async function fetchStakeableCoins() {
      try {
        console.log('Fetching stakeable coins...');
        const response = await axios.get('/api/staking/stakeable-coins', { withCredentials: true });
        console.log('Stakeable coins response:', response.data);
        setStakeableCoins(response.data || []);
      } catch (err) {
        console.error('Failed to fetch stakeable coins:', err);
        setStakeableCoins([]);
      }
    }
    fetchStakeableCoins();
  }, []);

  // Force refresh portfolio data


  // Check for recent filled orders and update portfolio
  const checkForFilledOrders = async () => {
    try {
      const ordersResponse = await axios.get('/api/orders');
      if (ordersResponse.data.orders) {
        const recentFilledOrders = ordersResponse.data.orders.filter(order =>
          order.status === 'FILLED' &&
          new Date(order.created_time) > new Date(Date.now() - 5 * 60 * 1000) // Last 5 minutes
        );

        if (recentFilledOrders.length > 0) {
          console.log('Found recent filled orders, refreshing portfolio...');
          setNotification({
            show: true,
            message: `Order filled! Portfolio updated.`,
            type: 'success'
          });
          // Auto-hide notification after 3 seconds
          setTimeout(() => {
            setNotification({ show: false, message: '', type: 'info' });
          }, 3000);

          // Refresh portfolio data
          const response = await axios.get('/api/coin-data-live');
          if (response.data.portfolio && response.data.portfolio.length > 0) {
            setPortfolio(response.data.portfolio);
          }
        }
      }
    } catch (error) {
      console.error('Error checking for filled orders:', error);
    }
  };

  // Toggle favorite for portfolio coins
  const toggleFavorite = async (coinId, currentFavorite) => {
    try {
      const response = await axios.post('/api/set-favorite', {
        id: coinId,
        favorite: !currentFavorite
      }, { withCredentials: true });

      if (response.data.success) {
        setPortfolio(prev => prev.map(coin =>
          coin.id === coinId ? { ...coin, favorite: !currentFavorite } : coin
        ));
      }
    } catch (err) {
      console.error('Toggle favorite error:', err);
    }
  };

  // Toggle favorite for watchlist coins
  const toggleWatchlistFavorite = async (symbol, currentFavorite) => {
    try {
      const response = await axios.post('/api/set-watchlist-favorite', {
        symbol: symbol,
        favorite: !currentFavorite
      }, { withCredentials: true });

      if (response.data.success) {
        setWatchlist(prev => prev.map(coin =>
          coin.symbol === symbol ? { ...coin, favorite: !currentFavorite } : coin
        ));
      }
    } catch (err) {
      console.error('Toggle watchlist favorite error:', err);
    }
  };

  // Toggle alert for portfolio coins
  const toggleAlert = async (coinId, currentAlertEnabled) => {
    try {
      const response = await axios.post('/api/set-alert', {
        id: coinId,
        alert_enabled: !currentAlertEnabled
      }, { withCredentials: true });

      if (response.data.success) {
        setPortfolio(prev => prev.map(coin =>
          coin.id === coinId ? { ...coin, alert_enabled: !currentAlertEnabled } : coin
        ));
      }
    } catch (err) {
      console.error('Toggle alert error:', err);
    }
  };

  // Toggle alert for watchlist coins
  const toggleWatchlistAlert = async (symbol, currentAlertEnabled) => {
    try {
      const response = await axios.post('/api/set-watch-alert', {
        symbol: symbol,
        alert_enabled: !currentAlertEnabled
      }, { withCredentials: true });

      if (response.data.success) {
        setWatchlist(prev => prev.map(coin =>
          coin.symbol === symbol ? { ...coin, alert_enabled: !currentAlertEnabled } : coin
        ));
      }
    } catch (err) {
      console.error('Toggle watchlist alert error:', err);
    }
  };

  // Get auto alert
  const getAutoAlert = async (item, direction, isWatchlist = false) => {
    try {
      const endpoint = isWatchlist ? '/api/auto-alert' : '/api/auto-alert';
      const response = await axios.get(endpoint, {
        params: {
          symbol: item.symbol,
          direction: direction
        },
        withCredentials: true
      });

      if (response.data.success) {
        const alertKey = direction === 'down' ? 'down_alert' : 'up_alert';

        if (isWatchlist) {
          setWatchlist(prev => prev.map(coin =>
            coin.symbol === item.symbol ? {
              ...coin,
              [alertKey]: response.data.value
            } : coin
          ));
        } else {
          setPortfolio(prev => prev.map(coin =>
            coin.id === item.id ? {
              ...coin,
              [alertKey]: response.data.value
            } : coin
          ));
        }
      }
    } catch (err) {
      console.error('Get auto alert error:', err);
    }
  };

  // Update alert type
  const updateAlertType = async (item, direction, newType, isWatchlist = false) => {
    try {
      const endpoint = isWatchlist ? '/api/set-watch-alert-type' : '/api/set-custom-pct-type';
      const data = isWatchlist ? {
        symbol: item.symbol,
        direction: direction,
        type: newType
      } : {
        id: item.id,
        direction: direction,
        type: newType
      };

      const response = await axios.post(endpoint, data, { withCredentials: true });

      if (response.data.success) {
        const typeKey = direction === 'down' ? 'custom_lower_type' : 'custom_upper_type';

        if (isWatchlist) {
          setWatchlist(prev => prev.map(coin =>
            coin.symbol === item.symbol ? {
              ...coin,
              [typeKey]: newType
            } : coin
          ));
        } else {
          setPortfolio(prev => prev.map(coin =>
            coin.id === item.id ? {
              ...coin,
              [typeKey]: newType
            } : coin
          ));
        }
      }
    } catch (err) {
      console.error('Update alert type error:', err);
    }
  };

  // Sorting functionality
  const handleSort = (key) => {
    let direction = 'asc';
    if (sortConfig.key === key && sortConfig.direction === 'asc') {
      direction = 'desc';
    }
    const nextConfig = { key, direction };
    setSortConfig(nextConfig);
    try {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('dashboardSortConfig', JSON.stringify(nextConfig));
      }
    } catch (err) {
      console.warn('Failed to persist sort config:', err);
    }
  };

  const sortData = (data, key) => {
    if (!key) return data;

    return [...data].sort((a, b) => {
      let aVal = a[key];
      let bVal = b[key];

      // Handle numeric values
      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return sortConfig.direction === 'asc' ? aVal - bVal : bVal - aVal;
      }

      // Handle string values
      if (typeof aVal === 'string' && typeof bVal === 'string') {
        return sortConfig.direction === 'asc' ?
          aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
      }

      // Handle undefined/null values
      if (aVal === undefined || aVal === null) aVal = '';
      if (bVal === undefined || bVal === null) bVal = '';

      return sortConfig.direction === 'asc' ?
        String(aVal).localeCompare(String(bVal)) :
        String(bVal).localeCompare(String(aVal));
    });
  };

  const getSortIcon = (key) => {
    if (sortConfig.key !== key) return '';
    return sortConfig.direction === 'asc' ? '▲' : '▼';
  };

  const renderHeaderLabel = (key, label) => {
    const icon = getSortIcon(key);
    if (!icon) return label;
    return (
      <span className="header-label">
        {label}
        <span className="sort-icon">{icon}</span>
      </span>
    );
  };

  // Note functions
  const openNoteModal = (coin) => {
    setEditingNote(coin);
    setNoteText(coin.note || '');
    setShowNoteModal(true);
  };

  const saveNote = async () => {
    if (!editingNote) return;

    try {
      const response = await axios.post('/api/update-note', {
        coin_id: editingNote.id,
        note: noteText
      }, { withCredentials: true });

      if (response.data.success) {
        setPortfolio(prev => prev.map(coin =>
          coin.id === editingNote.id ? { ...coin, note: noteText } : coin
        ));
        setShowNoteModal(false);
        setEditingNote(null);
        setNoteText('');
      } else {
        console.error('Save note failed:', response.data.error);
      }
    } catch (err) {
      console.error('Save note error:', err);
    }
  };

  const cancelNote = () => {
    setShowNoteModal(false);
    setEditingNote(null);
    setNoteText('');
  };

  const resolveTradingPair = (symbol) => {
    if (!symbol) return '';
    const cleaned = String(symbol).toUpperCase().replace(/[^A-Z0-9]/g, '');
    if (cleaned.endsWith('USDT')) {
      return cleaned;
    }
    return `${cleaned}USDT`;
  };

  const renderMobileActionsOverlay = () => {
    if (!isMobile || !openActionMenu.type || !openActionMenu.payload) return null;

    const isPortfolio = openActionMenu.type === 'portfolio' && openActionMenu.payload.coin;
    const isWatchlist = openActionMenu.type === 'watchlist' && openActionMenu.payload.item;

    const coin = isPortfolio ? openActionMenu.payload.coin : null;
    const item = isWatchlist ? openActionMenu.payload.item : null;
    const isPlaceholder = isPortfolio ? openActionMenu.payload.isPlaceholder : false;

    return (
      <div className="actions-overlay" onClick={closeActionMenu}>
        <div
          className="actions-bottom-sheet"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="actions-bottom-sheet__header">
            <span>{isPortfolio ? coin.symbol : item.symbol} Actions</span>
            <button className="actions-bottom-sheet__close" onClick={closeActionMenu}>×</button>
          </div>
          <div className="actions-bottom-sheet__body">
            <button
              onClick={() => {
                if (isPortfolio && !isPlaceholder) toggleAlert(coin.id, coin.alert_enabled);
                if (isWatchlist) toggleWatchlistAlert(item.symbol, item.alert_enabled);
                closeActionMenu();
              }}
              disabled={isPortfolio ? isPlaceholder : false}
            >
              {isPortfolio ? (coin.alert_enabled ? 'Disable Alerts' : 'Enable Alerts') : (item.alert_enabled ? 'Disable Alerts' : 'Enable Alerts')}
            </button>
            <button onClick={() => { openNews(isPortfolio ? coin.symbol : item.symbol); closeActionMenu(); }}>News</button>
            <button onClick={() => { refreshNews(isPortfolio ? coin.symbol : item.symbol); closeActionMenu(); }}>Refresh News</button>
            <button onClick={() => { openNoteModal(isPortfolio ? coin : item); closeActionMenu(); }}>Notes</button>
            <button onClick={() => { navigateToTrading(isPortfolio ? coin.symbol : item.symbol, 'BUY'); closeActionMenu(); }}>Buy</button>
            <button onClick={() => { navigateToTrading(isPortfolio ? coin.symbol : item.symbol, 'SELL'); closeActionMenu(); }}>Sell</button>
            {isPortfolio && (
              <button
                onClick={() => { handleStakeClick(coin); closeActionMenu(); }}
                disabled={
                  !stakeableCoins.includes(coin.symbol) ||
                  isPlaceholder ||
                  (coin.value && coin.value < 1)
                }
              >
                Stake
              </button>
            )}
            <button
              onClick={() => {
                if (isPortfolio && !isPlaceholder) hideCoin(coin.id);
                if (isWatchlist) deleteWatchlistItem(item.symbol);
                closeActionMenu();
              }}
              disabled={isPortfolio ? isPlaceholder : false}
            >
              {isPortfolio ? 'Hide' : 'Delete'}
            </button>
          </div>
        </div>
      </div>
    );
  };

  const navigateToTrading = (symbol, side) => {
    const pair = resolveTradingPair(symbol);
    if (!pair) {
      console.warn('Unable to determine trading pair for symbol:', symbol);
      return;
    }
    navigate('/trading', {
      state: {
        tradePrefill: {
          symbol: pair,
          side: side === 'SELL' ? 'SELL' : 'BUY'
        }
      }
    });
  };

  // News function - Show cached/existing analysis (NEWS button)
  const openNews = async (symbol) => {
    try {
      setNewsLoading(true);
      setNewsAnalysisSymbol(symbol);
      setShowNewsModal(true);

      // First try to get cached analysis by checking if we have recent data
      // If no cached data or it's old, fall back to fresh analysis
      const response = await axios.post('/api/ai/news-analysis', {
        symbol: symbol,
        use_cache: true  // Request cached data if available
      }, { withCredentials: true });

      if (response.data.error) {
        setNewsAnalysisData({
          error: true,
          message: response.data.error
        });
      } else {
        setNewsAnalysisData({
          error: false,
          symbol: response.data.symbol,
          analysis: response.data.analysis,
          timestamp: response.data.timestamp,
          prompt_used: response.data.prompt_used
        });
      }
    } catch (error) {
      console.error('Error fetching news analysis:', error);
      setNewsAnalysisData({
        error: true,
        message: error.response?.data?.error || 'Failed to fetch news analysis. Please try again.'
      });
    } finally {
      setNewsLoading(false);
    }
  };

  // Refresh news function - Forces fresh AI analysis (REFRESH button)
  const refreshNews = async (symbol) => {
    try {
      setNewsLoading(true);
      if (!showNewsModal) {
        setNewsAnalysisSymbol(symbol);
        setShowNewsModal(true);
      }

      // Force fresh analysis by bypassing cache
      const response = await axios.post('/api/ai/news-analysis', {
        symbol: symbol,
        force_fresh: true  // Force fresh analysis, bypass cache
      }, { withCredentials: true });

      if (response.data.error) {
        setNewsAnalysisData({
          error: true,
          message: response.data.error
        });
      } else {
        setNewsAnalysisData({
          error: false,
          symbol: response.data.symbol,
          analysis: response.data.analysis,
          timestamp: response.data.timestamp,
          prompt_used: response.data.prompt_used
        });
      }
    } catch (error) {
      console.error('Error refreshing news analysis:', error);
      setNewsAnalysisData({
        error: true,
        message: error.response?.data?.error || 'Failed to refresh news analysis. Please try again.'
      });
    } finally {
      setNewsLoading(false);
    }
  };

  // Hide coin function
  const hideCoin = async (coinId) => {
    try {
      console.log('Hiding coin with ID:', coinId);
      const response = await axios.post('/api/hide-coin', {
        coin_id: coinId
      }, { withCredentials: true });

      console.log('Hide response:', response.data);
      if (response.data.success) {
        setPortfolio(prev => prev.filter(coin => coin.id !== coinId));
        console.log('Coin hidden successfully');
      }
    } catch (err) {
      console.error('Hide coin error:', err);
    }
  };

  // Stake coin function - navigate to Staking page with pre-selected coin
  const handleStakeClick = (coin) => {
    // Navigate to Staking page with coin symbol in URL
    navigate(`/staking?coin=${coin.symbol}`);
  };

  const handleStakeSubmit = async () => {
    if (!stakingCoin || !stakeAmount || parseFloat(stakeAmount) <= 0) {
      alert('Please enter a valid amount');
      return;
    }

    try {
      const response = await axios.post('/api/staking/stake', {
        stakingAsset: stakingCoin.symbol,
        amount: parseFloat(stakeAmount),
        autoRestake: true
      }, { withCredentials: true });

      if (response.data.success) {
        setShowStakeModal(false);
        alert(`Successfully staked ${stakeAmount} ${stakingCoin.symbol}`);
        // Refresh portfolio data
        window.location.reload();
      } else {
        alert(response.data.error || 'Staking failed');
      }
    } catch (err) {
      console.error('Staking error:', err);
      alert(err.response?.data?.error || 'Failed to stake asset');
    }
  };

  // Delete watchlist item function
  const deleteWatchlistItem = async (symbol) => {
    try {
      const response = await axios.post('/api/watchlist/remove', {
        symbol: symbol
      }, { withCredentials: true });

      if (response.data.success) {
        setWatchlist(prev => prev.filter(item => item.symbol !== symbol));
      }
    } catch (err) {
      console.error('Delete watchlist item error:', err);
    }
  };

  // Add to watchlist function
  const addToWatchlist = async (e) => {
    e.preventDefault();
    if (!watchlistSymbol.trim()) return;

    setAddingToWatchlist(true);
    try {
      const response = await axios.post('/api/watchlist/add', {
        symbol: watchlistSymbol.trim().toUpperCase()
      }, { withCredentials: true });

      if (response.data.success) {
        // Clear the input
        setWatchlistSymbol('');

        // Refresh watchlist data to show the new item with current price
        const watchlistResponse = await axios.get('/api/watchlist-live', { withCredentials: true });
        if (watchlistResponse.data) {
          setWatchlist(watchlistResponse.data);
        }
      }
    } catch (err) {
      console.error('Add to watchlist error:', err);
    } finally {
      setAddingToWatchlist(false);
    }
  };

  // Render alert cell for portfolio (uncontrolled inputs like watchlist)
  const renderPortfolioAlertCell = (item, direction) => {
    const typeKey = direction === 'down' ? 'custom_lower_type' : 'custom_upper_type';
    const valKey = direction === 'down' ? 'custom_lower_val' : 'custom_upper_val';
    const pctKey = direction === 'down' ? 'custom_lower_pct' : 'custom_upper_pct';

    const currentType = item[typeKey] || '#';

    if (!item.id) {
      return <span style={{ color: '#888' }}>—</span>;
    }

    // Determine current value based on type (for initial load only) - format to 2 decimal places
    let currentValue = '';
    if (currentType === '#') {
      currentValue = item[valKey] !== null && item[valKey] !== undefined ? parseFloat(item[valKey]).toFixed(2) : '';
    } else if (currentType === '%' || currentType === 'Auto%') {
      currentValue = item[pctKey] !== null && item[pctKey] !== undefined ? parseFloat(item[pctKey]).toFixed(2) : '';
    }

    const handleValueChange = async (newValue) => {
      try {
        // Round to 2 decimal places before sending
        const roundedValue = newValue === '' ? null : parseFloat(parseFloat(newValue).toFixed(2));

        const data = {
          id: item.id,
          type: direction,
          pct_type: currentType,
          value: roundedValue
        };

        const response = await axios.post('/api/set-custom-pct-type', data, { withCredentials: true });

        if (response.data.success) {
          // Update portfolio state with response data
          setPortfolio(prev => prev.map(coin => {
            if (coin.id === item.id) {
              const updatedCoin = { ...coin };

              // Update the correct fields based on response
              if (response.data.custom_lower_type !== undefined) {
                updatedCoin.custom_lower_type = response.data.custom_lower_type;
              }
              if (response.data.custom_upper_type !== undefined) {
                updatedCoin.custom_upper_type = response.data.custom_upper_type;
              }
              if (response.data.custom_lower_val !== undefined) {
                updatedCoin.custom_lower_val = response.data.custom_lower_val;
              }
              if (response.data.custom_upper_val !== undefined) {
                updatedCoin.custom_upper_val = response.data.custom_upper_val;
              }
              if (response.data.custom_lower_pct !== undefined) {
                updatedCoin.custom_lower_pct = response.data.custom_lower_pct;
              }
              if (response.data.custom_upper_pct !== undefined) {
                updatedCoin.custom_upper_pct = response.data.custom_upper_pct;
              }

              return updatedCoin;
            }
            return coin;
          }));
        }
      } catch (err) {
        console.error('Save alert error:', err);
      }
    };

    const handleKeyPress = (e) => {
      if (e.key === 'Enter') {
        const value = e.target.value.replace(/[^0-9.]/g, '');
        // Format to 2 decimal places and update the input display
        const formattedValue = value === '' ? '' : parseFloat(value).toFixed(2);
        e.target.value = formattedValue;
        handleValueChange(formattedValue);
      }
    };

    const handleTypeChange = async (newType) => {
      try {
        // OPTIMISTIC UPDATE: Immediately update the UI before API call
        setPortfolio(prev => prev.map(coin => {
          if (coin.id === item.id) {
            const updatedCoin = { ...coin };

            // Immediately update the type field
            if (direction === 'down') {
              updatedCoin.custom_lower_type = newType;
              // Clear the value fields when changing type
              updatedCoin.custom_lower_val = null;
              updatedCoin.custom_lower_pct = null;
            } else {
              updatedCoin.custom_upper_type = newType;
              // Clear the value fields when changing type
              updatedCoin.custom_upper_val = null;
              updatedCoin.custom_upper_pct = null;
            }

            return updatedCoin;
          }
          return coin;
        }));

        const data = {
          id: item.id,
          type: direction,
          pct_type: newType,
          value: null // Clear value when changing type
        };

        const response = await axios.post('/api/set-custom-pct-type', data, { withCredentials: true });

        if (response.data.success) {
          // Update portfolio state with confirmed response data from backend
          setPortfolio(prev => prev.map(coin => {
            if (coin.id === item.id) {
              const updatedCoin = { ...coin };

              // Update the correct fields based on response
              if (response.data.custom_lower_type !== undefined) {
                updatedCoin.custom_lower_type = response.data.custom_lower_type;
              }
              if (response.data.custom_upper_type !== undefined) {
                updatedCoin.custom_upper_type = response.data.custom_upper_type;
              }
              if (response.data.custom_lower_val !== undefined) {
                updatedCoin.custom_lower_val = response.data.custom_lower_val;
              }
              if (response.data.custom_upper_val !== undefined) {
                updatedCoin.custom_upper_val = response.data.custom_upper_val;
              }
              if (response.data.custom_lower_pct !== undefined) {
                updatedCoin.custom_lower_pct = response.data.custom_lower_pct;
              }
              if (response.data.custom_upper_pct !== undefined) {
                updatedCoin.custom_upper_pct = response.data.custom_upper_pct;
              }

              return updatedCoin;
            }
            return coin;
          }));
        }
      } catch (err) {
        console.error('Update alert type error:', err);
        // Revert optimistic update on error by refreshing data
        fetchPortfolio();
      }
    };

    const isAutoType = currentType === 'Auto%';

    return (
      <div style={{
        display: 'flex',
        gap: '4px',
        alignItems: 'center',
        justifyContent: 'center'
      }}>
        <input
          type="text"
          defaultValue={currentValue}
          disabled={isAutoType}
          onKeyPress={handleKeyPress}
          onChange={(e) => {
            // Allow numbers and decimal point, limit to 2 decimal places
            let value = e.target.value.replace(/[^0-9.]/g, '');
            const parts = value.split('.');
            if (parts.length > 2) {
              value = parts[0] + '.' + parts.slice(1).join('');
            }
            if (parts[1] && parts[1].length > 2) {
              value = parts[0] + '.' + parts[1].substring(0, 2);
            }
            e.target.value = value;
          }}
          style={{
            width: '90px',
            padding: '2px 4px',
            fontSize: '12px',
            background: isAutoType ? '#2a2a2a' : '#1a1f23',
            color: isAutoType ? '#888' : '#fff',
            border: '1px solid #333',
            borderRadius: '2px',
            textAlign: 'center',
            cursor: isAutoType ? 'not-allowed' : 'text'
          }}
        />
        <select
          value={currentType}
          onChange={(e) => handleTypeChange(e.target.value)}
          style={{
            padding: '2px 2px',
            fontSize: '12px',
            background: '#1a1f23',
            color: '#fff',
            border: '1px solid #333',
            borderRadius: '2px',
            width: '45px'
          }}
        >
          <option value="#">#</option>
          <option value="%">%</option>
          <option value="Auto%">Auto%</option>
        </select>
      </div>
    );
  };

  // Render alert cell for watchlist (number only, no dropdown)
  const renderWatchlistAlertCell = (item, direction) => {
    const alertKey = direction === 'down' ? 'down_val' : 'up_val';
    const currentValue = item[alertKey] !== null && item[alertKey] !== undefined ? parseFloat(item[alertKey]).toFixed(2) : '';

    const handleValueChange = async (newValue) => {
      try {
        // Round to 2 decimal places before sending
        const roundedValue = newValue === '' ? null : parseFloat(parseFloat(newValue).toFixed(2));

        const data = {
          symbol: item.symbol,
          direction: direction,
          value: roundedValue
        };

        const response = await axios.post('/api/set-watch-alert', data, { withCredentials: true });

        if (response.data.success) {
          setWatchlist(prev => prev.map(coin => {
            if (coin.symbol === item.symbol) {
              return {
                ...coin,
                [alertKey]: roundedValue
              };
            }
            return coin;
          }));
        }
      } catch (err) {
        console.error('Save watchlist alert error:', err);
      }
    };

    const handleKeyPress = (e) => {
      if (e.key === 'Enter') {
        const value = e.target.value.replace(/[^0-9.]/g, '');
        // Format to 2 decimal places and update the input display
        const formattedValue = value === '' ? '' : parseFloat(value).toFixed(2);
        e.target.value = formattedValue;
        handleValueChange(formattedValue);
      }
    };

    return (
      <div style={{
        display: 'flex',
        gap: '4px',
        alignItems: 'center',
        justifyContent: 'center'
      }}>
        <input
          type="text"
          defaultValue={currentValue}
          onChange={(e) => {
            // Allow numbers and decimal point, limit to 2 decimal places
            let value = e.target.value.replace(/[^0-9.]/g, '');
            const parts = value.split('.');
            if (parts.length > 2) {
              value = parts[0] + '.' + parts.slice(1).join('');
            }
            if (parts[1] && parts[1].length > 2) {
              value = parts[0] + '.' + parts[1].substring(0, 2);
            }
            e.target.value = value;
          }}
          onKeyPress={handleKeyPress}
          style={{
            width: '100px',
            padding: '2px 4px',
            fontSize: '12px',
            background: '#1a1f23',
            color: '#fff',
            border: '1px solid #333',
            borderRadius: '2px',
            textAlign: 'center'
          }}
        />
      </div>
    );
  };

  const renderVolatilityCell = (item, tableType) => {
    const volatilityPct = item.volatility_pct !== null && item.volatility_pct !== undefined ? parseFloat(item.volatility_pct).toFixed(0) : '';

    const handleValueChange = async (newValue) => {
      try {
        const roundedValue = newValue === '' ? null : parseInt(newValue, 10);
        updateVolatilityPct(item, roundedValue, tableType);
      } catch (err) {
        console.error('Save volatility pct error:', err);
      }
    };

    const handleKeyPress = (e) => {
      if (e.key === 'Enter') {
        const value = e.target.value.replace(/[^0-9]/g, '');
        const formattedValue = value === '' ? '' : parseInt(value, 10);
        e.target.value = formattedValue;
        handleValueChange(formattedValue);
      }
    };

    return (
      <div style={{
        display: 'flex',
        gap: '4px',
        alignItems: 'center',
        justifyContent: 'center'
      }}>
        <input
          type="text"
          defaultValue={volatilityPct}
          onChange={(e) => {
            let value = e.target.value.replace(/[^0-9]/g, '');
            e.target.value = value;
          }}
          onKeyPress={handleKeyPress}
          style={{
            width: '60px',
            padding: '2px 4px',
            fontSize: '12px',
            background: '#1a1f23',
            color: '#fff',
            border: '1px solid #333',
            borderRadius: '2px',
            textAlign: 'center'
          }}
        />
        <span>%</span>
      </div>
    );
  };

  const updateVolatilityPct = async (item, value, tableType) => {
    try {
      const endpoint = '/api/set-volatility-pct';
      const data = {
        id: tableType === 'portfolio' ? item.id : null,
        symbol: tableType === 'watchlist' ? item.symbol : null,
        table_type: tableType,
        volatility_pct: value
      };

      const response = await axios.post(endpoint, data, { withCredentials: true });

      if (response.data.success) {
        if (tableType === 'portfolio') {
          setPortfolio(prev => prev.map(coin =>
            coin.id === item.id ? { ...coin, volatility_pct: value } : coin
          ));
        } else {
          setWatchlist(prev => prev.map(coin =>
            coin.symbol === item.symbol ? { ...coin, volatility_pct: value } : coin
          ));
        }
      }
    } catch (err) {
      console.error('Update volatility pct error:', err);
    }
  };

  if (loading) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        height: '50vh',
        color: '#fff',
        fontSize: '18px'
      }}>
        Loading dashboard...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{
        padding: '24px',
        color: '#f56565',
        textAlign: 'center',
        background: 'rgba(245, 101, 101, 0.1)',
        borderRadius: 8,
        border: '1px solid rgba(245, 101, 101, 0.3)'
      }}>
        {error}
      </div>
    );
  }

  if (needsLogin) {
    return (
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        height: '50vh',
        color: '#fff',
        textAlign: 'center'
      }}>
        <div style={{
          background: '#232b31',
          padding: '32px',
          borderRadius: '12px',
          border: '1px solid #333',
          maxWidth: '400px',
          width: '90%'
        }}>
          <h2 style={{ color: '#4fd1c5', marginBottom: '16px' }}>Session Expired</h2>
          <p style={{ color: '#ccc', marginBottom: '24px', lineHeight: '1.5' }}>
            Your session has expired. Please log in again to access your portfolio.
          </p>
          <button
            onClick={() => window.location.href = '/login'}
            style={{
              padding: '12px 24px',
              borderRadius: '6px',
              border: 'none',
              background: '#4fd1c5',
              color: '#fff',
              fontSize: '16px',
              fontWeight: 'bold',
              cursor: 'pointer',
              transition: 'all 0.2s'
            }}
          >
            Log In
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard-page-container">
      {/* Notification */}
      {notification.show && (
        <div style={{
          position: 'fixed',
          top: '20px',
          right: '20px',
          padding: '12px 20px',
          borderRadius: '8px',
          background: notification.type === 'success' ? '#48bb78' : notification.type === 'error' ? '#f56565' : '#4fd1c5',
          color: '#fff',
          zIndex: 1000,
          boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
          animation: 'slideIn 0.3s ease-out'
        }}>
          {notification.message}
          <button
            onClick={() => setNotification({ show: false, message: '', type: 'info' })}
            style={{
              marginLeft: '12px',
              background: 'none',
              border: 'none',
              color: '#fff',
              cursor: 'pointer',
              fontSize: '16px'
            }}
          >
            ×
          </button>
        </div>
      )}
      {/* Charts Section */}
      <div className="charts-container">
        {/* Allocations Chart */}
        <div className="chart-panel">
          <h2 className="chart-title">Allocations</h2>
          <div style={{ height: '300px' }}>
            <PortfolioPie portfolio={portfolio} isLightMode={isLightMode} />
          </div>
        </div>

        {/* Portfolio Trend Chart */}
        <div className="chart-panel">
          <h2 className="chart-title">Portfolio Trend</h2>
          <div style={{ height: '300px' }}>
            {trendLoading ? (
              <div style={{
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                height: '100%',
                color: '#666'
              }}>
                Loading trend...
              </div>
            ) : (
              <PortfolioTrend history={trendHistory} range={trendRange} isLightMode={isLightMode} />
            )}
          </div>

          {/* Time Range Buttons */}
          <div className="time-range-container">
            {TREND_RANGES.map(range => (
              <button
                key={range.key}
                onClick={() => setTrendRange(range.key)}
                className={`time-range-btn ${trendRange === range.key ? 'active' : ''}`}
              >
                {range.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Widgets Row: Fear & Greed, Total Value, CBBI */}
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'stretch',
        gap: '20px',
        marginBottom: '24px',
        flexWrap: 'wrap'
      }}>
        {/* Fear & Greed Index Widget */}
        <FearGreedWidget />

        {/* Total Value Widget */}
        <div style={{
          background: 'var(--card-bg, #ffffff)',
          borderRadius: '12px',
          boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1)',
          padding: '16px',
          minWidth: '280px',
          maxWidth: '320px',
          border: '1px solid var(--border-color, #e0e0e0)',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center'
        }}>
          <div style={{ marginBottom: '16px', textAlign: 'center' }}>
            <h3 style={{
              margin: '0 0 4px 0',
              fontSize: '16px',
              fontWeight: '600',
              color: 'var(--text-primary, #333333)'
            }}>
              Portfolio Value
            </h3>
            <small style={{
              fontSize: '12px',
              color: 'var(--text-secondary, #666666)',
              display: 'block'
            }}>
              Total Holdings (incl. staking & pending)
            </small>
          </div>
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '12px',
            flex: 1,
            justifyContent: 'center'
          }}>
            <div style={{
              fontSize: '32px',
              fontWeight: 'bold',
              color: 'var(--primary-color, #007bff)',
              textAlign: 'center'
            }}>
              ${totalValue ? totalValue.toFixed(2) : '0.00'}
            </div>
            <div style={{
              fontSize: '12px',
              color: 'var(--text-secondary, #666666)',
              opacity: '0.8',
              textAlign: 'center'
            }}>
              Includes Binance.US staking balances · Last updated: {new Date().toLocaleString()}
            </div>
          </div>
        </div>

        {/* CBBI Widget */}
        <CBBIWidget />

        {/* Staking Summary Widget */}
        <StakingSummaryWidget />
      </div>

      {/* Portfolio Table */}
      <div className="table-container portfolio-table">
        <div className="table-header">
          <h2 className="table-title">Portfolio</h2>
        </div>
        <table /* removed colgroup and resizing */ style={{ width: '100%' }}>
          {/* removed dynamic colgroup */}
          <thead>
            <tr>
              <th onClick={() => handleSort('symbol')} className="portfolio-header sortable">
                {renderHeaderLabel('symbol', 'Symbol')}
              </th>
              <th onClick={() => handleSort('amount')} className="portfolio-header sortable">
                {renderHeaderLabel('amount', 'Amount')}
              </th>
              <th onClick={() => handleSort('current_price')} className="portfolio-header sortable">
                {renderHeaderLabel('current_price', 'Current Price')}
              </th>
              <th onClick={() => handleSort('current_value')} className="portfolio-header sortable">
                {renderHeaderLabel('current_value', 'Current Value')}
              </th>
              <th onClick={() => handleSort('purchase_date')} className={`portfolio-header sortable ${isMobile ? 'mobile-hide' : ''}`}>
                {renderHeaderLabel('purchase_date', 'Purchase Date')}
              </th>
              <th className="portfolio-header">Price Down Alert</th>
              <th className="portfolio-header">Price Up Alert</th>
              <th onClick={() => handleSort('volatility_pct')} className="portfolio-header sortable">
                {renderHeaderLabel('volatility_pct', 'Volatility %')}
              </th>
              <th onClick={() => handleSort('avg_entry')} className={`portfolio-header sortable ${isMobile ? 'mobile-hide' : ''}`}>
                {renderHeaderLabel('avg_entry', 'Avg Entry')}
              </th>
              <th onClick={() => handleSort('pct_change')} className={`portfolio-header sortable ${isMobile ? 'mobile-hide' : ''}`}>
                {renderHeaderLabel('pct_change', '% Change')}
              </th>
              <th onClick={() => handleSort('sentiment')} className={`portfolio-header sortable ${isMobile ? 'mobile-hide' : ''}`}>
                {renderHeaderLabel('sentiment', 'Sentiment')}
              </th>
              <th className="portfolio-header">Actions</th>
            </tr>
          </thead>
          <tbody>
            {!Array.isArray(portfolio) || portfolio.length === 0 ? (
              <tr>
                <td colSpan="12" className="no-data">
                  No portfolio data available
                </td>
              </tr>
            ) : (
              sortData(portfolio, sortConfig.key).map((coin) => {
                const isPlaceholder = !!coin.pendingPlaceholder || !coin.id;
                const alertTitle = isPlaceholder
                  ? 'Alerts unavailable for pending-only entries'
                  : coin.alert_enabled
                    ? 'Alerts enabled'
                    : 'Alerts disabled';
                const alertToggleClass = `alert-toggle ${coin.alert_enabled ? 'alert-enabled' : 'alert-disabled'}${isPlaceholder ? ' alert-disabled' : ''}`;

                return (
                  <tr
                    key={coin.symbol}
                    className={coin.hasPendingOrder ? 'pending-order' : ''}
                    onMouseMove={(e) => handleRowHover(coin, e)}
                    onMouseLeave={handleRowLeave}
                  >
                    <td
                      className="symbol-cell"
                      onMouseEnter={(e) => handleSymbolHover(coin.symbol, e)}
                      onMouseLeave={handleSymbolLeave}
                      onClick={() => handleChartClick(coin.symbol)}
                      style={{ cursor: 'pointer' }}
                      title="Hover for 7-day chart, click to open on Binance"
                    >
                      {coin.symbol}
                    </td>
                    <td>{coin.pendingPlaceholder ? '0.0000' : (coin.amount !== undefined && coin.amount !== null ? coin.amount.toFixed(4) : '—')}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>{coin.current_price ? `$${coin.current_price.toFixed(2)}` : '—'}</td>
                    <td>{coin.current_value ? `$${coin.current_value.toFixed(2)}` : '—'}</td>
                    <td className={isMobile ? 'mobile-hide' : ''} style={{ whiteSpace: 'nowrap' }}>{coin.purchase_date ? coin.purchase_date.split(' ')[0] : '—'}</td>
                    <td style={{ textAlign: 'center' }}>{renderPortfolioAlertCell(coin, 'down')}</td>
                    <td style={{ textAlign: 'center' }}>{renderPortfolioAlertCell(coin, 'up')}</td>
                    <td style={{ textAlign: 'center' }}>{renderVolatilityCell(coin, 'portfolio')}</td>
                    <td className={isMobile ? 'mobile-hide' : ''} style={{ whiteSpace: 'nowrap' }}>{coin.avg_entry ? `$${coin.avg_entry.toFixed(2)}` : '—'}</td>
                    <td className={`${coin.pct_change >= 0 ? 'status-positive' : 'status-negative'} ${isMobile ? 'mobile-hide' : ''}`}>
                      {coin.pct_change !== undefined ? `${coin.pct_change >= 0 ? '+' : ''}${coin.pct_change.toFixed(2)}%` : '—'}
                    </td>
                    <td
                      className={isMobile ? 'mobile-hide' : ''}
                      title={coin.sentiment_last_updated ? `Last Updated: ${new Date(coin.sentiment_last_updated).toLocaleString()}` : 'No analysis date available'}
                      style={{ cursor: 'help' }}
                    >
                      {coin.sentiment || 'Hold'}
                    </td>
                    <td className="actions-cell" style={{ whiteSpace: 'nowrap', position: 'relative' }}>
                      {isMobile ? (
                        <>
                          <button
                            className="actions-dropdown-btn"
                            onClick={(e) => toggleActionMenu('portfolio', coin.symbol, e, { coin, isPlaceholder })}
                          >
                            Actions
                          </button>
                          {openActionMenu.type === 'portfolio' && openActionMenu.key === coin.symbol && (
                            <div style={{ display: 'none' }} />
                          )}
                        </>
                      ) : (
                        <>
                          <span
                            onClick={!isPlaceholder ? () => toggleAlert(coin.id, coin.alert_enabled) : undefined}
                            className={alertToggleClass}
                            title={alertTitle}
                            style={{ cursor: isPlaceholder ? 'not-allowed' : 'pointer' }}
                          >
                            🔔
                          </span>
                          <span
                            className="action-icon"
                            title="News"
                            onClick={() => openNews(coin.symbol)}
                            style={{ cursor: 'pointer', marginLeft: 8 }}
                          >
                            📄
                          </span>
                          <span
                            className="action-icon"
                            title="Refresh News"
                            onClick={() => refreshNews(coin.symbol)}
                            style={{ cursor: 'pointer', marginLeft: 8 }}
                          >
                            🔄
                          </span>
                          <span
                            className="action-icon"
                            title={coin.note ? `Note: ${coin.note}` : 'Add note'}
                            onClick={() => openNoteModal(coin)}
                            style={{ cursor: 'pointer', marginLeft: 8 }}
                          >
                            ✏️
                          </span>
                          <button
                            className="trade-action-btn buy"
                            onClick={() => navigateToTrading(coin.symbol, 'BUY')}
                          >
                            Buy
                          </button>
                          <button
                            className="trade-action-btn sell"
                            onClick={() => navigateToTrading(coin.symbol, 'SELL')}
                          >
                            Sell
                          </button>
                          <button
                            className="trade-action-btn stake"
                            onClick={() => handleStakeClick(coin)}
                            disabled={
                              !stakeableCoins.includes(coin.symbol) ||
                              isPlaceholder ||
                              (coin.value && coin.value < 1)
                            }
                            title={
                              !stakeableCoins.includes(coin.symbol)
                                ? 'Staking not available for this coin'
                                : (coin.value && coin.value < 1)
                                  ? 'Minimum $1 USDT value required to stake'
                                  : 'Stake this coin'
                            }
                          >
                            Stake
                          </button>
                          <button
                            className="trade-action-btn hide"
                            onClick={() => { if (!isPlaceholder) { hideCoin(coin.id); } }}
                            title={isPlaceholder ? 'Cannot hide pending-only entries' : 'Hide coin'}
                            disabled={isPlaceholder}
                          >
                            Hide
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pending Order Tooltip */}
      {orderTooltip.visible && (
        <div
          className="pending-order-tooltip"
          style={{
            position: 'fixed',
            left: `${orderTooltip.x}px`,
            top: `${orderTooltip.y}px`,
            backgroundColor: 'rgba(255, 215, 0, 0.95)',
            color: 'black',
            padding: '10px 15px',
            borderRadius: '6px',
            fontSize: '14px',
            fontWeight: '500',
            maxWidth: '350px',
            zIndex: 10000,
            pointerEvents: 'none',
            boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
            border: '2px solid rgba(0,0,0,0.2)',
            whiteSpace: 'pre-line'
          }}
        >
          {orderTooltip.text}
        </div>
      )}

      {/* Watchlist Section */}
      <div className="table-container watchlist-table">
        <div className="table-header">
          <h2 className="table-title">Watchlist</h2>
        </div>
        <div className="watchlist-input">
          <input
            type="text"
            placeholder="Symbol (e.g. SOL, BTC)"
            className="watchlist-symbol-input"
            value={watchlistSymbol}
            onChange={(e) => setWatchlistSymbol(e.target.value)}
            disabled={addingToWatchlist}
          />
          <button className="btn" onClick={addToWatchlist} disabled={addingToWatchlist}>
            {addingToWatchlist ? 'Adding...' : 'Add to Watchlist'}
          </button>
        </div>
        <table /* removed colgroup and resizing */ style={{ width: '100%' }}>
          {/* removed dynamic colgroup */}
          <thead>
            <tr>
              <th onClick={() => handleSort('symbol')} style={{ cursor: 'pointer' }}>
                Symbol {getSortIcon('symbol')}
              </th>
              <th onClick={() => handleSort('current_price')} style={{ cursor: 'pointer' }}>
                Current Price {getSortIcon('current_price')}
              </th>
              <th onClick={() => handleSort('sentiment')} className={isMobile ? 'mobile-hide' : ''} style={{ cursor: 'pointer' }}>
                Sentiment {getSortIcon('sentiment')}
              </th>
              <th>Price Down Alert</th>
              <th>Price Up Alert</th>
              <th className={isMobile ? 'mobile-hide' : ''}>Volatility %</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {!Array.isArray(watchlist) || watchlist.length === 0 ? (
              <tr>
                <td colSpan="6" className="no-data" style={{ textAlign: 'center' }}>
                  No watchlist items
                </td>
              </tr>
            ) : (
              sortData(watchlist, sortConfig.key).map((item) => (
                <tr key={item.symbol}>
                  <td
                    className="symbol-cell"
                    style={{ textAlign: 'center', cursor: 'pointer' }}
                    onMouseEnter={(e) => handleSymbolHover(item.symbol, e)}
                    onMouseLeave={handleSymbolLeave}
                    onClick={() => handleChartClick(item.symbol)}
                    title="Hover for 7-day chart, click to open on Binance"
                  >
                    {item.symbol}
                  </td>
                  <td style={{ whiteSpace: 'nowrap', textAlign: 'center' }}>{item.current_price ? `$${item.current_price.toFixed(2)}` : '—'}</td>
                  <td className={isMobile ? 'mobile-hide' : ''} style={{ textAlign: 'center' }}>{item.sentiment || 'Watch'}</td>
                  <td style={{ textAlign: 'center' }}>{renderWatchlistAlertCell(item, 'down')}</td>
                  <td style={{ textAlign: 'center' }}>{renderWatchlistAlertCell(item, 'up')}</td>
                  <td className={isMobile ? 'mobile-hide' : ''} style={{ textAlign: 'center' }}>{renderVolatilityCell(item, 'watchlist')}</td>
                  <td className="actions-cell" style={{ textAlign: 'center', whiteSpace: 'nowrap', position: 'relative' }}>
                    {isMobile ? (
                      <>
                        <button
                          className="actions-dropdown-btn"
                          onClick={(e) => toggleActionMenu('watchlist', item.symbol, e, { item })}
                        >
                          Actions
                        </button>
                        {openActionMenu.type === 'watchlist' && openActionMenu.key === item.symbol && (
                          <div style={{ display: 'none' }} />
                        )}
                      </>
                    ) : (
                      <>
                        <span
                          onClick={() => toggleWatchlistAlert(item.symbol, item.alert_enabled)}
                          className={`alert-toggle ${item.alert_enabled ? 'alert-enabled' : 'alert-disabled'}`}
                          title={item.alert_enabled ? 'Alerts enabled' : 'Alerts disabled'}
                          style={{ cursor: 'pointer' }}
                        >
                          🔔
                        </span>
                        <span
                          className="action-icon"
                          title="News"
                          onClick={() => openNews(item.symbol)}
                          style={{ cursor: 'pointer', marginLeft: 8 }}
                        >
                          📄
                        </span>
                        <span
                          className="action-icon"
                          title="Refresh News"
                          onClick={() => refreshNews(item.symbol)}
                          style={{ cursor: 'pointer', marginLeft: 8 }}
                        >
                          🔄
                        </span>
                        <span
                          className="action-icon"
                          title={item.note ? `Note: ${item.note}` : 'Add note'}
                          onClick={() => openNoteModal(item)}
                          style={{ cursor: 'pointer', marginLeft: 8 }}
                        >
                          ✏️
                        </span>
                        <button
                          className="trade-action-btn buy"
                          onClick={() => navigateToTrading(item.symbol, 'BUY')}
                          style={{ marginLeft: 8 }}
                        >
                          Buy
                        </button>
                        <button
                          className="btn"
                          style={{
                            background: '#f56565',
                            color: '#fff',
                            border: 'none',
                            padding: '4px 8px',
                            borderRadius: '4px',
                            cursor: 'pointer',
                            fontSize: '12px',
                            marginLeft: 8
                          }}
                          onClick={() => deleteWatchlistItem(item.symbol)}
                          title="Delete from watchlist"
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Note Modal */}
      {showNoteModal && (
        <div className="modal-overlay">
          <div className="modal-content">
            <div className="modal-header">
              Add Note for {editingNote?.symbol}
            </div>

            <div style={{ padding: '20px 24px', flex: 1 }}>
              <textarea
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
                placeholder="Enter your note here (max 5000 characters)..."
                maxLength={5000}
              />
              <div style={{
                marginTop: '12px',
                fontSize: '12px',
                color: '#666',
                textAlign: 'right'
              }}>
                {noteText.length}/5000 characters
              </div>
            </div>

            <div className="modal-actions">
              <button
                className="btn btn-secondary"
                onClick={cancelNote}
              >
                Cancel
              </button>
              <button
                className="btn"
                onClick={saveNote}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Price History Popup */}
      <PriceHistoryPopup
        symbol={hoverPopup.symbol}
        isVisible={hoverPopup.isVisible}
        position={hoverPopup.position}
        onClose={handleSymbolLeave}
        onChartClick={handleChartClick}
      />

      {/* Mobile Actions Overlay */}
      {renderMobileActionsOverlay()}

      {/* News Analysis Modal */}
      {showNewsModal && (
        <div className="modal-overlay" onClick={() => setShowNewsModal(false)}>
          <div className="modal-content analysis-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>📰 {newsAnalysisSymbol} News Analysis</h3>
              <button
                className="modal-close"
                onClick={() => setShowNewsModal(false)}
              >
                ×
              </button>
            </div>

            <div className="modal-body">
              {newsLoading ? (
                <div className="loading-container">
                  <div className="loading-spinner"></div>
                  <p>Analyzing latest news for {newsAnalysisSymbol}...</p>
                  <p style={{ fontSize: '14px', color: '#666' }}>
                    Searching web sources for real-time news and market impact analysis...
                  </p>
                </div>
              ) : newsAnalysisData?.error ? (
                <div className="error-container">
                  <h4>⚠️ Error</h4>
                  <p>{newsAnalysisData.message}</p>
                </div>
              ) : newsAnalysisData ? (
                <div className="analysis-content">
                  <div className="analysis-header">
                    <div className="analysis-meta">
                      <span className="timestamp">
                        📅 {newsAnalysisData.timestamp}
                      </span>
                    </div>
                  </div>

                  <div className="analysis-text" style={{
                    fontSize: '16px',
                    lineHeight: '1.6',
                    fontFamily: 'system-ui, -apple-system, sans-serif',
                    color: '#ffffff',
                    fontWeight: '400',
                    wordBreak: 'break-word',
                    overflowWrap: 'anywhere'
                  }}>
                    {newsAnalysisData.analysis.split('\n').map((paragraph, index) => (
                      paragraph.trim() && (
                        <p key={index} style={{ marginBottom: '16px', color: '#ffffff' }} dangerouslySetInnerHTML={{
                          __html: paragraph
                            .replace(/\*\*(.*?)\*\*/g, '<strong style="color: #4fd1c5; font-weight: 600;">$1</strong>')
                            .replace(/\*(.*?)\*/g, '<em style="color: #cccccc; font-style: italic;">$1</em>')
                            .replace(/((?:https?:\/\/|\/\/)[^\s]+)/g, (match) => {
                              const href = match.startsWith('//') ? `https:${match}` : match;
                              return `<a href="${href}" target="_blank" rel="noopener noreferrer" style="color: #4fd1c5; text-decoration: underline;">${match}</a>`;
                            })
                        }} />
                      )
                    ))}
                  </div>

                  <div className="analysis-footer">
                    <small style={{ color: '#666' }}>
                      Prompt used: {newsAnalysisData.prompt_used}
                    </small>
                  </div>
                </div>
              ) : null}
            </div>

            <div className="modal-actions">
              <button
                className="btn btn-secondary"
                onClick={() => setShowNewsModal(false)}
              >
                Close
              </button>
              {newsAnalysisData && !newsAnalysisData.error && (
                <button
                  className="btn btn-primary"
                  onClick={() => openNews(newsAnalysisSymbol)}
                >
                  Refresh Analysis
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Stake Modal */}
      {showStakeModal && stakingCoin && (
        <div className="modal-overlay" onClick={() => setShowStakeModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>💰 Stake {stakingCoin.symbol}</h3>
              <button className="modal-close" onClick={() => setShowStakeModal(false)}>×</button>
            </div>
            <div style={{ padding: '20px 24px' }}>
              <div style={{ marginBottom: '20px' }}>
                <label style={{ display: 'block', marginBottom: '8px', fontWeight: '500' }}>
                  Amount to Stake:
                </label>
                <input
                  type="number"
                  value={stakeAmount}
                  onChange={(e) => setStakeAmount(e.target.value)}
                  placeholder="0.00"
                  step="0.00000001"
                  style={{
                    width: '100%',
                    padding: '10px',
                    borderRadius: '6px',
                    border: '1px solid var(--border-color, #444)',
                    backgroundColor: 'var(--input-bg, #333)',
                    color: 'var(--text-primary, #fff)',
                    fontSize: '16px'
                  }}
                />
                <div style={{ marginTop: '8px', fontSize: '12px', color: '#888' }}>
                  Available: {stakingCoin.amount.toFixed(8)} {stakingCoin.symbol}
                </div>
              </div>

              <div style={{
                padding: '12px',
                borderRadius: '6px',
                backgroundColor: 'rgba(255, 152, 0, 0.1)',
                color: '#FFB74D',
                fontSize: '13px',
                marginBottom: '20px'
              }}>
                ⚠️ Staked assets will be locked for a period. Check the Staking page for details.
              </div>
            </div>
            <div className="modal-actions">
              <button className="btn btn-secondary" onClick={() => setShowStakeModal(false)}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={handleStakeSubmit}>
                Confirm Stake
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}

export default Dashboard;
