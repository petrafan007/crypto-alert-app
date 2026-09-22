import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { Link } from 'react-router-dom';
import { isWorking, number, strategyKind, orderKey } from '../utils/syntheticOrders.mjs';
import './SyntheticOrders.css';

export default function SyntheticOrdersWidget() {
  const [orders, setOrders] = useState([]), [broker, setBroker] = useState('all'), [error, setError] = useState('');
  useEffect(() => {
    let stopped = false, pending = false;
    const controller = new AbortController();
    const load = async () => {
      if (pending) return;
      pending = true;
      const results = await Promise.allSettled(['ladder', 'trailing'].map(name => axios.get(`/api/trading/${name}-orders`, { withCredentials: true, signal: controller.signal })));
      if (stopped) return;
      const failed = results.some(r => r.status !== 'fulfilled' || !r.value.data?.success);
      setError(failed ? 'Some synthetic orders could not be refreshed. Open order management to review.' : '');
      if (!failed) setOrders(results.flatMap((result, index) => (result.value.data[index ? 'trailing_orders' : 'ladder_orders'] || []).map(o => ({ ...o, parentKind: index ? 'TRAILING' : 'LADDER' }))).filter(o => isWorking(o.status) || ['FAILED', 'NEEDS_REVIEW'].includes(o.status)));
      pending = false;
    };
    load(); const timer = setInterval(load, 15000);
    return () => { stopped = true; controller.abort(); clearInterval(timer); };
  }, []);
  const filtered = orders.filter(o => broker === 'all' || o.broker === broker);
  return <div className="synthetic-orders widget-panel-inner" style={{ padding: 16, height: '100%', overflow: 'auto', boxSizing: 'border-box' }}>
    <h3>Synthetic orders</h3><div className="synthetic-filters"><label>Broker<select value={broker} onChange={e => setBroker(e.target.value)}><option value="all">All brokers</option><option value="binance">Binance.US</option><option value="webull">Webull</option></select></label></div>
    {error && <p role="alert" className="synthetic-warning">{error}</p>}
    {!filtered.length && <p>No active orders or orders needing review.</p>}
    {filtered.map(o => <div className="synthetic-step" key={orderKey(o)}>
      <strong>{o.symbol} · {o.side}</strong><small>{o.broker === 'webull' ? 'Webull' : 'Binance.US'} · {o.test_mode ? 'Paper' : 'Live'} · {strategyKind(o).toLowerCase()}</small>
      <small>{o.status.replaceAll('_', ' ')} · {o.execution_history_verified === false ? 'Legacy fills unverified' : `${number(o.filled_quantity || 0)} / ${number(o.total_quantity ?? o.quantity)} filled`}</small>
      {o.monitoring_error && <small className="synthetic-warning">{o.monitoring_error}</small>}
    </div>)}
    <p><Link to="/orders?tab=synthetic_orders">Manage synthetic orders →</Link></p><small>Refreshes every 15 seconds</small>
  </div>;
}
