import React from 'react';
import { formatEasternDateTime as formatEasternDateTimeValue } from '../utils/dateTime';
import { formatOrderSide, formatOrderStatus, formatOrderType } from '../utils/orderDisplay';

const number = (value, digits = 6) => Number.isFinite(Number(value))
  ? Number(value).toLocaleString(undefined, { maximumFractionDigits: digits })
  : '—';

const money = (value, currency = 'USD') => {
  if (!Number.isFinite(Number(value))) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency || 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(Number(value));
};

const friendly = (value, fallback = '—') => {
  const text = String(value || '').trim();
  if (!text) return fallback;
  return text.replaceAll('_', ' ').toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase());
};

const orderCategory = (order = {}) => {
  const hint = String(order.instrument_type || order.asset_class || order.security_type || '').toUpperCase();
  const symbol = String(order.symbol || order.ticker || '').toUpperCase();
  if (hint.includes('EVENT') || symbol.startsWith('KX')) return ['event', 'Event Contract'];
  if (hint.includes('OPTION')) return ['option', 'Option'];
  if (hint.includes('FUTURE')) return ['future', 'Futures'];
  if (hint.includes('CRYPTO') || hint.includes('COIN') || hint.includes('TOKEN')) return ['crypto', 'Crypto'];
  if (hint.includes('ETF')) return ['equity', 'ETF'];
  if (hint.includes('STOCK') || hint.includes('EQUITY') || hint.includes('SECURITY')) return ['equity', 'Equity'];
  return [String(order.source || '').toLowerCase() === 'binance' ? 'crypto' : 'other', 'Order'];
};

const optionDetails = (order = {}) => {
  const raw = String(order.symbol || order.ticker || '').trim().toUpperCase();
  const parsed = raw.match(/^([A-Z][A-Z0-9.]*)\s+(\d{4}-\d{2}-\d{2})\s+\$?([\d.]+)\s+(CALL|PUT)$/);
  const expiration = order.option_expiration || order.option_expire_date || order.expiration_date || parsed?.[2];
  const strike = order.option_strike ?? order.strike_price ?? parsed?.[3];
  const optionType = order.option_type || parsed?.[4];
  const parts = [];
  if (expiration) parts.push(String(expiration).slice(0, 10));
  if (strike !== undefined && strike !== null && strike !== '') parts.push(`${money(strike)} strike`);
  if (optionType) parts.push(friendly(optionType));
  return { symbol: parsed?.[1] || raw || '—', details: parts.join(' · ') };
};

const accountName = (order, accounts = []) => {
  const accountId = String(order.webull_account_id || order._webull_account_id || order.account_id || '').trim();
  if (String(order.source || order.origin || '').toLowerCase() !== 'webull') return 'Binance.US';
  const account = accounts.find((candidate) => String(candidate.account_id) === accountId);
  const label = account?.account_label || account?.account_name || order.webull_account_type || 'Webull account';
  const masked = account?.account_id_masked || (accountId ? `••••${accountId.slice(-4)}` : '');
  return masked ? `${label} (${masked})` : label;
};

export const unifiedOrderRow = (order, accounts = []) => {
  const [categoryKey, categoryLabel] = orderCategory(order);
  const option = optionDetails(order);
  const source = String(order.source || order.origin || '').toLowerCase();
  const isWebull = source === 'webull';
  const accountId = String(order.webull_account_id || order._webull_account_id || order.account_id || '').trim();
  return {
    id: `order-${source}-${order.id || order.order_id || order.orderId}`,
    recordKind: 'order',
    source: source === 'automation' || ['auto_buy', 'auto_sell'].includes(source) ? 'automation' : (isWebull ? 'webull' : 'binance'),
    sourceLabel: isWebull ? 'Webull' : (source === 'automation' ? 'Automation' : 'Binance.US'),
    accountId,
    accountLabel: accountName(order, accounts),
    date: order.created_at || order.create_time || order.placed_time || order.place_time || order.filled_time_at || order.time,
    categoryKey,
    categoryLabel,
    symbol: option.symbol,
    instrument: option.symbol,
    details: option.details,
    direction: formatOrderSide(order.side, friendly(order.side)),
    type: formatOrderType(order.order_type || order.type, friendly(order.order_type || order.type)),
    quantity: number(order.quantity ?? order.total_quantity ?? order.order_quantity),
    amount: null,
    currency: 'USD',
    price: Number(order.price ?? order.limit_price ?? order.order_price) > 0 ? money(order.price ?? order.limit_price ?? order.order_price) : 'Market',
    filled: number(order.filled_quantity ?? order.executed_quantity ?? order.filled_qty),
    fee: Number(order.fee ?? order.commission) > 0 ? money(order.fee ?? order.commission) : '—',
    status: formatOrderStatus(order.status || order.order_status, friendly(order.status || order.order_status)),
  };
};

export const unifiedActivityRow = (activity) => {
  const amountValue = Number(activity.net_amount);
  const activityType = friendly(activity.activity_type, 'Activity');
  const subType = friendly(activity.activity_sub_type, '');
  const explicitEvent = String(activity.activity_category || '').toUpperCase() === 'EVENT_CONTRACT';
  const categoryLabel = explicitEvent ? 'Event Contract' : activityType;
  const categoryKey = explicitEvent ? 'event' : 'activity';
  const symbol = String(activity.symbol || '').toUpperCase();
  const eventDetails = explicitEvent ? [
    activity.event_name,
    activity.yes_condition,
    activity.settle_side ? `${activity.settle_side} position` : null,
    activity.settle_result ? `Result: ${activity.settle_result}` : null,
    Number.isFinite(Number(activity.settle_quantity)) ? `${number(activity.settle_quantity)} contracts` : null,
  ].filter(Boolean).join(' · ') : '';
  return {
    id: `activity-webull-${activity.id}`,
    recordKind: 'activity',
    source: 'webull',
    sourceLabel: 'Webull',
    accountId: String(activity.account_id || ''),
    accountLabel: activity.account_label || activity.account_id_masked || 'Webull account',
    date: activity.biz_time || activity.trade_date,
    categoryKey,
    categoryLabel,
    symbol,
    instrument: symbol || activity.event_name || subType || activityType,
    details: eventDetails || (symbol && subType ? subType : ''),
    direction: Number.isFinite(amountValue) ? (amountValue > 0 ? 'Credit' : (amountValue < 0 ? 'Debit' : '—')) : '—',
    type: subType || activityType,
    quantity: '—',
    amount: Number.isFinite(amountValue) ? amountValue : null,
    currency: activity.currency || 'USD',
    price: '—',
    filled: '—',
    fee: '—',
    status: 'Completed',
  };
};

export const unifiedBinanceActivityRow = (activity) => {
  const exchange = String(activity.exchange || 'binance').toLowerCase();
  const isBinance = exchange === 'binance' || exchange === 'binance.us' || exchange === 'coinbase';
  const type = String(activity.type || 'ACTIVITY').toUpperCase();
  const asset = String(activity.asset || '—').toUpperCase();
  const isTrade = ['BUY', 'SELL'].includes(type);
  const quantity = Number.isFinite(Number(activity.amount)) ? `${number(activity.amount)} ${asset}` : '—';
  return {
    id: `activity-${exchange}-${activity.id}`,
    recordKind: 'activity',
    source: isBinance ? 'binance' : 'automation',
    sourceLabel: isBinance ? 'Binance.US' : friendly(exchange, 'Application'),
    accountId: isBinance ? 'binance' : exchange,
    accountLabel: isBinance ? 'Binance.US' : 'Application activity',
    date: activity.date,
    categoryKey: isTrade ? 'crypto' : 'activity',
    categoryLabel: isTrade ? 'Crypto Trade' : friendly(type, 'Activity'),
    symbol: asset,
    instrument: asset,
    details: activity.description || '',
    direction: type === 'BUY' ? 'Buy' : type === 'SELL' ? 'Sell' : friendly(type),
    type: friendly(type),
    quantity,
    amount: null,
    currency: 'USD',
    price: Number(activity.price_sold_at) > 0 ? money(activity.price_sold_at) : '—',
    filled: isTrade ? quantity : '—',
    fee: Number(activity.fee) > 0 ? money(activity.fee) : '—',
    status: friendly(activity.status, 'Completed'),
  };
};

export const buildUnifiedTransactionRows = (orders = [], activities = [], accounts = [], binanceActivities = []) => [
  ...orders.map((order) => unifiedOrderRow(order, accounts)),
  ...activities.map(unifiedActivityRow),
  ...binanceActivities.map(unifiedBinanceActivityRow),
];

export default function UnifiedTransactionTable({ rows = [], emptyMessage = 'No transactions are available.' }) {
  if (!rows.length) return <div className="empty-state"><p>{emptyMessage}</p></div>;
  return (
    <div className="table-container trading-table">
      <div className="order-table-scroll">
        <table className="unified-transaction-table">
          <thead><tr>
            <th>Date / Time (ET)</th><th>Source / Account</th><th>Category</th><th>Instrument / Details</th>
            <th>Direction</th><th>Type</th><th>Quantity / Amount</th><th>Price</th><th>Filled</th><th>Fee</th><th>Status</th>
          </tr></thead>
          <tbody>{rows.map((row) => (
            <tr key={row.id}>
              <td>{formatEasternDateTimeValue(row.date)}</td>
              <td><strong>{row.sourceLabel}</strong><small>{row.accountLabel}</small></td>
              <td>{row.categoryLabel}</td>
              <td><strong>{row.instrument || '—'}</strong>{row.details && <small>{row.details}</small>}</td>
              <td>{row.direction}</td><td>{row.type}</td>
              <td>{row.amount !== null ? money(row.amount, row.currency) : row.quantity}</td>
              <td>{row.price}</td><td>{row.filled}</td><td>{row.fee}</td><td>{row.status}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  );
}
