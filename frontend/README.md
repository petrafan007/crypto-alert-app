# Crypto Alert App - React Frontend

This is the React/Vite frontend for the Crypto Alert App, built to work alongside the existing Flask backend. The app now provides **full Coinbase API functionality** including trading, portfolio management, and AI-powered analysis.

## 🚀 **New Features - Full API Integration**

### ✅ **Trading Functionality**
- **Live Market Data**: Real-time prices, 24h changes, volume, highs/lows
- **Order Placement**: Market and limit orders for any trading pair
- **Order History**: Complete order tracking and management
- **Portfolio Analysis**: AI-powered insights and recommendations

### ✅ **AI-Powered Analysis**
- **Risk Assessment**: Automated portfolio risk evaluation
- **Trading Signals**: AI-generated buy/sell recommendations
- **Market Sentiment**: Real-time market sentiment analysis
- **Portfolio Optimization**: Diversification and rebalancing suggestions

### ✅ **Enhanced Portfolio Management**
- **Real-time Balances**: Live account balances and USD values
- **Trading Pairs**: Access to all available Coinbase trading pairs
- **Advanced Charts**: Portfolio allocation and trend analysis
- **Automated Alerts**: Price alerts and portfolio notifications

## Current Status

### ✅ **Completed Features**
- **Full Authentication**: OAuth-based login with session management
- **Trading Dashboard**: Complete trading interface with market data
- **Portfolio Management**: Real-time portfolio tracking and analysis
- **AI Analysis**: Risk assessment, trading signals, and recommendations
- **Order Management**: Place, track, and manage trading orders
- **Watchlist Management**: Add/remove coins with alerts
- **Responsive Design**: Modern dark theme with consistent styling
- **Real-time Data**: Live market data and portfolio updates

### 🔧 **In Progress**
- **Advanced AI Integration**: More sophisticated trading algorithms
- **Automated Trading**: AI-driven automated trading strategies
- **Advanced Charts**: More detailed technical analysis
- **Mobile Optimization**: Enhanced mobile experience

### 📋 **Planned Features**
- **Machine Learning Models**: Custom ML models for price prediction
- **Advanced Risk Management**: Portfolio hedging and protection
- **Social Trading**: Copy successful traders' strategies
- **News Integration**: Real-time news sentiment analysis
- **Backtesting**: Historical strategy testing and optimization

## Getting Started

### Prerequisites
- Node.js (v16 or higher)
- Flask backend running on port 5010
- Coinbase API credentials (OAuth setup)

### Installation
```bash
cd frontend
npm install
```

### Development
```bash
npm run dev
```

The app will be available at `http://localhost:5173`

### Building for Production
```bash
npm run build
```

## API Endpoints Used

### **Authentication**
- `POST /login` - User authentication via OAuth
- `GET /logout` - User logout

### **Portfolio & Market Data**
- `GET /api/true-portfolio-value` - Total portfolio value
- `GET /api/coin-data` - Portfolio holdings data
- `GET /api/account-balance` - Detailed account balances
- `GET /api/market-data/<symbol>` - Live market data for any symbol
- `GET /api/trading-pairs` - Available trading pairs

### **Trading**
- `POST /api/place-order` - Place buy/sell orders
- `GET /api/orders` - Order history and status
- `GET /api/portfolio-analysis` - AI-powered portfolio analysis

### **Watchlist Management**
- `GET /api/watchlist` - Watchlist data
- `POST /api/watchlist/add` - Add to watchlist
- `POST /api/watchlist/remove` - Remove from watchlist

### **Portfolio History**
- `GET /api/true-portfolio-history` - Portfolio trend data

## Trading Features

### **Order Types Supported**
- **Market Orders**: Immediate execution at current market price
- **Limit Orders**: Execution at specified price or better

### **Trading Pairs**
- All USD trading pairs available on Coinbase
- Real-time price data and 24h statistics
- Volume analysis and market sentiment

### **AI Analysis**
- **Risk Assessment**: Portfolio concentration and diversification analysis
- **Trading Signals**: Buy/sell recommendations based on technical analysis
- **Market Sentiment**: Bullish/bearish market analysis
- **Portfolio Optimization**: Rebalancing and diversification suggestions

## Project Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── AuthContext.jsx        # Authentication state management
│   │   ├── DashboardCharts.jsx    # Chart components
│   │   ├── AddToWatchlist.jsx     # Watchlist management
│   │   └── AIAnalysis.jsx         # AI-powered analysis
│   ├── pages/
│   │   ├── Dashboard.jsx          # Main dashboard with charts
│   │   ├── Login.jsx              # Authentication page
│   │   ├── Portfolio.jsx          # Portfolio details
│   │   ├── Watchlist.jsx          # Watchlist management
│   │   └── Trading.jsx            # Full trading interface
│   ├── App.jsx                    # Main app component
│   └── main.jsx                   # App entry point
├── package.json
└── vite.config.js                 # Vite configuration with proxy
```

## AI Integration

### **Current AI Features**
- **Risk Assessment**: Analyzes portfolio concentration and diversification
- **Trading Signals**: Generates buy/sell recommendations based on price movements
- **Market Sentiment**: Determines bullish/bearish market conditions
- **Portfolio Optimization**: Suggests rebalancing and diversification strategies

### **Future AI Enhancements**
- **Machine Learning Models**: Custom ML models for price prediction
- **Sentiment Analysis**: News and social media sentiment integration
- **Pattern Recognition**: Advanced technical analysis patterns
- **Automated Trading**: AI-driven trading strategies

## Development Notes

- **Vite + React**: Fast development and building
- **API Proxy**: Requests proxied to Flask backend on port 5010
- **OAuth Authentication**: Secure session-based authentication
- **Real-time Data**: Live market data and portfolio updates
- **AI Analysis**: Local AI analysis with room for ML integration
- **Responsive Design**: Works on desktop and mobile devices

## Security Considerations

- **OAuth Authentication**: Secure Coinbase API access
- **Session Management**: Secure session handling
- **API Rate Limiting**: Respects Coinbase API limits
- **Error Handling**: Comprehensive error handling and user feedback

## Next Steps for AI Enhancement

1. **Integrate OpenAI/Google AI**: Add advanced language model analysis
2. **Custom ML Models**: Develop specialized crypto trading models
3. **Sentiment Analysis**: Add news and social media sentiment
4. **Backtesting Framework**: Test strategies on historical data
5. **Automated Trading**: Implement AI-driven trading strategies

## Disclaimer

This application is for educational and personal use only. Trading cryptocurrencies involves significant risk and may result in substantial losses. Always do your own research and consider consulting with a financial advisor before making investment decisions. The AI analysis provided is for informational purposes only and should not be considered as financial advice.
