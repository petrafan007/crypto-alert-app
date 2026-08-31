import sys

with open("frontend/src/pages/WebullTrading.jsx", "r") as f:
    content = f.read()

replacement = """                    />
                  )}
                  
                  {/* Options Payoff Chart Preview */}
                  {selectedInstrumentType === 'OPTION' && orderForm.optionStrike && orderForm.optionExpiration && (
                    <div style={{ marginTop: '20px' }}>
                      <OptionsPayoffChart
                        baselinePrice={Number(latestAssetPrice || 0) || Number(orderForm.optionStrike)}
                        strikePrice={Number(orderForm.optionStrike)}
                        entryPremium={Number(orderForm.price || 0)}
                        multiplier={100}
                        iv={0.1501}
                        riskFreeRate={0.0379}
                        startingDTE={
                          Math.max(0, Math.floor((new Date(orderForm.optionExpiration).getTime() - Date.now()) / (1000 * 3600 * 24))) || 1
                        }
                        optionType={orderForm.optionType}
                        action={orderForm.side}
                      />
                    </div>
                  )}
"""

content = content.replace("                    />\n                  )}", replacement)

with open("frontend/src/pages/WebullTrading.jsx", "w") as f:
    f.write(content)
