import React from 'react';
import { money, number } from '../utils/syntheticOrders.mjs';
import './SyntheticOrders.css';

export function ExecutionProceeds({ row, review }) {
  const { quoteAsset: quote, baseAsset: base, side } = review;
  return <div className="synthetic-proceeds">
    <span>{side === 'SELL' ? 'Sell' : 'Buy'} {number(row.quantity)} {base} at {money(row.price, quote)}</span>
    <span>{side === 'SELL' ? 'Gross proceeds' : 'Purchase cost'}: <strong>{money(row.gross, quote)}</strong></span>
    <span>Est. taker fee {row.rate !== null ? `(${number(row.rate * 100)}%)` : ''}: <strong>{row.fee === null ? 'Unavailable' : money(row.fee, quote)}</strong>{side === 'BUY' && row.rate !== null ? ` (${number(row.quantity * row.rate)} ${base})` : ''}</span>
    <span>{side === 'SELL' ? 'Net proceeds' : 'Net asset received'}: <strong>{side === 'SELL' ? money(row.net, quote) : row.netQuantity === null ? 'Unavailable' : `${number(row.netQuantity)} ${base}`}</strong></span>
    {row.cumulativeGross !== undefined && <span>Cumulative gross: {money(row.cumulativeGross, quote)} · Fees: {money(row.cumulativeFee, quote)} · Net value: {money(row.cumulativeNet, quote)}</span>}
    {row.bnbFee !== null && row.bnbFee !== undefined && <small>If eligible BNB covers the fee: {money(row.bnbFee, quote)} equivalent paid separately in BNB; {side === 'SELL' ? `cash proceeds ${money(row.gross, quote)}, economic net ${money(row.bnbNet, quote)}` : `receive ${number(row.quantity)} ${base} before any non-BNB adjustments`}. Available BNB and its conversion price at execution determine eligibility.</small>}
  </div>;
}

export default function SyntheticOrderReview({ review, branchOnly }) {
  if (!review) return null;
  const branches = branchOnly ? review.branches.filter(b => b.prefix === branchOnly) : review.branches;
  return <div className="synthetic-review">
    {!branchOnly && <>
      <p><strong>Exact trigger rules and estimated execution values</strong></p>
      <p>Both directions share {number(review.total)} {review.baseAsset}. After any fill, the other direction can execute only the remainder. When both sides qualify on one observation, protection is processed first. A complete fill cancels unused steps.</p>
      {review.requested !== review.total && <p>Requested {number(review.requested)} {review.baseAsset}; the broker quantity increment leaves {number(review.requested - review.total)} {review.baseAsset} outside this strategy.</p>}
      {!review.quantityStep && <p>Broker quantity increments are unavailable; displayed quantities are provisional until server validation.</p>}
    </>}
    {branches.map(branch => <section className="synthetic-review-branch" key={branch.prefix}>
      {!branchOnly && <h4>{branch.label} · {branch.mode}</h4>}
      <p>{branch.explanation}</p>
      {branch.rows.map((row, index) => <div className="synthetic-review-step" key={index}>
        <strong>{row.name}: {row.condition}</strong>
        <ExecutionProceeds row={row} review={review} />
        {row.remaining && <small>Values use the full currently configured quantity. For a smaller remainder, gross = remaining quantity × trigger price; fee = gross × the applicable rate.</small>}
      </div>)}
    </section>)}
    {!branchOnly && <>
      <p>Each direction is a separate scenario assuming its listed fills occur at those trigger prices. Do not add the two directions together. A gap can execute multiple rungs at one observed market price. Actual market fills, fees and future trailing peaks can differ.</p>
      <p>{review.fees ? `${review.fees.source}. Rate checked ${new Date(review.fees.as_of).toLocaleString()}.` : 'Account fee data is unavailable; net values are not assumed.'} {review.fees?.paper ? 'Paper fees use the published standard schedule without BNB discounts.' : 'Base estimates deduct the fee from the received asset; eligible BNB payment is shown separately.'}</p>
    </>}
  </div>;
}
