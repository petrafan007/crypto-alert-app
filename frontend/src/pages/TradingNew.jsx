import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import OrderFeedbackModal from '../components/OrderFeedbackModal';
import TwoFactorModal from '../components/TwoFactorModal';
import ConvertDustModal from '../components/ConvertDustModal';
import CancelOrderModal from '../components/CancelOrderModal';
import TradingChart from '../components/TradingChart';
import TradePermissionModal from '../components/TradePermissionModal';
import ApiKeyRequiredModal from '../components/ApiKeyRequiredModal';
import './Trading.css';
import { useLocation, useNavigate } from 'react-router-dom';

const TradingNew = () => {
  console.log('TradingNew component rendering...');
  const location = useLocation();
  const navigate = useNavigate();

  // Trading Settings
  const [settings, setSettings] = useState({
    test_mode_enabled: true,
    max_order_size_usd: 1000,
    daily_loss_limit_usd: 500,
    require_2fa: false
  });

  // Order Form State
  const [orderForm, setOrderForm] = useState({
    symbol: 'BTCUSDT',
    side: 'BUY',
    type: 'MARKET',
    quantity: '',
    // derived quote amount stored separately
    price: '',
    stopPrice: '',
    stopLimitPrice: '', // For OCO orders
    stopLimitTimeInForce: 'GTC', // For OCO orders
    timeInForce: 'GTC' // GTC, IOC, FOK
  });
  const [quoteQuantity, setQuoteQuantity] = useState('');
  const lastEditedRef = useRef(null);

  // UI State
  const [orders, setOrders] = useState([]);
  const [portfolio, setPortfolio] = useState([]);
  const [testOrders, setTestOrders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('order'); // 'order', 'history', 'portfolio'
  const [showCanceledOrders, setShowCanceledOrders] = useState(false);

  // Modal state for feedback
  const [feedbackModal, setFeedbackModal] = useState({
    isVisible: false,
    message: '',
    type: 'success' // 'success', 'error', 'warning'
  });

  // 2FA Modal state
  const [twoFactorModal, setTwoFactorModal] = useState({
    isVisible: false,
    orderData: null
  });

  // New state for Binance.US features
  const [currentPrices, setCurrentPrices] = useState({ base: 0, quote: 0 });
  const [balances, setBalances] = useState({
    base: 0,
    base_locked: 0,
    base_total: 0,
    quote: 0,
    quote_locked: 0,
    quote_total: 0
  });
  const [balancePercentage, setBalancePercentage] = useState(0);
  const [estimatedFee, setEstimatedFee] = useState({ amount: 0, usd: 0, asset: '' });
  const [openOrders, setOpenOrders] = useState([]);
  const [cancelModal, setCancelModal] = useState({
    isVisible: false,
    order: null,
    error: '',
    loading: false,
  });

  // Order types fetched from API
  const [orderTypes, setOrderTypes] = useState([]);

  // Permission Check States
  const [showApiKeyModal, setShowApiKeyModal] = useState(false);
  const [showPermissionModal, setShowPermissionModal] = useState(false);

  // Convert Dust modal state
  const [dustModal, setDustModal] = useState({ isVisible: false });

  // Properly extract base and quote assets (matches backend logic)
  // For USDTUSD: base=USDT, quote=USD
  // For BTCUSD: base=BTC, quote=USD
  // For BTCUSDT: base=BTC, quote=USDT
  const baseAsset = orderForm.symbol.endsWith('USD') && !orderForm.symbol.endsWith('USDT')
    ? orderForm.symbol.slice(0, -3)  // Remove 'USD'
    : orderForm.symbol.endsWith('USDT')
      ? orderForm.symbol.slice(0, -4)  // Remove 'USDT'
      : orderForm.symbol;
  const quoteAsset = orderForm.symbol.endsWith('USD') && !orderForm.symbol.endsWith('USDT') ? 'USD' : 'USDT';

  const determinePriceForCalculations = (formState = orderForm) => {
    const marketPrice = parseFloat(currentPrices.base) || 0;
    const limitPrice = parseFloat(formState.price);
    const stopPrice = parseFloat(formState.stopPrice);
    const stopLimitPrice = parseFloat(formState.stopLimitPrice);

    switch (formState.type) {
      case 'LIMIT':
      case 'LIMIT_MAKER':
        return limitPrice > 0 ? limitPrice : marketPrice;
      case 'STOP_LOSS':
      case 'TAKE_PROFIT':
        return stopPrice > 0 ? stopPrice : marketPrice;
      case 'STOP_LOSS_LIMIT':
      case 'TAKE_PROFIT_LIMIT':
        if (limitPrice > 0) return limitPrice;
        if (stopLimitPrice > 0) return stopLimitPrice;
        if (stopPrice > 0) return stopPrice;
        return marketPrice;
      case 'OCO':
        if (formState.side === 'BUY') {
          // For BUY OCO, we MUST be able to afford the more expensive order
          return Math.max(limitPrice || 0, stopLimitPrice || 0, stopPrice || 0, marketPrice);
        }
        // For SELL OCO, funds are in base asset, so choosing limitPrice is fine for display
        if (limitPrice > 0) return limitPrice;
        if (stopLimitPrice > 0) return stopLimitPrice;
        if (stopPrice > 0) return stopPrice;
        return marketPrice;
      default:
        return marketPrice;
    }
  };

  const formatNumberString = (num, decimals = 2) => {
    if (!Number.isFinite(num)) return '';
    const fixed = num.toFixed(decimals);
    return fixed
      .replace(/(\.\d*?[1-9])0+$/g, '$1')
      .replace(/\.0+$/g, '')
      .replace(/\.$/, '');
  };

  const handleBaseQuantityChange = (value) => {
    lastEditedRef.current = 'base';
    setOrderForm((prev) => ({ ...prev, quantity: value }));

    if (!value) {
      setQuoteQuantity('');
      return;
    }

    const numeric = parseFloat(value);
    if (Number.isNaN(numeric)) {
      setQuoteQuantity('');
      return;
    }

    const price = determinePriceForCalculations();
    if (price > 0) {
      const total = numeric * price;
      setQuoteQuantity(Number.isFinite(total) ? formatNumberString(total, 2) : '');
    } else {
      setQuoteQuantity('');
    }
  };

  const handleQuoteQuantityChange = (value) => {
    lastEditedRef.current = 'quote';
    setQuoteQuantity(value);

    if (!value) {
      setOrderForm((prev) => ({ ...prev, quantity: '' }));
      return;
    }

    const numeric = parseFloat(value);
    if (Number.isNaN(numeric)) {
      return;
    }

    const price = determinePriceForCalculations();
    if (price > 0) {
      const baseAmount = numeric / price;
      setOrderForm((prev) => ({
        ...prev,
        quantity: Number.isFinite(baseAmount)
          ? (baseAmount > 0 ? formatNumberString(baseAmount, 8) : '0')
          : prev.quantity
      }));
    }
  };

  const renderTimeInForceSelector = () => (
    <div className="form-group">
      <label>Time in Force</label>
      <div className="time-in-force-selector">
        <label className="radio-option">
          <input
            type="radio"
            name="timeInForce"
            value="GTC"
            checked={orderForm.timeInForce === 'GTC'}
            onChange={(e) => setOrderForm({ ...orderForm, timeInForce: e.target.value })}
          />
          <span>GTC - Good Till Cancel</span>
        </label>
        <label className="radio-option">
          <input
            type="radio"
            name="timeInForce"
            value="IOC"
            checked={orderForm.timeInForce === 'IOC'}
            onChange={(e) => setOrderForm({ ...orderForm, timeInForce: e.target.value })}
          />
          <span>IOC - Immediate or Cancel</span>
        </label>
        <label className="radio-option">
          <input
            type="radio"
            name="timeInForce"
            value="FOK"
            checked={orderForm.timeInForce === 'FOK'}
            onChange={(e) => setOrderForm({ ...orderForm, timeInForce: e.target.value })}
          />
          <span>FOK - Fill or Kill</span>
        </label>
      </div>
      <small className="form-help">
        {orderForm.timeInForce === 'GTC' && 'Order remains active until filled or cancelled'}
        {orderForm.timeInForce === 'IOC' && 'Immediately execute as much as possible, cancel remainder'}
        {orderForm.timeInForce === 'FOK' && 'Must fill entire order immediately or cancel'}
      </small>
    </div>
  );

  const renderOrderTypeFields = () => {
    const cells = [];

    const placeholderCell = (key) => (
      <div className="order-grid-item order-grid-item--placeholder" key={key} aria-hidden="true" />
    );

    const limitPriceCell = (key, helpText) => (
      <div className="order-grid-item" key={`limit-${key}`}>
        <div className="form-group">
          <label htmlFor="price">Limit Price ({quoteAsset})</label>
          <input
            id="price"
            type="number"
            step="0.01"
            value={orderForm.price}
            onChange={(e) => setOrderForm({ ...orderForm, price: e.target.value })}
            placeholder="Enter limit price"
            className="form-control"
            required
            autoComplete="off"
          />
          {helpText && <small className="form-help">{helpText}</small>}
        </div>
      </div>
    );

    const stopPriceCell = (key, helpText) => (
      <div className="order-grid-item" key={`stop-${key}`}>
        <div className="form-group">
          <label htmlFor="stopPrice">Stop Price ({quoteAsset})</label>
          <input
            id="stopPrice"
            type="number"
            step="0.01"
            value={orderForm.stopPrice}
            onChange={(e) => setOrderForm({ ...orderForm, stopPrice: e.target.value })}
            placeholder="Enter stop price"
            className="form-control"
            required
            autoComplete="off"
          />
          {helpText && <small className="form-help">{helpText}</small>}
        </div>
      </div>
    );

    const stopLimitPriceCell = (key) => (
      <div className="order-grid-item" key={`stop-limit-${key}`}>
        <div className="form-group">
          <label htmlFor="stopLimitPrice">Stop Limit Price ({quoteAsset})</label>
          <input
            id="stopLimitPrice"
            type="number"
            step="0.01"
            value={orderForm.stopLimitPrice}
            onChange={(e) => setOrderForm({ ...orderForm, stopLimitPrice: e.target.value })}
            placeholder="Stop loss execution price"
            className="form-control"
            required
            autoComplete="off"
          />
          <small className="form-help">
            Price at which the stop-loss limit order will be placed
          </small>
        </div>
      </div>
    );

    switch (orderForm.type) {
      case 'LIMIT':
        cells.push(
          limitPriceCell('main'),
          <div className="order-grid-item" key="tif-limit">
            {renderTimeInForceSelector()}
          </div>
        );
        break;
      case 'MARKET':
        break;
      case 'STOP_LOSS':
      case 'TAKE_PROFIT':
        cells.push(
          stopPriceCell('single'),
          placeholderCell('stop-placeholder')
        );
        break;
      case 'STOP_LOSS_LIMIT':
      case 'TAKE_PROFIT_LIMIT':
        cells.push(
          limitPriceCell('combo'),
          stopPriceCell('combo'),
          <div className="order-grid-item" key="tif-stoplimit">
            {renderTimeInForceSelector()}
          </div>,
          placeholderCell('stoplimit-placeholder')
        );
        break;
      case 'LIMIT_MAKER':
        cells.push(
          limitPriceCell('maker'),
          <div className="order-grid-item" key="tif-maker">
            {renderTimeInForceSelector()}
          </div>
        );
        break;
      case 'OCO':
        cells.push(
          limitPriceCell(
            'oco',
            orderForm.side === 'SELL'
              ? 'Must be greater than current market price'
              : 'Must be less than current market price'
          ),
          stopPriceCell(
            'oco',
            orderForm.side === 'SELL'
              ? 'Must be less than current market price'
              : 'Must be greater than current market price'
          ),
          stopLimitPriceCell('oco'),
          placeholderCell('oco-placeholder')
        );
        break;
      default:
        break;
    }

    return cells;
  };

  const buildOrderConfirmationDetails = () => {
    const qty = parseFloat(orderForm.quantity || 0);
    const marketPrice = parseFloat(currentPrices.base || 0);
    const effectivePrice = orderForm.type === 'MARKET'
      ? marketPrice
      : determinePriceForCalculations();
    const estimatedValue = qty > 0 && effectivePrice > 0
      ? (qty * effectivePrice).toFixed(2)
      : '0.00';

    return {
      side: orderForm.side,
      symbol: orderForm.symbol,
      type: orderForm.type,
      quantity: orderForm.quantity,
      price: orderForm.price,
      stopPrice: orderForm.stopPrice,
      stopLimitPrice: orderForm.stopLimitPrice,
      timeInForce: orderForm.timeInForce,
      stopLimitTimeInForce: orderForm.stopLimitTimeInForce,
      estimatedValue,
    };
  };

  useEffect(() => {
    if (location.state?.tradePrefill) {
      const { symbol, side } = location.state.tradePrefill;
      setOrderForm((prev) => ({
        ...prev,
        symbol: symbol || prev.symbol,
        side: side || prev.side,
        type: prev.type,
        quantity: '',
        price: '',
        stopPrice: '',
        stopLimitPrice: ''
      }));
      setQuoteQuantity('');
      setBalancePercentage(0);
      navigate('.', { replace: true, state: {} });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state]);

  // Popular trading pairs
  const tradingPairs = [
    // USD pairs (top of list for easy access)
    'USDTUSD', 'BTCUSD', 'ETHUSD',
    // USDT pairs
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'DOGEUSDT',
    'XRPUSDT', 'DOTUSDT', 'UNIUSDT', 'LTCUSDT', 'LINKUSDT',
    'SOLUSDT', 'MATICUSDT', 'AVAXUSDT', 'ATOMUSDT', 'ALGOUSDT',
    // Added requested pairs
    'SUIUSDT', 'CELRUSDT', 'FETUSDT', 'LPTUSDT', 'ONTUSDT', 'KSMUSDT'
  ];


  // Load settings and data on mount
  useEffect(() => {
    // Check trade permission first
    const checkPermission = async () => {
      try {
        const response = await axios.get('/api/check-trade-permission', { withCredentials: true });
        if (!response.data.has_api_key) {
          // No API key configured
          setShowApiKeyModal(true);
        } else if (!response.data.has_permission) {
          // Has API key but no trading permission
          setShowPermissionModal(true);
        }
      } catch (err) {
        console.error('Failed to check trade permission:', err);
      }
    };
    checkPermission();

    loadTradingSettings();
    loadOrderTypes();
    loadOrders();
    loadOpenOrders();
    if (settings.test_mode_enabled) {
      loadTestPortfolio();
      loadTestOrders();
    }
  }, []);

  const loadOrderTypes = async () => {
    try {
      const response = await axios.get('/api/trading/order-types');
      if (response.data.success) {
        setOrderTypes(response.data.order_types);
      }
    } catch (error) {
      console.error('Failed to load order types:', error);
      // Fallback to basic order types if API fails
      setOrderTypes([
        { value: 'MARKET', label: 'Market Order', description: 'Execute immediately at current market price' },
        { value: 'LIMIT', label: 'Limit Order', description: 'Execute at specified price or better' }
      ]);
    }
  };

  useEffect(() => {
    const price = determinePriceForCalculations();

    // If the user last edited the USD/Quote amount, price changes should adjust the Base quantity
    if (lastEditedRef.current === 'quote') {
      const currentQuote = parseFloat(quoteQuantity);
      if (!Number.isNaN(currentQuote) && price > 0) {
        const newBase = currentQuote / price;
        const formatted = formatNumberString(newBase, 8);
        if (formatted !== orderForm.quantity) {
          setOrderForm(prev => ({ ...prev, quantity: formatted }));
        }
      }
    }
    // Otherwise, price changes adjust the USD/Quote amount (Default or after editing Base)
    else {
      const currentBase = parseFloat(orderForm.quantity);
      if (!Number.isNaN(currentBase) && price > 0) {
        const newQuote = currentBase * price;
        const formatted = formatNumberString(newQuote, 2);
        if (formatted !== quoteQuantity) {
          setQuoteQuantity(formatted);
        }
      }
    }
  }, [
    orderForm.type,
    orderForm.price,
    orderForm.stopPrice,
    orderForm.stopLimitPrice,
    orderForm.symbol,
    currentPrices.base,
  ]);

  useEffect(() => {
    if (activeTab === 'history') {
      loadOpenOrders();
      loadOrders();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  const loadTradingSettings = async () => {
    try {
      const response = await axios.get('/api/trading/settings', { withCredentials: true });
      if (response.data.success) {
        setSettings(response.data.settings);
      }
    } catch (error) {
      console.error('Failed to load trading settings:', error);
      setFeedbackModal({
        isVisible: true,
        message: 'Failed to load trading settings: ' + (error.response?.data?.error || error.message),
        type: 'error'
      });
    }
  };

  const normalizeOrderRecord = (order) => {
    if (!order || typeof order !== 'object') {
      return order;
    }

    const safeFloat = (value) =>
      value === null || value === undefined || value === ''
        ? null
        : parseFloat(value);

    const createdAt =
      order.created_at ||
      order.time ||
      (order.updateTime ? new Date(order.updateTime).toISOString() : null);

    const quantity =
      safeFloat(order.quantity) ??
      safeFloat(order.origQty) ??
      safeFloat(order.executedQty) ??
      0;

    const executedQuantity =
      safeFloat(order.filled_quantity) ??
      safeFloat(order.executed_qty) ??
      safeFloat(order.executedQty) ??
      quantity;

    const cumulativeQuote =
      safeFloat(order.cumulative_quote_qty) ??
      safeFloat(order.cummulativeQuoteQty) ??
      safeFloat(order.quoteQuantity);

    const price =
      safeFloat(order.price) ??
      safeFloat(order.limit_price) ??
      (executedQuantity && cumulativeQuote
        ? cumulativeQuote / Math.max(executedQuantity, 1e-9)
        : null);

    const filledPrice =
      safeFloat(order.filled_price) ??
      safeFloat(order.avg_fill_price) ??
      (executedQuantity && cumulativeQuote
        ? cumulativeQuote / Math.max(executedQuantity, 1e-9)
        : price) ??
      0;

    return {
      ...order,
      id:
        order.id ??
        order.binance_order_id ??
        order.orderId ??
        `order-${order.symbol}-${createdAt || Date.now()}`,
      order_type:
        order.order_type || order.type || order.orderType || order.order_type_desc || 'UNKNOWN',
      quantity: quantity ?? 0,
      price: price ?? 0,
      filled_quantity: executedQuantity ?? 0,
      filled_price: filledPrice ?? 0,
      created_at: createdAt,
      status: order.status || 'UNKNOWN',
    };
  };

  const loadOrders = async () => {
    try {
      const response = await axios.get('/api/trading/real-orders?limit=all', { withCredentials: true });
      if (response.data.success) {
        const normalized = (response.data.orders || []).map(normalizeOrderRecord);
        setOrders(normalized);
      }
    } catch (error) {
      console.error('Failed to load orders:', error);
    }
  };

  const loadTestPortfolio = async () => {
    try {
      const response = await axios.get('/api/trading/portfolio', { withCredentials: true });
      if (response.data.success) {
        setPortfolio(response.data.holdings);
      }
    } catch (error) {
      console.error('Failed to load test portfolio:', error);
    }
  };

  const loadTestOrders = async () => {
    try {
      const response = await axios.get('/api/trading/test-orders?limit=100', { withCredentials: true });
      if (response.data.success) {
        const normalized = (response.data.orders || []).map(normalizeOrderRecord);
        setTestOrders(normalized);
      }
    } catch (error) {
      console.error('Failed to load test orders:', error);
    }
  };

  const backfillTestPortfolio = async () => {
    try {
      setLoading(true);
      const response = await axios.post('/api/trading/portfolio/backfill', {}, { withCredentials: true });
      if (response.data.success) {
        setFeedbackModal({
          isVisible: true,
          message: response.data.message || 'Test portfolio backfilled successfully from your real holdings!',
          type: 'success'
        });
        await loadTestPortfolio(); // Reload portfolio after backfill
      } else {
        setFeedbackModal({
          isVisible: true,
          message: response.data.error || 'Failed to backfill test portfolio',
          type: 'error'
        });
      }
    } catch (error) {
      console.error('Failed to backfill test portfolio:', error);
      setFeedbackModal({
        isVisible: true,
        message: 'Failed to backfill test portfolio: ' + (error.response?.data?.error || error.message),
        type: 'error'
      });
    } finally {
      setLoading(false);
    }
  };

  // Load current market prices
  const loadCurrentPrices = async () => {
    try {
      const response = await axios.get(`/api/trading/price/${orderForm.symbol}`, { withCredentials: true });
      if (response.data.success) {
        setCurrentPrices(response.data.prices);
      }
    } catch (error) {
      console.error('Failed to load current prices:', error);
    }
  };

  // Load user balances for selected trading pair
  const loadBalances = async () => {
    try {
      const response = await axios.get(`/api/trading/balances/${orderForm.symbol}`, { withCredentials: true });
      if (response.data.success) {
        setBalances(response.data.balances);
      }
    } catch (error) {
      console.error('Failed to load balances:', error);
    }
  };

  // Load open orders
  const loadOpenOrders = async () => {
    try {
      const response = await axios.get('/api/trading/open-orders', { withCredentials: true });
      if (response.data.success) {
        setOpenOrders(response.data.orders || []);
      }
    } catch (error) {
      console.error('Failed to load open orders:', error);
    }
  };

  const openCancelModalForOrder = (order) => {
    setCancelModal({
      isVisible: true,
      order,
      error: '',
      loading: false,
    });
  };

  const closeCancelModal = () => {
    setCancelModal({ isVisible: false, order: null, error: '', loading: false });
  };

  const handleCancelOrderConfirm = async (twoFactorCode) => {
    if (!cancelModal.order) {
      return;
    }

    const orderId = cancelModal.order.order_id || cancelModal.order.orderId || cancelModal.order.id;
    const symbol = cancelModal.order.symbol;

    if (!orderId || !symbol) {
      setCancelModal((prev) => ({
        ...prev,
        error: 'Unable to determine order reference for cancellation.',
      }));
      return;
    }

    setCancelModal((prev) => ({ ...prev, loading: true, error: '' }));

    try {
      const response = await axios.post(
        `/api/cancel-order/${orderId}`,
        {
          symbol,
          two_factor_code: twoFactorCode,
        },
        { withCredentials: true }
      );

      if (response.data.success) {
        setCancelModal({ isVisible: false, order: null, error: '', loading: false });
        setOpenOrders((prev) =>
          prev.filter((order) => (order.order_id || order.orderId || order.id) !== orderId)
        );
        await loadOpenOrders();
        await loadOrders();
        setFeedbackModal({
          isVisible: true,
          message: `Order ${symbol} #${orderId} cancelled successfully`,
          type: 'success',
        });
      } else {
        setCancelModal((prev) => ({
          ...prev,
          loading: false,
          error: response.data.error || 'Failed to cancel order.',
        }));
      }
    } catch (error) {
      const message = error.response?.data?.error || error.message || 'Failed to cancel order.';
      setCancelModal((prev) => ({ ...prev, loading: false, error: message }));
    }
  };

  // Load actual trading fees from Binance.US
  const loadTradingFees = async () => {
    try {
      const response = await axios.get(`/api/trading/fees/${orderForm.symbol}`, { withCredentials: true });
      if (response.data.success) {
        return response.data.fees;
      }
    } catch (error) {
      console.error('Failed to load trading fees:', error);
      // Fall back to default Binance.US rates: 0.1% maker, 0.4% taker
      return { makerRate: 0.001, takerRate: 0.004 };
    }
  };

  // Calculate estimated fee using actual Binance.US rates
  const calculateFee = async () => {
    const qty = parseFloat(orderForm.quantity) || 0;
    const price = determinePriceForCalculations();

    if (qty === 0 || price === 0) {
      setEstimatedFee({ amount: 0, usd: 0, asset: '', rate: 0 });
      return;
    }

    // Get actual trading fees from Binance.US (cached)
    const fees = await loadTradingFees();

    // Determine if this would be a maker or taker order
    // LIMIT orders are typically maker, MARKET orders are taker
    // For worst-case estimate, use taker rate
    const feeRate = orderForm.type === 'MARKET' ? fees.takerRate : fees.makerRate;

    // Binance.US charges fees on the asset you RECEIVE
    // BUY: Fee is on the base asset (BTC, ETH, etc.)
    // SELL: Fee is on the quote asset (USDT, USD)

    if (orderForm.side === 'BUY') {
      // When buying BTC with USDT, fee is charged in BTC
      // Fee = quantity * fee_rate (NOT price * quantity * fee_rate)
      const feeAsset = orderForm.symbol.replace('USDT', '').replace('USD', '');
      const feeInAsset = qty * feeRate;
      const feeInUSD = feeInAsset * price;

      setEstimatedFee({
        amount: feeInAsset,
        usd: feeInUSD,
        asset: feeAsset,
        rate: feeRate
      });
    } else {
      // When selling BTC for USDT, fee is charged in USDT
      // Fee = (quantity * price) * fee_rate
      const total = qty * price;
      const feeInUSDT = total * feeRate;

      setEstimatedFee({
        amount: feeInUSDT,
        usd: feeInUSDT,
        asset: 'USDT',
        rate: feeRate
      });
    }
  };

  // Instant fee calculation using cached rates (no API call)
  const calculateFeeInstant = () => {
    const qty = parseFloat(orderForm.quantity) || 0;
    const price = determinePriceForCalculations();

    if (qty === 0 || price === 0) {
      setEstimatedFee({ amount: 0, usd: 0, asset: '', rate: 0 });
      return;
    }

    // Use existing fee rate from state, or default to Binance.US rates
    // Market orders = taker (0.4%), Limit orders = maker (0.1%)
    const feeRate = estimatedFee.rate || (orderForm.type === 'MARKET' ? 0.004 : 0.001);

    if (orderForm.side === 'BUY') {
      const feeAsset = orderForm.symbol.replace('USDT', '').replace('USD', '');
      const feeInAsset = qty * feeRate;
      const feeInUSD = feeInAsset * price;

      setEstimatedFee({
        amount: feeInAsset,
        usd: feeInUSD,
        asset: feeAsset,
        rate: feeRate
      });
    } else {
      const total = qty * price;
      const feeInUSDT = total * feeRate;

      setEstimatedFee({
        amount: feeInUSDT,
        usd: feeInUSDT,
        asset: 'USDT',
        rate: feeRate
      });
    }
  };

  // Handle balance slider change
  const handleBalanceSliderChange = (percentage) => {
    setBalancePercentage(percentage);

    // Calculate quantity based on percentage of available balance
    if (orderForm.side === 'SELL') {
      // Selling: use base asset balance
      lastEditedRef.current = 'base';
      const availableQty = balances.base;
      const selectedQty = (availableQty * percentage) / 100;
      handleBaseQuantityChange(selectedQty.toFixed(8));
    } else {
      // Buying: calculate how much we can buy with quote asset balance
      lastEditedRef.current = 'quote';
      const availableQuote = balances.quote;
      const price = determinePriceForCalculations();
      if (price > 0) {
        // Use a 0.1% buffer to avoid rounding issues with fees
        const availableQty = (availableQuote * 0.999) / price;
        const selectedQty = (availableQty * percentage) / 100;

        // Update both fields
        const formattedBase = selectedQty.toFixed(8);
        setOrderForm((prev) => ({ ...prev, quantity: formattedBase }));
        setQuoteQuantity(formatNumberString((availableQuote * percentage) / 100, 2));
      }
    }
  };

  // Update prices and balances when symbol changes
  useEffect(() => {
    loadCurrentPrices();
    loadBalances();
    loadOpenOrders();
    calculateFee(); // Load fees on symbol change

    // Set up refresh intervals
    const priceInterval = setInterval(loadCurrentPrices, 5000); // Prices every 5s
    const feeInterval = setInterval(calculateFee, 10000); // Fees every 10s

    return () => {
      clearInterval(priceInterval);
      clearInterval(feeInterval);
    };
  }, [orderForm.symbol]);

  // Instant recalculation when quantity/price changes (no API call)
  useEffect(() => {
    calculateFeeInstant();
  }, [orderForm.quantity, orderForm.price, orderForm.side]);

  // Update fee when price updates (use instant calculation)
  useEffect(() => {
    if (orderForm.quantity > 0) {
      calculateFeeInstant();
    }
  }, [currentPrices]);

  const handleSettingsUpdate = async (updates) => {
    try {
      const response = await axios.post('/api/trading/settings', updates, { withCredentials: true });
      if (response.data.success) {
        setSettings(response.data.settings);
        setFeedbackModal({
          isVisible: true,
          message: 'Trading settings updated successfully!',
          type: 'success'
        });
      }
    } catch (error) {
      setFeedbackModal({
        isVisible: true,
        message: 'Failed to update settings: ' + (error.response?.data?.error || error.message),
        type: 'error'
      });
    }
  };

  const handleOrderSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);

    try {
      if (!orderForm.quantity || parseFloat(orderForm.quantity) <= 0) {
        setFeedbackModal({
          isVisible: true,
          message: 'Please enter a valid quantity greater than 0.',
          type: 'error'
        });
        setLoading(false);
        return;
      }

      if (['LIMIT', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT', 'LIMIT_MAKER'].includes(orderForm.type)) {
        if (!orderForm.price || parseFloat(orderForm.price) <= 0) {
          setFeedbackModal({
            isVisible: true,
            message: 'Price is required for limit orders.',
            type: 'error'
          });
          setLoading(false);
          return;
        }
      }

      if (['STOP_LOSS', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT', 'TAKE_PROFIT_LIMIT'].includes(orderForm.type)) {
        if (!orderForm.stopPrice || parseFloat(orderForm.stopPrice) <= 0) {
          setFeedbackModal({
            isVisible: true,
            message: 'Stop price is required for stop orders.',
            type: 'error'
          });
          setLoading(false);
          return;
        }
      }

      if (orderForm.type === 'OCO') {
        if (!orderForm.price || parseFloat(orderForm.price) <= 0) {
          setFeedbackModal({
            isVisible: true,
            message: 'Limit price is required for OCO orders.',
            type: 'error'
          });
          setLoading(false);
          return;
        }
        if (!orderForm.stopPrice || parseFloat(orderForm.stopPrice) <= 0) {
          setFeedbackModal({
            isVisible: true,
            message: 'Stop price is required for OCO orders.',
            type: 'error'
          });
          setLoading(false);
          return;
        }
        if (!orderForm.stopLimitPrice || parseFloat(orderForm.stopLimitPrice) <= 0) {
          setFeedbackModal({
            isVisible: true,
            message: 'Stop limit price is required for OCO orders.',
            type: 'error'
          });
          setLoading(false);
          return;
        }
      }

      if (['STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT'].includes(orderForm.type)) {
        const limit = parseFloat(orderForm.price || 0);
        const stop = parseFloat(orderForm.stopPrice || 0);
        if (!Number.isFinite(limit) || !Number.isFinite(stop)) {
          setFeedbackModal({
            isVisible: true,
            message: 'Please enter both limit and stop prices for stop-limit orders.',
            type: 'error'
          });
          setLoading(false);
          return;
        }
        if (orderForm.side === 'BUY' && limit < stop) {
          setFeedbackModal({
            isVisible: true,
            message: 'For buy stop-limit orders, the limit price must be greater than or equal to the stop price so the order does not execute immediately.',
            type: 'error'
          });
          setLoading(false);
          return;
        }
        if (orderForm.side === 'SELL' && limit > stop) {
          setFeedbackModal({
            isVisible: true,
            message: 'For sell stop-limit orders, the limit price must be less than or equal to the stop price so the order does not execute immediately.',
            type: 'error'
          });
          setLoading(false);
          return;
        }
      }

      if (settings.require_2fa && settings.totp_enabled) {
        setTwoFactorModal({
          isVisible: true,
          orderData: buildOrderConfirmationDetails()
        });
        setLoading(false);
        return;
      }

      await submitOrder(null);
    } catch (error) {
      console.error('Order submission error:', error);
      if (error.response?.data?.requires_2fa) {
        setTwoFactorModal({
          isVisible: true,
          orderData: buildOrderConfirmationDetails()
        });
      } else {
        const errorMessage = error.response?.data?.error || error.message || 'Failed to place order. Please check your connection and try again.';
        setFeedbackModal({
          isVisible: true,
          message: errorMessage,
          type: 'error'
        });
      }
    } finally {
      setLoading(false);
    }
  };

  const handle2FAVerify = async (code) => {
    try {
      // Verify 2FA code
      const verifyResponse = await axios.post('/api/trading/2fa/verify', { code }, { withCredentials: true });

      if (!verifyResponse.data.success) {
        throw new Error(verifyResponse.data.error || 'Verification failed');
      }

      const token = verifyResponse.data.token;

      // Close 2FA modal
      setTwoFactorModal({ isVisible: false, orderData: null });
      setLoading(true);

      // Submit order with token
      await submitOrder(token);

    } catch (error) {
      throw error; // Re-throw to be caught by modal
    }
  };

  const handleDustSuccess = (_data, toAsset) => {
    setFeedbackModal({
      isVisible: true,
      message: `Small balances successfully converted to ${toAsset}! Your portfolio chart will update shortly.`,
      type: 'success',
    });
  };

  const submitOrder = async (twofaToken) => {
    try {
      setLoading(true);

      // Choose endpoint based on order type and test mode
      let endpoint;
      if (orderForm.type === 'OCO') {
        endpoint = settings.test_mode_enabled ? '/api/trading/test-oco-order' : '/api/trading/oco-order';
      } else {
        endpoint = settings.test_mode_enabled ? '/api/trading/test-order' : '/api/trading/place-order';
      }

      // Add 2FA token to request if present
      const orderData = { ...orderForm };
      if (twofaToken) {
        orderData.twofa_token = twofaToken;
      }
      if (quoteQuantity) {
        orderData.quoteQuantity = quoteQuantity;
        orderData.quote_quantity = quoteQuantity;
        orderData.quote_amount = quoteQuantity;
      }

      const response = await axios.post(endpoint, orderData, { withCredentials: true });

      if (response.data.success) {
        const successMessage = settings.test_mode_enabled
          ? `Test order placed successfully!\n\n${orderForm.side} ${orderForm.quantity} ${orderForm.symbol.replace('USDT', '')} validated with Binance.US and simulated.\n\nYour test portfolio has been updated.`
          : `Real order placed successfully!\n\nOrder ID: ${response.data.binance_order_id}\n\nYour portfolio will be updated once the order is filled.`;

        setFeedbackModal({
          isVisible: true,
          message: successMessage,
          type: 'success'
        });

        // Clear form
        setOrderForm({
          ...orderForm,
          quantity: '',
          price: '',
          stopPrice: '',
          stopLimitPrice: ''
        });

        // Reload orders and portfolio
        await loadOrders();
        if (settings.test_mode_enabled) {
          await loadTestPortfolio();
          await loadTestOrders();
        }

        // Reload balances
        await loadBalances();
      } else {
        // Check if 2FA is required
        if (response.data.requires_2fa) {
          setTwoFactorModal({
            isVisible: true,
            orderData: buildOrderConfirmationDetails()
          });
          return;
        }

        setFeedbackModal({
          isVisible: true,
          message: response.data.error || 'Order failed. Please try again.',
          type: 'error'
        });
      }
    } catch (error) {
      console.error('Order submission error:', error);
      if (error.response?.data?.requires_2fa) {
        setTwoFactorModal({
          isVisible: true,
          orderData: buildOrderConfirmationDetails()
        });
      } else {
        const errorMessage = error.response?.data?.error || error.message || 'Failed to place order. Please check your connection and try again.';
        setFeedbackModal({
          isVisible: true,
          message: errorMessage,
          type: 'error'
        });
      }
    } finally {
      setLoading(false);
    }
  };

  const formatNumber = (num, decimals = 2) => {
    if (num === null || num === undefined) return 'N/A';
    return parseFloat(num).toFixed(decimals);
  };

  const formatDate = (dateString) => {
    if (!dateString) return 'N/A';
    return new Date(dateString).toLocaleString();
  };

  const isCanceledStatus = (status) => {
    if (!status) return false;
    const normalized = status.toString().toUpperCase();
    return normalized.includes('CANCEL');
  };

  const filteredOrders = showCanceledOrders
    ? orders
    : orders.filter((order) => !isCanceledStatus(order.status));

  return (
    <div className="trading-container" style={{ minHeight: '100vh', padding: '20px', color: 'white' }}>
      {/* API Key Required Modal */}
      <ApiKeyRequiredModal
        show={showApiKeyModal}
        onClose={() => setShowApiKeyModal(false)}
        isLightMode={false}
      />
      {/* Trade Permission Modal */}
      <TradePermissionModal
        show={showPermissionModal}
        onClose={() => setShowPermissionModal(false)}
        pageName="trading"
        isLightMode={false}
      />
      <div className="trading-header">
        <div className="trading-header-left">
          <h1 style={{ fontSize: '2rem', margin: 0 }}>🔄 Trading Center</h1>

          {/* Test Mode Banner */}
          {settings.test_mode_enabled && (
            <div className="test-mode-banner">
              <span className="test-badge">TEST MODE</span>
              <span className="test-description">
                Orders are validated with Binance.US but not executed. Safe for testing strategies.
              </span>
            </div>
          )}
        </div>

        {/* Convert Dust button + Test Mode toggle */}
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '16px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '6px', paddingTop: '4px' }}>
            <button
              id="convert-dust-btn"
              onClick={() => setDustModal({ isVisible: true })}
              style={{
                padding: '8px 16px',
                borderRadius: '8px',
                border: '1px solid rgba(102,126,234,0.5)',
                background: 'rgba(102,126,234,0.12)',
                color: 'var(--text-primary, #c7d2fe)',
                fontSize: '0.85rem',
                fontWeight: 600,
                cursor: 'pointer',
                whiteSpace: 'nowrap',
                transition: 'all 0.2s',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'rgba(102,126,234,0.22)';
                e.currentTarget.style.borderColor = '#667eea';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'rgba(102,126,234,0.12)';
                e.currentTarget.style.borderColor = 'rgba(102,126,234,0.5)';
              }}
              title="Convert small balances (dust) to BNB, BTC, ETH, or USDT"
            >
              🪙 Convert Dust
            </button>
          </div>

          <div className="trading-mode-toggle">
            <span className="trading-mode-caption">Test Mode</span>
            <label className="toggle-switch">
              <input
                type="checkbox"
                checked={settings.test_mode_enabled}
                onChange={(e) => handleSettingsUpdate({ test_mode_enabled: e.target.checked })}
              />
              <span className="toggle-slider"></span>
            </label>
            <span className="trading-mode-status">{settings.test_mode_enabled ? 'Enabled' : 'Disabled'}</span>
          </div>
        </div>
      </div>

      {/* Order Feedback Modal */}
      <OrderFeedbackModal
        isVisible={feedbackModal.isVisible}
        onClose={() => setFeedbackModal({ ...feedbackModal, isVisible: false })}
        message={feedbackModal.message}
        type={feedbackModal.type}
      />

      {/* Two Factor Authentication Modal */}
      <TwoFactorModal
        isVisible={twoFactorModal.isVisible}
        onClose={() => setTwoFactorModal({ isVisible: false, orderData: null })}
        onVerify={handle2FAVerify}
        orderDetails={twoFactorModal.orderData}
      />

      {/* Convert Dust Modal */}
      <ConvertDustModal
        isVisible={dustModal.isVisible}
        onClose={() => setDustModal({ isVisible: false })}
        require2fa={settings.require_2fa}
        onSuccess={handleDustSuccess}
      />

      <CancelOrderModal
        isVisible={cancelModal.isVisible}
        onClose={closeCancelModal}
        onConfirm={handleCancelOrderConfirm}
        order={cancelModal.order}
        loading={cancelModal.loading}
        error={cancelModal.error}
      />

      {/* Tab Navigation */}
      <div className="trading-tabs">
        <button
          className={`tab-button ${activeTab === 'order' ? 'active' : ''}`}
          onClick={() => setActiveTab('order')}
        >
          📝 Place Order
        </button>
        <button
          className={`tab-button ${activeTab === 'history' ? 'active' : ''}`}
          onClick={() => setActiveTab('history')}
        >
          📜 Order History
        </button>
        {settings.test_mode_enabled && (
          <button
            className={`tab-button ${activeTab === 'portfolio' ? 'active' : ''}`}
            onClick={() => setActiveTab('portfolio')}
          >
            💼 Test Portfolio
          </button>
        )}
      </div>

      {/* Tab Content */}
      <div className="trading-content">

        {/* ORDER FORM TAB */}
        {activeTab === 'order' && (
          <div className="order-form-container">
            {/* Trading Chart - Full Width */}
            <TradingChart
              key={orderForm.symbol}
              symbol={orderForm.symbol}
              onSymbolChange={(newSymbol) => {
                setOrderForm({
                  ...orderForm,
                  symbol: newSymbol,
                  quantity: '',
                  price: '',
                  stopPrice: '',
                  stopLimitPrice: ''
                });
                setQuoteQuantity('');
                setBalancePercentage(0);
              }}
              tradingPairs={tradingPairs.map(pair => ({ id: pair, display_name: pair }))}
            />

            <form onSubmit={handleOrderSubmit} className="order-form">
              <div className="order-grid">
                {/* LEFT COLUMN: Balances, Withdraw, Order Side */}
                <div className="order-grid-item">
                  <div className="balance-display-section info-card">
                    <div className="balance-item">
                      <span className="balance-label">{baseAsset} Available:</span>
                      <span className="balance-value">{balances.base.toFixed(8)}</span>
                    </div>
                    <div className="balance-item">
                      <span className="balance-label">{quoteAsset} Available:</span>
                      <span className="balance-value">{balances.quote.toFixed(2)}</span>
                    </div>
                  </div>
                </div>

                {/* RIGHT COLUMN: Current Price, Deposit */}
                <div className="order-grid-item">
                  <div className="price-display-section info-card">
                    <div className="price-item">
                      <span className="price-label">{baseAsset}</span>
                      <span className="price-value">
                        {currentPrices.base > 0 ? `$${currentPrices.base.toFixed(2)}` : '—'}
                      </span>
                    </div>
                    <div className="price-item">
                      <span className="price-label">{quoteAsset}</span>
                      <span className="price-value">$1.00</span>
                    </div>
                  </div>
                </div>

                {/* Withdraw/Deposit buttons removed */}

                {/* LEFT: Order Side */}
                <div className="order-grid-item">
                  <div className="form-group">
                    <label>Order Side</label>
                    <div className="side-toggle">
                      <button
                        type="button"
                        className={`side-button buy ${orderForm.side === 'BUY' ? 'active' : ''}`}
                        onClick={() => {
                          setOrderForm({ ...orderForm, side: 'BUY' });
                          setBalancePercentage(0);
                        }}
                      >
                        📈 BUY
                      </button>
                      <button
                        type="button"
                        className={`side-button sell ${orderForm.side === 'SELL' ? 'active' : ''}`}
                        onClick={() => {
                          setOrderForm({ ...orderForm, side: 'SELL' });
                          setBalancePercentage(0);
                        }}
                      >
                        📉 SELL
                      </button>
                    </div>
                  </div>
                </div>
                <div className="order-grid-item">
                  <div className="form-group">
                    <label htmlFor="type">Order Type</label>
                    <select
                      id="type"
                      value={orderForm.type}
                      onChange={(e) => {
                        setOrderForm({
                          ...orderForm,
                          type: e.target.value,
                          price: '',
                          stopPrice: '',
                          stopLimitPrice: ''
                        });
                        setQuoteQuantity('');
                      }}
                      className="form-control"
                    >
                      {orderTypes.map(type => (
                        <option key={type.value} value={type.value}>
                          {type.label}
                        </option>
                      ))}
                    </select>
                    <small className="form-help">
                      {orderTypes.find(t => t.value === orderForm.type)?.description}
                    </small>
                  </div>
                </div>

                <div className="order-grid-item">
                  <div className="form-group">
                    <label htmlFor="quantity">{baseAsset} Quantity</label>
                    <input
                      id="quantity"
                      type="text"
                      inputMode="decimal"
                      value={orderForm.quantity}
                      onChange={(e) => handleBaseQuantityChange(e.target.value)}
                      placeholder={`Enter ${baseAsset} quantity`}
                      className="form-control"
                      required
                      autoComplete="off"
                    />
                  </div>
                </div>
                <div className="order-grid-item">
                  <div className="form-group">
                    <label htmlFor="quoteQuantity">{quoteAsset} Quantity</label>
                    <input
                      id="quoteQuantity"
                      type="text"
                      inputMode="decimal"
                      value={quoteQuantity}
                      onChange={(e) => handleQuoteQuantityChange(e.target.value)}
                      placeholder={`Enter ${quoteAsset} amount`}
                      className="form-control"
                      autoComplete="off"
                    />
                  </div>
                </div>

                <div className="order-grid-item">
                  <div className="form-group">
                    <label>
                      Use Balance: {balancePercentage}%
                      {balancePercentage > 0 && (
                        <span className="balance-amount">
                          {' '}({orderForm.side === 'SELL'
                            ? `${((balances.base * balancePercentage) / 100).toFixed(8)} ${baseAsset}`
                            : `${((balances.quote * balancePercentage) / 100).toFixed(2)} ${quoteAsset}`})
                        </span>
                      )}
                    </label>
                    <input
                      type="range"
                      min="0"
                      max="100"
                      step="1"
                      value={balancePercentage}
                      onChange={(e) => handleBalanceSliderChange(parseInt(e.target.value, 10))}
                      className="balance-slider"
                    />
                    <div className="slider-labels">
                      <span>0%</span>
                      <span>25%</span>
                      <span>50%</span>
                      <span>75%</span>
                      <span>100%</span>
                    </div>
                  </div>
                </div>
                <div className="order-grid-item order-grid-item--placeholder" aria-hidden="true" />

                {renderOrderTypeFields()}

                {estimatedFee.amount > 0 && (
                  <div className="order-grid-item grid-span-2">
                    <div className="fee-display-section">
                      <div className="fee-row">
                        <span className="fee-label">Estimated Fee:</span>
                        <span className="fee-value">
                          {estimatedFee.amount.toFixed(8)} {estimatedFee.asset}
                        </span>
                      </div>
                      <div className="fee-row">
                        <span className="fee-label">Fee in USD:</span>
                        <span className="fee-value">${estimatedFee.usd.toFixed(2)}</span>
                      </div>
                      <div className="fee-total">
                        <span className="fee-label">{orderForm.side === 'BUY' ? 'Total Cost:' : 'You Receive:'}:</span>
                        <span className="fee-value">
                          {orderForm.side === 'BUY'
                            ? `$${((parseFloat(orderForm.quantity || 0) * determinePriceForCalculations()) + estimatedFee.usd).toFixed(2)}`
                            : `${(parseFloat(orderForm.quantity || 0) * determinePriceForCalculations() - estimatedFee.usd).toFixed(2)} ${quoteAsset}`
                          }
                        </span>
                      </div>
                    </div>
                  </div>
                )}

                <div className="order-grid-item grid-span-2 order-submit-cell">
                  <button
                    type="submit"
                    className={`submit-button ${orderForm.side.toLowerCase()}`}
                    disabled={loading}
                  >
                    {loading ? (
                      <span>⏳ Processing...</span>
                    ) : (
                      <span>
                        {settings.test_mode_enabled ? '🧪 Place Test Order' : '⚡ Place Real Order'}
                      </span>
                    )}
                  </button>
                </div>

                {!settings.test_mode_enabled && (
                  <div className="order-grid-item grid-span-2">
                    <div className="real-order-warning">
                      ⚠️ <strong>WARNING:</strong> You are in REAL TRADING MODE. This will place an actual order on Binance.US.
                    </div>
                  </div>
                )}
              </div>
            </form>
          </div>
        )}

        {/* ORDER HISTORY TAB */}
        {activeTab === 'history' && (
          <div className="order-history-container">

            {/* Open Orders Section */}
            <div className="open-orders-section">
              <div className="order-history-header">
                <h2>Open Orders</h2>
              </div>

              {openOrders.length === 0 ? (
                <div className="empty-state">
                  <p>No open orders</p>
                </div>
              ) : (
                <div className="table-container trading-table">
                  <div className="order-table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Date</th>
                          <th>Symbol</th>
                          <th>Side</th>
                          <th>Type</th>
                          <th>Quantity</th>
                          <th>Price</th>
                          <th>Filled</th>
                          <th>Status</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {openOrders.map((order, idx) => (
                          <tr key={order.id || idx} className="open-order-row">
                            <td>{formatDate(order.created_at || order.time)}</td>
                            <td className="symbol-cell">{order.symbol}</td>
                            <td>
                              <span className={`badge badge-${order.side.toLowerCase()}`}>
                                {order.side}
                              </span>
                            </td>
                            <td>{order.order_type || order.type}</td>
                            <td>{formatNumber(order.quantity || order.origQty, 8)}</td>
                            <td>{order.price ? `$${formatNumber(order.price)}` : '-'}</td>
                            <td>{formatNumber(order.filled_quantity || order.executedQty || 0, 8)}</td>
                            <td>
                              <span className="badge badge-open">
                                {order.status}
                              </span>
                            </td>
                            <td>
                              <button
                                className="btn btn-danger cancel-order-btn"
                                onClick={() => openCancelModalForOrder(order)}
                                disabled={
                                  cancelModal.loading &&
                                  cancelModal.order &&
                                  (cancelModal.order.order_id || cancelModal.order.orderId || cancelModal.order.id) ===
                                  (order.order_id || order.orderId || order.id)
                                }
                              >
                                Cancel Order
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>

            {/* All Orders History */}
            <div className="order-history-header" style={{ marginTop: '2rem' }}>
              <h2>Order History</h2>
              <div className="order-history-toggle">
                <label className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={showCanceledOrders}
                    onChange={(e) => setShowCanceledOrders(e.target.checked)}
                  />
                  <span className="toggle-slider"></span>
                </label>
                <span className="order-history-toggle-label">Show Canceled Orders</span>
              </div>
            </div>

            {filteredOrders.length === 0 ? (
              <div className="empty-state">
                <p>{orders.length === 0 ? 'No orders yet. Place your first order to get started!' : 'No orders match your filters.'}</p>
              </div>
            ) : (
              <div className="table-container trading-table">
                <div className="order-table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Symbol</th>
                        <th>Side</th>
                        <th>Type</th>
                        <th>Quantity</th>
                        <th>Price</th>
                        <th>Filled</th>
                        <th>Status</th>
                        <th>Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredOrders.map((order) => (
                        <tr key={order.id}>
                          <td>{formatDate(order.created_at)}</td>
                          <td className="symbol-cell">{order.symbol}</td>
                          <td>
                            <span className={`badge badge-${order.side.toLowerCase()}`}>
                              {order.side}
                            </span>
                          </td>
                          <td>{order.order_type}</td>
                          <td>{formatNumber(order.quantity, 8)}</td>
                          <td>{order.price ? `$${formatNumber(order.price)}` : '-'}</td>
                          <td>{formatNumber(order.filled_quantity, 8)}</td>
                          <td>
                            <span className={`badge badge-${order.status.toLowerCase()}`}>
                              {order.status}
                            </span>
                          </td>
                          <td>
                            ${formatNumber((order.filled_quantity || 0) * (order.filled_price || 0))}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}

        {/* TEST PORTFOLIO TAB */}
        {activeTab === 'portfolio' && settings.test_mode_enabled && (
          <div className="portfolio-container">
            <div className="portfolio-header">
              <h2>Test Portfolio</h2>
              <div className="portfolio-actions">
                <button onClick={backfillTestPortfolio} className="backfill-button" disabled={loading}>
                  🔄 Backfill from Real Portfolio
                </button>
                <button onClick={() => { loadTestPortfolio(); loadTestOrders(); }} className="refresh-button">
                  🔄 Refresh
                </button>
              </div>
            </div>

            {/* Portfolio Balances Section */}
            <div className="portfolio-section">
              <h3>💰 Current Holdings</h3>
              {portfolio.length === 0 ? (
                <div className="empty-state">
                  <p>No holdings yet. Use the "Backfill from Real Portfolio" button above to initialize with your actual coins, or buy some assets to see them here!</p>
                </div>
              ) : (
                <div className="table-container portfolio-table">
                  <table style={{ width: '100%' }}>
                    <thead>
                      <tr>
                        <th>Symbol</th>
                        <th>Quantity</th>
                        <th>Avg Price</th>
                        <th>Current Price</th>
                        <th>Cost Basis</th>
                        <th>Current Value</th>
                        <th>P&L</th>
                        <th>P&L %</th>
                      </tr>
                    </thead>
                    <tbody>
                      {portfolio.map((holding) => (
                        <tr key={holding.symbol}>
                          <td><strong>{holding.symbol}</strong></td>
                          <td>{formatNumber(holding.quantity, 8)}</td>
                          <td>${formatNumber(holding.average_price)}</td>
                          <td>${formatNumber(holding.current_price)}</td>
                          <td>${formatNumber(holding.cost_basis)}</td>
                          <td>${formatNumber(holding.current_value)}</td>
                          <td className={holding.pnl >= 0 ? 'status-positive' : 'status-negative'}>
                            {holding.pnl >= 0 ? '📈' : '📉'} ${formatNumber(Math.abs(holding.pnl))}
                          </td>
                          <td className={holding.pnl >= 0 ? 'status-positive' : 'status-negative'}>
                            {formatNumber(holding.pnl_pct, 2)}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr className="summary-row">
                        <td colSpan="4"><strong>Total Portfolio</strong></td>
                        <td><strong>${formatNumber(portfolio.reduce((sum, h) => sum + h.cost_basis, 0))}</strong></td>
                        <td><strong>${formatNumber(portfolio.reduce((sum, h) => sum + h.current_value, 0))}</strong></td>
                        <td className={portfolio.reduce((sum, h) => sum + h.pnl, 0) >= 0 ? 'status-positive' : 'status-negative'}>
                          <strong>${formatNumber(Math.abs(portfolio.reduce((sum, h) => sum + h.pnl, 0)))}</strong>
                        </td>
                        <td></td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              )}
            </div>

            {/* Test Orders History Section */}
            <div className="portfolio-section">
              <h3>📜 Test Order History</h3>
              {testOrders.length === 0 ? (
                <div className="empty-state">
                  <p>No test orders yet. Place a test order to see it here!</p>
                </div>
              ) : (
                <div className="table-container portfolio-table">
                  <table style={{ width: '100%' }}>
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Symbol</th>
                        <th>Side</th>
                        <th>Type</th>
                        <th>Quantity</th>
                        <th>Price</th>
                        <th>Fill Price</th>
                        <th>Status</th>
                        <th>Notes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {testOrders.map((order) => (
                        <tr key={order.id}>
                          <td>{new Date(order.created_at).toLocaleString()}</td>
                          <td><strong>{order.symbol}</strong></td>
                          <td className={order.side === 'BUY' ? 'status-positive' : 'status-negative'}>
                            {order.side === 'BUY' ? '📈' : '📉'} {order.side}
                          </td>
                          <td>{order.type}</td>
                          <td>{formatNumber(order.quantity, 8)}</td>
                          <td>{order.price ? '$' + formatNumber(order.price) : '-'}</td>
                          <td>{order.simulated_fill_price ? '$' + formatNumber(order.simulated_fill_price) : '-'}</td>
                          <td>
                            <span className={`status-badge ${order.status.toLowerCase()}`}>
                              {order.status}
                            </span>
                          </td>
                          <td className="notes-cell">{order.notes || '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default TradingNew;
