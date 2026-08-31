import sys

with open("frontend/src/pages/Orders.jsx", "r") as f:
    content = f.read()

old_button = """<button
                      className="btn btn-sm btn-outline-danger"
                      onClick={() => onCancelOrder(order)}
                      disabled={cancellingId === order.id}
                      title="Cancel Order"
                    >"""
                    
new_button = """{getAssetClass(order) === 'option' && (
                      <button
                        className="btn btn-sm btn-outline-primary"
                        style={{ marginRight: '8px' }}
                        onClick={async () => {
                           try {
                             const res = await fetch('/api/options/thesis/export', {
                               method: 'POST',
                               headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('token')}` },
                               body: JSON.stringify({
                                 baseline_price: order.price || 0,
                                 strike_price: order.option_strike || 0,
                                 entry_premium: order.price || 0,
                                 multiplier: 100, iv: 0.1501, risk_free_rate: 0.0379, starting_dte: 18, option_type: order.option_type || 'PUT'
                               })
                             });
                             if (!res.ok) throw new Error('Export failed');
                             const blob = await res.blob();
                             const url = window.URL.createObjectURL(blob);
                             const a = document.createElement('a');
                             a.href = url;
                             a.download = `Thesis_${order.symbol}.xlsx`;
                             a.click();
                           } catch (err) {
                             console.error(err);
                             alert('Failed to export thesis');
                           }
                        }}
                        title="Export Thesis"
                      >
                        Export
                      </button>
                    )}
                    <button
                      className="btn btn-sm btn-outline-danger"
                      onClick={() => onCancelOrder(order)}
                      disabled={cancellingId === order.id}
                      title="Cancel Order"
                    >"""

content = content.replace(old_button, new_button)

with open("frontend/src/pages/Orders.jsx", "w") as f:
    f.write(content)
