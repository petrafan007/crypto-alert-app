import React, { useState, useEffect } from 'react';
import axios from 'axios';
import AIAnalysis from '../components/AIAnalysis';
import { useAuth } from '../components/AuthContext';
import TradingChart from '../components/TradingChart';
import TwoFactorModal from '../components/TwoFactorModal';
import TradePermissionModal from '../components/TradePermissionModal';
import ApiKeyRequiredModal from '../components/ApiKeyRequiredModal';

export default function Trading({ isLightMode }) {
  const { isLoggingOut } = useAuth();
  const [selectedPair, setSelectedPair] = useState('BTC-USD');
  const [tradingPairs, setTradingPairs] = useState([]);
  const [filteredPairs, setFilteredPairs] = useState([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [marketData, setMarketData] = useState(null);
  const [orderType, setOrderType] = useState('MARKET');
  const [side, setSide] = useState('BUY');
  const [amount, setAmount] = useState('');
  const [limitPrice, setLimitPrice] = useState('');
  const [stopPrice, setStopPrice] = useState('');
  const [stopLimitPrice, setStopLimitPrice] = useState('');
  const [execution, setExecution] = useState('allow_taker');
  const [timeInForce, setTimeInForce] = useState('good_til_canceled');
  const [loading, setLoading] = useState(false);
  const [orderHistory, setOrderHistory] = useState([]);
  const [portfolioAnalysis, setPortfolioAnalysis] = useState(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [availableBalance, setAvailableBalance] = useState(0);
  const [subtotal, setSubtotal] = useState(0);
  const [fee, setFee] = useState(0);
  const [total, setTotal] = useState(0);
  const [tradingSettings, setTradingSettings] = useState(null);
  const [is2faModalVisible, setIs2faModalVisible] = useState(false);
  const [orderDetailsFor2fa, setOrderDetailsFor2fa] = useState(null);

  // Permission Check States
  const [showApiKeyModal, setShowApiKeyModal] = useState(false);
  const [showPermissionModal, setShowPermissionModal] = useState(false);

  useEffect(() => {
    // Check trade permission first
    const checkPermission = async () => {
      try {
        const response = await axios.get('/api/check-trade-permission', { withCredentials: true });
        if (!response.data.has_api_key) {
          setShowApiKeyModal(true);
        } else if (!response.data.has_permission) {
          setShowPermissionModal(true);
        }
      } catch (err) {
        console.error('Failed to check trade permission:', err);
      }
    };
    checkPermission();

    fetchTradingPairs();
    fetchOrderHistory();
    fetchPortfolioAnalysis();
    fetchTradingSettings();
  }, []);

  useEffect(() => {
    if (selectedPair) {
      fetchMarketData(selectedPair);
      calculateOrderSummary();
    }
  }, [selectedPair, amount, limitPrice, orderType, side]);

  // Filter trading pairs based on search term
  useEffect(() => {
    if (searchTerm.trim() === '') {
      setFilteredPairs(tradingPairs);
    } else {
      const filtered = tradingPairs.filter(pair =>
        pair.display_name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        pair.id?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        pair.base_currency?.toLowerCase().includes(searchTerm.toLowerCase())
      );
      setFilteredPairs(filtered);
    }
  }, [searchTerm, tradingPairs]);

  const fetchTradingSettings = async () => {
    try {
      const response = await axios.get('/api/trading/settings');
      if (response.data.success) {
        setTradingSettings(response.data.settings);
      }
    } catch (error) {
      console.error('Failed to fetch trading settings:', error);
    }
  };

  const fetchTradingPairs = async () => {
    try {
      // Don't make API calls if we're logging out
      if (isLoggingOut || window.globalIsLoggingOut) {
        return;
      }

      const response = await axios.get('/api/trading-pairs');
      setTradingPairs(response.data.pairs || []);
      setFilteredPairs(response.data.pairs || []);
    } catch (error) {
      console.error('Failed to fetch trading pairs:', error);
    }
  };

  const fetchMarketData = async (symbol) => {
    try {
      // Don't make API calls if we're logging out
      if (isLoggingOut || window.globalIsLoggingOut) {
        return;
      }

      const response = await axios.get(`/api/market-data/${symbol}`);
      setMarketData(response.data);
    } catch (error) {
      console.error('Failed to fetch market data:', error);
    }
  };

  const fetchOrderHistory = async () => {
    try {
      // Don't make API calls if we're logging out
      if (isLoggingOut || window.globalIsLoggingOut) {
        return;
      }

      const response = await axios.get('/api/orders');
      setOrderHistory(response.data.orders || []);
    } catch (error) {
      console.error('Failed to fetch order history:', error);
    }
  };

  const fetchPortfolioAnalysis = async () => {
    try {
      // Don't make API calls if we're logging out
      if (isLoggingOut || window.globalIsLoggingOut) {
        return;
      }

      const response = await axios.get('/api/portfolio-analysis');
      setPortfolioAnalysis(response.data);
    } catch (error) {
      console.error('Failed to fetch portfolio analysis:', error);
    }
  };

  const calculateOrderSummary = () => {
    if (!amount || !marketData) return;

    const amountValue = parseFloat(amount) || 0;
    const price = orderType === 'LIMIT' ? parseFloat(limitPrice) || marketData.price : marketData.price;

    // Calculate subtotal
    const calculatedSubtotal = amountValue;
    setSubtotal(calculatedSubtotal);

    // Calculate fee (simplified - Coinbase typically charges 0.5% for market orders)
    const feeRate = orderType === 'MARKET' ? 0.005 : 0.0035;
    const calculatedFee = calculatedSubtotal * feeRate;
    setFee(calculatedFee);

    // Calculate total
    const calculatedTotal = calculatedSubtotal + calculatedFee;
    setTotal(calculatedTotal);
  };

  const handlePercentageClick = (percentage) => {
    if (!availableBalance) return;

    let newAmount;
    if (side === 'BUY') {
      // For buy orders, use USD balance
      newAmount = (availableBalance * percentage) / 100;
    } else {
      // For sell orders, use crypto balance
      newAmount = (availableBalance * percentage) / 100;
    }

    setAmount(newAmount.toFixed(6));
  };

  const proceedWithOrderPlacement = async (twofaToken = null) => {
    setLoading(true);
    try {
      const orderData = {
        side,
        symbol: selectedPair.replace('-', ''),
        type: orderType,
        quantity: parseFloat(amount),
        timeInForce,
        ...(orderType === 'LIMIT' && { price: parseFloat(limitPrice) }),
        ...(orderType === 'STOP_LOSS' && { stopPrice: parseFloat(stopPrice) }),
        ...(orderType === 'STOP_LOSS_LIMIT' && { price: parseFloat(limitPrice), stopPrice: parseFloat(stopPrice) }),
        ...(orderType === 'TAKE_PROFIT' && { stopPrice: parseFloat(stopPrice) }),
        ...(orderType === 'TAKE_PROFIT_LIMIT' && { price: parseFloat(limitPrice), stopPrice: parseFloat(stopPrice) }),
        ...(orderType === 'LIMIT_MAKER' && { price: parseFloat(limitPrice) }),
        ...(orderType === 'OCO' && {
          price: parseFloat(limitPrice), // The price for the limit order
          stopPrice: parseFloat(stopPrice), // The price that triggers the stop order
          stopLimitPrice: parseFloat(stopLimitPrice) // The price for the limit order that is created when the stop is triggered
        }),
        ...(twofaToken && { twofa_token: twofaToken })
      };

      const endpoint = tradingSettings?.test_mode_enabled ? '/api/trading/test-order' : '/api/trading/place-order';
      const response = await axios.post(endpoint, orderData);

      if (response.data.success) {
        alert(`Order placed successfully! Order ID: ${response.data.order?.id || response.data.binance_order_id}`);
        setAmount('');
        setLimitPrice('');
        setStopPrice('');
        setStopLimitPrice('');
        fetchOrderHistory();
      } else {
        alert(`Failed to place order: ${response.data.error}`);
      }
    } catch (error) {
      console.error('Place order error:', error);
      alert('Failed to place order. Please try again.');
    } finally {
      setLoading(false);
      setIs2faModalVisible(false);
    }
  };

  const handleVerify2faAndPlaceOrder = async (code) => {
    try {
      const response = await axios.post('/api/trading/2fa/verify', { code });
      if (response.data.success) {
        await proceedWithOrderPlacement(response.data.token);
      } else {
        throw new Error(response.data.error || 'Invalid 2FA code');
      }
    } catch (error) {
      console.error('2FA verification failed:', error);
      throw new Error(error.response?.data?.error || '2FA verification failed');
    }
  };

  const handlePlaceOrder = async (e) => {
    e.preventDefault();
    if (!amount || !selectedPair) return;

    const orderDetails = {
      side,
      symbol: selectedPair.replace('-', ''),
      type: orderType,
      quantity: parseFloat(amount),
      price: orderType.includes('LIMIT') || orderType === 'OCO' ? parseFloat(limitPrice) : null,
      stopPrice: orderType.includes('STOP') || orderType === 'OCO' ? parseFloat(stopPrice) : null,
      stopLimitPrice: orderType === 'OCO' ? parseFloat(stopLimitPrice) : null,
      estimatedValue: total,
    };

    if (tradingSettings?.require_2fa) {
      setOrderDetailsFor2fa(orderDetails);
      setIs2faModalVisible(true);
    } else {
      await proceedWithOrderPlacement();
    }
  };

  const handleCancelOrder = async (orderId) => {
    if (!confirm('Are you sure you want to cancel this order?')) return;

    try {
      const response = await axios.post(`/api/cancel-order/${orderId}`);
      if (response.data.success) {
        alert('Order cancelled successfully!');
        fetchOrderHistory(); // Refresh order history
      } else {
        alert('Failed to cancel order: ' + response.data.error);
      }
    } catch (error) {
      console.error('Cancel order error:', error);
      alert('Failed to cancel order. Please try again.');
    }
  };

  const getOrderTypeDescription = (type) => {
    switch (type) {
      case 'MARKET': return 'Market: Execute immediately at current price';
      case 'LIMIT': return 'Limit: Execute at specified price or better';
      case 'STOP': return 'Stop: Trigger when price reaches stop level';
      case 'OCO': return 'One-Cancels-Other: Two orders, one cancels the other';
      default: return type;
    }
  };

  const getOrderStatusColor = (status) => {
    switch (status) {
      case 'OPEN': return '#f56565';
      case 'FILLED': return '#48bb78';
      case 'CANCELLED': return '#e53e3e';
      case 'EXPIRED': return '#ed8936';
      default: return '#718096';
    }
  };

  const formatCurrency = (value) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(value);
  };

  const getButtonText = () => {
    const baseCurrency = selectedPair.split('-')[0];
    return `${side} ${baseCurrency}`;
  };

  return (
    <div className="trading-page-container">
      {/* API Key Required Modal */}
      <ApiKeyRequiredModal
        show={showApiKeyModal}
        onClose={() => setShowApiKeyModal(false)}
        isLightMode={isLightMode}
      />
      {/* Trade Permission Modal */}
      <TradePermissionModal
        show={showPermissionModal}
        onClose={() => setShowPermissionModal(false)}
        pageName="trading"
        isLightMode={isLightMode}
      />

      <h1 className="trading-title">Advanced Trading Dashboard</h1>
      <TwoFactorModal
        isVisible={is2faModalVisible}
        onClose={() => setIs2faModalVisible(false)}
        onVerify={handleVerify2faAndPlaceOrder}
        orderDetails={orderDetailsFor2fa}
      />
      {/* Chart placed full-width above grid */}
      <div className="panel" style={{ gridColumn: '1 / -1' }}>
        <TradingChart
          symbol={selectedPair.replace('-', '').includes('USD') ? selectedPair.replace('-', '') : selectedPair.replace('-', '') + 'USDT'}
          onSymbolChange={(newSymbol) => {
            // Convert back to hyphenated format (e.g., "BTCUSDT" -> "BTC-USDT" or "BTCUSD" -> "BTC-USD")
            let baseAsset;
            let quoteAsset;
            if (newSymbol.endsWith('USDT')) {
              baseAsset = newSymbol.replace('USDT', '');
              quoteAsset = 'USDT';
            } else if (newSymbol.endsWith('USD')) {
              baseAsset = newSymbol.replace('USD', '');
              quoteAsset = 'USD';
            } else {
              baseAsset = newSymbol;
              quoteAsset = 'USDT';
            }
            setSelectedPair(`${baseAsset}-${quoteAsset}`);
          }}
          tradingPairs={filteredPairs}
        />
      </div>
      <div className="trading-grid">
        <div className="panel market-data-panel">
          <h3 className="panel-title">Market Data</h3>
          {marketData && (
            <div className="market-stats">
              <div className="stat"><div className="stat-label">Price</div><div className="stat-value">{formatCurrency(marketData.price)}</div></div>
              <div className="stat"><div className="stat-label">24h Change</div><div className={`stat-value ${marketData.change_24h >= 0 ? 'pos' : 'neg'}`}>{marketData.change_24h >= 0 ? '+' : ''}{marketData.change_24h.toFixed(2)}%</div></div>
              <div className="stat"><div className="stat-label">24h High</div><div className="stat-sub">{formatCurrency(marketData.high_24h)}</div></div>
              <div className="stat"><div className="stat-label">24h Low</div><div className="stat-sub">{formatCurrency(marketData.low_24h)}</div></div>
            </div>
          )}
        </div>
        <div className="panel order-panel">
          <h3 className="panel-title">Place Order</h3>
          <form onSubmit={handlePlaceOrder} className="order-form">
            <div className="form-group">
              <label className="field-label">Order Type</label>
              <select value={orderType} onChange={(e) => setOrderType(e.target.value)} className="select-input">
                <option value="MARKET">Market</option><option value="LIMIT">Limit</option><option value="STOP">Stop</option><option value="OCO">OCO (One-Cancels-Other)</option>
              </select>
              <div className="help-text">{getOrderTypeDescription(orderType)}</div>
            </div>
            <div className="form-group">
              <label className="field-label">Side</label>
              <div className="side-toggle">
                <button type="button" onClick={() => setSide('BUY')} className={`side-btn buy ${side === 'BUY' ? 'active' : ''}`}>BUY</button>
                <button type="button" onClick={() => setSide('SELL')} className={`side-btn sell ${side === 'SELL' ? 'active' : ''}`}>SELL</button>
              </div>
            </div>
            <div className="form-group">
              <label className="field-label">Amount (USD)</label>
              <input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Enter amount" className="text-input" step="0.01" min="0" />
              <div className="percent-buttons">
                <button type="button" onClick={() => handlePercentageClick(25)}>25%</button>
                <button type="button" onClick={() => handlePercentageClick(50)}>50%</button>
                <button type="button" onClick={() => handlePercentageClick(100)}>Max</button>
              </div>
            </div>
            {(orderType === 'LIMIT' || orderType === 'OCO') && (
              <div className="form-group"><label className="field-label">Limit Price (USD)</label><input type="number" value={limitPrice} onChange={(e) => setLimitPrice(e.target.value)} className="text-input" step="0.01" min="0" /></div>
            )}
            {(orderType === 'STOP' || orderType === 'OCO') && (
              <>
                <div className="form-group"><label className="field-label">Stop Price (USD)</label><input type="number" value={stopPrice} onChange={(e) => setStopPrice(e.target.value)} className="text-input" step="0.01" min="0" /></div>
                <div className="form-group"><label className="field-label">Stop Limit Price (USD)</label><input type="number" value={stopLimitPrice} onChange={(e) => setStopLimitPrice(e.target.value)} className="text-input" step="0.01" min="0" /></div>
              </>
            )}
            <div className="form-group"><label className="field-label">Execution</label><select value={execution} onChange={(e) => setExecution(e.target.value)} className="select-input"><option value="allow_taker">Allow Taker</option><option value="post_only">Post Only</option></select></div>
            <div className="form-group"><label className="field-label">Time in Force</label><select value={timeInForce} onChange={(e) => setTimeInForce(e.target.value)} className="select-input"><option value="good_til_canceled">Good Til Canceled</option><option value="good_til_time">Good Til Time</option><option value="immediate_or_cancel">Immediate or Cancel</option></select></div>
            <div className="order-summary">
              <div className="row"><span>Subtotal:</span><span>{formatCurrency(subtotal)}</span></div>
              <div className="row"><span>Fee:</span><span>{formatCurrency(fee)}</span></div>
              <div className="row total"><span>Total:</span><span>{formatCurrency(total)}</span></div>
            </div>
            <button type="submit" disabled={loading || !amount} className={`place-order-btn ${side.toLowerCase()} ${loading ? 'loading' : ''}`}>{loading ? 'Placing Order...' : getButtonText()}</button>
          </form>
        </div>
      </div>
      <div className="panel order-history-panel">
        <h3 className="panel-title">Order History</h3>
        <div className="table-scroll">
          <table className="history-table">
            <thead><tr><th>Order ID</th><th>Product</th><th>Side</th><th>Type</th><th>Status</th><th>Filled Size</th><th>Fees</th><th>Created</th><th>Actions</th></tr></thead>
            <tbody>{orderHistory.length === 0 ? (<tr><td colSpan="9" className="empty">No orders found</td></tr>) : orderHistory.map(order => (
              <tr key={order.order_id}>
                <td className="mono small">{order.order_id}</td>
                <td>{order.product_id}</td>
                <td className={`side ${order.side.toLowerCase()}`}>{order.side}</td>
                <td>{order.order_type}</td>
                <td className={`status ${order.status.toLowerCase()}`}>{order.status}</td>
                <td>{order.filled_size || '0'}</td>
                <td>{formatCurrency(order.fees || 0)}</td>
                <td className="small">{new Date(order.created_time).toLocaleDateString()}</td>
                <td>{order.status === 'OPEN' && (<button onClick={() => handleCancelOrder(order.order_id)} className="small-btn cancel-btn">Cancel</button>)}</td>
              </tr>))}
            </tbody>
          </table>
        </div>
      </div>
      {portfolioAnalysis && (<div className="panel"><AIAnalysis data={portfolioAnalysis} /></div>)}
    </div>
  );
}