# Exchange-Aware Navigation & Account Views — Review Checklist

Status: **Implemented through v2.39.0 — reviewed product decisions applied**
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
- [x] Webull active order execution is implemented in v2.34.0 for equities/ETFs and crypto with pre-trade review and open order cancellation; options execution remains staged pending options risk model.
- [x] Webull AI stores provider-neutral, read-only signals: crypto and equities/ETFs use distinct prompt families, fixed forecast horizons, immutable grading configurations, and the same manual/scheduled lifecycle. Scheduling is opt-in and disabled by default; options now have contract-level chart/quote identity but remain unavailable to AI pending an options-specific risk model.
- [x] A new top-level **Orders** destination replaces AI Analysis and provides combined Open Orders and Order History for all accounts.
- [x] Combined order views must visibly retain their exchange/source identity.
- [x] Webull Trading stores a user-selected default account and otherwise prefers an equity/cash account, while each position is resolved within the selected account. [Implemented in v2.39.0]

## Requirements review checklist

### Navigation and information architecture

- [ ] CHK001 Are the exact labels, order, and visual behavior of the Trading exchange menu specified for desktop and mobile? [Clarity, Gap]
- [ ] CHK002 Is the route/deep-link behavior defined for Binance.US Trading, Webull Trading, and the combined Orders destination? [Completeness, Gap]
- [ ] CHK003 Are the fallback and active-state requirements specified if only one exchange is connected? [Scenario Coverage, Gap]
- [ ] CHK004 Is it explicit whether the exchange selected in Trading should persist across refreshes and browser sessions? [Ambiguity, Gap]
- [ ] CHK005 Are the navigation requirements consistent with removal of the global AI Analysis route, including existing direct links and bookmarks? [Consistency, Gap]

### Dashboard account selector

- [x] CHK006 The selector is right aligned between navigation and dashboard panels, defaults to All Accounts, and requires an equivalent responsive/mobile layout. [Decision]
- [ ] CHK007 Are the dashboard panels governed by the selector enumerated, including value cards, allocations, trend, portfolio table, movers, performance, and recent activity? [Completeness, Gap]
- [ ] CHK008 Is the All Accounts aggregation rule defined for cash, account net liquidation value, holdings, P&L, allocations, and duplicate symbols across exchanges? [Completeness, Gap]
- [ ] CHK009 Are the expected source badges and exchange-specific row behavior specified for each dashboard table? [Clarity, Gap]
- [ ] CHK010 Is the no-data behavior specified for an exchange that is disconnected, has no accounts, or returns an empty portfolio? [Scenario Coverage, Gap]
- [ ] CHK011 Are account-selection persistence and cross-page interaction requirements specified? [Ambiguity, Gap]

### Binance.US Trading context

- [ ] CHK012 Are the exact Binance.US tab order and retained behaviors specified: Place Order, Open Orders, Order History, Trade Chart, and AI Analysis? [Completeness]
- [ ] CHK013 Is the scope of the moved AI Analysis tab defined, including whether all current AI Analysis content and settings move unchanged? [Clarity, Gap]
- [ ] CHK014 Are Binance-only safeguards specified so Webull symbols, balances, and orders cannot appear as Binance-tradable items? [Consistency, Safety]
- [ ] CHK015 Are backwards-compatibility requirements defined for existing `/trading` links, saved browser locations, and dashboard links to Binance pairs? [Scenario Coverage, Gap]

### Webull Trading context

- [x] CHK016 Webull Place Order supports live execution for equities/ETFs and crypto as of v2.34.0. [Decision]
- [x] CHK017 Webull order placement supports Equities, ETFs, and Crypto with Market and Limit order types, account selection, pre-trade review modal, and confirmation safeguards. [Implemented in v2.34.0]
- [ ] CHK018 Are the Webull Open Orders and Order History inclusion rules defined for equities, options, futures, crypto, and multi-leg/combo orders? [Completeness, Gap]
- [x] CHK019 Webull Trade Chart supports imported equities/ETFs, crypto, and contract-mapped options with their own Webull historical bars and completed order markers. Option quote/Greeks data uses a dedicated endpoint and reports missing OPRA entitlement without substituting the underlying. Futures remain out of scope. [Decision]
- [x] CHK020 Webull crypto and equities/ETFs use separated prompt families and a provider-neutral stored-signal lifecycle. Scheduled runs are opt-in; no Webull signal can place, amend, or cancel an order. Options now have contract-level chart/quote identity but remain unavailable to AI pending an options-specific prompt and risk model. [Decision]
- [ ] CHK021 Are read-only degradation requirements specified for expired Webull authorization, API rate limits, or unsupported Webull account types? [Exception Coverage, Gap]

### Combined Orders destination

- [ ] CHK022 Is the combined Orders page’s exact tab structure and default tab defined? [Clarity, Gap]
- [ ] CHK023 Are source labels, account labels, product/instrument labels, and sort precedence specified for a mixed order ledger? [Completeness, Gap]
- [ ] CHK024 Are filters specified for exchange, account, symbol, product type, status, and time range? [Completeness, Gap]
- [x] CHK025 Cancellation behavior is explicitly constrained to the owning exchange and account (routed to Webull OpenAPI or Binance.US with no cross-exchange fallback). [Implemented in v2.34.0]
- [x] CHK026 Combined Orders renders Binance.US open orders first; rate-limited Webull account reads merge progressively with in-view account progress, while history loads on demand. [Implemented in v2.39.0]

### Data integrity, security, and release scope

- [ ] CHK027 Is the source-of-truth and refresh policy defined for imported holdings and dynamic order data from each exchange? [Completeness, Gap]
- [ ] CHK028 Are total-value and allocation calculations protected against double-counting Webull position values and account cash? [Consistency, Safety]
- [ ] CHK029 Are data-retention and migration requirements specified for existing Webull snapshots and prior combined-order behavior? [Dependency, Gap]
- [ ] CHK030 Are credentials, tokens, and account identifiers required to remain server-only across every new exchange-aware surface? [Security]
- [ ] CHK031 Are accessibility requirements specified for the new menus, selector, tab sets, keyboard navigation, focus states, and status announcements? [Non-Functional, Gap]
- [x] CHK032 Initial Combined Orders loading must not block on sequential multi-account Webull reads or the exchange-wide history scan. [Implemented in v2.38.5]
- [ ] CHK033 Is the release/version plan defined, including documentation updates and a rollback path if one provider is unavailable after deployment? [Release Readiness, Gap]

## Implementation sequence

1. [x] Define shared exchange/account context and Dashboard selector behavior.
2. [x] Split the existing Binance.US Trading experience and embed its AI Analysis tab.
3. [x] Add the dedicated Webull trading shell with explicitly approved capabilities.
4. [x] Add the combined Orders center with source- and account-safe data handling.
5. [x] Update Help, test all context-switching and empty/error states, then release and upgrade.

## Decisions still needed before implementation

All initial product decisions are resolved. The remaining checklist items are implementation-detail and acceptance-criteria review points.
