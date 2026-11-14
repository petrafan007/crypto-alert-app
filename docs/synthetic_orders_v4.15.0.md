# Synthetic stock and ETF orders in extended hours (v4.15.0)

Webull stock and ETF synthetic orders (Ladder / Trailing Stop, single targets, and the Stop Loss and OCO forms below) can now run in **Regular + Extended Hours**, not only in Regular Hours. This updates the session rule in [synthetic_orders_v3.9.0.md](synthetic_orders_v3.9.0.md).

## Sessions

| Trading Session on the order | When the app watches the price | Price source |
|---|---|---|
| Only Regular Hours (CORE) | 9:30 AM – 4:00 PM ET on trading days | Webull snapshot |
| Including Extended Hours (ALL) | 4:00 AM – 8:00 PM ET on trading days (after-hours ends 5:00 PM ET on early-close days) | Webull in regular hours; Yahoo Finance in pre-market and after-hours |
| Overnight (NIGHT) | Not supported: no overnight price feed is available | — |

Trading days, holidays and early closes come from the exchange calendar (`services/market_calendar_service.py`, `equity_session_phase`).

## What is sent when a trigger is reached

- **Regular hours:** a Market order, as before.
- **Pre-market and after-hours:** Webull accepts only whole-share Limit orders, so the app sends a Limit order priced past the trigger by the order's **price cap** (default 1%, allowed 0.1%–5%): a buy at trigger + cap, a sell at trigger − cap. It fills like a market order but never beyond the cap.
- If that Limit order has not filled after **5 minutes**, it is cancelled at Webull and the strategy stops with that reason. Review any partial fill before creating a new order.
- Extended-hours orders require whole shares; fractional quantities are refused when the order is created.

## Price data

Webull's basic snapshot reports only the regular-session last trade, so pre-market and after-hours triggers use Yahoo Finance one-minute extended-hours bars (`services/extended_hours_quote_service.py`). A Yahoo price older than 5 minutes is refused, so nothing triggers on an old quote. While the market is closed, a new order is checked against Yahoo's last after-hours price, which is more current than the regular close. Yahoo's data is unofficial and can lag.

## In the order ticket

- **Single Order, Trading Session = Including Extended Hours:** Stop Loss and Ladder / Trailing Stop are available and marked **(Synthetic)**. A synthetic Stop Loss is one trigger for the whole quantity: a Buy stop must be above the current price, a Sell stop below it. A price-cap field appears and the confirmation dialog explains the synthetic behaviour.
- **Conditional Orders while the market is closed:** a valid two-leg OCO (same side, same whole-share quantity, one trigger above and one below the market) is offered as a **Synthetic OCO**: whichever trigger is reached first executes the whole quantity and the other is dropped. A Stop Loss Limit leg's limit price is replaced by the price cap.
- Synthetic orders cannot replace a pending Webull order from the Replace Pending Order dialog.

## Limitations

- Synthetic orders run only while the app's server and workers are running.
- A price gap past the trigger fills only within the cap; otherwise the order times out.
- Synthetic Stop Loss Limit (with its own limit price) is not offered.
