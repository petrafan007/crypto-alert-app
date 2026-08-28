# Exchange-Aware Navigation & Account Views — Review Checklist

Status: **Acceptance criteria defined and implemented through v2.43.1**
Scope: Replace the current Binance-centric navigation model with explicit Binance.US, Webull, and All Accounts contexts.

## Confirmed product decisions

- [x] The Dashboard remains the consolidated account overview.
- [x] The Dashboard receives an account selector placed below the navigation and above the dashboard panels, right aligned, defaulting to **All Accounts**.
- [x] Dashboard selector choices are **Binance.US**, **Webull**, and **All Accounts**.
- [x] The existing Trading page becomes the dedicated **Binance.US Trading** page.
- [x] The top-level **Trading** navigation item becomes an extensible exchange selector with **Binance.US** and **Webull** now, leaving room for future providers.
- [x] The top-level **AI Analysis** navigation item is removed.
- [x] Binance.US Trading receives **AI Analysis** as a tab.
- [x] A dedicated **Webull Trading** page is added with Place Order, Open Orders, Order History, Trade Chart, and AI Analysis tabs.
- [x] Webull active order execution is implemented for equities/ETFs, crypto, and contract-level single-leg options (Calls & Puts) with pre-trade risk review, 2FA authentication, and open order cancellation. [Implemented in v2.43.0]
- [x] Webull AI stores provider-neutral, read-only signals: crypto, equities/ETFs, and options use tailored prompt pathways with contract Greeks context, fixed forecast horizons, and immutable grading configurations. Scheduling is opt-in and disabled by default. [Implemented in v2.43.0]
- [x] A new top-level **Orders** destination replaces AI Analysis and provides combined Open Orders and Order History for all accounts.
- [x] Combined order views must visibly retain their exchange/source identity.
- [x] Webull Trading stores a user-selected default account and otherwise prefers an equity/cash account, while each position is resolved within the selected account. [Implemented in v2.39.0]
- [x] Webull assets have full hover and symbol-click parity with Binance.US assets: hovering over a Webull stock, ETF, or crypto in the Portfolio or Watchlist table displays the interactive 7-day performance chart popup (with real-time hourly stock/ETF market data), and clicking the symbol or popup header routes directly to Webull Trading with pre-selected ticker and account. [Implemented in v2.42.0]
- [x] Dashboard supports 1-click Quick Trade for Webull equities/crypto with exchange switching in All Accounts scope, and displays multi-timeframe asset performance (7D, 3D, 1D, 12H, 1H) for Webull holdings when in Webull or All Accounts scope. [Implemented in v2.43.0]
- [x] AI Copilot receives unified multi-asset context spanning Binance.US holdings, cash balances, Webull equities/ETFs/options, full watchlist telemetry, and recent trades with native Binance OCO matching-engine linkage awareness. [Implemented in v2.41.0 & v2.41.1]

## Requirements review checklist

### Navigation and information architecture

- [x] CHK001 The desktop and mobile menu is a `📈 Trading` button followed by **Binance.US** then **Webull**. It opens on click, stays open while moving into the popover, and closes only after a menu choice, outside click, or Escape. [Decision, Implemented]
- [x] CHK002 Canonical routes are `/trading/binance`, `/trading/webull`, and `/orders`. `/trading` remains a Binance.US-compatible route and `/webull-trading` remains a Webull-compatible route. Symbol, side, instrument type, and account deep-link parameters are preserved on the Webull route. [Decision, Implemented]
- [x] CHK003 Both exchange choices remain visible even when one is disconnected. The selected workspace reports its own connection/no-data state and never falls back to the other exchange or treats its assets as tradable there. [Decision, Implemented]
- [x] CHK004 The URL, not a transient menu selection, determines the active trading workspace after refresh. The Dashboard scope persists in browser storage; the Webull default account persists as a user setting. [Decision, Implemented]
- [x] CHK005 `/ai-analysis` redirects to Binance.US Trading’s AI tab. The global navigation has no AI Analysis item, preserving old links without creating a second AI workspace. [Decision, Implemented]

### Dashboard account selector

- [x] CHK006 The selector is right aligned between navigation and dashboard panels, defaults to All Accounts, and requires an equivalent responsive/mobile layout. [Decision]
- [x] CHK007 The selector governs account totals, portfolio value cards, allocations, trend, portfolio table, owned-asset highlighting, risk/quick-trade behavior, performance, and recent activity. Binance-only Watchlist, staking, and execution controls are hidden or replaced with an explicit Webull-scope message. [Decision, Implemented]
- [x] CHK008 **All Accounts** equals Binance.US portfolio value plus each imported Webull account’s net liquidation value. Imported Webull positions remain separate source/account rows; their position value and account cash are never added a second time. Same-symbol holdings are not merged across exchanges, and P&L remains source-specific. [Decision, Implemented]
- [x] CHK009 Portfolio and Watchlist rows show their source identity and asset type. Binance.US rows retain Binance actions and routing; Webull rows use the Webull mark/account pill, support interactive 7-day performance chart hover with stock/ETF market data, and route directly to Webull Trading on symbol click. The Binance watchlist is unavailable in Webull-only scope. [Decision, Implemented in v2.42.0]
- [x] CHK010 A disconnected or empty source shows zero/empty scoped data and a clear connection or no-data message. It never exposes stale data from the other exchange, silently switches scope, or enables the wrong exchange’s action. [Decision, Implemented]
- [x] CHK011 Dashboard scope is saved as `dashboard_account_scope` in browser storage. Webull’s saved default account is independent of Dashboard scope; explicit Portfolio, Watchlist, and mover deep links override it only for the requested Webull action. [Decision, Implemented]

### Binance.US Trading context

- [x] CHK012 Binance.US Trading retains this tab order: Place Order, Open Orders, Order History, Trade Chart, AI Analysis. Its existing Binance.US pair search, balances, order controls, chart, and history remain unchanged. [Decision, Implemented]
- [x] CHK013 The former global AI Analysis content and its settings are retained inside the Binance.US AI Analysis tab. The legacy global URL redirects there. [Decision, Implemented]
- [x] CHK014 Binance.US trading only consumes Binance.US pairs, balances, and orders. Webull holdings/actions carry explicit source/account context and route to Webull; Webull instruments cannot become Binance.US order candidates. [Decision, Implemented]
- [x] CHK015 `/trading` remains Binance.US-compatible, `/trading/binance` is canonical, and existing Binance deep links retain their selected pair/side behavior. [Decision, Implemented]

### Webull Trading context

- [x] CHK016 Webull Place Order supports live execution for equities/ETFs and crypto as of v2.34.0. [Decision]
- [x] CHK017 Webull order placement supports equities/ETFs, crypto, and single-leg options with account selection, pre-trade review, and app 2FA confirmation safeguards. The selected-account Max, quote-value, and percentage controls preserve fractional stock/ETF quantities during Regular Hours (CORE); Webull fractional stock/ETF orders are Market-only, greater than zero and no more than one share, and must meet the $5 minimum. Extended and Overnight stock/ETF sessions require whole shares. Browser and server validation present the same constraint with no silent failure. [Implemented in v2.43.1]
- [x] CHK018 Webull Open Orders and Order History include the instruments Webull returns for the selected account: equities/ETFs, crypto, options, futures, and multi-leg/combo orders. Multi-leg responses are flattened into their executable legs; each keeps Webull/account identity and remains managed only through Webull. [Decision, Implemented]
- [x] CHK019 Webull Trade Chart supports imported equities/ETFs, crypto, and contract-mapped options with their own Webull historical bars and completed order markers. Option quote/Greeks data uses a dedicated endpoint and reports missing OPRA entitlement without substituting the underlying. Futures remain out of scope. [Decision]
- [x] CHK020 Webull crypto and equities/ETFs use separated prompt families and a provider-neutral stored-signal lifecycle. Scheduled runs are opt-in; no Webull signal can place, amend, or cancel an order. Options now have contract-level chart/quote identity but remain unavailable to AI pending an options-specific prompt and risk model. [Decision]
- [x] CHK021 Expired authorization, entitlement, rate-limit, unsupported-account, or unavailable-data responses show an explicit Webull notice, retain any safely loaded data, and never substitute Binance.US data. Webull order reads are cached/rate-limited and merge progressively where possible. [Decision, Implemented]

### Combined Orders destination

- [x] CHK022 Combined Orders opens on **Open Orders** and provides **Order History** as the second tab. History is fetched on demand from the persisted order/activity ledger, never by an exchange-wide API scan; Open Orders begins with Binance.US plus app automation and progressively merges Webull account results. [Decision, Implemented in v2.40.2]
- [x] CHK023 The Account column contains only the owning account and is centered: `Binance.US` for Binance and app automation, and the connected Webull account’s masked label for Webull. Automation identity remains visible in the existing Side/Type fields, not the Account column. Rows sort newest-first within both tabs. [Decision, Implemented in v2.40.2]
- [x] CHK024 Combined Orders provides client-side filters for source, account, symbol, product type (crypto, stock/ETF, option, future, automation, other), status, and time range (24 hours, 7/30/90 days, all). Filters apply consistently to Open Orders and History without triggering additional exchange reads; app-managed orders are recognized from either current automation fields or legacy `AUTO_BUY`/`AUTO_SELL` order types. [Implemented in v2.40.1]
- [x] CHK025 Cancellation behavior is constrained to the owning exchange and account (routed to Webull OpenAPI or Binance.US with no cross-exchange fallback). Combined Orders and Webull Open Orders use the shared theme-aware native cancellation modal, show the precise provider/account/order or trigger details, and require a six-digit 2FA code; Webull and app-trigger cancellation endpoints enforce enabled 2FA server-side. [Implemented in v2.40.3]
- [x] CHK026 Combined Orders renders Binance.US-native orders and active in-app Auto-Buy/Auto-Sell triggers first; rate-limited Webull account reads merge progressively with in-view account progress, while history loads on demand. [Implemented in v2.39.1]

### Data integrity, security, and release scope

- [x] CHK027 Binance.US balances/orders are fetched from Binance.US; active Auto-Buy/Auto-Sell triggers are app records; Webull holdings use the latest imported snapshot; Webull quotes use the signed basic snapshot and refresh every 30 seconds; and Webull orders use signed, short-lived cached reads. [Decision, Implemented]
- [x] CHK028 Dashboard totals use account net liquidation values for Webull and do not add imported position values/cash a second time. Allocation/table rows keep source/account identity and never merge same-symbol positions across exchanges. [Decision, Implemented]
- [x] CHK029 Webull account/holding snapshots are upserted by user/account/instrument on import, stale rows from the imported account set are removed on a successful replacement snapshot, and schema additions use idempotent application migrations. Combined Order History is a database-only view of the existing `real_orders` and `all_activities` ledger; entering it never creates a second ledger or reads an exchange API. [Decision, Implemented in v2.40.2]
- [x] CHK030 Credentials, secrets, access tokens, and signed-request material remain encrypted and server-only. The browser receives only the minimally required non-secret account reference/masked label to select and scope a Webull action; it never receives a token or signing secret. [Decision, Implemented]
- [x] CHK031 Navigation controls expose menu/tab/select semantics, labels, keyboard focus, and Escape dismissal. Async Webull refresh progress uses a status announcement, while responsive layouts preserve operable controls on mobile. [Decision, Implemented]
- [x] CHK032 Initial Combined Orders loading must not block on sequential multi-account Webull reads or the exchange-wide history scan. [Implemented in v2.38.5]
- [x] CHK033 Every release updates the visible package/footer version, README, and applicable checklist/help text; then builds, verifies, commits/pushes, publishes a GitHub tag/release, deploys the exact tag to the personal instance, restarts the service, and verifies local/public health. If one provider fails, its explicit error state is retained while the other provider remains isolated and operational; rollback is the preceding tagged release after preserving local deployment changes. [Decision, Implemented]

## Implementation sequence

1. [x] Define shared exchange/account context and Dashboard selector behavior.
2. [x] Split the existing Binance.US Trading experience and embed its AI Analysis tab.
3. [x] Add the dedicated Webull trading shell with explicitly approved capabilities.
4. [x] Add the combined Orders center with source- and account-safe data handling.
5. [x] Update Help, test all context-switching and empty/error states, then release and upgrade.

## Decisions and acceptance status

All navigation, account-scope, exchange-boundary, order-view, data-integrity, accessibility, and release acceptance rules are now resolved and checked above. Future releases should add a new unchecked checklist item only for a genuinely new, undecided capability.
