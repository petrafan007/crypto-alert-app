# Synthetic review and Binance.US paper funding — v3.9.1

## Conditions and proceeds

The review describes both strategy directions, including each rung, quantity, trigger condition, gross proceeds/cost, estimated fee, net received amount and cumulative values. A full fill on either side consumes the shared quantity; the other side only has the remainder. Protection takes priority when both sides qualify on one observation. Cancel-only protection submits no trade and incurs no trading commission.

SELL trails the highest observed price since activation. BUY trails the lowest. An unmet activation hurdle supplies an explicitly hypothetical starting watermark; an already-satisfied hurdle uses the current reference price. Percentage and amount trails show their corresponding trigger and proceeds calculation. The first activating quote can pass the hurdle, and subsequent peaks/troughs move the trigger.

Trigger-price arithmetic is shown for each independent direction. Actual market proceeds cannot be guaranteed: observed gaps, slippage, changing commission rates and a smaller remaining quantity change the result. Quantities follow the broker increment and the server's rung allocation rules, with any excluded quantity disclosed. USD/USDT prices and monetary totals use two decimal places; asset quantities retain precision.

## Binance.US commission sources

Verified on September 22, 2026:

- [Binance.US fee schedule](https://www.binance.us/fees): standard maker rate 0%, standard taker rate 0.02%; BNB/USD taker rate 0.01%. Account volume tiers can reduce rates.
- [Current US BNB fee-payment policy](https://support.binance.us/en/articles/9842918-using-bnb-to-pay-for-trading-fees): 5% off eligible trading fees when sufficient available BNB pays the fee. Insufficient BNB incurs the regular fee.
- [Binance.US commission API](https://docs.binance.us/#get-account-commission-rates-user_data): signed `GET /api/v3/account/commission`, including standard, side-specific, tax and discount information.
- [Binance.US API reference](https://docs.binance.us/): fallback signed `GET /sapi/v1/asset/query/trading-fee`, matched to the requested symbol. The installed SDK's `get_trade_fee()` uses a different Binance.com endpoint, so the app calls the US endpoint explicitly.

Synthetic orders are strategies managed by this app. Their actual exchange submissions are MARKET orders; each executed child therefore uses the applicable taker commission. No additional fictional “synthetic order fee” is added. No trade means no trading commission.

Live rates come from the account APIs and are refreshed every minute. Missing data produces unavailable estimates rather than a guessed 0.1% fee. Zero rates remain zero. The standard estimate deducts fees from the received asset: quote currency for SELL, base asset for BUY. A separate conditional BNB-payment scenario applies the current US 5% discount to standard commission, without discounting tax or other commission. Final eligibility and BNB conversion depend on funds and prices at execution. Old examples in the API reference mentioning a 25% discount are not used as the current US policy.

A read-only integration check of the connected BTC/USDT account confirmed 0% maker, 0.02% taker and enabled BNB fee payment. No live trade was submitted as part of verification.

Paper simulation uses the published standard schedule without volume or BNB discounts. Every simulated synthetic child records and applies its taker fee in the same database transaction as the fill and balances.

## Paper account controls

Enable Binance.US Test Mode and choose **Deposit Fake Money**. The modal offers 1,000 / 5,000 / 10,000 presets, custom amounts, and separate USD/USDT funding. Deposits add to the current simulated cash balance. Inputs must be positive, finite, at most one billion and have no more than two decimal places.

**Reset Account** requires confirmation. It sets Binance paper balances and holdings to zero and cancels that user's outstanding Binance paper strategies/orders, while retaining history. It leaves live trading, Webull and other users untouched. Funding/reset serialize with Binance synthetic paper executions.

Ordinary paper fills and synthetic fills now use the same transactional ledger and received-asset fee accounting. Ordinary Binance test orders retain their existing immediate-fill simulation behavior, including native limit/OCO tests; synthetic strategies wait for their configured conditions. Paper purchases use simulated funds rather than signed exchange test orders checked against a real account. Public exchange rules and quotes still require connectivity. Paper portfolio cash appears without trading credentials; unavailable market valuations are shown as unavailable.

Webull and Binance share the funding modal, including theme styles, validation, keyboard navigation and confirmation controls. Their account services remain separate.

## Verification and deployment

Tests use isolated in-memory ledgers and mocked broker calls. Coverage includes deposits, currency/account isolation, invalid inputs, confirmed reset, retained history, received-asset fees, multiple synthetic children, ordinary paper purchases, commission endpoint fallback/failure, zero fees and the pinned SDK's initialization behavior.

The browser harness checks six broker/theme strategy scenarios and the actual Binance page in both themes. It covers both-direction confirmation, every rung, activation-hurdle proceeds, two-decimal formatting, presets/custom deposits/reset confirmation, fee/payload wiring, aligned header controls and mobile layout.

```sh
.venv/bin/python -m unittest discover -s tests -p test_binance_paper_fees.py
node tests/synthetic_review.test.mjs
node frontend/src/utils/syntheticOrders.test.mjs
node tests/synthetic_orders.browser.mjs /path/to/playwright
node tests/binance_trading.browser.mjs /path/to/playwright
npm --prefix frontend run build
```

No database schema migration is required for this release. Restart both the application and its worker so the new fee accounting and SDK compatibility fix take effect. This upgrade does not deposit or reset funds automatically.
