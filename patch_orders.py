import sys

with open("frontend/src/pages/Orders.jsx", "r") as f:
    content = f.read()

# Replace table header
old_header = '<th>Date / Time</th><th className="combined-order-account-heading">Account</th><th>Symbol</th><th>Side</th><th>Type</th><th>Quantity</th><th>Price</th><th>Filled</th><th>Fee</th><th>Status</th>\n              {open && <th>Actions</th>}'
new_header = '<th>Date / Time</th><th className="combined-order-account-heading">Account</th><th>Symbol</th><th>Side</th><th>Type</th><th>Quantity</th><th>Price</th><th>Filled</th><th>Fee</th><th>Status</th>\n              {open && <th>Est. P&L (if filled)</th>}\n              {open && <th>Actions</th>}'
content = content.replace(old_header, new_header)

old_body = """                <td>{formatOrderStatus(order.status, order.status)}</td>
                {open && (
                  <td>
                    <button"""

new_body = """                <td>{formatOrderStatus(order.status, order.status)}</td>
                {open && (
                  <td>
                    {(() => {
                      if (getAssetClass(order) === 'option' && String(order.side).includes('SELL')) {
                         const costBasis = order.cost_price || order.avg_price || 0;
                         const currentPx = order.price || order.limit_price || 0;
                         if (costBasis > 0 && currentPx > 0) {
                           const pnl = (currentPx - costBasis) * 100 * order.quantity;
                           return <span style={{color: pnl >= 0 ? '#10b981' : '#ef4444'}}>{pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}</span>;
                         }
                      }
                      return '—';
                    })()}
                  </td>
                )}
                {open && (
                  <td>
                    <button"""

content = content.replace(old_body, new_body)

with open("frontend/src/pages/Orders.jsx", "w") as f:
    f.write(content)
