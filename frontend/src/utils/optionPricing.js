export function optionIntrinsic(underlyingPrice, strikePrice, optionType) {
  return optionType === 'CALL'
    ? Math.max(underlyingPrice - strikePrice, 0)
    : Math.max(strikePrice - underlyingPrice, 0);
}

export function americanOptionPrice({
  underlyingPrice,
  strikePrice,
  dte,
  riskFreeRate,
  iv,
  optionType,
  dividendYield = 0,
}) {
  if (dte <= 0) return optionIntrinsic(underlyingPrice, strikePrice, optionType);

  const years = dte / 365;
  const safeIv = Math.max(Number(iv) || 0, 0.000000001);
  const steps = Math.max(50, Math.min(200, Math.trunc(dte) * 4));
  const timeStep = years / steps;
  const up = Math.exp(safeIv * Math.sqrt(timeStep));
  const down = 1 / up;
  const growth = Math.exp((riskFreeRate - dividendYield) * timeStep);
  const probability = (growth - down) / (up - down);
  if (!(probability >= 0 && probability <= 1)) return null;
  const discount = Math.exp(-riskFreeRate * timeStep);

  let optionValues = Array.from({ length: steps + 1 }, (_, index) => {
    const assetPrice = underlyingPrice * (up ** (steps - index)) * (down ** index);
    return optionIntrinsic(assetPrice, strikePrice, optionType);
  });

  for (let step = steps - 1; step >= 0; step -= 1) {
    optionValues = Array.from({ length: step + 1 }, (_, index) => {
      const continuation = discount * (
        probability * optionValues[index]
        + (1 - probability) * optionValues[index + 1]
      );
      const assetPrice = underlyingPrice * (up ** (step - index)) * (down ** index);
      return Math.max(continuation, optionIntrinsic(assetPrice, strikePrice, optionType));
    });
  }
  return optionValues[0];
}

export function deriveImpliedVolatility({
  marketPremium,
  underlyingPrice,
  strikePrice,
  dte,
  riskFreeRate,
  optionType,
  dividendYield = 0,
}) {
  const premium = Number(marketPremium);
  const intrinsic = optionIntrinsic(underlyingPrice, strikePrice, optionType);
  const upperBound = optionType === 'CALL' ? underlyingPrice : strikePrice;
  if (!(premium > 0) || premium < intrinsic || premium > upperBound) return null;

  const priceAt = (iv) => americanOptionPrice({
    underlyingPrice,
    strikePrice,
    dte,
    riskFreeRate,
    iv,
    optionType,
    dividendYield,
  });
  let low = 0.01;
  let high = 5;
  const lowPrice = priceAt(low);
  const highPrice = priceAt(high);
  if (lowPrice == null || highPrice == null || premium < lowPrice - 0.005 || premium > highPrice + 0.005) return null;

  for (let iteration = 0; iteration < 60; iteration += 1) {
    const midpoint = (low + high) / 2;
    if (priceAt(midpoint) < premium) low = midpoint;
    else high = midpoint;
  }
  const result = (low + high) / 2;
  return Math.abs(priceAt(result) - premium) <= 0.005 ? result : null;
}

export function adaptiveScenarioRangePercent(baselinePrice, strikePrice, entryPremium, optionType) {
  const breakeven = optionType === 'CALL'
    ? strikePrice + entryPremium
    : strikePrice - entryPremium;
  const maximumMove = Math.max(
    0.10,
    Math.abs(strikePrice / baselinePrice - 1),
    Math.abs(breakeven / baselinePrice - 1),
  );
  return Math.max(10, Math.ceil((maximumMove * 100) / 5 - 1e-12) * 5);
}