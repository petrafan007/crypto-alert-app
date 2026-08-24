import React, { useEffect, useState, useRef, useMemo } from 'react';
import { createPortal } from 'react-dom';
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
import PortfolioPerformanceTable from '../components/PortfolioPerformanceTable';
import DashboardWidgetGrid from '../components/DashboardWidgetGrid';
import TopMoversWidget from '../components/TopMoversWidget';
import RecentTradesWidget from '../components/RecentTradesWidget';
import AIPulseWidget from '../components/AIPulseWidget';
import StakingYieldWidget from '../components/StakingYieldWidget';
import RiskMonitorWidget from '../components/RiskMonitorWidget';
import QuickTradeWidget from '../components/QuickTradeWidget';
import GasMonitorWidget from '../components/GasMonitorWidget';
import { FaSyncAlt } from 'react-icons/fa';
import CryptoIcon from '../components/CryptoIcon';
import TableColumnModal from '../components/TableColumnModal';
import CancelOrderConfirmModal from '../components/CancelOrderConfirmModal';

const TREND_RANGES = [
  { key: '4H', label: '4H' },
  { key: '12H', label: '12H' },
  { key: '24H', label: '24H' },
  { key: '7D', label: '7D' },
  { key: '30D', label: '30D' },
  { key: '90D', label: '90D' },
  { key: '1Y', label: '1Y' },
  { key: 'ALL', label: 'ALL' }
];

export const PORTFOLIO_DEFAULT_COLUMNS = [
  'symbol',
  'amount',
  'current_price',
  'current_value',
  'down_alert',
  'up_alert',
  'volatility_pct',
  'avg_entry',
  'pct_change',
  'sentiment',
  'actions'
];

export const PORTFOLIO_REQUIRED_COLUMNS = ['symbol', 'amount', 'current_price', 'current_value', 'actions'];

export const PORTFOLIO_COLUMN_DEFINITIONS = {
  symbol: { label: 'Symbol', required: true, sortable: true, defaultWidth: 120, description: 'Asset ticker and icon' },
  amount: { label: 'Amount', required: true, sortable: true, defaultWidth: 110, description: 'Holdings quantity' },
  current_price: { label: 'Current Price', required: true, sortable: true, defaultWidth: 120, description: 'Live market rate' },
  current_value: { label: 'Current Value', required: true, sortable: true, defaultWidth: 120, description: 'Total value in USDT' },
  down_alert: { label: 'Price Down Alert', required: false, sortable: false, defaultWidth: 140, description: 'Drop price alert' },
  up_alert: { label: 'Price Up Alert', required: false, sortable: false, defaultWidth: 140, description: 'Surge price alert' },
  volatility_pct: { label: 'Volatility %', required: false, sortable: true, defaultWidth: 120, description: 'Historical volatility' },
  avg_entry: { label: 'Avg Entry', required: false, sortable: true, defaultWidth: 110, description: 'Average buy price' },
  pct_change: { label: '% Change', required: false, sortable: true, defaultWidth: 110, description: 'Unrealized P&L %' },
  change_24h: { label: '24h % Change', required: false, sortable: true, defaultWidth: 110, description: '24-hour price change %' },
  sentiment: { label: 'Sentiment', required: false, sortable: true, defaultWidth: 150, description: 'AI market sentiment' },
  high_low_24h: { label: '24h High / Low', required: false, sortable: false, defaultWidth: 140, description: '24-hour high and low range' },
  volume_24h: { label: '24h Volume ($)', required: false, sortable: false, defaultWidth: 130, description: '24-hour trading volume' },
  market_cap: { label: 'Market Cap', required: false, sortable: false, defaultWidth: 130, description: 'Market capitalization' },
  pnl_usd: { label: 'Profit & Loss ($)', required: false, sortable: true, defaultWidth: 120, description: 'Unrealized profit in USD' },
  allocation_pct: { label: 'Allocation %', required: false, sortable: true, defaultWidth: 110, description: 'Percent of portfolio' },
  target_price: { label: 'Target Price', required: false, sortable: false, defaultWidth: 120, description: 'Target take-profit price' },
  last_updated: { label: 'Last Updated', required: false, sortable: false, defaultWidth: 130, description: 'Last price check timestamp' },
  actions: { label: 'Actions', required: true, sortable: false, defaultWidth: 440, description: 'Trade and manage actions' }
};

export const WATCHLIST_DEFAULT_COLUMNS = [
  'symbol',
  'current_price',
  'down_alert',
  'up_alert',
  'volatility_pct',
  'sentiment',
  'actions'
];

export const WATCHLIST_REQUIRED_COLUMNS = ['symbol', 'current_price', 'actions'];

export const WATCHLIST_COLUMN_DEFINITIONS = {
  symbol: { label: 'Symbol', required: true, sortable: true, defaultWidth: 120, description: 'Asset ticker and icon' },
  current_price: { label: 'Current Price', required: true, sortable: true, defaultWidth: 120, description: 'Live market rate' },
  down_alert: { label: 'Price Down Alert', required: false, sortable: false, defaultWidth: 140, description: 'Drop price alert' },
  up_alert: { label: 'Price Up Alert', required: false, sortable: false, defaultWidth: 140, description: 'Surge price alert' },
  volatility_pct: { label: 'Volatility %', required: false, sortable: false, defaultWidth: 120, description: 'Historical volatility' },
  sentiment: { label: 'Sentiment', required: false, sortable: true, defaultWidth: 150, description: 'AI market sentiment' },
  pct_change: { label: '24h % Change', required: false, sortable: true, defaultWidth: 110, description: '24-hour price change %' },
  high_low_24h: { label: '24h High / Low', required: false, sortable: false, defaultWidth: 140, description: '24-hour high and low range' },
  volume_24h: { label: '24h Volume ($)', required: false, sortable: false, defaultWidth: 130, description: '24-hour trading volume' },
  market_cap: { label: 'Market Cap', required: false, sortable: false, defaultWidth: 130, description: 'Market capitalization' },
  target_price: { label: 'Target Price', required: false, sortable: false, defaultWidth: 120, description: 'Target price alert' },
  last_updated: { label: 'Last Updated', required: false, sortable: false, defaultWidth: 130, description: 'Last price check timestamp' },
  actions: { label: 'Actions', required: true, sortable: false, defaultWidth: 350, description: 'Watchlist actions' }
};

function Dashboard({ isLightMode }) {
  const { isLoggingOut, user } = useAuth();
  const navigate = useNavigate();
  const [totalValue, setTotalValue] = useState(null);
  const [portfolio, setPortfolio] = useState([]);
  const [watchlist, setWatchlist] = useState([]);
  const [loading, setLoading] = useState(true);
  const pendingAddedWatchlistSymbolsRef = useRef(new Map());

  // Helper to preserve pending optimistic watchlist items across background poll intervals
  const mergeWatchlistPreservingPending = (newList, prevList) => {
    if (!Array.isArray(newList)) return prevList || [];
    const newSymbols = new Set(newList.map(c => (c.symbol || '').toUpperCase()));

    // Clean up confirmed additions from the ref map if they are now present in the server's list
    for (const [sym] of pendingAddedWatchlistSymbolsRef.current.entries()) {
      if (newSymbols.has(sym)) {
        pendingAddedWatchlistSymbolsRef.current.delete(sym);
      }
    }

    // Collect all unconfirmed additions that the server's list doesn't have yet
    const pendingItems = Array.from(pendingAddedWatchlistSymbolsRef.current.values())
      .filter(item => !newSymbols.has((item.symbol || '').toUpperCase()));

    if (pendingItems.length === 0) return newList;
    return [...pendingItems, ...newList];
  };

  const [usdPairBases, setUsdPairBases] = useState(new Set());
  const [usdtPairBases, setUsdtPairBases] = useState(new Set());
  const [tradingPairsLoaded, setTradingPairsLoaded] = useState(false);
  const [error, setError] = useState(null);
  const [trendHistory, setTrendHistory] = useState([]);
  const [pendingOrders, setPendingOrders] = useState([]);
  const [orderTooltip, setOrderTooltip] = useState({ isVisible: false, text: '', position: { x: 0, y: 0 } });
  const [trendRange, setTrendRange] = useState('7D');
  const [trendLoading, setTrendLoading] = useState(true);
  const [refreshingSentiment, setRefreshingSentiment] = useState({});

  // Column customization state - Portfolio
  const [portfolioVisibleCols, setPortfolioVisibleCols] = useState(() => {
    try {
      const saved = localStorage.getItem('crypto_portfolio_visible_columns');
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) {
          PORTFOLIO_REQUIRED_COLUMNS.forEach(rc => {
            if (!parsed.includes(rc)) parsed.push(rc);
          });
          return parsed;
        }
      }
    } catch (e) {}
    return [...PORTFOLIO_DEFAULT_COLUMNS];
  });

  const [portfolioColOrder, setPortfolioColOrder] = useState(() => {
    try {
      const saved = localStorage.getItem('crypto_portfolio_column_order');
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) {
          let filtered = parsed.filter(c => c !== 'symbol' && c !== 'actions' && PORTFOLIO_COLUMN_DEFINITIONS[c]);
          return ['symbol', ...filtered, 'actions'];
        }
      }
    } catch (e) {}
    return [...PORTFOLIO_DEFAULT_COLUMNS];
  });

  const [portfolioColWidths, setPortfolioColWidths] = useState(() => {
    try {
      const saved = localStorage.getItem('crypto_portfolio_column_widths');
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed && typeof parsed === 'object') {
          if (parsed.actions && parsed.actions < 420) {
            parsed.actions = 440;
          }
          return parsed;
        }
      }
    } catch (e) {}
    return {};
  });

  // Column customization state - Watchlist
  const [watchlistVisibleCols, setWatchlistVisibleCols] = useState(() => {
    try {
      const saved = localStorage.getItem('crypto_watchlist_visible_columns');
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) {
          WATCHLIST_REQUIRED_COLUMNS.forEach(rc => {
            if (!parsed.includes(rc)) parsed.push(rc);
          });
          return parsed;
        }
      }
    } catch (e) {}
    return [...WATCHLIST_DEFAULT_COLUMNS];
  });

  const [watchlistColOrder, setWatchlistColOrder] = useState(() => {
    try {
      const saved = localStorage.getItem('crypto_watchlist_column_order');
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) {
          let filtered = parsed.filter(c => c !== 'symbol' && c !== 'actions' && WATCHLIST_COLUMN_DEFINITIONS[c]);
          return ['symbol', ...filtered, 'actions'];
        }
      }
    } catch (e) {}
    return [...WATCHLIST_DEFAULT_COLUMNS];
  });

  const [watchlistColWidths, setWatchlistColWidths] = useState(() => {
    try {
      const saved = localStorage.getItem('crypto_watchlist_column_widths');
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed && typeof parsed === 'object') {
          if (parsed.actions && parsed.actions < 320) {
            parsed.actions = 350;
          }
          return parsed;
        }
      }
    } catch (e) {}
    return {};
  });

  const totalPortfolioWidth = useMemo(() => {
    const cols = portfolioColOrder.filter(k => portfolioVisibleCols.includes(k) && PORTFOLIO_COLUMN_DEFINITIONS[k]);
    return cols.reduce((acc, k) => acc + (portfolioColWidths[k] || PORTFOLIO_COLUMN_DEFINITIONS[k]?.defaultWidth || 120), 0);
  }, [portfolioColOrder, portfolioVisibleCols, portfolioColWidths]);

  const totalWatchlistWidth = useMemo(() => {
    const cols = watchlistColOrder.filter(k => watchlistVisibleCols.includes(k) && WATCHLIST_COLUMN_DEFINITIONS[k]);
    return cols.reduce((acc, k) => acc + (watchlistColWidths[k] || WATCHLIST_COLUMN_DEFINITIONS[k]?.defaultWidth || 120), 0);
  }, [watchlistColOrder, watchlistVisibleCols, watchlistColWidths]);

  // Symbols currently held in the portfolio, used to highlight owned coins in the Top Movers widget
  const ownedSymbols = useMemo(() => {
    return new Set(portfolio.map(c => (c.symbol || '').toUpperCase()).filter(Boolean));
  }, [portfolio]);

  // Modals and context menus
  const [columnModal, setColumnModal] = useState({ isOpen: false, tableType: 'portfolio' });
  const [cancelContextMenu, setCancelContextMenu] = useState({ isOpen: false, coin: null, x: 0, y: 0, orders: [] });
  const [cancelModalState, setCancelModalState] = useState({ isOpen: false, coin: null, order: null, loading: false, error: null });
  const [draggedColKey, setDraggedColKey] = useState(null);
  const [dragOverColKey, setDragOverColKey] = useState(null);
  const [isResizing, setIsResizing] = useState(false);

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
  const [mobileTab, setMobileTab] = useState('charts'); // 'charts' | 'tables'
  const [openActionMenu, setOpenActionMenu] = useState({ type: null, key: null, payload: null });
  const [openTradeQuoteMenu, setOpenTradeQuoteMenu] = useState({ type: null, key: null, side: null, position: null });
  const [volatilityHoursSetting, setVolatilityHoursSetting] = useState(24);
  const [autoSellModal, setAutoSellModal] = useState({
    isOpen: false,
    symbol: '',
    coin: null,
    tableType: 'portfolio',
    quoteCurrency: 'USDT',
    volatilityPct: 0,
    volatilityHours: 24,
    loading: false,
    error: ''
  });
  const [autoBuyModal, setAutoBuyModal] = useState({
    isOpen: false,
    symbol: '',
    coin: null,
    tableType: 'portfolio',
    quoteCurrency: 'USDT',
    amount: '',
    volatilityPct: 0,
    volatilityHours: 24,
    freeBalance: 0,
    reservedBalance: 0,
    availableBalance: 0,
    activeCommitments: [],
    loadingBalance: false,
    loading: false,
    error: ''
  });

  // Coin Performance filter modal state
  const [showPerformanceCoinModal, setShowPerformanceCoinModal] = useState(false);
  const [performanceHiddenCoins, setPerformanceHiddenCoins] = useState(() => {
    try {
      const direct = localStorage.getItem('crypto_performance_hidden_coins_persistent');
      if (direct) return JSON.parse(direct) || [];
      const legacy = localStorage.getItem('crypto_performance_hidden_coins_v1_69') || localStorage.getItem('crypto_performance_hidden_coins');
      if (legacy) {
        const parsed = JSON.parse(legacy) || [];
        localStorage.setItem('crypto_performance_hidden_coins_persistent', JSON.stringify(parsed));
        return parsed;
      }
    } catch (e) {}
    return [];
  });
  const [performanceCoinDraft, setPerformanceCoinDraft] = useState([]);
  const [performanceCoinSearch, setPerformanceCoinSearch] = useState('');

  // Recent Order History filter modal state
  const [showRecentTradesModal, setShowRecentTradesModal] = useState(false);
  const [recentTradesConfig, setRecentTradesConfig] = useState(() => {
    try {
      const direct = localStorage.getItem('crypto_recent_trades_config_persistent');
      if (direct) {
        const parsed = JSON.parse(direct);
        return {
          maxOrders: typeof parsed.maxOrders === 'number' ? Math.max(0, Math.min(20, parsed.maxOrders)) : 5,
          statusFilters: Array.isArray(parsed.statusFilters) && parsed.statusFilters.length > 0
            ? parsed.statusFilters
            : ['FILLED', 'NEW', 'CANCELED', 'PARTIALLY_FILLED']
        };
      }
    } catch (e) {}
    return {
      maxOrders: 5,
      statusFilters: ['FILLED', 'NEW', 'CANCELED', 'PARTIALLY_FILLED']
    };
  });
  const [recentTradesDraftMaxOrders, setRecentTradesDraftMaxOrders] = useState(5);
  const [recentTradesDraftStatuses, setRecentTradesDraftStatuses] = useState(['FILLED', 'NEW', 'CANCELED', 'PARTIALLY_FILLED']);

  // Top Gainers & Losers (market-wide) config modal state
  const [showTopMoversModal, setShowTopMoversModal] = useState(false);
  const [topMoversConfig, setTopMoversConfig] = useState(() => {
    try {
      const saved = localStorage.getItem('crypto_top_movers_config_persistent');
      if (saved) {
        const parsed = JSON.parse(saved);
        return { count: Math.max(3, Math.min(25, parseInt(parsed.count, 10) || 10)) };
      }
    } catch (e) {}
    return { count: 10 };
  });
  const [topMoversDraftCount, setTopMoversDraftCount] = useState(10);

  const tradeQuoteMenuStyle = isMobile
    ? { display: 'flex', flexDirection: 'column', gap: 4, margin: '0 0 4px' }
    : { position: 'fixed', top: openTradeQuoteMenu.position?.top ?? 0, left: openTradeQuoteMenu.position?.left ?? 0, zIndex: 1000, display: 'flex', flexDirection: 'column', gap: 4, minWidth: 154 };

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

  useEffect(() => {
    const fetchSettings = async () => {
      try {
        const res = await axios.get('/api/settings', { withCredentials: true });
        const vh = res.data?.volatility_hours ?? res.data?.settings?.volatility_hours;
        if (vh !== undefined && vh !== null && vh !== '') {
          setVolatilityHoursSetting(parseInt(vh, 10) || 24);
        }
      } catch (e) {}
    };
    fetchSettings();
  }, []);

  // Load the set of coins that actually have a USD and/or USDT trading pair on Binance.US,
  // so Buy/Sell/Auto-Buy/Auto-Sell quote-currency options can be hidden when a pair doesn't exist.
  useEffect(() => {
    const fetchTradingPairs = async () => {
      try {
        const res = await axios.get('/api/trading-pairs', { withCredentials: true });
        const pairs = Array.isArray(res.data?.pairs) ? res.data.pairs : [];
        const usdBases = new Set();
        const usdtBases = new Set();
        pairs.forEach(p => {
          const base = (p.base_currency || '').toUpperCase();
          const quote = (p.quote_currency || '').toUpperCase();
          if (!base) return;
          if (quote === 'USD') usdBases.add(base);
          else if (quote === 'USDT') usdtBases.add(base);
        });
        setUsdPairBases(usdBases);
        setUsdtPairBases(usdtBases);
      } catch (e) {
      } finally {
        setTradingPairsLoaded(true);
      }
    };
    fetchTradingPairs();
  }, []);

  // Whether a coin actually has a live USD/USDT pair on Binance.US; fails "open" (true)
  // until the pairs list has loaded so options aren't hidden prematurely.
  const hasUsdPair = (symbol) => !tradingPairsLoaded || usdPairBases.has((symbol || '').toUpperCase());
  const hasUsdtPair = (symbol) => !tradingPairsLoaded || usdtPairBases.has((symbol || '').toUpperCase());

  const closeActionMenu = () => setOpenActionMenu({ type: null, key: null, payload: null });
  const closeTradeQuoteMenu = () => setOpenTradeQuoteMenu({ type: null, key: null, side: null, position: null });

  // Close trade quote menu on outside click or scroll
  useEffect(() => {
    if (!openTradeQuoteMenu.key) return;

    const handleOutsideClick = (e) => {
      if (e.target.closest('.trade-quote-menu') || e.target.closest('.trade-action-btn')) {
        return;
      }
      closeTradeQuoteMenu();
    };

    const handleScroll = (e) => {
      if (e.target.closest && e.target.closest('.trade-quote-menu')) return;
      closeTradeQuoteMenu();
    };

    document.addEventListener('mousedown', handleOutsideClick);
    window.addEventListener('scroll', handleScroll, true);

    return () => {
      document.removeEventListener('mousedown', handleOutsideClick);
      window.removeEventListener('scroll', handleScroll, true);
    };
  }, [openTradeQuoteMenu.key]);

  const handleOpenPerformanceCoinModal = () => {
    setPerformanceCoinDraft([...performanceHiddenCoins]);
    setPerformanceCoinSearch('');
    setShowPerformanceCoinModal(true);
  };

  const handleSavePerformanceCoinModal = () => {
    setPerformanceHiddenCoins(performanceCoinDraft);
    try {
      localStorage.setItem('crypto_performance_hidden_coins_persistent', JSON.stringify(performanceCoinDraft));
    } catch (e) {
      console.error('Error saving performance hidden coins:', e);
    }
    setShowPerformanceCoinModal(false);
  };

  const handleOpenRecentTradesModal = () => {
    setRecentTradesDraftMaxOrders(recentTradesConfig.maxOrders !== undefined ? recentTradesConfig.maxOrders : 5);
    setRecentTradesDraftStatuses(recentTradesConfig.statusFilters || ['FILLED', 'NEW', 'CANCELED', 'PARTIALLY_FILLED']);
    setShowRecentTradesModal(true);
  };

  const handleSaveRecentTradesModal = () => {
    const clampedMax = Math.max(0, Math.min(20, parseInt(recentTradesDraftMaxOrders, 10) || 0));
    const newConfig = {
      maxOrders: clampedMax,
      statusFilters: recentTradesDraftStatuses.length > 0 ? recentTradesDraftStatuses : ['FILLED']
    };
    setRecentTradesConfig(newConfig);
    try {
      localStorage.setItem('crypto_recent_trades_config_persistent', JSON.stringify(newConfig));
    } catch (e) {
      console.error('Error saving recent trades config:', e);
    }
    setShowRecentTradesModal(false);
  };

  const handleOpenTopMoversModal = () => {
    setTopMoversDraftCount(topMoversConfig.count || 10);
    setShowTopMoversModal(true);
  };

  const handleSaveTopMoversModal = () => {
    const clamped = Math.max(3, Math.min(25, parseInt(topMoversDraftCount, 10) || 10));
    const newConfig = { count: clamped };
    setTopMoversConfig(newConfig);
    try {
      localStorage.setItem('crypto_top_movers_config_persistent', JSON.stringify(newConfig));
    } catch (e) {
      console.error('Error saving top movers config:', e);
    }
    setShowTopMoversModal(false);
  };

  const toggleTradeQuoteMenu = (type, key, side, event) => {
    const buttonRect = event?.currentTarget && !isMobile
      ? event.currentTarget.getBoundingClientRect()
      : null;
    setOpenTradeQuoteMenu(prev =>
      prev.type === type && prev.key === key && prev.side === side
        ? { type: null, key: null, side: null, position: null }
        : {
          type,
          key,
          side,
          position: buttonRect
            ? {
              top: Math.max(8, Math.min(buttonRect.bottom + 6, window.innerHeight - 130)),
              left: Math.max(8, Math.min(buttonRect.left, window.innerWidth - 196))
            }
            : null
        }
    );
  };

  const handleTriggerAutoSellClick = (symbol, coinObj = null, quoteCurrency = 'USDT', tableType = 'portfolio') => {
    let coin = coinObj;
    if (!coin) {
      if (tableType === 'watchlist') {
        coin = (watchlist || []).find(c => c.symbol === symbol);
      } else {
        coin = (portfolio || []).find(c => c.symbol === symbol);
      }
    }
    let volPct = 0;
    if (coin && coin.volatility_pct !== null && coin.volatility_pct !== undefined) {
      volPct = parseFloat(coin.volatility_pct);
    }
    setAutoSellModal({
      isOpen: true,
      symbol: symbol || (coin ? coin.symbol : ''),
      coin: coin,
      tableType: tableType,
      quoteCurrency: quoteCurrency,
      volatilityPct: volPct > 0 ? volPct : (coin?.auto_sell_volatility_pct || 5),
      volatilityHours: volatilityHoursSetting,
      loading: false,
      error: ''
    });
  };

  const handleConfirmAutoSell = async (enable = true) => {
    if (!autoSellModal.symbol) return;
    setAutoSellModal(prev => ({ ...prev, loading: true, error: '' }));
    try {
      const payload = {
        symbol: autoSellModal.symbol,
        id: autoSellModal.coin?.id,
        table_type: autoSellModal.tableType,
        quote_currency: autoSellModal.quoteCurrency,
        volatility_pct: autoSellModal.volatilityPct,
        enabled: enable
      };
      const res = await axios.post('/api/portfolio/trigger-auto-sell', payload, { withCredentials: true });
      if (res.data.success) {
        if (autoSellModal.tableType === 'watchlist') {
          setWatchlist(prev =>
            prev.map(c =>
              c.symbol === autoSellModal.symbol || (autoSellModal.coin && c.id === autoSellModal.coin.id)
                ? {
                  ...c,
                  auto_sell_enabled: enable,
                  auto_sell_volatility_pct: autoSellModal.volatilityPct,
                  auto_sell_quote_currency: autoSellModal.quoteCurrency,
                  volatility_pct: autoSellModal.volatilityPct
                }
                : c
            )
          );
        } else {
          setPortfolio(prev =>
            prev.map(c =>
              c.symbol === autoSellModal.symbol || (autoSellModal.coin && c.id === autoSellModal.coin.id)
                ? {
                  ...c,
                  auto_sell_enabled: enable,
                  auto_sell_volatility_pct: autoSellModal.volatilityPct,
                  auto_sell_quote_currency: autoSellModal.quoteCurrency,
                  volatility_pct: autoSellModal.volatilityPct
                }
                : c
            )
          );
        }
        setNotification({
          show: true,
          message: res.data.message || (enable ? `Auto-sell activated for ${autoSellModal.symbol}!` : `Auto-sell disabled for ${autoSellModal.symbol}`),
          type: 'success'
        });
        setTimeout(() => setNotification({ show: false, message: '', type: 'info' }), 5000);
        setAutoSellModal(prev => ({ ...prev, isOpen: false, loading: false, error: '' }));
      } else {
        setAutoSellModal(prev => ({ ...prev, loading: false, error: res.data.error || 'Failed to update auto-sell' }));
      }
    } catch (err) {
      console.error('Trigger auto-sell error:', err);
      setAutoSellModal(prev => ({
        ...prev,
        loading: false,
        error: err.response?.data?.error || 'Failed to update auto-sell. Please check your volatility settings.'
      }));
    }
  };

  const handleTriggerAutoBuyClick = async (symbol, coinObj = null, quoteCurrency = 'USDT', tableType = 'portfolio') => {
    let coin = coinObj;
    if (!coin) {
      if (tableType === 'watchlist') {
        coin = (watchlist || []).find(c => c.symbol === symbol);
      } else {
        coin = (portfolio || []).find(c => c.symbol === symbol);
      }
    }
    let volPct = 0;
    if (coin && coin.volatility_pct !== null && coin.volatility_pct !== undefined) {
      volPct = parseFloat(coin.volatility_pct);
    }

    const currentAlloc = coin?.auto_buy_amount ? String(coin.auto_buy_amount) : '';

    setAutoBuyModal({
      isOpen: true,
      symbol: symbol || (coin ? coin.symbol : ''),
      coin: coin,
      tableType: tableType,
      quoteCurrency: quoteCurrency,
      amount: currentAlloc,
      volatilityPct: volPct > 0 ? volPct : (coin?.auto_buy_volatility_pct || 5),
      volatilityHours: volatilityHoursSetting,
      freeBalance: 0,
      reservedBalance: 0,
      availableBalance: 0,
      activeCommitments: [],
      loadingBalance: true,
      loading: false,
      error: ''
    });

    try {
      const res = await axios.get('/api/portfolio/auto-buy-balance-info', {
        params: {
          quote_currency: quoteCurrency,
          symbol: symbol,
          id: coin?.id,
          table_type: tableType
        },
        withCredentials: true
      });
      if (res.data?.success) {
        setAutoBuyModal(prev => ({
          ...prev,
          freeBalance: res.data.free_balance || 0,
          reservedBalance: res.data.reserved_balance || 0,
          availableBalance: res.data.available_balance || 0,
          activeCommitments: res.data.active_commitments || [],
          loadingBalance: false
        }));
      } else {
        setAutoBuyModal(prev => ({ ...prev, loadingBalance: false, error: res.data?.error || '' }));
      }
    } catch (e) {
      setAutoBuyModal(prev => ({ ...prev, loadingBalance: false, error: 'Could not fetch live balance info' }));
    }
  };

  const handleConfirmAutoBuy = async (enable = true) => {
    if (!autoBuyModal.symbol) return;
    if (enable) {
      const numAmt = parseFloat(autoBuyModal.amount);
      if (isNaN(numAmt) || numAmt < 1.00) {
        setAutoBuyModal(prev => ({ ...prev, error: `Minimum allocation amount is $1.00 ${prev.quoteCurrency}.` }));
        return;
      }
      if (numAmt > autoBuyModal.availableBalance + 0.0001) {
        setAutoBuyModal(prev => ({
          ...prev,
          error: `Cannot allocate $${numAmt.toFixed(2)}. Available uncommitted balance is only $${prev.availableBalance.toFixed(2)} ${prev.quoteCurrency}.`
        }));
        return;
      }
    }

    setAutoBuyModal(prev => ({ ...prev, loading: true, error: '' }));
    try {
      const payload = {
        symbol: autoBuyModal.symbol,
        id: autoBuyModal.coin?.id,
        table_type: autoBuyModal.tableType,
        quote_currency: autoBuyModal.quoteCurrency,
        amount: parseFloat(autoBuyModal.amount) || 0,
        volatility_pct: autoBuyModal.volatilityPct,
        enabled: enable
      };
      const res = await axios.post('/api/portfolio/trigger-auto-buy', payload, { withCredentials: true });
      if (res.data.success) {
        if (autoBuyModal.tableType === 'watchlist') {
          setWatchlist(prev =>
            prev.map(c =>
              c.symbol === autoBuyModal.symbol || (autoBuyModal.coin && c.id === autoBuyModal.coin.id)
                ? {
                  ...c,
                  auto_buy_enabled: enable,
                  auto_buy_amount: parseFloat(autoBuyModal.amount) || 0,
                  auto_buy_quote_currency: autoBuyModal.quoteCurrency,
                  auto_buy_volatility_pct: autoBuyModal.volatilityPct,
                  volatility_pct: autoBuyModal.volatilityPct
                }
                : c
            )
          );
        } else {
          setPortfolio(prev =>
            prev.map(c =>
              c.symbol === autoBuyModal.symbol || (autoBuyModal.coin && c.id === autoBuyModal.coin.id)
                ? {
                  ...c,
                  auto_buy_enabled: enable,
                  auto_buy_amount: parseFloat(autoBuyModal.amount) || 0,
                  auto_buy_quote_currency: autoBuyModal.quoteCurrency,
                  auto_buy_volatility_pct: autoBuyModal.volatilityPct,
                  volatility_pct: autoBuyModal.volatilityPct
                }
                : c
            )
          );
        }
        setNotification({
          show: true,
          message: res.data.message || (enable ? `Auto-buy activated for ${autoBuyModal.symbol}!` : `Auto-buy disabled for ${autoBuyModal.symbol}`),
          type: 'success'
        });
        setTimeout(() => setNotification({ show: false, message: '', type: 'info' }), 5000);
        setAutoBuyModal(prev => ({ ...prev, isOpen: false, loading: false, error: '' }));
      } else {
        setAutoBuyModal(prev => ({ ...prev, loading: false, error: res.data.error || 'Failed to update auto-buy' }));
      }
    } catch (err) {
      console.error('Trigger auto-buy error:', err);
      setAutoBuyModal(prev => ({
        ...prev,
        loading: false,
        error: err.response?.data?.error || 'Failed to update auto-buy. Please check your volatility settings.'
      }));
    }
  };

  const renderDesktopTradeQuoteMenu = () => {
    if (isMobile || !openTradeQuoteMenu.position || typeof document === 'undefined') return null;

    const { key: symbol, side, type } = openTradeQuoteMenu;
    const isBuy = side === 'BUY';
    const isUsdt = symbol === 'USDT';
    const coin = type === 'watchlist'
      ? (watchlist || []).find(w => w.symbol === symbol)
      : (portfolio || []).find(c => c.symbol === symbol);
    const showUsd = hasUsdPair(symbol);
    const showUsdt = hasUsdtPair(symbol);

    return createPortal(
      <div className="trade-quote-menu" style={tradeQuoteMenuStyle} role="menu" aria-label={`${isBuy ? 'Buy' : 'Sell'} ${symbol}`}>
        {isBuy ? (
          <>
            {showUsd && (
              <>
                <button role="menuitem" onClick={() => { navigateToTrading(symbol, 'BUY', 'USD'); closeTradeQuoteMenu(); }}>
                  Buy with USD
                </button>
                <button role="menuitem" onClick={() => { handleTriggerAutoBuyClick(symbol, coin, 'USD', type); closeTradeQuoteMenu(); }}>
                  Trigger Auto-Buy (USD)
                </button>
              </>
            )}
            {showUsdt && (
              <>
                <button
                  role="menuitem"
                  onClick={() => {
                    if (!isUsdt) {
                      navigateToTrading(symbol, 'BUY', 'USDT'); closeTradeQuoteMenu();
                    }
                  }}
                  disabled={isUsdt}
                  title={isUsdt ? 'Cannot purchase USDT with USDT' : undefined}
                >
                  Buy with USDT
                </button>
                <button
                  role="menuitem"
                  onClick={() => {
                    if (!isUsdt) {
                      handleTriggerAutoBuyClick(symbol, coin, 'USDT', type); closeTradeQuoteMenu();
                    }
                  }}
                  disabled={isUsdt}
                  title={isUsdt ? 'Cannot auto-buy USDT with USDT' : undefined}
                >
                  Trigger Auto-Buy (USDT)
                </button>
              </>
            )}
          </>
        ) : (
          <>
            {showUsd && (
              <>
                <button role="menuitem" onClick={() => { navigateToTrading(symbol, 'SELL', 'USD'); closeTradeQuoteMenu(); }}>
                  Sell for USD
                </button>
                <button role="menuitem" onClick={() => { handleTriggerAutoSellClick(symbol, coin, 'USD', type); closeTradeQuoteMenu(); }}>
                  Trigger Auto-Sell (USD)
                </button>
              </>
            )}
            {showUsdt && (
              <>
                <button
                  role="menuitem"
                  onClick={() => {
                    if (!isUsdt) {
                      navigateToTrading(symbol, 'SELL', 'USDT'); closeTradeQuoteMenu();
                    }
                  }}
                  disabled={isUsdt}
                  title={isUsdt ? 'Cannot sell USDT for USDT' : undefined}
                >
                  Sell for USDT
                </button>
                <button
                  role="menuitem"
                  onClick={() => {
                    if (!isUsdt) {
                      handleTriggerAutoSellClick(symbol, coin, 'USDT', type); closeTradeQuoteMenu();
                    }
                  }}
                  disabled={isUsdt}
                  title={isUsdt ? 'Cannot auto-sell USDT for USDT' : undefined}
                >
                  Trigger Auto-Sell (USDT)
                </button>
              </>
            )}
          </>
        )}
      </div>,
      document.body
    );
  };

  const toggleActionMenu = (type, key, event, payload = null) => {
    if (!isMobile) return;
    setOpenActionMenu(prev =>
      prev.type === type && prev.key === key
        ? { type: null, key: null, payload: null }
        : { type, key, payload }
    );
  };


  const hoverTimeoutRef = useRef(null);

  // Hover popup functions
  const handleSymbolHover = (symbol, event) => {
    if (hoverTimeoutRef.current) clearTimeout(hoverTimeoutRef.current);
    const rect = event.currentTarget.getBoundingClientRect();
    
    // Prevent cutting off on edges
    let xPos = rect.left + rect.width / 2 - 150;
    if (xPos < 10) xPos = 10;
    if (xPos + 350 > window.innerWidth) xPos = window.innerWidth - 350;
    
    setHoverPopup({
      isVisible: true,
      symbol: symbol,
      position: {
        x: xPos,
        y: Math.max(10, rect.top - 260) // Position above symbol securely
      }
    });
  };

  const handleSymbolLeave = () => {
    hoverTimeoutRef.current = setTimeout(() => {
      setHoverPopup({
        isVisible: false,
        symbol: null,
        position: { x: 0, y: 0 }
      });
    }, 200);
  };

  const handlePopupMouseEnter = () => {
    if (hoverTimeoutRef.current) clearTimeout(hoverTimeoutRef.current);
  };

  const handleChartClick = (symbol) => {
    // Open the exchange in a new tab
    window.open(getTradeUrl(symbol), '_blank');
  };

  // Get pending orders for a specific coin
  const getPendingOrdersForCoin = (symbol) => {
    if (!pendingOrders || !Array.isArray(pendingOrders)) return [];
    const sym = (symbol || '').toUpperCase();
    return pendingOrders.filter(order => (order.asset || '').toUpperCase() === sym || (order.symbol || '').startsWith(sym));
  };

  const getAllPendingItemsForCoin = (coin) => {
    if (!coin || !coin.symbol) return [];
    const sym = (coin.symbol || '').toUpperCase();
    const exchangeOrders = getPendingOrdersForCoin(sym);
    const items = [...exchangeOrders];
    const curPrice = Number(coin.current_price || coin.current || 0);

    if (coin.auto_buy_enabled) {
      const vol = coin.auto_buy_volatility_pct || coin.volatility_pct || '—';
      const volNum = Number(vol);
      const amt = coin.auto_buy_amount !== undefined && coin.auto_buy_amount !== null ? Number(coin.auto_buy_amount).toFixed(2) : '—';
      const quote = coin.auto_buy_quote_currency || 'USDT';
      const triggerPrice = curPrice > 0 && !isNaN(volNum) && volNum > 0 ? (curPrice * (1 + volNum / 100)) : null;
      const formattedPrice = triggerPrice ? `$${triggerPrice >= 1 ? triggerPrice.toFixed(2) : triggerPrice.toFixed(4)}` : null;

      items.push({
        id: `autobuy-${coin.id || sym}`,
        isAutoBuy: true,
        trigger_type: 'auto_buy',
        side: 'AUTO-BUY',
        type: 'AUTO_BUY',
        symbol: sym,
        volatility_pct: vol,
        amount: amt,
        price: triggerPrice,
        trigger_price: triggerPrice,
        current_price: curPrice,
        quote_currency: quote,
        table_type: coin.table_type || (coin.isWatchlist ? 'watchlist' : 'portfolio'),
        title: `Auto-Buy Surge Trigger (${quote})`,
        details: formattedPrice ? `+${vol}% surge @ ${formattedPrice} ($${amt} ${quote})` : `+${vol}% surge trigger ($${amt} ${quote})`
      });
    }

    if (coin.auto_sell_enabled) {
      const vol = coin.auto_sell_volatility_pct || coin.volatility_pct || '—';
      const volNum = Number(vol);
      const quote = coin.auto_sell_quote_currency || 'USDT';
      const triggerPrice = curPrice > 0 && !isNaN(volNum) && volNum > 0 ? (curPrice * (1 - volNum / 100)) : null;
      const formattedPrice = triggerPrice ? `$${triggerPrice >= 1 ? triggerPrice.toFixed(2) : triggerPrice.toFixed(4)}` : null;

      items.push({
        id: `autosell-${coin.id || sym}`,
        isAutoSell: true,
        trigger_type: 'auto_sell',
        side: 'AUTO-SELL',
        type: 'AUTO_SELL',
        symbol: sym,
        volatility_pct: vol,
        price: triggerPrice,
        trigger_price: triggerPrice,
        current_price: curPrice,
        quote_currency: quote,
        table_type: coin.table_type || (coin.isWatchlist ? 'watchlist' : 'portfolio'),
        title: `Auto-Sell Drop Trigger (${quote})`,
        details: formattedPrice ? `-${vol}% drop @ ${formattedPrice} for ${quote}` : `-${vol}% drop trigger`
      });
    }

    return items;
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

  // Generate tooltip text for pending orders & auto triggers
  const generateOrderTooltipText = (coin, orders) => {
    const lines = [];

    if (orders && orders.length > 0) {
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
        const assetSymbol = (order.asset || coin?.symbol || '').toUpperCase();
        const priceReference = Number(order.trigger_price || order.price || 0);
        const quoteValue = order.quantity_usdt !== undefined && order.quantity_usdt !== null
          ? Number(order.quantity_usdt)
          : orderQuantity * priceReference;
        const usdText = formatOrderUsd(quoteValue);
        const sizeDescription = quantityText
          ? `${quantityText} ${assetSymbol}${usdText ? ` (~${usdText} USDT)` : ''}`
          : assetSymbol || 'this asset';

        return `Pending ${orderTypeName} ${side} for ${sizeDescription} when price ${order.direction || ''} ${trigger} USDT`;
      };
      lines.push(...orders.map(describeOrder));
    }

    if (coin.auto_buy_enabled) {
      const vol = coin.auto_buy_volatility_pct || coin.volatility_pct || '—';
      const amt = coin.auto_buy_amount !== undefined && coin.auto_buy_amount !== null ? Number(coin.auto_buy_amount).toFixed(2) : '—';
      const quote = coin.auto_buy_quote_currency || 'USDT';
      lines.push(`⚡ Active Auto-Buy: Automatically purchases with $${amt} ${quote} on +${vol}% surge in ${volatilityHours}h`);
    }

    if (coin.auto_sell_enabled) {
      const vol = coin.auto_sell_volatility_pct || coin.volatility_pct || '—';
      const quote = coin.auto_sell_quote_currency || 'USDT';
      lines.push(`⚡ Active Auto-Sell: Automatically sells for ${quote} on -${vol}% drop in ${volatilityHours}h`);
    }

    return lines.join('\n');
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
    const hasTriggers = coin.auto_buy_enabled || coin.auto_sell_enabled;

    if (orders.length > 0 || hasTriggers) {
      const rect = event.currentTarget.getBoundingClientRect();
      setOrderTooltip({
        visible: true,
        text: generateOrderTooltipText(coin, orders),
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
                setWatchlist(prev => mergeWatchlistPreservingPending(watchlistResponse.value.data || [], prev));
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
            setWatchlist(prev => mergeWatchlistPreservingPending(watchlistResponse.value.data || [], prev));
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
    if (!key || !Array.isArray(data)) return data || [];

    const isNumericColumn = [
      'amount',
      'current_price',
      'current_value',
      'avg_entry',
      'pct_change',
      'change_24h',
      'volatility_pct',
      'high_low_24h',
      'volume_24h',
      'market_cap',
      'pnl_usd',
      'allocation_pct',
      'target_price',
      'down_alert',
      'up_alert'
    ].includes(key);

    const getSortValue = (item) => {
      if (!item) return null;
      if (key === 'pnl_usd') {
        if (item.current_value !== undefined && item.cost_basis !== undefined && item.cost_basis > 0) {
          return item.current_value - item.cost_basis;
        }
        if (item.current_price && item.avg_entry && item.amount) {
          return item.amount * (item.current_price - item.avg_entry);
        }
        return null;
      }
      if (key === 'allocation_pct') {
        return item.current_value !== undefined && item.current_value !== null ? Number(item.current_value) : null;
      }
      if (key === 'avg_entry') {
        const isStable = ['USD', 'USDT', 'USDC', 'BUSD', 'DAI'].includes((item.symbol || '').toUpperCase());
        if (isStable) return 1.0;
        return item.avg_entry !== undefined && item.avg_entry !== null ? Number(item.avg_entry) : null;
      }
      if (key === 'current_price') {
        const isStable = ['USD', 'USDT', 'USDC', 'BUSD', 'DAI'].includes((item.symbol || '').toUpperCase());
        if (isStable) return 1.0;
        return item.current_price !== undefined && item.current_price !== null ? Number(item.current_price) : null;
      }
      if (key === 'pct_change') {
        return item.pct_change !== undefined && item.pct_change !== null ? Number(item.pct_change) : null;
      }
      if (key === 'change_24h') {
        return item.change_24h !== undefined && item.change_24h !== null ? Number(item.change_24h) : null;
      }
      if (key === 'current_value') {
        return item.current_value !== undefined && item.current_value !== null ? Number(item.current_value) : null;
      }
      if (key === 'sentiment') {
        return typeof item.sentiment === 'object' ? (item.sentiment?.score ?? item.sentiment?.label ?? '') : (item.sentiment || '');
      }
      return item[key];
    };

    return [...data].sort((a, b) => {
      const aVal = getSortValue(a);
      const bVal = getSortValue(b);

      if (isNumericColumn) {
        const isANull = aVal === null || aVal === undefined || aVal === '' || isNaN(Number(aVal));
        const isBNull = bVal === null || bVal === undefined || bVal === '' || isNaN(Number(bVal));

        if (isANull && isBNull) return 0;
        if (isANull) return 1; // nulls always at the bottom
        if (isBNull) return -1;

        const numA = Number(aVal);
        const numB = Number(bVal);
        return sortConfig.direction === 'asc' ? numA - numB : numB - numA;
      }

      const strA = (aVal ?? '').toString().toLowerCase();
      const strB = (bVal ?? '').toString().toLowerCase();
      return sortConfig.direction === 'asc' ? strA.localeCompare(strB) : strB.localeCompare(strA);
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

  // Drag and drop column reordering
  const handleColDragStart = (tableType, colKey, e) => {
    if (colKey === 'symbol' || colKey === 'actions') {
      e.preventDefault();
      return;
    }
    setDraggedColKey({ tableType, colKey });
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', colKey);
  };

  const handleColDragOver = (tableType, targetColKey, e) => {
    if (!draggedColKey || draggedColKey.tableType !== tableType) return;
    if (targetColKey === 'symbol' || targetColKey === 'actions') return;
    if (draggedColKey.colKey === targetColKey) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setDragOverColKey(targetColKey);
  };

  const handleColDrop = (tableType, targetColKey, e) => {
    e.preventDefault();
    setDragOverColKey(null);
    if (!draggedColKey || draggedColKey.tableType !== tableType) return;
    const sourceColKey = draggedColKey.colKey;
    setDraggedColKey(null);

    if (sourceColKey === targetColKey) return;
    if (targetColKey === 'symbol' || targetColKey === 'actions') return;
    if (sourceColKey === 'symbol' || sourceColKey === 'actions') return;

    if (tableType === 'portfolio') {
      setPortfolioColOrder(prev => {
        const list = [...prev];
        const sourceIdx = list.indexOf(sourceColKey);
        const targetIdx = list.indexOf(targetColKey);
        if (sourceIdx < 0 || targetIdx < 0) return prev;
        list.splice(sourceIdx, 1);
        list.splice(targetIdx, 0, sourceColKey);
        const result = ['symbol', ...list.filter(c => c !== 'symbol' && c !== 'actions'), 'actions'];
        try {
          localStorage.setItem('crypto_portfolio_column_order', JSON.stringify(result));
        } catch (err) {}
        return result;
      });
    } else {
      setWatchlistColOrder(prev => {
        const list = [...prev];
        const sourceIdx = list.indexOf(sourceColKey);
        const targetIdx = list.indexOf(targetColKey);
        if (sourceIdx < 0 || targetIdx < 0) return prev;
        list.splice(sourceIdx, 1);
        list.splice(targetIdx, 0, sourceColKey);
        const result = ['symbol', ...list.filter(c => c !== 'symbol' && c !== 'actions'), 'actions'];
        try {
          localStorage.setItem('crypto_watchlist_column_order', JSON.stringify(result));
        } catch (err) {}
        return result;
      });
    }
  };

  const handleColDragEnd = () => {
    setDraggedColKey(null);
    setDragOverColKey(null);
  };

  // Column resizing
  const handleResizeStart = (tableType, colKey, e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsResizing(true);
    document.body.classList.add('is-resizing-columns');

    const startX = e.clientX;
    const currentWidths = tableType === 'portfolio' ? portfolioColWidths : watchlistColWidths;
    const colDefs = tableType === 'portfolio' ? PORTFOLIO_COLUMN_DEFINITIONS : WATCHLIST_COLUMN_DEFINITIONS;
    const minW = colKey === 'actions' ? (tableType === 'portfolio' ? 380 : 280) : 60;
    const startWidth = currentWidths[colKey] || colDefs[colKey]?.defaultWidth || 120;

    let latestWidth = startWidth;

    const handleMouseMove = (moveEvent) => {
      moveEvent.preventDefault();
      const delta = moveEvent.clientX - startX;
      latestWidth = Math.max(minW, Math.round(startWidth + delta));
      if (tableType === 'portfolio') {
        setPortfolioColWidths(prev => ({ ...prev, [colKey]: latestWidth }));
      } else {
        setWatchlistColWidths(prev => ({ ...prev, [colKey]: latestWidth }));
      }
    };

    const handleMouseUp = () => {
      setIsResizing(false);
      document.body.classList.remove('is-resizing-columns');
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);

      if (tableType === 'portfolio') {
        setPortfolioColWidths(prev => {
          const next = { ...prev, [colKey]: latestWidth };
          try {
            localStorage.setItem('crypto_portfolio_column_widths', JSON.stringify(next));
          } catch (err) {}
          return next;
        });
      } else {
        setWatchlistColWidths(prev => {
          const next = { ...prev, [colKey]: latestWidth };
          try {
            localStorage.setItem('crypto_watchlist_column_widths', JSON.stringify(next));
          } catch (err) {}
          return next;
        });
      }
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  };

  // Column modal handlers
  const handleSavePortfolioColumns = (newCols) => {
    setPortfolioVisibleCols(newCols);
    setPortfolioColOrder(prev => {
      const order = [...prev];
      newCols.forEach(c => {
        if (!order.includes(c)) {
          const actionsIdx = order.indexOf('actions');
          if (actionsIdx >= 0) order.splice(actionsIdx, 0, c);
          else order.push(c);
        }
      });
      try {
        localStorage.setItem('crypto_portfolio_column_order', JSON.stringify(order));
      } catch (err) {}
      return order;
    });
    try {
      localStorage.setItem('crypto_portfolio_visible_columns', JSON.stringify(newCols));
    } catch (err) {}
  };

  const handleResetPortfolioColumns = () => {
    setPortfolioVisibleCols([...PORTFOLIO_DEFAULT_COLUMNS]);
    setPortfolioColOrder([...PORTFOLIO_DEFAULT_COLUMNS]);
    setPortfolioColWidths({});
    try {
      localStorage.removeItem('crypto_portfolio_visible_columns');
      localStorage.removeItem('crypto_portfolio_column_order');
      localStorage.removeItem('crypto_portfolio_column_widths');
    } catch (err) {}
  };

  const handleSaveWatchlistColumns = (newCols) => {
    setWatchlistVisibleCols(newCols);
    setWatchlistColOrder(prev => {
      const order = [...prev];
      newCols.forEach(c => {
        if (!order.includes(c)) {
          const actionsIdx = order.indexOf('actions');
          if (actionsIdx >= 0) order.splice(actionsIdx, 0, c);
          else order.push(c);
        }
      });
      try {
        localStorage.setItem('crypto_watchlist_column_order', JSON.stringify(order));
      } catch (err) {}
      return order;
    });
    try {
      localStorage.setItem('crypto_watchlist_visible_columns', JSON.stringify(newCols));
    } catch (err) {}
  };

  const handleResetWatchlistColumns = () => {
    setWatchlistVisibleCols([...WATCHLIST_DEFAULT_COLUMNS]);
    setWatchlistColOrder([...WATCHLIST_DEFAULT_COLUMNS]);
    setWatchlistColWidths({});
    try {
      localStorage.removeItem('crypto_watchlist_visible_columns');
      localStorage.removeItem('crypto_watchlist_column_order');
      localStorage.removeItem('crypto_watchlist_column_widths');
    } catch (err) {}
  };

  // Cancel order handlers
  const handleCancelButtonClick = (coin, coinOrders, event) => {
    event.stopPropagation();
    if (!coinOrders || coinOrders.length === 0) return;

    if (coinOrders.length === 1) {
      setCancelModalState({
        isOpen: true,
        coin,
        order: coinOrders[0],
        loading: false,
        error: null
      });
    } else {
      const rect = event.currentTarget.getBoundingClientRect();
      const menuWidth = 360;
      const padding = 16;
      let posX = rect.right - menuWidth;
      if (posX + menuWidth > window.innerWidth - padding) {
        posX = window.innerWidth - menuWidth - padding;
      }
      if (posX < padding) {
        posX = padding;
      }
      const posY = rect.bottom + window.scrollY + 6;
      setCancelContextMenu({
        isOpen: true,
        coin,
        x: Math.round(posX),
        y: Math.round(posY),
        orders: coinOrders
      });
    }
  };

  const handleSelectOrderFromMenu = (order, coin) => {
    setCancelContextMenu({ isOpen: false, coin: null, x: 0, y: 0, orders: [] });
    setCancelModalState({
      isOpen: true,
      coin,
      order,
      loading: false,
      error: null
    });
  };

  const handleConfirmCancelOrder = async (order, twoFactorCode) => {
    setCancelModalState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const isAutoBuy = !!order.isAutoBuy || order.trigger_type === 'auto_buy';
      const isAutoSell = !!order.isAutoSell || order.trigger_type === 'auto_sell';
      const symbol = (order.symbol || cancelModalState.coin?.symbol || '').toUpperCase();

      if (isAutoBuy) {
        const payload = {
          symbol,
          table_type: order.table_type || (cancelModalState.coin?.isWatchlist ? 'watchlist' : 'portfolio'),
          enabled: false
        };
        if (twoFactorCode) payload.two_factor_code = twoFactorCode;

        const response = await axios.post('/api/portfolio/trigger-auto-buy', payload, { withCredentials: true });
        if (response.data.success) {
          setPortfolio(prev => prev.map(c => ((c.symbol || '').toUpperCase() === symbol ? { ...c, auto_buy_enabled: false } : c)));
          setWatchlist(prev => prev.map(w => ((w.symbol || '').toUpperCase() === symbol ? { ...w, auto_buy_enabled: false } : w)));
          setCancelModalState({ isOpen: false, coin: null, order: null, loading: false, error: null });

          // Background refresh
          axios.get('/api/coin-data-live').then(r => r.data?.portfolio && setPortfolio(r.data.portfolio)).catch(() => {});
          axios.get('/api/watchlist-live', { withCredentials: true }).then(r => Array.isArray(r.data) && setWatchlist(prev => mergeWatchlistPreservingPending(r.data, prev))).catch(() => {});
          return { success: true };
        } else {
          setCancelModalState(prev => ({ ...prev, loading: false, error: response.data.error || 'Failed to cancel auto-buy trigger' }));
          return response.data;
        }
      } else if (isAutoSell) {
        const payload = {
          symbol,
          table_type: order.table_type || (cancelModalState.coin?.isWatchlist ? 'watchlist' : 'portfolio'),
          enabled: false
        };
        if (twoFactorCode) payload.two_factor_code = twoFactorCode;

        const response = await axios.post('/api/portfolio/trigger-auto-sell', payload, { withCredentials: true });
        if (response.data.success) {
          setPortfolio(prev => prev.map(c => ((c.symbol || '').toUpperCase() === symbol ? { ...c, auto_sell_enabled: false } : c)));
          setWatchlist(prev => prev.map(w => ((w.symbol || '').toUpperCase() === symbol ? { ...w, auto_sell_enabled: false } : w)));
          setCancelModalState({ isOpen: false, coin: null, order: null, loading: false, error: null });

          // Background refresh
          axios.get('/api/coin-data-live').then(r => r.data?.portfolio && setPortfolio(r.data.portfolio)).catch(() => {});
          axios.get('/api/watchlist-live', { withCredentials: true }).then(r => Array.isArray(r.data) && setWatchlist(prev => mergeWatchlistPreservingPending(r.data, prev))).catch(() => {});
          return { success: true };
        } else {
          setCancelModalState(prev => ({ ...prev, loading: false, error: response.data.error || 'Failed to cancel auto-sell trigger' }));
          return response.data;
        }
      } else {
        const orderId = order.order_id || order.orderId || order.id;
        const payload = { symbol };
        if (twoFactorCode) {
          payload.two_factor_code = twoFactorCode;
        }
        const response = await axios.post(`/api/cancel-order/${orderId}`, payload, { withCredentials: true });

        if (response.data.success || response.status === 200) {
          setPendingOrders(prev => prev.filter(o => (o.order_id || o.orderId || o.id) !== orderId));
          setPortfolio(prev => prev.map(c => {
            if ((c.symbol || '').toUpperCase() === symbol) {
              const remaining = getPendingOrdersForCoin(symbol).filter(o => (o.order_id || o.orderId || o.id) !== orderId);
              return { ...c, hasPendingOrder: remaining.length > 0 };
            }
            return c;
          }));

          setCancelModalState({ isOpen: false, coin: null, order: null, loading: false, error: null });

          // Background refresh
          axios.get('/api/coin-data-live').then(r => r.data?.portfolio && setPortfolio(r.data.portfolio)).catch(() => {});
          axios.get('/api/pending-orders', { withCredentials: true }).then(r => r.data?.pending_orders && setPendingOrders(r.data.pending_orders)).catch(() => {});

          return { success: true };
        } else {
          setCancelModalState(prev => ({ ...prev, loading: false, error: response.data.error || 'Failed to cancel order' }));
          return response.data;
        }
      }
    } catch (err) {
      console.error('Cancel order error:', err);
      const errMsg = err.response?.data?.error || err.message || 'Failed to cancel order';
      const requires2fa = err.response?.data?.requires_2fa;
      setCancelModalState(prev => ({ ...prev, loading: false, error: errMsg }));
      if (requires2fa) {
        return { requires_2fa: true };
      }
      throw err;
    }
  };

  useEffect(() => {
    const handleOutsideClick = () => {
      if (cancelContextMenu.isOpen) {
        setCancelContextMenu({ isOpen: false, coin: null, x: 0, y: 0, orders: [] });
      }
    };
    if (cancelContextMenu.isOpen) {
      document.addEventListener('click', handleOutsideClick);
      return () => document.removeEventListener('click', handleOutsideClick);
    }
  }, [cancelContextMenu.isOpen]);

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
    if (cleaned === 'USDT') {
      return 'USDTUSD';
    }
    if (cleaned.endsWith('USDT') || (cleaned.endsWith('USD') && cleaned.length > 3)) {
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
            {/* Buy button */}
            <button
              onClick={(event) => {
                const sym = isPortfolio ? coin.symbol : item.symbol;
                if (sym !== 'USD') {
                  toggleTradeQuoteMenu(openActionMenu.type, openActionMenu.key, 'BUY', event);
                }
              }}
              disabled={(isPortfolio ? coin.symbol : item.symbol) === 'USD'}
              style={(isPortfolio ? coin.symbol : item.symbol) === 'USD' ? { opacity: 0.4, cursor: 'not-allowed' } : undefined}
            >
              Buy
            </button>
            {openTradeQuoteMenu.type === openActionMenu.type && openTradeQuoteMenu.key === openActionMenu.key && openTradeQuoteMenu.side === 'BUY' && (
              <div className="trade-quote-menu" style={tradeQuoteMenuStyle}>
                {hasUsdPair(isPortfolio ? coin.symbol : item.symbol) && (
                  <>
                    <button onClick={() => { navigateToTrading(isPortfolio ? coin.symbol : item.symbol, 'BUY', 'USD'); closeActionMenu(); closeTradeQuoteMenu(); }}>Buy with USD</button>
                    <button onClick={() => { handleTriggerAutoBuyClick(isPortfolio ? coin.symbol : item.symbol, isPortfolio ? coin : item, 'USD', openActionMenu.type); closeActionMenu(); closeTradeQuoteMenu(); }}>Trigger Auto-Buy (USD)</button>
                  </>
                )}
                {hasUsdtPair(isPortfolio ? coin.symbol : item.symbol) && (
                  <>
                    <button
                      onClick={() => {
                        const sym = isPortfolio ? coin.symbol : item.symbol;
                        if (sym !== 'USDT') {
                          navigateToTrading(sym, 'BUY', 'USDT'); closeActionMenu(); closeTradeQuoteMenu();
                        }
                      }}
                      disabled={(isPortfolio ? coin.symbol : item.symbol) === 'USDT'}
                      style={(isPortfolio ? coin.symbol : item.symbol) === 'USDT' ? { opacity: 0.4, cursor: 'not-allowed' } : undefined}
                    >
                      Buy with USDT
                    </button>
                    <button
                      onClick={() => {
                        const sym = isPortfolio ? coin.symbol : item.symbol;
                        if (sym !== 'USDT') {
                          handleTriggerAutoBuyClick(sym, isPortfolio ? coin : item, 'USDT', openActionMenu.type); closeActionMenu(); closeTradeQuoteMenu();
                        }
                      }}
                      disabled={(isPortfolio ? coin.symbol : item.symbol) === 'USDT'}
                      style={(isPortfolio ? coin.symbol : item.symbol) === 'USDT' ? { opacity: 0.4, cursor: 'not-allowed' } : undefined}
                    >
                      Trigger Auto-Buy (USDT)
                    </button>
                  </>
                )}
              </div>
            )}

            {/* Sell button - only available for Portfolio, disabled for USD */}
            {isPortfolio && (
              <>
                <button
                  onClick={(event) => {
                    if (coin.symbol !== 'USD') {
                      toggleTradeQuoteMenu(openActionMenu.type, openActionMenu.key, 'SELL', event);
                    }
                  }}
                  disabled={coin.symbol === 'USD'}
                  style={coin.symbol === 'USD' ? { opacity: 0.4, cursor: 'not-allowed' } : undefined}
                >
                  Sell
                </button>
                {openTradeQuoteMenu.type === openActionMenu.type && openTradeQuoteMenu.key === openActionMenu.key && openTradeQuoteMenu.side === 'SELL' && (
                  <div className="trade-quote-menu" style={tradeQuoteMenuStyle}>
                    {hasUsdPair(coin.symbol) && (
                      <>
                        <button onClick={() => { navigateToTrading(coin.symbol, 'SELL', 'USD'); closeActionMenu(); closeTradeQuoteMenu(); }}>Sell for USD</button>
                        <button onClick={() => { handleTriggerAutoSellClick(coin.symbol, coin, 'USD', openActionMenu.type); closeActionMenu(); closeTradeQuoteMenu(); }}>Trigger Auto-Sell (USD)</button>
                      </>
                    )}
                    {hasUsdtPair(coin.symbol) && (
                      <>
                        <button
                          onClick={() => {
                            if (coin.symbol !== 'USDT') {
                              navigateToTrading(coin.symbol, 'SELL', 'USDT'); closeActionMenu(); closeTradeQuoteMenu();
                            }
                          }}
                          disabled={coin.symbol === 'USDT'}
                          style={coin.symbol === 'USDT' ? { opacity: 0.4, cursor: 'not-allowed' } : undefined}
                        >
                          Sell for USDT
                        </button>
                        <button
                          onClick={() => {
                            if (coin.symbol !== 'USDT') {
                              handleTriggerAutoSellClick(coin.symbol, coin, 'USDT', openActionMenu.type); closeActionMenu(); closeTradeQuoteMenu();
                            }
                          }}
                          disabled={coin.symbol === 'USDT'}
                          style={coin.symbol === 'USDT' ? { opacity: 0.4, cursor: 'not-allowed' } : undefined}
                        >
                          Trigger Auto-Sell (USDT)
                        </button>
                      </>
                    )}
                  </div>
                )}
              </>
            )}
            {isPortfolio && (
              <>
                <button
                  onClick={() => { handleStakeClick(coin); closeActionMenu(); }}
                  disabled={
                    !stakeableCoins.includes(coin.symbol) ||
                    isPlaceholder ||
                    (coin.current_value && coin.current_value < 1)
                  }
                >
                  Stake
                </button>
                {(() => {
                  const allPendingItems = getAllPendingItemsForCoin(coin);
                  const hasOrders = allPendingItems.length > 0;
                  return (
                    <button
                      onClick={(e) => {
                        closeActionMenu();
                        if (hasOrders) handleCancelButtonClick(coin, allPendingItems, e);
                      }}
                      disabled={!hasOrders}
                      style={!hasOrders ? { opacity: 0.4, cursor: 'not-allowed' } : { color: '#ef4444' }}
                    >
                      Cancel Active ({allPendingItems.length})
                    </button>
                  );
                })()}
              </>
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

  const navigateToTrading = (symbol, side, quote = 'USDT') => {
    const cleanSymbol = String(symbol || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
    const cleanBase = cleanSymbol === 'USDT'
      ? 'USDT'
      : cleanSymbol.endsWith('USDT')
        ? cleanSymbol.slice(0, -4)
        : cleanSymbol.endsWith('USD')
          ? cleanSymbol.slice(0, -3)
          : cleanSymbol;
    const pair = `${cleanBase}${quote === 'USD' ? 'USD' : 'USDT'}`;
    if (!pair) {
      console.warn('Unable to determine trading pair for symbol:', symbol);
      return;
    }
    navigate('/trading', {
      state: {
        tradePrefill: {
          symbol: pair,
          side: side === 'SELL' ? 'SELL' : 'BUY',
          baseCoin: cleanBase
        }
      }
    });
  };

  // Dynamic price formatter based on price magnitude:
  // >= $1.00: 2 decimals
  // $0.01 - $0.999...: 3 decimals
  // $0.001 - $0.0099...: 4 decimals
  // $0.0001 - $0.00099...: 5 decimals
  // < $0.0001: 6 decimals
  const formatDynamicPrice = (price) => {
    if (price === null || price === undefined || price === '' || isNaN(Number(price))) return '—';
    const num = Number(price);
    if (num === 0) return '$0.00';
    const absNum = Math.abs(num);
    let decimals = 2;
    if (absNum >= 1.0) {
      decimals = 2;
    } else if (absNum >= 0.01) {
      decimals = 3;
    } else if (absNum >= 0.001) {
      decimals = 4;
    } else if (absNum >= 0.0001) {
      decimals = 5;
    } else {
      decimals = 6;
    }
    return `$${num.toLocaleString('en-US', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals
    })}`;
  };

  // Date formatting helpers that guarantee UTC timestamps are properly parsed and converted to user local time
  const formatLocalDateTime = (dateStr) => {
    if (!dateStr) return '';
    let s = String(dateStr).trim();
    if (!s.endsWith('Z') && !s.includes('+') && !s.slice(10).includes('-')) {
      s += 'Z';
    }
    const d = new Date(s);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleString();
  };

  const formatLocalDate = (dateStr) => {
    if (!dateStr) return '';
    let s = String(dateStr).trim();
    if (!s.endsWith('Z') && !s.includes('+') && !s.slice(10).includes('-')) {
      s += 'Z';
    }
    const d = new Date(s);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  };

  // Helper to build a clean tooltip for the News icon (showing cached news if available)
  const getNewsTooltip = (coinOrItem) => {
    if (!coinOrItem || !coinOrItem.cached_news) {
      return "News (Click to fetch latest news)";
    }
    const cleanNews = String(coinOrItem.cached_news)
      .replace(/#{1,6}\s+/g, '') // remove markdown headings
      .replace(/\*\*/g, '')      // remove bold markers
      .replace(/\*/g, '')       // remove italic/bullet markers
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1') // remove markdown links
      .replace(/\s+/g, ' ')      // normalize whitespace
      .trim();

    const dateStr = coinOrItem.cached_news_date
      ? formatLocalDate(coinOrItem.cached_news_date)
      : '';

    const preview = cleanNews.length > 350 ? cleanNews.slice(0, 350) + '...' : cleanNews;
    return dateStr ? `[${dateStr}] ${preview}` : preview;
  };

  // News function - Show cached/today's analysis (NEWS button)
  const openNews = async (symbol) => {
    try {
      setNewsLoading(true);
      setNewsAnalysisSymbol(symbol);
      setShowNewsModal(true);

      // Backend checks daily cache; if cached from today, returns cached. Otherwise automatically fetches fresh today.
      const response = await axios.post('/api/ai/news-analysis', {
        symbol: symbol,
        force_fresh: false
      }, { withCredentials: true });

      if (response.data.error) {
        setNewsAnalysisData({
          error: true,
          message: response.data.error
        });
      } else {
        const analysis = response.data.analysis;
        const nowIso = new Date().toISOString();
        setNewsAnalysisData({
          error: false,
          symbol: response.data.symbol,
          analysis: analysis,
          timestamp: response.data.timestamp,
          prompt_used: response.data.prompt_used
        });

        // Update cached_news in portfolio and watchlist state
        setPortfolio(prev => prev.map(c => c.symbol === symbol ? {
          ...c,
          cached_news: analysis,
          cached_news_date: nowIso
        } : c));
        setWatchlist(prev => prev.map(w => w.symbol === symbol ? {
          ...w,
          cached_news: analysis,
          cached_news_date: nowIso
        } : w));
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
        const analysis = response.data.analysis;
        const nowIso = new Date().toISOString();
        setNewsAnalysisData({
          error: false,
          symbol: response.data.symbol,
          analysis: analysis,
          timestamp: response.data.timestamp,
          prompt_used: response.data.prompt_used
        });

        // Update cached_news in portfolio and watchlist state
        setPortfolio(prev => prev.map(c => c.symbol === symbol ? {
          ...c,
          cached_news: analysis,
          cached_news_date: nowIso
        } : c));
        setWatchlist(prev => prev.map(w => w.symbol === symbol ? {
          ...w,
          cached_news: analysis,
          cached_news_date: nowIso
        } : w));
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
    const cleanSym = watchlistSymbol.trim().toUpperCase();
    if (!cleanSym) return;

    // Clear input immediately so user can continue interacting
    setWatchlistSymbol('');

    // Optimistic item to render immediately (0ms latency)
    const tempId = `temp-${Date.now()}`;
    const tempItem = {
      id: tempId,
      symbol: cleanSym,
      current_price: null,
      alert_enabled: false,
      favorite: false,
      sentiment: 'Checking now...',
      sentiment_reason: '',
      sentiment_last_updated: null,
      volatility_pct: null,
      down_val: null,
      up_val: null,
      note: ''
    };

    // Track in ref so background poll intervals (/api/watchlist-live) cannot wipe it out before the server responds
    pendingAddedWatchlistSymbolsRef.current.set(cleanSym, tempItem);

    setWatchlist(prev => {
      if (prev.some(c => (c.symbol || '').toUpperCase() === cleanSym)) return prev;
      return [tempItem, ...prev];
    });

    setAddingToWatchlist(true);
    try {
      const response = await axios.post('/api/watchlist/add', {
        symbol: cleanSym
      }, { withCredentials: true });

      if (response.data && response.data.success) {
        const itemFromServer = response.data.item || {
          id: response.data.id || tempId,
          symbol: cleanSym,
          current_price: response.data.current_price || 0,
          alert_enabled: false,
          favorite: false,
          sentiment: 'Checking now...',
          sentiment_reason: '',
          sentiment_last_updated: null,
          volatility_pct: null,
          down_val: null,
          up_val: null,
          note: ''
        };
        // Update ref with server-confirmed item
        pendingAddedWatchlistSymbolsRef.current.set(cleanSym, itemFromServer);
        setWatchlist(prev => {
          const index = prev.findIndex(c => c.id === tempId || (c.symbol || '').toUpperCase() === cleanSym);
          if (index !== -1) {
            const copy = [...prev];
            copy[index] = { ...copy[index], ...itemFromServer };
            return copy;
          }
          return [itemFromServer, ...prev];
        });
      } else {
        // Revert on failure
        pendingAddedWatchlistSymbolsRef.current.delete(cleanSym);
        setWatchlist(prev => prev.filter(c => c.id !== tempId && (c.symbol || '').toUpperCase() !== cleanSym));
      }
    } catch (err) {
      console.error('Add to watchlist error:', err);
      pendingAddedWatchlistSymbolsRef.current.delete(cleanSym);
      setWatchlist(prev => prev.filter(c => c.id !== tempId && (c.symbol || '').toUpperCase() !== cleanSym));
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
      // Treat the model's default 0% as "no alert configured yet" so new coins render blank
      currentValue = item[pctKey] !== null && item[pctKey] !== undefined && Number(item[pctKey]) !== 0 ? parseFloat(item[pctKey]).toFixed(2) : '';
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

    const handleBlur = (e) => {
      const value = e.target.value.replace(/[^0-9.]/g, '');
      const formattedValue = value === '' ? '' : parseFloat(value).toFixed(2);
      e.target.value = formattedValue;
      handleValueChange(formattedValue);
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
          onBlur={handleBlur}
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

    const handleBlur = (e) => {
      const value = e.target.value.replace(/[^0-9.]/g, '');
      const formattedValue = value === '' ? '' : parseFloat(value).toFixed(2);
      e.target.value = formattedValue;
      handleValueChange(formattedValue);
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
          onBlur={handleBlur}
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

    const handleBlur = (e) => {
      const value = e.target.value.replace(/[^0-9]/g, '');
      const formattedValue = value === '' ? '' : parseInt(value, 10);
      e.target.value = formattedValue;
      handleValueChange(formattedValue);
    };

    return (
      <div style={{
        display: 'grid',
        gridTemplateColumns: '18px 1fr 18px',
        alignItems: 'center',
        width: '100%',
        minWidth: '85px'
      }}>
        <span style={{ display: 'flex', justifyContent: 'flex-start' }}>
          {item.auto_sell_enabled && (
            <span
              title={`⚡ Auto-Sell Active: Automatically sells for ${item.auto_sell_quote_currency || 'USDT'} if price drops > ${item.auto_sell_volatility_pct || item.volatility_pct}% in ${volatilityHoursSetting}h.`}
              style={{ fontSize: '13px', cursor: 'help', color: '#ef4444', filter: 'drop-shadow(0 0 4px rgba(239, 68, 68, 0.7))' }}
            >
              ⚡
            </span>
          )}
        </span>
        <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}>
          <input
            type="text"
            defaultValue={volatilityPct}
            onChange={(e) => {
              let value = e.target.value.replace(/[^0-9]/g, '');
              e.target.value = value;
            }}
            onKeyPress={handleKeyPress}
            onBlur={handleBlur}
            style={{
              width: '45px',
              padding: '2px 4px',
              fontSize: '12px',
              background: '#1a1f23',
              color: '#fff',
              border: (item.auto_sell_enabled || item.auto_buy_enabled) ? '1px solid #38bdf8' : '1px solid #333',
              borderRadius: '2px',
              textAlign: 'center',
              boxShadow: (item.auto_sell_enabled || item.auto_buy_enabled) ? '0 0 6px rgba(56, 189, 248, 0.4)' : 'none'
            }}
          />
          <span style={{ fontSize: '12px' }}>%</span>
        </span>
        <span style={{ display: 'flex', justifyContent: 'flex-end' }}>
          {item.auto_buy_enabled && (
            <span
              title={`🚀 Auto-Buy Active: Automatically purchases with $${parseFloat(item.auto_buy_amount || 0).toFixed(2)} ${item.auto_buy_quote_currency || 'USDT'} if price surges > +${item.auto_buy_volatility_pct || item.volatility_pct}% in ${volatilityHoursSetting}h.`}
              style={{ fontSize: '13px', cursor: 'help', color: '#22c55e', filter: 'drop-shadow(0 0 4px rgba(34, 197, 94, 0.7))' }}
            >
              🚀
            </span>
          )}
        </span>
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
        // Mirror backend sync: keep active auto-buy/auto-sell trigger snapshot values
        // aligned with the newly edited volatility % so displayed trigger prices update instantly.
        const applyUpdate = (coin) => ({
          ...coin,
          volatility_pct: value,
          ...(coin.auto_buy_enabled ? { auto_buy_volatility_pct: value } : {}),
          ...(coin.auto_sell_enabled ? { auto_sell_volatility_pct: value } : {})
        });
        if (tableType === 'portfolio') {
          setPortfolio(prev => prev.map(coin =>
            coin.id === item.id ? applyUpdate(coin) : coin
          ));
        } else {
          setWatchlist(prev => prev.map(coin =>
            coin.symbol === item.symbol ? applyUpdate(coin) : coin
          ));
        }
      }
    } catch (err) {
      console.error('Update volatility pct error:', err);
    }
  };

  const handleToggleSentimentTracking = async (item, isWatchlist, e) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    const tableType = isWatchlist ? 'watchlist' : 'portfolio';
    const nextEnabled = item.sentiment_tracking_enabled === false;
    try {
      const response = await axios.post('/api/toggle-sentiment-tracking', {
        id: tableType === 'portfolio' ? item.id : null,
        symbol: tableType === 'watchlist' ? item.symbol : null,
        table_type: tableType,
        enabled: nextEnabled
      }, { withCredentials: true });

      if (response.data.success) {
        const applyUpdate = (coin) => ({
          ...coin,
          sentiment_tracking_enabled: nextEnabled,
          sentiment: response.data.sentiment || coin.sentiment
        });
        if (isWatchlist) {
          setWatchlist(prev => prev.map(coin => coin.symbol === item.symbol ? applyUpdate(coin) : coin));
        } else {
          setPortfolio(prev => prev.map(coin => coin.id === item.id ? applyUpdate(coin) : coin));
        }
      }
    } catch (err) {
      console.error('Toggle sentiment tracking error:', err);
    }
  };

  const getProviderDisplayName = (provider) => {
    switch ((provider || '').toLowerCase()) {
      case 'openai': return 'OpenAI';
      case 'gemini': return 'Google Gemini';
      case 'zai': return 'Z.AI';
      case 'perplexity': return 'Perplexity';
      case 'inception': return 'Inception Labs';
      default: return provider || 'AI';
    }
  };

  const getTierDisplayName = (tier) => {
    if (!tier) return 'Primary';
    return tier.charAt(0).toUpperCase() + tier.slice(1).toLowerCase();
  };

  const handleSingleSentimentRefresh = async (symbol, isWatchlist, e) => {
    if (e) {
      e.stopPropagation();
    }
    if (!symbol) return;
    const cleanSymbol = symbol.toUpperCase().trim();
    if (['USD', 'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDP'].includes(cleanSymbol)) return;
    
    // Find initial timestamp so we know when a fresh analysis has landed
    const currentCoin = isWatchlist
      ? watchlist.find(x => (x.symbol || '').toUpperCase() === cleanSymbol)
      : portfolio.find(x => (x.symbol || '').toUpperCase() === cleanSymbol);
    const initialLastUpdated = currentCoin?.sentiment_last_updated || null;

    setRefreshingSentiment(prev => ({ ...prev, [cleanSymbol]: true }));
    
    // Optimistically update local state to "Checking now..."
    if (isWatchlist) {
      setWatchlist(prev => prev.map(item => (item.symbol || '').toUpperCase() === cleanSymbol ? { ...item, sentiment: 'Checking now...' } : item));
    } else {
      setPortfolio(prev => prev.map(coin => (coin.symbol || '').toUpperCase() === cleanSymbol ? { ...coin, sentiment: 'Checking now...' } : coin));
    }

    try {
      await axios.post('/api/force-sentiment-analysis', {
        symbol: cleanSymbol,
        target: isWatchlist ? 'watchlist' : 'portfolio'
      }, { withCredentials: true });

      // Poll until the result updates with a newer sentiment_last_updated or moves past "Checking now..."
      let attempts = 0;
      const pollInterval = setInterval(async () => {
        attempts++;
        try {
          if (isWatchlist) {
            const res = await axios.get('/api/watchlist-live', { withCredentials: true });
            if (res.data) {
              const found = res.data.find(x => (x.symbol || '').toUpperCase() === cleanSymbol);
              if (found) {
                const isFinished = (found.sentiment_last_updated && found.sentiment_last_updated !== initialLastUpdated && found.sentiment !== 'Checking now...')
                  || (attempts > 6 && found.sentiment !== 'Checking now...' && found.sentiment !== 'Watch');
                
                if (found.sentiment === 'Checking now...' || !isFinished) {
                  setWatchlist(prev => mergeWatchlistPreservingPending(res.data.map(item => (item.symbol || '').toUpperCase() === cleanSymbol ? { ...item, sentiment: 'Checking now...' } : item), prev));
                } else {
                  setWatchlist(prev => mergeWatchlistPreservingPending(res.data, prev));
                  clearInterval(pollInterval);
                  setRefreshingSentiment(prev => {
                    const next = { ...prev };
                    delete next[cleanSymbol];
                    return next;
                  });
                }
              }
            }
          } else {
            const res = await axios.get('/api/coin-data-live');
            if (res.data?.portfolio) {
              const found = res.data.portfolio.find(x => (x.symbol || '').toUpperCase() === cleanSymbol);
              if (found) {
                const isFinished = (found.sentiment_last_updated && found.sentiment_last_updated !== initialLastUpdated && found.sentiment !== 'Checking now...')
                  || (attempts > 6 && found.sentiment !== 'Checking now...' && found.sentiment !== 'Hold');

                if (found.sentiment === 'Checking now...' || !isFinished) {
                  setPortfolio(res.data.portfolio.map(c => (c.symbol || '').toUpperCase() === cleanSymbol ? { ...c, sentiment: 'Checking now...' } : c));
                } else {
                  setPortfolio(res.data.portfolio);
                  clearInterval(pollInterval);
                  setRefreshingSentiment(prev => {
                    const next = { ...prev };
                    delete next[cleanSymbol];
                    return next;
                  });
                }
              }
            }
          }
        } catch (pollErr) {
          console.error('Error polling after sentiment refresh:', pollErr);
        }

        if (attempts >= 35) {
          clearInterval(pollInterval);
          setRefreshingSentiment(prev => {
            const next = { ...prev };
            delete next[cleanSymbol];
            return next;
          });
          // Final fetch
          if (isWatchlist) {
            axios.get('/api/watchlist-live', { withCredentials: true }).then(r => r.data && setWatchlist(prev => mergeWatchlistPreservingPending(r.data, prev))).catch(() => {});
          } else {
            axios.get('/api/coin-data-live').then(r => r.data?.portfolio && setPortfolio(r.data.portfolio)).catch(() => {});
          }
        }
      }, 2000);
    } catch (err) {
      console.error('Failed to trigger single sentiment refresh:', err);
      setRefreshingSentiment(prev => {
        const next = { ...prev };
        delete next[cleanSymbol];
        return next;
      });
    }
  };

  const renderSentimentCell = (coin, isWatchlist = false) => {
    const sym = (coin.symbol || '').toUpperCase().trim();
    if (['USD', 'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDP'].includes(sym)) {
      return (
        <td
          style={{ textAlign: 'center', whiteSpace: 'nowrap', padding: '6px 8px', color: 'var(--text-secondary, #94a3b8)' }}
        >
          —
        </td>
      );
    }
    if (coin.sentiment_tracking_enabled === false) {
      return (
        <td
          title="Sentiment tracking is disabled for this coin. Double-click to re-enable."
          onDoubleClick={(e) => handleToggleSentimentTracking(coin, isWatchlist, e)}
          style={{ textAlign: 'center', whiteSpace: 'nowrap', padding: '6px 8px', cursor: 'pointer' }}
        >
          <span style={{
            fontSize: '0.8rem',
            fontStyle: 'italic',
            color: 'var(--text-secondary, #94a3b8)',
            opacity: 0.7
          }}>
            🚫 Not Tracked
          </span>
        </td>
      );
    }
    const rawSentiment = coin.sentiment || (isWatchlist ? 'Watch' : 'Hold');
    const isChecking = rawSentiment === 'Checking now...' || !!refreshingSentiment[coin.symbol];
    const sentiment = isChecking ? 'Checking now...' : rawSentiment;
    const reason = coin.sentiment_reason || '';
    const lastUpdated = coin.sentiment_last_updated ? `Last Updated: ${formatLocalDateTime(coin.sentiment_last_updated)}` : '';
    
    const metaParts = [];
    if (coin.sentiment_tier || coin.sentiment_provider || coin.sentiment_model) {
      metaParts.push(`Tier: ${getTierDisplayName(coin.sentiment_tier)}`);
      metaParts.push(`Provider: ${getProviderDisplayName(coin.sentiment_provider)}`);
      if (coin.sentiment_model) {
        metaParts.push(`Model: ${coin.sentiment_model}`);
      }
    }
    if (coin.sentiment_search_status) {
      let icon = '🔍';
      const statusLower = coin.sentiment_search_status.toLowerCase();
      if (statusLower.includes('brave') && !statusLower.includes('failed')) {
        icon = '✅';
      } else if (statusLower.includes('fallback') || statusLower.includes('duckduckgo')) {
        icon = '⚠️';
      } else if (statusLower.includes('unavailable') || statusLower.includes('failed')) {
        icon = '❌';
      }
      metaParts.push(`Web Search: ${icon} ${coin.sentiment_search_status}`);
    }
    const metaInfo = metaParts.join('\n');

    let tooltip = '';
    const tooltipSections = [];
    if (isChecking) {
      tooltipSections.push('Sentiment analysis currently in progress for this coin...');
    } else {
      if (reason) tooltipSections.push(reason);
      if (lastUpdated) {
        if (metaInfo) {
          tooltipSections.push(`${lastUpdated}\n${metaInfo}`);
        } else {
          tooltipSections.push(lastUpdated);
        }
      } else if (metaInfo) {
        tooltipSections.push(metaInfo);
      }
    }
    
    tooltip = tooltipSections.length > 0 ? tooltipSections.join('\n\n') : 'No sentiment explanation available';

    let color = isWatchlist ? '#63b3ed' : '#ecc94b';
    let bg = 'transparent';
    let label = sentiment;

    if (isChecking) {
      color = '#38bdf8';
      bg = 'rgba(56, 189, 248, 0.15)';
      label = '⏳ Checking now...';
    } else if (isWatchlist) {
      if (['Definitely Buy', 'Strong Buy', 'Buy Immediately'].includes(sentiment)) {
        color = '#00e676'; // Bright vibrant green
        label = 'Definitely Buy';
      } else if (['Consider Buying', 'Buy'].includes(sentiment)) {
        color = '#48bb78'; // Soft green
        label = 'Consider Buying';
      } else if (['Watch', 'Hold', 'Neutral'].includes(sentiment)) {
        color = '#63b3ed'; // Sky blue / slate
        label = 'Watch';
      } else if (['Avoid', 'Sell', 'Sell Immediately', 'Strong Sell', 'Do Not Buy'].includes(sentiment)) {
        color = '#f56565'; // Soft Red
        label = 'Avoid';
      } else if (sentiment === 'Error') {
        color = '#fc8181';
        bg = 'rgba(245, 101, 101, 0.2)';
        label = '⚠️ Error';
      }
    } else {
      if (['Buy Immediately', 'Strong Buy'].includes(sentiment)) {
        color = '#00e676'; // Bright vibrant green
      } else if (['Consider Buying', 'Buy'].includes(sentiment)) {
        color = '#48bb78'; // Green
      } else if (['Sell Immediately', 'Strong Sell'].includes(sentiment)) {
        color = '#f56565'; // Vibrant red
      } else if (['Consider Selling', 'Sell'].includes(sentiment)) {
        color = '#ed8936'; // Orange / Soft red
      } else if (sentiment === 'Hold') {
        color = '#ecc94b'; // Gold
      } else if (sentiment === 'Error') {
        color = '#fc8181'; // Red Error
        bg = 'rgba(245, 101, 101, 0.2)';
        label = '⚠️ Error';
      }
    }

    return (
      <td
        title={`${tooltip}\n\nDouble-click to disable sentiment tracking for this coin.`}
        onDoubleClick={(e) => handleToggleSentimentTracking(coin, isWatchlist, e)}
        style={{
          cursor: isChecking ? 'wait' : 'help',
          whiteSpace: 'nowrap',
          textAlign: 'center',
          padding: '6px 8px'
        }}
      >
        <div
          className={`sentiment-pill-wrapper ${coin.hasPendingOrder ? 'pending-highlight-sentiment' : ''}`}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '6px',
            background: coin.hasPendingOrder ? 'rgba(15, 23, 42, 0.92)' : 'transparent',
            padding: coin.hasPendingOrder ? '3px 8px' : '0',
            borderRadius: coin.hasPendingOrder ? '6px' : '0',
            border: coin.hasPendingOrder ? '1px solid rgba(0, 0, 0, 0.35)' : 'none',
            boxShadow: coin.hasPendingOrder ? '0 1px 4px rgba(0, 0, 0, 0.4)' : 'none'
          }}
        >
          <span
            style={{
              color: color,
              fontWeight: 'bold',
              background: bg,
              padding: bg !== 'transparent' ? '2px 6px' : '0',
              borderRadius: '4px',
              textDecoration: (!isChecking && reason) ? 'underline dotted' : 'none',
              textUnderlineOffset: '3px',
              fontSize: '0.88rem',
              display: 'inline-flex',
              alignItems: 'center',
              whiteSpace: 'nowrap',
              textShadow: coin.hasPendingOrder ? '0 1px 2px rgba(0,0,0,0.6)' : 'none'
            }}
          >
            {label}
          </span>
          <button
            type="button"
            onClick={(e) => handleSingleSentimentRefresh(coin.symbol, isWatchlist, e)}
            disabled={isChecking}
            title={isChecking ? 'Analysis in progress...' : `Refresh sentiment for ${coin.symbol}`}
            style={{
              background: 'transparent',
              border: 'none',
              color: isChecking ? '#38bdf8' : (coin.hasPendingOrder ? '#94a3b8' : 'rgba(255, 255, 255, 0.45)'),
              cursor: isChecking ? 'not-allowed' : 'pointer',
              padding: '2px',
              borderRadius: '4px',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '0.82rem',
              transition: 'all 0.2s',
              flexShrink: 0
            }}
            onMouseEnter={(e) => {
              if (!isChecking) {
                e.currentTarget.style.color = '#38bdf8';
                e.currentTarget.style.background = 'rgba(56, 189, 248, 0.15)';
              }
            }}
            onMouseLeave={(e) => {
              if (!isChecking) {
                e.currentTarget.style.color = coin.hasPendingOrder ? '#94a3b8' : 'rgba(255, 255, 255, 0.45)';
                e.currentTarget.style.background = 'transparent';
              }
            }}
          >
            <FaSyncAlt style={{ animation: isChecking ? 'spin 1s linear infinite' : 'none' }} />
          </button>
        </div>
      </td>
    );
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
      {/* Mobile-Only Charts vs Tables Segmented Tab Bar */}
      {isMobile && (
        <div className="mobile-dashboard-tabs">
          <button
            type="button"
            className={`mobile-dashboard-tab-btn ${mobileTab === 'charts' ? 'active' : ''}`}
            onClick={() => setMobileTab('charts')}
          >
            📊 Charts
          </button>
          <button
            type="button"
            className={`mobile-dashboard-tab-btn ${mobileTab === 'tables' ? 'active' : ''}`}
            onClick={() => setMobileTab('tables')}
          >
            📋 Tables
          </button>
        </div>
      )}

      {/* Interactive Customizable Widgets Grid */}
      <div className={`dashboard-widgets-section ${isMobile && mobileTab !== 'charts' ? 'mobile-hidden' : ''}`}>
        <DashboardWidgetGrid
          isLightMode={isLightMode}
        renderWidgetContent={(widgetId) => {
          switch (widgetId) {
            case 'allocations':
              return (
                <div className="chart-panel widget-panel-inner" style={{ height: '100%', padding: '16px', display: 'flex', flexDirection: 'column' }}>
                  <h2 className="chart-title" style={{ margin: '0 0 12px 0', fontSize: '1.1rem' }}>Allocations</h2>
                  <div style={{ flex: 1, minHeight: '260px', width: '100%' }}>
                    <PortfolioPie portfolio={portfolio} isLightMode={isLightMode} totalValue={totalValue} />
                  </div>
                </div>
              );
            case 'trend':
              return (
                <div className="chart-panel widget-panel-inner" style={{ height: '100%', padding: '16px', display: 'flex', flexDirection: 'column' }}>
                  <h2 className="chart-title" style={{ margin: '0 0 12px 0', fontSize: '1.1rem' }}>Portfolio Trend</h2>
                  <div style={{ flex: 1, minHeight: '220px', width: '100%' }}>
                    {trendLoading ? (
                      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', color: '#94a3b8' }}>
                        Loading trend...
                      </div>
                    ) : (
                      <PortfolioTrend history={trendHistory} range={trendRange} isLightMode={isLightMode} />
                    )}
                  </div>
                  <div className="time-range-container" style={{ marginTop: '8px', display: 'flex', justifyContent: 'center', gap: '4px', flexWrap: 'wrap' }}>
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
              );
            case 'fear_greed':
              return <FearGreedWidget />;
            case 'portfolio_value':
              return (
                <div className="portfolio-value-widget-card widget-panel-inner" style={{ padding: '20px', height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center' }}>
                  <div style={{ marginBottom: '14px', textAlign: 'center' }}>
                    <h3 style={{ margin: '0 0 4px 0', fontSize: '16px', fontWeight: '600', color: 'var(--text-primary, #ffffff)' }}>
                      Portfolio Value
                    </h3>
                    <small style={{ fontSize: '12px', color: 'var(--text-secondary, #94a3b8)', display: 'block' }}>
                      Total Holdings (incl. staking & pending)
                    </small>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px', flex: 1, justifyContent: 'center' }}>
                    <div style={{ fontSize: '32px', fontWeight: 'bold', color: 'var(--primary-color, #38bdf8)', textAlign: 'center' }}>
                      ${totalValue != null ? Number(totalValue).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '0.00'}
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--text-secondary, #94a3b8)', opacity: '0.85', textAlign: 'center' }}>
                      Includes Binance.US staking balances · Last updated: {new Date().toLocaleTimeString()}
                    </div>
                  </div>
                </div>
              );
            case 'cbbi':
              return <CBBIWidget />;
            case 'staking':
              return <StakingSummaryWidget />;
            case 'performance':
              return <PortfolioPerformanceTable hiddenCoins={performanceHiddenCoins} onEdit={handleOpenPerformanceCoinModal} />;
            case 'top_movers':
              return <TopMoversWidget isLightMode={isLightMode} config={topMoversConfig} onEdit={handleOpenTopMoversModal} ownedSymbols={ownedSymbols} onCoinClick={(symbol) => navigateToTrading(symbol, 'BUY', 'USDT')} />;
            case 'recent_trades':
              return <RecentTradesWidget isLightMode={isLightMode} config={recentTradesConfig} onEdit={handleOpenRecentTradesModal} />;
            case 'ai_pulse':
              return <AIPulseWidget isLightMode={isLightMode} />;
            case 'staking_rewards':
              return <StakingYieldWidget isLightMode={isLightMode} />;
            case 'risk_monitor':
              return <RiskMonitorWidget isLightMode={isLightMode} portfolio={portfolio} totalValue={totalValue} />;
            case 'quick_trade':
              return <QuickTradeWidget isLightMode={isLightMode} portfolio={portfolio} />;
            case 'gas_monitor':
              return <GasMonitorWidget isLightMode={isLightMode} />;
            default:
              return null;
          }
        }}
      />
      </div>

      {/* Tables Section */}
      <div className={`dashboard-tables-section ${isMobile && mobileTab !== 'tables' ? 'mobile-hidden' : ''}`}>
        {/* Portfolio Table */}
        <div className="table-container portfolio-table">
          <div className="table-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px', marginBottom: '8px' }}>
            <h2 className="table-title" style={{ margin: 0 }}>Portfolio</h2>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <div style={{ fontSize: '15px', fontWeight: '700', color: 'var(--accent-primary, #4fd1c5)', letterSpacing: '0.3px' }}>
                Total Value: ${(totalValue != null ? Number(totalValue) : (portfolio || []).reduce((acc, c) => acc + (parseFloat(c.current_value) || 0), 0)).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USDT
              </div>
              <button
                type="button"
                className="table-customize-columns-btn"
                onClick={() => setColumnModal({ isOpen: true, tableType: 'portfolio' })}
                title="Customize Portfolio Columns"
                aria-label="Customize Portfolio Columns"
              >
                ✏️
              </button>
            </div>
          </div>
          <div className="table-scroll-wrapper">
            <table style={{ width: `${totalPortfolioWidth}px`, minWidth: '100%', tableLayout: 'fixed', borderCollapse: 'collapse' }}>
              <colgroup>
                {portfolioColOrder
                  .filter((colKey) => portfolioVisibleCols.includes(colKey) && PORTFOLIO_COLUMN_DEFINITIONS[colKey])
                  .map((colKey) => {
                    const colDef = PORTFOLIO_COLUMN_DEFINITIONS[colKey] || { defaultWidth: 120 };
                    const width = portfolioColWidths[colKey] || colDef.defaultWidth;
                    return <col key={colKey} style={{ width: `${width}px` }} />;
                  })}
              </colgroup>
              <thead>
                <tr>
                  {portfolioColOrder
                    .filter((colKey) => portfolioVisibleCols.includes(colKey) && PORTFOLIO_COLUMN_DEFINITIONS[colKey])
                    .map((colKey) => {
                      const colDef = PORTFOLIO_COLUMN_DEFINITIONS[colKey] || { label: colKey };
                      const isSortable = !!colDef.sortable;
                      const isDraggable = colKey !== 'symbol' && colKey !== 'actions';
                      const width = portfolioColWidths[colKey] || colDef.defaultWidth;

                      return (
                        <th
                          key={colKey}
                          onClick={isSortable ? () => handleSort(colKey) : undefined}
                          className={`portfolio-header ${isSortable ? 'sortable' : ''} ${dragOverColKey === colKey ? 'drag-over-target' : ''}`}
                          draggable={isDraggable && !isResizing}
                          onDragStart={(e) => handleColDragStart('portfolio', colKey, e)}
                          onDragOver={(e) => handleColDragOver('portfolio', colKey, e)}
                          onDrop={(e) => handleColDrop('portfolio', colKey, e)}
                          onDragEnd={handleColDragEnd}
                          style={{
                            width: `${width}px`,
                            minWidth: `${width}px`,
                            maxWidth: `${width}px`,
                            boxSizing: 'border-box',
                            cursor: isDraggable ? 'grab' : isSortable ? 'pointer' : 'default',
                            position: 'relative'
                          }}
                          title={isDraggable ? 'Click to sort (if sortable) or drag to reorder column' : undefined}
                        >
                          <div className="table-header-cell-content" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {isSortable ? renderHeaderLabel(colKey, colDef.label) : colDef.label}
                          </div>
                          <div
                            className="col-resizer-handle"
                            draggable={false}
                            onDragStart={(e) => { e.preventDefault(); e.stopPropagation(); }}
                            onMouseDown={(e) => handleResizeStart('portfolio', colKey, e)}
                            onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}
                            title="Drag to resize column width"
                          />
                        </th>
                      );
                    })}
                </tr>
              </thead>
              <tbody>
                {!Array.isArray(portfolio) || portfolio.length === 0 ? (
                  <tr>
                    <td
                      colSpan={portfolioColOrder.filter((k) => portfolioVisibleCols.includes(k) && PORTFOLIO_COLUMN_DEFINITIONS[k]).length || 11}
                      className="no-data"
                      style={{ textAlign: 'center' }}
                    >
                      No portfolio data available
                    </td>
                  </tr>
                ) : (
                  sortData(portfolio, sortConfig.key).map((coin) => {
                    const sym = (coin.symbol || '').toUpperCase().trim();
                    const isStable = ['USD', 'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDP'].includes(sym);
                    const isPlaceholder = !!coin.pendingPlaceholder || !coin.id;
                    const alertTitle = isPlaceholder
                      ? 'Alerts unavailable for pending-only entries'
                      : coin.alert_enabled
                        ? 'Alerts enabled'
                        : 'Alerts disabled';

                    const visibleCols = portfolioColOrder.filter(
                      (k) => portfolioVisibleCols.includes(k) && PORTFOLIO_COLUMN_DEFINITIONS[k]
                    );

                    const hasExchangeOrder = !!coin.hasPendingOrder || getPendingOrdersForCoin(coin.symbol).length > 0;
                    const isAutoBuy = !!coin.auto_buy_enabled;
                    const isAutoSell = !!coin.auto_sell_enabled;

                    let rowClass = '';
                    if (hasExchangeOrder) {
                      rowClass = 'pending-order';
                    } else if (isAutoBuy && isAutoSell) {
                      rowClass = 'auto-both-active';
                    } else if (isAutoBuy) {
                      rowClass = 'auto-buy-active';
                    } else if (isAutoSell) {
                      rowClass = 'auto-sell-active';
                    }

                    return (
                      <tr
                        key={coin.id || coin.symbol}
                        className={rowClass}
                        onMouseMove={(e) => handleRowHover(coin, e)}
                        onMouseLeave={handleRowLeave}
                      >
                        {visibleCols.map((colKey) => {
                          switch (colKey) {
                            case 'symbol':
                              return (
                                <td
                                  key="symbol"
                                  className="symbol-cell"
                                  onMouseEnter={(e) => handleSymbolHover(coin.symbol, e)}
                                  onMouseLeave={handleSymbolLeave}
                                  onClick={() => handleChartClick(coin.symbol)}
                                  style={{ cursor: 'pointer', textAlign: 'center' }}
                                  title="Hover for 7-day chart, click to open on Binance"
                                >
                                  <div className="coin-symbol-container" style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', justifyContent: 'center' }}>
                                    <CryptoIcon symbol={coin.symbol} size={20} />
                                    <span>{coin.symbol}</span>
                                  </div>
                                </td>
                              );
                            case 'amount':
                              return (
                                <td key="amount" style={{ textAlign: 'center' }}>
                                  {coin.pendingPlaceholder ? '0.0000' : (coin.amount !== undefined && coin.amount !== null ? coin.amount.toFixed(4) : '—')}
                                </td>
                              );
                            case 'current_price':
                              return (
                                <td key="current_price" style={{ whiteSpace: 'nowrap', textAlign: 'center' }}>
                                  {isStable
                                    ? '$1.00'
                                    : formatDynamicPrice(coin.current_price)}
                                </td>
                              );
                            case 'current_value':
                              return (
                                <td key="current_value" style={{ whiteSpace: 'nowrap', textAlign: 'center' }}>
                                  {coin.current_value !== undefined && coin.current_value !== null ? `$${coin.current_value.toFixed(2)}` : '—'}
                                </td>
                              );
                            case 'down_alert':
                              return (
                                <td key="down_alert" style={{ textAlign: 'center' }}>
                                  {renderPortfolioAlertCell(coin, 'down')}
                                </td>
                              );
                            case 'up_alert':
                              return (
                                <td key="up_alert" style={{ textAlign: 'center' }}>
                                  {renderPortfolioAlertCell(coin, 'up')}
                                </td>
                              );
                            case 'volatility_pct':
                              return (
                                <td key="volatility_pct" style={{ textAlign: 'center' }}>
                                  {renderVolatilityCell(coin, 'portfolio')}
                                </td>
                              );
                            case 'avg_entry':
                              return (
                                <td key="avg_entry" style={{ whiteSpace: 'nowrap', textAlign: 'center' }}>
                                  {isStable ? '$1.00' : (coin.avg_entry ? `$${coin.avg_entry.toFixed(2)}` : '—')}
                                </td>
                              );
                            case 'pct_change':
                              return (
                                <td
                                  key="pct_change"
                                  className={!isStable && coin.pct_change >= 0 ? 'status-positive' : !isStable && coin.pct_change < 0 ? 'status-negative' : ''}
                                  style={{
                                    whiteSpace: 'nowrap',
                                    textAlign: 'center',
                                    color: !isStable && coin.pct_change !== undefined && coin.pct_change !== null
                                      ? (coin.pct_change >= 0 ? '#22c55e' : '#ef4444')
                                      : undefined,
                                    fontWeight: '600'
                                  }}
                                >
                                  {isStable ? '—' : (coin.pct_change !== undefined && coin.pct_change !== null ? `${coin.pct_change >= 0 ? '+' : ''}${coin.pct_change.toFixed(2)}%` : '—')}
                                </td>
                              );
                            case 'change_24h':
                              return (
                                <td
                                  key="change_24h"
                                  className={!isStable && coin.change_24h >= 0 ? 'status-positive' : !isStable && coin.change_24h < 0 ? 'status-negative' : ''}
                                  style={{
                                    whiteSpace: 'nowrap',
                                    textAlign: 'center',
                                    color: !isStable && coin.change_24h !== undefined && coin.change_24h !== null
                                      ? (coin.change_24h >= 0 ? '#4ade80' : '#f87171')
                                      : undefined,
                                    fontWeight: '600'
                                  }}
                                >
                                  {isStable ? '—' : (coin.change_24h !== undefined && coin.change_24h !== null ? `${coin.change_24h >= 0 ? '+' : ''}${Number(coin.change_24h).toFixed(2)}%` : '—')}
                                </td>
                              );
                            case 'sentiment':
                              return renderSentimentCell(coin, false);
                            case 'high_low_24h':
                              return (
                                <td key="high_low_24h" style={{ whiteSpace: 'nowrap', textAlign: 'center', fontSize: '0.85rem' }}>
                                  {coin.high_24h && coin.low_24h ? (
                                    <span>
                                      <span style={{ color: '#4ade80' }}>${coin.high_24h >= 1 ? coin.high_24h.toFixed(2) : coin.high_24h.toFixed(4)}</span> / <span style={{ color: '#f87171' }}>${coin.low_24h >= 1 ? coin.low_24h.toFixed(2) : coin.low_24h.toFixed(4)}</span>
                                    </span>
                                  ) : '—'}
                                </td>
                              );
                            case 'volume_24h':
                              return (
                                <td key="volume_24h" style={{ whiteSpace: 'nowrap', textAlign: 'center' }}>
                                  {coin.volume_24h ? `$${Number(coin.volume_24h).toLocaleString('en-US', { maximumFractionDigits: 0 })}` : '—'}
                                </td>
                              );
                            case 'market_cap':
                              return (
                                <td key="market_cap" style={{ whiteSpace: 'nowrap', textAlign: 'center' }}>
                                  {coin.market_cap ? `$${Number(coin.market_cap).toLocaleString('en-US', { maximumFractionDigits: 0 })}` : (coin.rank ? `#${coin.rank}` : '—')}
                                </td>
                              );
                            case 'pnl_usd': {
                              const pnl = (coin.current_value !== undefined && coin.cost_basis !== undefined && coin.cost_basis > 0)
                                ? (coin.current_value - coin.cost_basis)
                                : (coin.current_price && coin.avg_entry && coin.amount)
                                  ? (coin.amount * (coin.current_price - coin.avg_entry))
                                  : null;
                              return (
                                <td
                                  key="pnl_usd"
                                  className={pnl && pnl >= 0 ? 'status-positive' : pnl && pnl < 0 ? 'status-negative' : ''}
                                  style={{
                                    whiteSpace: 'nowrap',
                                    textAlign: 'center',
                                    color: pnl !== null ? (pnl >= 0 ? '#22c55e' : '#ef4444') : undefined,
                                    fontWeight: '600'
                                  }}
                                >
                                  {isStable || pnl === null ? '—' : `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}`}
                                </td>
                              );
                            }
                            case 'allocation_pct': {
                              const totVal = Number(totalValue) || (portfolio || []).reduce((acc, c) => acc + (parseFloat(c.current_value) || 0), 0);
                              const alloc = (totVal > 0 && coin.current_value) ? ((coin.current_value / totVal) * 100) : 0;
                              return (
                                <td key="allocation_pct" style={{ whiteSpace: 'nowrap', textAlign: 'center' }}>
                                  {alloc > 0 ? `${alloc.toFixed(1)}%` : '—'}
                                </td>
                              );
                            }
                            case 'target_price': {
                              const target = coin.target_price || coin.custom_upper_val || coin.up_alert || null;
                              return (
                                <td key="target_price" style={{ whiteSpace: 'nowrap', textAlign: 'center' }}>
                                  {target ? `$${Number(target).toFixed(2)}` : '—'}
                                </td>
                              );
                            }
                            case 'last_updated':
                              return (
                                <td key="last_updated" style={{ whiteSpace: 'nowrap', textAlign: 'center', fontSize: '0.82rem', color: '#94a3b8' }}>
                                  {coin.last_updated || 'Live'}
                                </td>
                              );
                            case 'actions':
                              return (
                                <td key="actions" className="actions-cell" style={{ whiteSpace: 'nowrap', position: 'relative', textAlign: 'center' }}>
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
                                    <div className="actions-cell-content">
                                      <button
                                        type="button"
                                        onClick={!isPlaceholder ? () => toggleAlert(coin.id, coin.alert_enabled) : undefined}
                                        className={`action-icon-btn alert-btn ${coin.alert_enabled ? 'alert-enabled' : 'alert-disabled'}`}
                                        title={alertTitle}
                                        disabled={isPlaceholder}
                                        style={{ cursor: isPlaceholder ? 'not-allowed' : 'pointer' }}
                                      >
                                        🔔
                                      </button>
                                      <button
                                        type="button"
                                        className="action-icon-btn news-btn"
                                        title={getNewsTooltip(coin)}
                                        onClick={() => openNews(coin.symbol)}
                                      >
                                        📰
                                      </button>
                                      <button
                                        type="button"
                                        className="action-icon-btn note-btn"
                                        title={coin.note ? `Note: ${coin.note}` : 'Add note'}
                                        onClick={() => openNoteModal(coin)}
                                      >
                                        ✏️
                                      </button>
                                      <button
                                        className="trade-action-btn buy"
                                        onClick={(event) => coin.symbol !== 'USD' && toggleTradeQuoteMenu('portfolio', coin.symbol, 'BUY', event)}
                                        disabled={coin.symbol === 'USD'}
                                        title={coin.symbol === 'USD' ? 'Cannot purchase fiat USD' : 'Buy'}
                                        style={coin.symbol === 'USD' ? { opacity: 0.4, cursor: 'not-allowed' } : undefined}
                                      >
                                        Buy
                                      </button>
                                      <button
                                        className="trade-action-btn sell"
                                        onClick={(event) => coin.symbol !== 'USD' && toggleTradeQuoteMenu('portfolio', coin.symbol, 'SELL', event)}
                                        disabled={coin.symbol === 'USD'}
                                        title={coin.symbol === 'USD' ? 'Cannot sell fiat USD' : 'Sell'}
                                        style={coin.symbol === 'USD' ? { opacity: 0.4, cursor: 'not-allowed' } : undefined}
                                      >
                                        Sell
                                      </button>
                                      <button
                                        className="trade-action-btn stake"
                                        onClick={() => handleStakeClick(coin)}
                                        disabled={
                                          !stakeableCoins.includes(coin.symbol) ||
                                          isPlaceholder ||
                                          (coin.current_value && coin.current_value < 1)
                                        }
                                        title={
                                          !stakeableCoins.includes(coin.symbol)
                                            ? 'Staking not available for this coin'
                                            : (coin.current_value && coin.current_value < 1)
                                              ? 'Minimum $1 USDT value required to stake'
                                              : 'Stake this coin'
                                        }
                                      >
                                        Stake
                                      </button>
                                      {(() => {
                                        const allPendingItems = getAllPendingItemsForCoin(coin);
                                        const hasOrders = allPendingItems.length > 0;
                                        return (
                                          <button
                                            type="button"
                                            className={`trade-action-btn cancel ${!hasOrders ? 'disabled-cancel' : ''}`}
                                            onClick={(e) => hasOrders && handleCancelButtonClick(coin, allPendingItems, e)}
                                            disabled={!hasOrders}
                                            title={hasOrders ? `Cancel ${allPendingItems.length} active order(s)/trigger(s) for ${coin.symbol}` : 'No pending orders or active triggers to cancel'}
                                          >
                                            Cancel
                                          </button>
                                        );
                                      })()}
                                      <button
                                        className="trade-action-btn hide"
                                        onClick={() => { if (!isPlaceholder) { hideCoin(coin.id); } }}
                                        title={isPlaceholder ? 'Cannot hide pending-only entries' : 'Hide coin'}
                                        disabled={isPlaceholder}
                                      >
                                        Hide
                                      </button>
                                    </div>
                                  )}
                                </td>
                              );
                            default:
                              return <td key={colKey}>—</td>;
                          }
                        })}
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
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
          <div className="table-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
            <h2 className="table-title" style={{ margin: 0 }}>Watchlist</h2>
            <button
              type="button"
              className="table-customize-columns-btn"
              onClick={() => setColumnModal({ isOpen: true, tableType: 'watchlist' })}
              title="Customize Watchlist Columns"
              aria-label="Customize Watchlist Columns"
            >
              ✏️
            </button>
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
          <div className="table-scroll-wrapper">
            <table style={{ width: `${totalWatchlistWidth}px`, minWidth: '100%', tableLayout: 'fixed', borderCollapse: 'collapse' }}>
              <colgroup>
                {watchlistColOrder
                  .filter((colKey) => watchlistVisibleCols.includes(colKey) && WATCHLIST_COLUMN_DEFINITIONS[colKey])
                  .map((colKey) => {
                    const colDef = WATCHLIST_COLUMN_DEFINITIONS[colKey] || { defaultWidth: 120 };
                    const width = watchlistColWidths[colKey] || colDef.defaultWidth;
                    return <col key={colKey} style={{ width: `${width}px` }} />;
                  })}
              </colgroup>
              <thead>
                <tr>
                  {watchlistColOrder
                    .filter((colKey) => watchlistVisibleCols.includes(colKey) && WATCHLIST_COLUMN_DEFINITIONS[colKey])
                    .map((colKey) => {
                      const colDef = WATCHLIST_COLUMN_DEFINITIONS[colKey] || { label: colKey };
                      const isSortable = !!colDef.sortable;
                      const isDraggable = colKey !== 'symbol' && colKey !== 'actions';
                      const width = watchlistColWidths[colKey] || colDef.defaultWidth;

                      return (
                        <th
                          key={colKey}
                          onClick={isSortable ? () => handleSort(colKey) : undefined}
                          className={`watchlist-header ${isSortable ? 'sortable' : ''} ${dragOverColKey === colKey ? 'drag-over-target' : ''}`}
                          draggable={isDraggable && !isResizing}
                          onDragStart={(e) => handleColDragStart('watchlist', colKey, e)}
                          onDragOver={(e) => handleColDragOver('watchlist', colKey, e)}
                          onDrop={(e) => handleColDrop('watchlist', colKey, e)}
                          onDragEnd={handleColDragEnd}
                          style={{
                            width: `${width}px`,
                            minWidth: `${width}px`,
                            maxWidth: `${width}px`,
                            boxSizing: 'border-box',
                            cursor: isDraggable ? 'grab' : isSortable ? 'pointer' : 'default',
                            position: 'relative'
                          }}
                          title={isDraggable ? 'Click to sort (if sortable) or drag to reorder column' : undefined}
                        >
                          <div className="table-header-cell-content" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {isSortable ? renderHeaderLabel(colKey, colDef.label) : colDef.label}
                          </div>
                          <div
                            className="col-resizer-handle"
                            draggable={false}
                            onDragStart={(e) => { e.preventDefault(); e.stopPropagation(); }}
                            onMouseDown={(e) => handleResizeStart('watchlist', colKey, e)}
                            onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}
                            title="Drag to resize column width"
                          />
                        </th>
                      );
                    })}
                </tr>
              </thead>
              <tbody>
                {!Array.isArray(watchlist) || watchlist.length === 0 ? (
                  <tr>
                    <td
                      colSpan={watchlistColOrder.filter((k) => watchlistVisibleCols.includes(k) && WATCHLIST_COLUMN_DEFINITIONS[k]).length || 7}
                      className="no-data"
                      style={{ textAlign: 'center' }}
                    >
                      No watchlist items
                    </td>
                  </tr>
                ) : (
                  sortData(watchlist, sortConfig.key).map((item) => {
                    const visibleCols = watchlistColOrder.filter(
                      (k) => watchlistVisibleCols.includes(k) && WATCHLIST_COLUMN_DEFINITIONS[k]
                    );

                    const hasExchangeOrder = getPendingOrdersForCoin(item.symbol).length > 0;
                    const isAutoBuy = !!item.auto_buy_enabled;
                    const isAutoSell = !!item.auto_sell_enabled;

                    let rowClass = '';
                    if (hasExchangeOrder) {
                      rowClass = 'pending-order';
                    } else if (isAutoBuy && isAutoSell) {
                      rowClass = 'auto-both-active';
                    } else if (isAutoBuy) {
                      rowClass = 'auto-buy-active';
                    } else if (isAutoSell) {
                      rowClass = 'auto-sell-active';
                    }

                    return (
                      <tr
                        key={item.symbol}
                        className={rowClass}
                        onMouseMove={(e) => handleRowHover(item, e)}
                        onMouseLeave={handleRowLeave}
                      >
                        {visibleCols.map((colKey) => {
                          switch (colKey) {
                            case 'symbol':
                              return (
                                <td
                                  key="symbol"
                                  className="symbol-cell"
                                  style={{ textAlign: 'center', cursor: 'pointer' }}
                                  onMouseEnter={(e) => handleSymbolHover(item.symbol, e)}
                                  onMouseLeave={handleSymbolLeave}
                                  onClick={() => handleChartClick(item.symbol)}
                                  title="Hover for 7-day chart, click to open on Binance"
                                >
                                  <div className="coin-symbol-container" style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', justifyContent: 'center' }}>
                                    <CryptoIcon symbol={item.symbol} size={20} />
                                    <span>{item.symbol}</span>
                                  </div>
                                </td>
                              );
                            case 'current_price':
                              return (
                                <td key="current_price" style={{ whiteSpace: 'nowrap', textAlign: 'center' }}>
                                  {formatDynamicPrice(item.current_price)}
                                </td>
                              );
                            case 'down_alert':
                              return (
                                <td key="down_alert" style={{ textAlign: 'center' }}>
                                  {renderWatchlistAlertCell(item, 'down')}
                                </td>
                              );
                            case 'up_alert':
                              return (
                                <td key="up_alert" style={{ textAlign: 'center' }}>
                                  {renderWatchlistAlertCell(item, 'up')}
                                </td>
                              );
                            case 'volatility_pct':
                              return (
                                <td key="volatility_pct" style={{ textAlign: 'center' }}>
                                  {renderVolatilityCell(item, 'watchlist')}
                                </td>
                              );
                            case 'sentiment':
                              return renderSentimentCell(item, true);
                            case 'pct_change':
                              return (
                                <td
                                  key="pct_change"
                                  style={{
                                    whiteSpace: 'nowrap',
                                    textAlign: 'center',
                                    color: (item.pct_change || 0) >= 0 ? '#22c55e' : '#ef4444',
                                    fontWeight: '600'
                                  }}
                                >
                                  {item.pct_change !== undefined && item.pct_change !== null ? `${item.pct_change >= 0 ? '+' : ''}${item.pct_change.toFixed(2)}%` : '—'}
                                </td>
                              );
                            case 'high_low_24h':
                              return (
                                <td key="high_low_24h" style={{ whiteSpace: 'nowrap', textAlign: 'center', fontSize: '0.85rem' }}>
                                  {item.high_24h && item.low_24h ? (
                                    <span>
                                      <span style={{ color: '#4ade80' }}>${item.high_24h >= 1 ? item.high_24h.toFixed(2) : item.high_24h.toFixed(4)}</span> / <span style={{ color: '#f87171' }}>${item.low_24h >= 1 ? item.low_24h.toFixed(2) : item.low_24h.toFixed(4)}</span>
                                    </span>
                                  ) : '—'}
                                </td>
                              );
                            case 'volume_24h':
                              return (
                                <td key="volume_24h" style={{ whiteSpace: 'nowrap', textAlign: 'center' }}>
                                  {item.volume_24h ? `$${Number(item.volume_24h).toLocaleString('en-US', { maximumFractionDigits: 0 })}` : '—'}
                                </td>
                              );
                            case 'market_cap':
                              return (
                                <td key="market_cap" style={{ whiteSpace: 'nowrap', textAlign: 'center' }}>
                                  {item.market_cap ? `$${Number(item.market_cap).toLocaleString('en-US', { maximumFractionDigits: 0 })}` : (item.rank ? `#${item.rank}` : '—')}
                                </td>
                              );
                            case 'target_price': {
                              const target = item.target_price || item.custom_upper_val || item.up_alert || null;
                              return (
                                <td key="target_price" style={{ whiteSpace: 'nowrap', textAlign: 'center' }}>
                                  {target ? `$${Number(target).toFixed(2)}` : '—'}
                                </td>
                              );
                            }
                            case 'last_updated':
                              return (
                                <td key="last_updated" style={{ whiteSpace: 'nowrap', textAlign: 'center', fontSize: '0.82rem', color: '#94a3b8' }}>
                                  {item.last_updated || 'Live'}
                                </td>
                              );
                            case 'actions':
                              return (
                                <td key="actions" className="actions-cell" style={{ textAlign: 'center', whiteSpace: 'nowrap', position: 'relative' }}>
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
                                    <div className="actions-cell-content">
                                      <button
                                        type="button"
                                        onClick={() => toggleWatchlistAlert(item.symbol, item.alert_enabled)}
                                        className={`action-icon-btn alert-btn ${item.alert_enabled ? 'alert-enabled' : 'alert-disabled'}`}
                                        title={item.alert_enabled ? 'Alerts enabled' : 'Alerts disabled'}
                                      >
                                        🔔
                                      </button>
                                      <button
                                        type="button"
                                        className="action-icon-btn news-btn"
                                        title={getNewsTooltip(item)}
                                        onClick={() => openNews(item.symbol)}
                                      >
                                        📰
                                      </button>
                                      <button
                                        type="button"
                                        className="action-icon-btn note-btn"
                                        title={item.note ? `Note: ${item.note}` : 'Add note'}
                                        onClick={() => openNoteModal(item)}
                                      >
                                        ✏️
                                      </button>
                                      <button
                                        className="trade-action-btn buy"
                                        onClick={(event) => item.symbol !== 'USD' && toggleTradeQuoteMenu('watchlist', item.symbol, 'BUY', event)}
                                        disabled={item.symbol === 'USD'}
                                        title={item.symbol === 'USD' ? 'Cannot purchase fiat USD' : 'Buy'}
                                        style={item.symbol === 'USD' ? { opacity: 0.4, cursor: 'not-allowed' } : undefined}
                                      >
                                        Buy
                                      </button>
                                      {(() => {
                                        const allPendingItems = getAllPendingItemsForCoin({ ...item, isWatchlist: true });
                                        const hasOrders = allPendingItems.length > 0;
                                        if (!hasOrders) return null;
                                        return (
                                          <button
                                            type="button"
                                            className="trade-action-btn cancel"
                                            onClick={(e) => handleCancelButtonClick({ ...item, isWatchlist: true }, allPendingItems, e)}
                                            title={`Cancel ${allPendingItems.length} active order(s)/trigger(s) for ${item.symbol}`}
                                          >
                                            Cancel
                                          </button>
                                        );
                                      })()}
                                      <button
                                        className="trade-action-btn delete"
                                        onClick={() => deleteWatchlistItem(item.symbol)}
                                        title="Delete from watchlist"
                                      >
                                        🗑️
                                      </button>
                                    </div>
                                  )}
                                </td>
                              );
                            default:
                              return <td key={colKey}>—</td>;
                          }
                        })}
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
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
        onMouseEnter={handlePopupMouseEnter}
        onChartClick={handleChartClick}
      />

      {/* Mobile Actions Overlay */}
      {renderMobileActionsOverlay()}
      {renderDesktopTradeQuoteMenu()}

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
                className="btn btn-primary"
                onClick={() => refreshNews(newsAnalysisSymbol)}
                disabled={newsLoading}
              >
                {newsLoading ? 'Refreshing...' : 'Refresh Analysis'}
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => setShowNewsModal(false)}
              >
                Close
              </button>
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

      {/* Auto-Sell Confirmation Modal */}
      {autoSellModal.isOpen && (
        <div className="modal-overlay" onClick={() => setAutoSellModal(prev => ({ ...prev, isOpen: false }))}>
          <div className="modal-content auto-sell-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '460px' }}>
            <div className="modal-header">
              <h3 style={{ display: 'flex', alignItems: 'center', gap: '8px', margin: 0 }}>
                <span>⚡</span> Trigger Auto-Sell ({autoSellModal.symbol})
              </h3>
              <button className="modal-close" onClick={() => setAutoSellModal(prev => ({ ...prev, isOpen: false }))}>×</button>
            </div>
            <div style={{ padding: '20px 24px' }}>
              <p style={{ fontSize: '14px', lineHeight: '1.6', margin: '0 0 16px', color: 'var(--text-primary, #e2e8f0)' }}>
                You are about to enable an automatic sale of <strong>{autoSellModal.symbol} for {autoSellModal.quoteCurrency}</strong> when the price drops more than <strong>{autoSellModal.volatilityPct}%</strong> within the past <strong>{autoSellModal.volatilityHours} hour(s)</strong> (configured in Settings). Are you sure you want to do this?
              </p>

              {autoSellModal.coin?.auto_sell_enabled && (
                <div style={{
                  padding: '10px 14px',
                  borderRadius: '6px',
                  backgroundColor: 'rgba(34, 197, 94, 0.12)',
                  color: '#4ade80',
                  fontSize: '13px',
                  marginBottom: '16px',
                  border: '1px solid rgba(34, 197, 94, 0.3)'
                }}>
                  ⚡ Auto-Sell is currently <strong>ACTIVE</strong> for {autoSellModal.symbol} ({autoSellModal.coin.auto_sell_quote_currency || 'USDT'}).
                </div>
              )}

              {autoSellModal.error && (
                <div style={{
                  padding: '10px 14px',
                  borderRadius: '6px',
                  backgroundColor: 'rgba(239, 68, 68, 0.15)',
                  color: '#f87171',
                  fontSize: '13px',
                  marginBottom: '16px',
                  border: '1px solid rgba(239, 68, 68, 0.3)'
                }}>
                  {autoSellModal.error}
                </div>
              )}
            </div>
            <div className="modal-actions" style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', padding: '16px 24px', borderTop: '1px solid var(--border-color, rgba(255,255,255,0.08))' }}>
              {autoSellModal.coin?.auto_sell_enabled && (
                <button
                  className="btn btn-secondary"
                  style={{ marginRight: 'auto', color: '#f87171', borderColor: 'rgba(239,68,68,0.4)' }}
                  onClick={() => handleConfirmAutoSell(false)}
                  disabled={autoSellModal.loading}
                >
                  Disable Auto-Sell
                </button>
              )}
              <button
                className="btn btn-secondary"
                onClick={() => setAutoSellModal(prev => ({ ...prev, isOpen: false }))}
                disabled={autoSellModal.loading}
              >
                No
              </button>
              <button
                className="btn btn-primary"
                style={{ backgroundColor: '#22c55e', borderColor: '#22c55e', color: '#fff', fontWeight: '600' }}
                onClick={() => handleConfirmAutoSell(true)}
                disabled={autoSellModal.loading}
              >
                {autoSellModal.loading ? 'Enabling...' : 'Yes'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Auto-Buy Confirmation Modal */}
      {autoBuyModal.isOpen && (
        <div className="modal-overlay" onClick={() => setAutoBuyModal(prev => ({ ...prev, isOpen: false }))}>
          <div className="modal-content auto-buy-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '480px' }}>
            <div className="modal-header">
              <h3 style={{ display: 'flex', alignItems: 'center', gap: '8px', margin: 0 }}>
                <span>🚀</span> Trigger Auto-Buy ({autoBuyModal.symbol})
              </h3>
              <button className="modal-close" onClick={() => setAutoBuyModal(prev => ({ ...prev, isOpen: false }))}>×</button>
            </div>
            <div style={{ padding: '20px 24px' }}>
              <p style={{ fontSize: '14px', lineHeight: '1.6', margin: '0 0 16px', color: 'var(--text-primary, #e2e8f0)' }}>
                You are about to enable an automatic purchase of <strong>{autoBuyModal.symbol} with {autoBuyModal.quoteCurrency}</strong> when the price surges more than <strong>{autoBuyModal.volatilityPct}%</strong> within the past <strong>{autoBuyModal.volatilityHours} hour(s)</strong> (configured in Settings).
              </p>

              {/* Immediate insufficient balance banner */}
              {!autoBuyModal.loadingBalance && autoBuyModal.availableBalance < 1.00 && (
                <div style={{
                  padding: '12px 14px',
                  borderRadius: '6px',
                  backgroundColor: 'rgba(239, 68, 68, 0.18)',
                  color: '#f87171',
                  fontSize: '13px',
                  fontWeight: '600',
                  marginBottom: '16px',
                  border: '1px solid rgba(239, 68, 68, 0.4)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px'
                }}>
                  <span>⚠️</span>
                  <span>Not enough {autoBuyModal.quoteCurrency} to place this order (minimum $1.00 required).</span>
                </div>
              )}

              {/* Live Balance Summary */}
              <div style={{
                padding: '12px 14px',
                borderRadius: '8px',
                backgroundColor: 'rgba(15, 23, 42, 0.6)',
                border: '1px solid var(--border-color, rgba(255, 255, 255, 0.1))',
                marginBottom: '16px',
                fontSize: '13px'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                  <span style={{ color: 'var(--text-secondary, #94a3b8)' }}>Binance.US Free Balance:</span>
                  <strong style={{ color: '#38bdf8' }}>${autoBuyModal.freeBalance.toFixed(2)} {autoBuyModal.quoteCurrency}</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                  <span style={{ color: 'var(--text-secondary, #94a3b8)' }}>Reserved for other Auto-Buys:</span>
                  <span style={{ color: autoBuyModal.reservedBalance > 0 ? '#f59e0b' : '#94a3b8' }}>
                    ${autoBuyModal.reservedBalance.toFixed(2)} {autoBuyModal.quoteCurrency}
                  </span>
                </div>
                <div style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  paddingTop: '6px',
                  borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                  fontWeight: '600'
                }}>
                  <span style={{ color: 'var(--text-primary, #fff)' }}>Available to Allocate:</span>
                  <span style={{ color: autoBuyModal.availableBalance >= 1.00 ? '#4ade80' : '#f87171' }}>
                    ${autoBuyModal.availableBalance.toFixed(2)} {autoBuyModal.quoteCurrency}
                  </span>
                </div>
              </div>

              {/* Allocation Input */}
              <div style={{ marginBottom: '16px' }}>
                <label style={{ display: 'block', fontSize: '13px', fontWeight: '500', marginBottom: '6px', color: 'var(--text-primary, #e2e8f0)' }}>
                  Allocation Amount ({autoBuyModal.quoteCurrency}) <span style={{ color: '#94a3b8', fontSize: '11px' }}>(Min $1.00)</span>
                </label>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <div style={{ position: 'relative', flex: 1 }}>
                    <span style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: '#94a3b8', fontSize: '14px' }}>$</span>
                    <input
                      type="number"
                      min="1"
                      step="any"
                      placeholder="0.00"
                      value={autoBuyModal.amount}
                      onChange={(e) => setAutoBuyModal(prev => ({ ...prev, amount: e.target.value, error: '' }))}
                      disabled={autoBuyModal.availableBalance < 1.00 || autoBuyModal.loadingBalance}
                      style={{
                        width: '100%',
                        padding: '10px 12px 10px 26px',
                        borderRadius: '6px',
                        border: '1px solid var(--border-color, #334155)',
                        backgroundColor: autoBuyModal.availableBalance < 1.00 ? 'rgba(0, 0, 0, 0.4)' : 'rgba(0, 0, 0, 0.25)',
                        color: autoBuyModal.availableBalance < 1.00 ? '#64748b' : 'var(--text-primary, #fff)',
                        fontSize: '14px',
                        cursor: autoBuyModal.availableBalance < 1.00 ? 'not-allowed' : 'text'
                      }}
                    />
                  </div>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => setAutoBuyModal(prev => ({ ...prev, amount: prev.availableBalance > 0 ? String(prev.availableBalance) : '', error: '' }))}
                    disabled={autoBuyModal.availableBalance < 1.00 || autoBuyModal.loadingBalance}
                    style={{ padding: '0 16px', fontWeight: '600', fontSize: '12px' }}
                  >
                    MAX
                  </button>
                </div>
              </div>

              {autoBuyModal.activeCommitments.length > 0 && (
                <div style={{ marginBottom: '16px', fontSize: '12px', color: '#94a3b8' }}>
                  <span>Active commitments: </span>
                  {autoBuyModal.activeCommitments.map((c, i) => (
                    <span key={i} style={{ color: c.is_current ? '#38bdf8' : '#e2e8f0', marginRight: '6px' }}>
                      {c.symbol}: ${c.amount.toFixed(2)}{c.is_current ? ' (current)' : ''}{i < autoBuyModal.activeCommitments.length - 1 ? ',' : ''}
                    </span>
                  ))}
                </div>
              )}

              {autoBuyModal.coin?.auto_buy_enabled && (
                <div style={{
                  padding: '10px 14px',
                  borderRadius: '6px',
                  backgroundColor: 'rgba(34, 197, 94, 0.12)',
                  color: '#4ade80',
                  fontSize: '13px',
                  marginBottom: '16px',
                  border: '1px solid rgba(34, 197, 94, 0.3)'
                }}>
                  🚀 Auto-Buy is currently <strong>ACTIVE</strong> for {autoBuyModal.symbol} (${parseFloat(autoBuyModal.coin.auto_buy_amount || 0).toFixed(2)} {autoBuyModal.quoteCurrency}).
                </div>
              )}

              {autoBuyModal.error && (
                <div style={{
                  padding: '10px 14px',
                  borderRadius: '6px',
                  backgroundColor: 'rgba(239, 68, 68, 0.15)',
                  color: '#f87171',
                  fontSize: '13px',
                  marginBottom: '16px',
                  border: '1px solid rgba(239, 68, 68, 0.3)'
                }}>
                  {autoBuyModal.error}
                </div>
              )}
            </div>
            <div className="modal-actions" style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', padding: '16px 24px', borderTop: '1px solid var(--border-color, rgba(255,255,255,0.08))' }}>
              {autoBuyModal.coin?.auto_buy_enabled && (
                <button
                  className="btn btn-secondary"
                  style={{ marginRight: 'auto', color: '#f87171', borderColor: 'rgba(239,68,68,0.4)' }}
                  onClick={() => handleConfirmAutoBuy(false)}
                  disabled={autoBuyModal.loading}
                >
                  Disable Auto-Buy
                </button>
              )}
              <button
                className="btn btn-secondary"
                onClick={() => setAutoBuyModal(prev => ({ ...prev, isOpen: false }))}
                disabled={autoBuyModal.loading}
              >
                Cancel
              </button>
              <button
                className="btn btn-primary"
                style={{ backgroundColor: '#22c55e', borderColor: '#22c55e', color: '#fff', fontWeight: '600' }}
                onClick={() => handleConfirmAutoBuy(true)}
                disabled={autoBuyModal.loading || autoBuyModal.availableBalance < 1.00 || !autoBuyModal.amount || parseFloat(autoBuyModal.amount) < 1.00}
              >
                {autoBuyModal.loading ? 'Enabling...' : 'Enable Auto-Buy'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Coin Performance Visibility Filter Modal */}
      {showPerformanceCoinModal && (
        <div className="modal-overlay" onClick={() => setShowPerformanceCoinModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '520px', width: '90%' }}>
            <div className="modal-header">
              <h3 style={{ display: 'flex', alignItems: 'center', gap: '8px', margin: 0 }}>
                <span>✏️</span> Customize Coin Performance
              </h3>
              <button className="modal-close" onClick={() => setShowPerformanceCoinModal(false)}>×</button>
            </div>

            <div style={{ padding: '16px 20px' }}>
              <p style={{ margin: '0 0 12px 0', fontSize: '13px', color: 'var(--text-secondary, #94a3b8)', lineHeight: 1.5 }}>
                Select which assets from your <strong>Portfolio</strong> and <strong>Watchlist</strong> appear in the Coin Performance panel:
              </p>

              {/* Search & Bulk Select Controls */}
              <div style={{ display: 'flex', gap: '8px', marginBottom: '14px', alignItems: 'center' }}>
                <input
                  type="text"
                  placeholder="Search coins (e.g. BTC, ETH)..."
                  value={performanceCoinSearch}
                  onChange={(e) => setPerformanceCoinSearch(e.target.value)}
                  style={{
                    flex: 1,
                    padding: '8px 12px',
                    borderRadius: '6px',
                    border: '1px solid var(--border-color, #334155)',
                    backgroundColor: 'var(--input-bg, #1e293b)',
                    color: 'var(--text-primary, #fff)',
                    fontSize: '13px'
                  }}
                />
                <button
                  type="button"
                  className="btn btn-secondary"
                  style={{ padding: '6px 10px', fontSize: '12px', whiteSpace: 'nowrap' }}
                  onClick={() => {
                    setPerformanceCoinDraft([]);
                  }}
                >
                  Select All
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  style={{ padding: '6px 10px', fontSize: '12px', whiteSpace: 'nowrap' }}
                  onClick={() => {
                    const allSyms = Array.from(new Set([
                      ...(portfolio || []).map(c => c.symbol),
                      ...(watchlist || []).map(w => w.symbol)
                    ])).filter(Boolean);
                    setPerformanceCoinDraft(allSyms);
                  }}
                >
                  Deselect All
                </button>
              </div>

              {/* Coin Checkbox List */}
              <div style={{
                maxHeight: '280px',
                overflowY: 'auto',
                border: '1px solid var(--border-color, #334155)',
                borderRadius: '8px',
                padding: '8px',
                backgroundColor: 'rgba(0, 0, 0, 0.2)',
                display: 'flex',
                flexDirection: 'column',
                gap: '4px'
              }}>
                {(() => {
                  const combined = [];
                  const seen = new Set();

                  (portfolio || []).forEach(c => {
                    if (c.symbol && !seen.has(c.symbol.toUpperCase())) {
                      seen.add(c.symbol.toUpperCase());
                      combined.push({ symbol: c.symbol.toUpperCase(), source: 'Portfolio' });
                    }
                  });

                  (watchlist || []).forEach(w => {
                    if (w.symbol && !seen.has(w.symbol.toUpperCase())) {
                      seen.add(w.symbol.toUpperCase());
                      combined.push({ symbol: w.symbol.toUpperCase(), source: 'Watchlist' });
                    }
                  });

                  combined.sort((a, b) => a.symbol.localeCompare(b.symbol));

                  const filtered = combined.filter(c =>
                    !performanceCoinSearch.trim() ||
                    c.symbol.toLowerCase().includes(performanceCoinSearch.toLowerCase().trim())
                  );

                  if (filtered.length === 0) {
                    return (
                      <div style={{ textAlign: 'center', padding: '24px', color: '#94a3b8', fontSize: '13px' }}>
                        No matching coins found.
                      </div>
                    );
                  }

                  return filtered.map(({ symbol, source }) => {
                    const isVisible = !performanceCoinDraft.includes(symbol);
                    return (
                      <label
                        key={symbol}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          padding: '8px 12px',
                          borderRadius: '6px',
                          backgroundColor: isVisible ? 'rgba(56, 189, 248, 0.08)' : 'transparent',
                          cursor: 'pointer',
                          transition: 'background-color 0.15s ease'
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <input
                            type="checkbox"
                            checked={isVisible}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setPerformanceCoinDraft(prev => prev.filter(s => s !== symbol));
                              } else {
                                setPerformanceCoinDraft(prev => [...prev, symbol]);
                              }
                            }}
                            style={{ cursor: 'pointer', width: '16px', height: '16px' }}
                          />
                          <CryptoIcon symbol={symbol} size={20} />
                          <span style={{ fontWeight: '600', fontSize: '14px', color: 'var(--text-primary, #fff)' }}>
                            {symbol}
                          </span>
                        </div>
                        <span style={{
                          fontSize: '11px',
                          padding: '2px 6px',
                          borderRadius: '4px',
                          backgroundColor: source === 'Portfolio' ? 'rgba(34, 197, 94, 0.15)' : 'rgba(148, 163, 184, 0.15)',
                          color: source === 'Portfolio' ? '#4ade80' : '#94a3b8',
                          fontWeight: '500'
                        }}>
                          {source}
                        </span>
                      </label>
                    );
                  });
                })()}
              </div>
            </div>

            <div className="modal-actions" style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', padding: '14px 20px', borderTop: '1px solid var(--border-color, rgba(255,255,255,0.08))' }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setShowPerformanceCoinModal(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                style={{ backgroundColor: '#0284c7', borderColor: '#0284c7', color: '#fff', fontWeight: '600' }}
                onClick={handleSavePerformanceCoinModal}
              >
                Save Selection
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Recent Order History Settings Modal */}
      {showRecentTradesModal && (
        <div className="modal-overlay" onClick={() => setShowRecentTradesModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '500px', width: '90%' }}>
            <div className="modal-header">
              <h3 style={{ display: 'flex', alignItems: 'center', gap: '8px', margin: 0 }}>
                <span>✏️</span> Customize Recent Order History
              </h3>
              <button className="modal-close" onClick={() => setShowRecentTradesModal(false)}>×</button>
            </div>

            <div style={{ padding: '18px 20px', display: 'flex', flexDirection: 'column', gap: '18px' }}>
              {/* Section 1: Maximum Orders to Display */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                  <label style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-primary, #fff)' }}>
                    Max Orders to Display
                  </label>
                  <span style={{
                    fontSize: '13px',
                    fontWeight: '700',
                    color: '#38bdf8',
                    background: 'rgba(56, 189, 248, 0.15)',
                    padding: '2px 8px',
                    borderRadius: '6px',
                    border: '1px solid rgba(56, 189, 248, 0.3)'
                  }}>
                    {recentTradesDraftMaxOrders === 0 ? '0 (Hidden)' : `${recentTradesDraftMaxOrders} orders`}
                  </span>
                </div>
                <p style={{ margin: '0 0 10px 0', fontSize: '12px', color: 'var(--text-secondary, #94a3b8)', lineHeight: 1.4 }}>
                  Select how many recent trades to display in the table (0 to 20):
                </p>

                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <input
                    type="range"
                    min="0"
                    max="20"
                    step="1"
                    value={recentTradesDraftMaxOrders}
                    onChange={(e) => setRecentTradesDraftMaxOrders(parseInt(e.target.value, 10) || 0)}
                    style={{
                      flex: 1,
                      accentColor: '#0284c7',
                      cursor: 'pointer'
                    }}
                  />
                  <input
                    type="number"
                    min="0"
                    max="20"
                    value={recentTradesDraftMaxOrders}
                    onChange={(e) => {
                      const val = parseInt(e.target.value, 10);
                      if (!isNaN(val)) {
                        setRecentTradesDraftMaxOrders(Math.max(0, Math.min(20, val)));
                      } else {
                        setRecentTradesDraftMaxOrders(0);
                      }
                    }}
                    style={{
                      width: '56px',
                      padding: '6px 8px',
                      textAlign: 'center',
                      borderRadius: '6px',
                      border: '1px solid var(--border-color, #334155)',
                      backgroundColor: 'var(--input-bg, #1e293b)',
                      color: 'var(--text-primary, #fff)',
                      fontSize: '13px',
                      fontWeight: '600'
                    }}
                  />
                </div>

                {/* Quick select pills */}
                <div style={{ display: 'flex', gap: '6px', marginTop: '8px' }}>
                  {[0, 5, 10, 15, 20].map(val => (
                    <button
                      key={val}
                      type="button"
                      onClick={() => setRecentTradesDraftMaxOrders(val)}
                      style={{
                        padding: '3px 8px',
                        fontSize: '11px',
                        fontWeight: '600',
                        borderRadius: '4px',
                        cursor: 'pointer',
                        background: recentTradesDraftMaxOrders === val ? '#0284c7' : 'rgba(255,255,255,0.06)',
                        color: recentTradesDraftMaxOrders === val ? '#ffffff' : 'var(--text-secondary, #94a3b8)',
                        border: `1px solid ${recentTradesDraftMaxOrders === val ? '#38bdf8' : 'var(--border-color, rgba(255,255,255,0.1))'}`,
                        transition: 'all 0.15s ease'
                      }}
                    >
                      {val === 0 ? 'None (0)' : val}
                    </button>
                  ))}
                </div>
              </div>

              {/* Section 2: Order Status Filters */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                  <label style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-primary, #fff)' }}>
                    Order Statuses to Show
                  </label>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      style={{ padding: '2px 8px', fontSize: '11px' }}
                      onClick={() => setRecentTradesDraftStatuses(['FILLED', 'NEW', 'CANCELED', 'PARTIALLY_FILLED'])}
                    >
                      Select All
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      style={{ padding: '2px 8px', fontSize: '11px' }}
                      onClick={() => setRecentTradesDraftStatuses([])}
                    >
                      Deselect All
                    </button>
                  </div>
                </div>
                <p style={{ margin: '0 0 10px 0', fontSize: '12px', color: 'var(--text-secondary, #94a3b8)', lineHeight: 1.4 }}>
                  Choose which order statuses appear in your recent history feed:
                </p>

                <div style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '6px',
                  border: '1px solid var(--border-color, #334155)',
                  borderRadius: '8px',
                  padding: '10px',
                  backgroundColor: 'rgba(0, 0, 0, 0.2)'
                }}>
                  {[
                    { id: 'FILLED', label: 'Filled Orders', desc: 'Completed & fully executed buy/sell trades', color: '#4ade80', bg: 'rgba(34, 197, 94, 0.15)' },
                    { id: 'NEW', label: 'New / Open Orders', desc: 'Active pending limit or stop orders on Binance', color: '#38bdf8', bg: 'rgba(56, 189, 248, 0.15)' },
                    { id: 'CANCELED', label: 'Canceled Orders', desc: 'Orders that were cancelled before executing', color: '#94a3b8', bg: 'rgba(148, 163, 184, 0.15)' },
                    { id: 'PARTIALLY_FILLED', label: 'Partially Filled Orders', desc: 'Orders partially executed but not yet completed', color: '#fbbf24', bg: 'rgba(245, 158, 11, 0.15)' }
                  ].map(statusItem => {
                    const isChecked = recentTradesDraftStatuses.includes(statusItem.id);
                    return (
                      <label
                        key={statusItem.id}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          padding: '8px 10px',
                          borderRadius: '6px',
                          backgroundColor: isChecked ? 'rgba(56, 189, 248, 0.08)' : 'transparent',
                          cursor: 'pointer',
                          transition: 'background-color 0.15s ease'
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setRecentTradesDraftStatuses(prev => [...prev, statusItem.id]);
                              } else {
                                setRecentTradesDraftStatuses(prev => prev.filter(id => id !== statusItem.id));
                              }
                            }}
                            style={{ cursor: 'pointer', width: '16px', height: '16px' }}
                          />
                          <div>
                            <div style={{ fontWeight: '600', fontSize: '13px', color: 'var(--text-primary, #fff)' }}>
                              {statusItem.label}
                            </div>
                            <div style={{ fontSize: '11px', color: 'var(--text-secondary, #94a3b8)' }}>
                              {statusItem.desc}
                            </div>
                          </div>
                        </div>
                        <span style={{
                          fontSize: '10px',
                          fontWeight: '700',
                          padding: '2px 6px',
                          borderRadius: '4px',
                          backgroundColor: statusItem.bg,
                          color: statusItem.color
                        }}>
                          {statusItem.id}
                        </span>
                      </label>
                    );
                  })}
                </div>
              </div>
            </div>

            <div className="modal-actions" style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', padding: '14px 20px', borderTop: '1px solid var(--border-color, rgba(255,255,255,0.08))' }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setShowRecentTradesModal(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                style={{ backgroundColor: '#0284c7', borderColor: '#0284c7', color: '#fff', fontWeight: '600' }}
                onClick={handleSaveRecentTradesModal}
              >
                Save Selection
              </button>
            </div>
          </div>
        </div>
      )}

      {showTopMoversModal && (
        <div className="modal-overlay" onClick={() => setShowTopMoversModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '460px', width: '90%' }}>
            <div className="modal-header">
              <h3 style={{ display: 'flex', alignItems: 'center', gap: '8px', margin: 0 }}>
                <span>✏️</span> Customize Top Gainers & Losers
              </h3>
              <button className="modal-close" onClick={() => setShowTopMoversModal(false)}>×</button>
            </div>

            <div style={{ padding: '18px 20px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                <label style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-primary, #fff)' }}>
                  Coins Per Side
                </label>
                <span style={{
                  fontSize: '13px',
                  fontWeight: '700',
                  color: '#38bdf8',
                  background: 'rgba(56, 189, 248, 0.15)',
                  padding: '2px 8px',
                  borderRadius: '6px',
                  border: '1px solid rgba(56, 189, 248, 0.3)'
                }}>
                  Top {topMoversDraftCount} each
                </span>
              </div>
              <p style={{ margin: '0 0 6px 0', fontSize: '12px', color: 'var(--text-secondary, #94a3b8)', lineHeight: 1.4 }}>
                Choose how many gainers and losers to display across all Binance.US coins (3 to 25 per side):
              </p>

              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <input
                  type="range"
                  min="3"
                  max="25"
                  step="1"
                  value={topMoversDraftCount}
                  onChange={(e) => setTopMoversDraftCount(parseInt(e.target.value, 10) || 10)}
                  className="slim-range-slider"
                  style={{ flex: 1, accentColor: '#0284c7', cursor: 'pointer' }}
                />
                <input
                  type="number"
                  min="3"
                  max="25"
                  value={topMoversDraftCount}
                  onChange={(e) => {
                    const val = parseInt(e.target.value, 10);
                    setTopMoversDraftCount(isNaN(val) ? 10 : Math.max(3, Math.min(25, val)));
                  }}
                  style={{
                    width: '56px',
                    padding: '6px 8px',
                    textAlign: 'center',
                    borderRadius: '6px',
                    border: '1px solid var(--border-color, #334155)',
                    backgroundColor: 'var(--input-bg, #1e293b)',
                    color: 'var(--text-primary, #fff)',
                    fontSize: '13px',
                    fontWeight: '600'
                  }}
                />
              </div>

              <div style={{ display: 'flex', gap: '6px', marginTop: '4px' }}>
                {[3, 5, 10, 15, 25].map(val => (
                  <button
                    key={val}
                    type="button"
                    onClick={() => setTopMoversDraftCount(val)}
                    style={{
                      padding: '3px 8px',
                      fontSize: '11px',
                      fontWeight: '600',
                      borderRadius: '4px',
                      cursor: 'pointer',
                      background: topMoversDraftCount === val ? '#0284c7' : 'rgba(255,255,255,0.06)',
                      color: topMoversDraftCount === val ? '#ffffff' : 'var(--text-secondary, #94a3b8)',
                      border: `1px solid ${topMoversDraftCount === val ? '#38bdf8' : 'var(--border-color, rgba(255,255,255,0.1))'}`,
                      transition: 'all 0.15s ease'
                    }}
                  >
                    {val}
                  </button>
                ))}
              </div>

              <p style={{ margin: '4px 0 0 0', fontSize: '11px', color: 'var(--text-secondary, #94a3b8)' }}>
                Coins you currently hold in your Portfolio are highlighted with a ★ badge.
              </p>
            </div>

            <div className="modal-actions" style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', padding: '14px 20px', borderTop: '1px solid var(--border-color, rgba(255,255,255,0.08))' }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setShowTopMoversModal(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                style={{ backgroundColor: '#0284c7', borderColor: '#0284c7', color: '#fff', fontWeight: '600' }}
                onClick={handleSaveTopMoversModal}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Table Column Customization Modal */}
      <TableColumnModal
        isOpen={columnModal.isOpen}
        onClose={() => setColumnModal(prev => ({ ...prev, isOpen: false }))}
        tableType={columnModal.tableType}
        columnDefinitions={columnModal.tableType === 'portfolio' ? PORTFOLIO_COLUMN_DEFINITIONS : WATCHLIST_COLUMN_DEFINITIONS}
        visibleColumns={columnModal.tableType === 'portfolio' ? portfolioVisibleCols : watchlistVisibleCols}
        onSave={columnModal.tableType === 'portfolio' ? handleSavePortfolioColumns : handleSaveWatchlistColumns}
        onReset={columnModal.tableType === 'portfolio' ? handleResetPortfolioColumns : handleResetWatchlistColumns}
      />

      {/* Cancel Order Confirmation Modal */}
      <CancelOrderConfirmModal
        isOpen={cancelModalState.isOpen}
        onClose={() => setCancelModalState({ isOpen: false, coin: null, order: null, loading: false, error: null })}
        order={cancelModalState.order}
        coin={cancelModalState.coin}
        onConfirm={handleConfirmCancelOrder}
        loading={cancelModalState.loading}
        error={cancelModalState.error}
      />

      {/* Floating Cancel Orders Context Menu */}
      {cancelContextMenu.isOpen && cancelContextMenu.coin && (
        <div
          className="cancel-orders-context-menu"
          style={{
            position: 'absolute',
            left: `${cancelContextMenu.x}px`,
            top: `${cancelContextMenu.y}px`,
            zIndex: 2000
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="cancel-context-header">
            <span>Cancel Order ({cancelContextMenu.coin.symbol})</span>
            <button
              type="button"
              className="cancel-context-close"
              onClick={() => setCancelContextMenu({ isOpen: false, coin: null, x: 0, y: 0, orders: [] })}
            >
              ✕
            </button>
          </div>
          <div className="cancel-context-list">
            {cancelContextMenu.orders.map((ord, idx) => {
              const isAutoBuy = !!ord.isAutoBuy || ord.trigger_type === 'auto_buy';
              const isAutoSell = !!ord.isAutoSell || ord.trigger_type === 'auto_sell';
              const side = isAutoBuy ? 'AUTO-BUY' : isAutoSell ? 'AUTO-SELL' : (ord.side || 'ORDER').toUpperCase();
              const type = isAutoBuy ? 'Auto-Buy Surge Trigger' : isAutoSell ? 'Auto-Sell Drop Trigger' : (ord.type || ord.order_type || 'LIMIT').replace(/_/g, ' ');
              const qty = ord.quantity || ord.origQty;
              const price = ord.price || ord.trigger_price;
              return (
                <button
                  key={ord.order_id || ord.id || idx}
                  type="button"
                  className="cancel-context-item"
                  onClick={() => handleSelectOrderFromMenu(ord, cancelContextMenu.coin)}
                >
                  <span className={`cancel-item-badge badge-${side.toLowerCase().replace(/_/g, '-')}`}>{side}</span>
                  <div className="cancel-item-details">
                    <div className="cancel-item-title">{type} ({ord.symbol || cancelContextMenu.coin.symbol})</div>
                    <div className="cancel-item-sub">
                      {ord.details || (
                        <>
                          {qty && `${qty} `}
                          {price && `@ $${Number(price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 6 })}`}
                        </>
                      )}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

    </div>
  );
}

export default Dashboard;
