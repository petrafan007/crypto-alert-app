# Options UI & Thesis Export Checklist (v2.66.0)

## Phase 1: Interactive Payoff Chart (Frontend)
- [x] Implement Options Payoff Line/Area Chart component.
  - [x] X-axis: Underlying Asset Price.
  - [x] Y-axis: Profit/Loss ($).
  - [x] Calculate and highlight Max Profit and Max Loss boundaries.
  - [x] Display Estimated Premium / Total Debit.
- [x] Implement Draggable Hexagonal Badge Marker.
  - [x] Pin to the underlying price curve.
  - [x] Display: Action (Buy/Sell), Strike/Price, Type (Call/Put).
  - [x] Enable dragging left/right along the X-axis to dynamically probe expected P&L.
- [x] Implement Date/Time DTE Slider.
  - [x] Spans from Day 1 (Entry Date) to Day 0 (Expiration Date).
  - [x] Display the exact date/time corresponding to the slider position.
  - [x] Dynamically recalculate theoretical option pricing (Black-Scholes) as the slider moves to visualize time decay ($\Theta$).

## Phase 2: Excel Thesis Export (Backend/Frontend)
- [x] Implement Excel Workbook Generation Service (using a library like `openpyxl` or `exceljs`).
- [x] Generate `Assumptions` Sheet.
  - [x] Inputs: Baseline price, Strike, Premium, Multiplier, IV, Risk-Free Rate, Expiry, DTE.
  - [x] Outputs: Total Premium at Risk, Expiration Breakeven, Breakeven % Change.
- [x] Generate `Option Price Matrix` Sheet.
  - [x] Rows: 21 percentage steps (+10% down to -10%, with 0% midpoint).
  - [x] Columns: Actual Calendar Dates across the contract duration.
  - [x] Cells: Pre-populate with Excel-compatible Black-Scholes formulas (`NORMSDIST`) tailored for Calls/Puts.
- [x] Generate `P&L Matrix` Sheet.
  - [x] Mirror rows and columns from Option Price Matrix.
  - [x] Calculate net dollar profit/loss per contract.
- [x] Generate `Combined View` Sheet.
  - [x] Display aggregated string formatting: `Estimated Option Price / Net P&L`.
- [x] Ensure universal compatibility for both **Calls** and **Puts**.

## Phase 3: Workflow Integrations
- [x] Pre-Trade Integration.
  - [x] Embed the interactive payoff chart in the options order entry view.
  - [x] Add "Export Thesis" button for scenario preview before purchase.
- [x] Pending Orders / Active Positions Integration.
  - [x] Display real-time liquidation P&L (if closed immediately at current mark).
  - [x] Add "Export Thesis" button for live scenario tracking.
- [x] Hourly Background Thesis Updates.
  - [x] Create a background job to recalculate option scenarios every hour.
  - [x] Update underlying prices and remaining DTE without overloading backend resources.

## Phase 4: Release & Deployment
- [x] Bump version to `2.66.0` (in `README.md`, config, etc.).
- [x] Rebuild the frontend (`npm run build` in `frontend`).
- [x] Commit all changes to GitHub.
- [x] Create and publish GitHub release `v2.66.0`.
- [x] Upgrade the personal instance at `/home/jcavallarojr/crypto_alert_app`.
