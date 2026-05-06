# CryptoApp Prompt Logic Documentation



### Global Settings
- The prompts can be manually triggered, but also should be automaticaly triggered by the settings in the Settings.jsx page, specifically the AI Tradings Settings section.
A. **Analysis Frequency**: Controls how often the Dashboard workflows (Market, Risk, Portfolio) run. Options:
   - **Daily**: Runs once every 24 hours.
   - **Weekly**: Runs once every 7 days.
   - **Hourly**: Runs every hour *only* within the Analysis Window.
B. **Analysis Window (Start/End)**: Only applies when Frequency is **"Hourly"**. Defines the active hours (e.g., 08:00 to 23:59) for hourly reports.
C. **Confidence Threshold**: Used for **Sentiment Analysis**. If the AI's confidence score (e.g., 85%) meets or exceeds this threshold, a Telegram alert is triggered.
D. **Risk Tolerance**: (Low/Medium/High) Injected into all AI prompts to tailor the advice structure.
E. **Max Tokens**: The max amount of tokens sent/received per request.

* Sentiment Analysis runs on a hardcoded 30-minute interval but respects the Analysis Window and uses the Confidence Threshold for alerts.

There should be a queue that only allows ONE workflow to go at a time to avoid too many requests at once.


### Overview
This section provides a code-accurate, step-by-step explanation of how the Market Analysis feature works in the current CryptoApp codebase, including how user portfolio data is accessed and incorporated into the AI's response. This is based on direct inspection of the code and database, not just intended design.


---

### 1. Workflow Trigger
- The Market Analysis workflow is triggered by a frontend/API call to `/api/ai/market-analysis-workflow`.
- This endpoint is handled in `main.py`.

### 2. Context Building
- The backend gathers user-specific data:
  - Portfolio holdings (coin, amount, purchase date)
  - Watchlist coins
  - Recent activity (trades, transactions)
- This is done via helper functions (e.g., `build_db_context`, `get_user_ai_prompts`, `get_user_ai_settings`).
- Data is pulled from `crypto.db` (portfolio), `exchange_logs.db` (transactions), and other sources.

### 3. AI Prompt Construction
- The backend constructs a prompt for the AI using the gathered context.
- User-specific prompt templates are fetched from the `ai_prompts` table.
- The prompt includes:
  - Market conditions
  - User's portfolio details (actual coin balances, purchase dates)
  - Watchlist and recent activity

### 4. AI Call
- The prompt is sent to the AI (OpenAI/Z.AI) via `call_ai_with_web_search`.
- The AI may also use Brave Search results for additional context.

### 5. AI Response Logging
- The AI's response is logged in the `ai_conversations` table in `ai_conversations.db`.
- Each entry includes: date, time, prompt_type, sender, and the full AI response body.

### 6. Example Output (from DB, Sep 21, 2025, 12:58 PM EST)
- The AI response includes:
  - Market overview and trends
  - **Portfolio Analysis** section listing actual user holdings:
    - BTC: 0.0023 (purchased August 30)
    - ETH: 0.1176 (accumulated in late August and early September)
    - XRP: 24.16 (purchased September 10)
  - Performance assessment and trading recommendations tailored to the user's portfolio
  - References to watchlist coins (e.g., Solana)

### 7. Conclusion
- The Market Analysis workflow does use real portfolio data to generate the AI response, as evidenced by the direct inclusion of coin balances and purchase dates in the output.
- This has been verified by querying the `ai_conversations` table for the relevant entry.

---

## Risk Assessment Workflow (as of Sep 21, 2025)

### Step-by-Step Code Flow

1. **Workflow Trigger**
   - The workflow is triggered by a frontend/API call to `/api/ai/risk-assessment-workflow`.

2. **Manual Request Always Runs**
   - If the request is manual, the workflow always proceeds, regardless of cache or time since last run.

3. **Prompt Preparation: Stage 1**
   - Fetch `risk_assessment_pre` from the database for the current user.
   - Send `risk_assessment_pre` as the initial prompt to the AI (Stage 1).

4. **Web Search and Coin Data Gathering: Stage 2**
   - Perform Brave web search using queries generated from Stage 1.
   - Gather all non-stablecoin, non-hidden coins from the user's portfolio (from the database).
   - Fetch `risk_assessment_post` from the database for the current user.
   - Combine the Brave search results, coin data, and `risk_assessment_post` into a single prompt.
   - Send this combined prompt to the AI (Stage 2).
   - Log this prompt as a user message in the `ai_conversations` table.

5. **AI Response: Stage 3**
   - The AI generates a holistic risk assessment based on the combined context.
   - Store the AI's response as an AI message in the `ai_conversations` table.

6. **Response Returned**
   - The AI's response is returned to the frontend/user as the workflow result.

### Key Points
- No default or fallback prompts are used; only `risk_assessment_pre` and `risk_assessment_post` from the database are used.
- The workflow mirrors the 3-stage agentic process of Market Analysis.
- All context (search results and coin data) is included in the Stage 2 prompt.
- Logging is performed for both the user prompt (Stage 2) and the AI response (Stage 3).

---

## Portfolio Review Workflow (as of Sep 21, 2025)

### Step-by-Step Code Flow

1. **Workflow Trigger**
   - The workflow is triggered by a frontend/API call to `/api/ai/portfolio-review-workflow`.

2. **Manual Request Always Runs**
   - If the request is manual, the workflow always proceeds, regardless of cache or time since last run.

3. **Prompt Preparation: Stage 1**
   - Fetch `portfolio_review_pre` from the database for the current user.
   - Send `portfolio_review_pre` as the initial prompt to the AI (Stage 1).

4. **Web Search and Coin Data Gathering: Stage 2**
   - Perform Brave web search using queries generated from Stage 1.
   - Gather all non-stablecoin, non-hidden coins from the user's portfolio (from the database).
   - Fetch `portfolio_review_post` from the database for the current user.
   - Combine the Brave search results, coin data, and `portfolio_review_post` into a single prompt.
   - Send this combined prompt to the AI (Stage 2).
   - Log this prompt as a user message in the `ai_conversations` table.

5. **AI Response: Stage 3**
   - The AI generates a holistic portfolio review based on the combined context.
   - Store the AI's response as an AI message in the `ai_conversations` table.

6. **Response Returned**
   - The AI's response is returned to the frontend/user as the workflow result.

### Key Points
- No hardcoded prompts are used; only `portfolio_review_pre` and `portfolio_review_post` from the database are used.
- The workflow mirrors the 3-stage agentic process of Market Analysis and Risk Assessment.
- All context (search results and coin data) is included in the Stage 2 prompt.
- Logging is performed for both the user prompt (Stage 2) and the AI response (Stage 3).

---

## Coin & News Analysis Workflow (as of Sep 21, 2025)

### Step-by-Step Code Flow

1. **Workflow Trigger**
   - The workflow is triggered by a POST request to `/api/ai/news-analysis` with a specific coin symbol when clicking the refresh news button on a coin in the portfolio or watchlist on the dashboard page.

2. **Cache Check (Optional)**
   - If `use_cache` is true and not forcing fresh, the workflow checks for a recent (last 4 hours) cached analysis for the coin in the `ai_conversations` table.
   - If found, the cached result is returned. If not, the workflow proceeds.

3. **Prompt Preparation: Stage 1**
   - Fetch `coin_analysis_pre` from the database for the current user.
   - Replace `{symbol}` and `{datetime}` placeholders with the requested coin and current date/time.
   - Send `coin_analysis_pre` as the initial prompt to the AI (Stage 1) to generate search queries.

4. **Web Search and Coin Data Gathering: Stage 2**
   - Perform Brave web search or (duckduckgo as a fallback) using the queries generated from Stage 1. Brave Web Search is done using the Brave Search API: a primary and fallback API keys are entered in the Settings page and stored in the credentials table for the logged in user.
   - Query the `coins` table for the specific coin being analyzed (by symbol and user, not hidden).
   - Gather all relevant coin data (amount, value, etc.) for that coin.
   - Fetch `coin_analysis_post` from the database for the current user.
   - Combine the Brave search results, specific coin data, and `coin_analysis_post` into a single prompt.
   - Send this combined prompt to the AI (Stage 2).
   - Log this prompt as a user message in the `ai_conversations` table, linked to the coin symbol.

5. **AI Response: Stage 3**
   - The AI generates a news and coin analysis based on the combined context.
   - Store the AI's response as an AI message in the `ai_conversations` table, linked to the coin symbol.

6. **Response Returned**
   - The AI's response is returned to the frontend/user as the workflow result, along with the prompt used and timestamp. Clicking the news button will display those results and they should also appear in the ai copilot sidebar.

### Key Points
- No hardcoded prompts are used; only `coin_analysis_pre` and `coin_analysis_post` from the database are used.
- The workflow mirrors the 3-stage agentic process of the other workflows, but always includes the specific coin's data in the Stage 2 prompt.
- Logging is performed for both the user prompt (Stage 2) and the AI response (Stage 3), linked to the coin symbol.
- Caching is supported for recent analyses.

---

## Sentiment Analysis Workflow (as of Sep 21, 2025)

### Step-by-Step Code Flow

1. **Workflow Trigger**
   - The workflow is triggered automatically by a background job every 30 minutes for each user.
   - For each user, the workflow iterates through all non-hidden coins in their portfolio, processing one coin at a time (never in parallel).

2. **Prompt Preparation: Stage 1**
   - Fetch `sentiment_prompt_pre` from the database for the current user.
   - Replace `{symbol}`, `{amount}`, and `{datetime}` placeholders with the coin symbol, amount, and current date/time.
   - Send `sentiment_prompt_pre` as the initial prompt to the AI (Stage 1) to generate search queries.

3. **Web Search and Coin Data Gathering: Stage 2**
   - Perform a Brave web search using the queries generated from Stage 1.
   - Query the `coins` table for the specific coin being analyzed (by symbol and user, not hidden).
   - Gather all relevant coin data (amount, value, etc.) for that coin.
   - Fetch `sentiment_prompt_post` from the database for the current user.
   - Combine the Brave search results, specific coin data, and `sentiment_prompt_post` into a single prompt.
   - Send this combined prompt to the AI (Stage 2).
   - Log this prompt as a user message in the `ai_conversations` table, linked to the coin symbol.

4. **AI Response: Stage 3**
   - The AI generates a sentiment result based on the combined context.
   - The AI response must include a **Confidence Score** (e.g., "Confidence: 85%").
   - Store the AI's response as an AI message in the `ai_conversations` table.
   - Update the `sentiment` column for the coin in the `coins` table.
   - **Alert Trigger**: If `Confidence >= User Threshold`, trigger a Telegram Alert.

5. **No API Endpoint**
   - There is no public API endpoint for sentiment analysis; the workflow is background-only.

### Key Points
- No hardcoded prompts are used; only `sentiment_prompt_pre` and `sentiment_prompt_post` from the database are used.
- The workflow mirrors the 3-stage agentic process of the other workflows, always including the specific coin's data in the Stage 2 prompt.
- Logging is performed for both the user prompt (Stage 2) and the AI response (Stage 3), linked to the coin symbol.
- The result is always written to the `sentiment` column for each coin.
- No duplicate or conflicting code paths exist for sentiment analysis.

---

### Timing:

**Sentiment Analysis Frequency**: Configurable per-user via `sentiment_analysis_frequency_hours` in `user_settings` (default: 24 hours). The background job checks if a coin's `sentiment_last_updated` is older than this threshold before re-analyzing.

---

## AI Copilot Sidebar Workflow (as of Jan 21, 2026)

### Overview
The AI Copilot sidebar provides a conversational interface for users to ask questions about their portfolio and the market.

### Step-by-Step Code Flow

1. **User Sends Message**
   - User types a message in the sidebar chat input.
   - Message is sent to `/api/ai/chat` (POST) with the message body and optional conversation_id.

2. **Context Gathering**
   - Backend fetches comprehensive portfolio context (holdings, values, performance).
   - Backend queries recent conversation history from `ai_conversations` table using SQLAlchemy ORM.

3. **3-Stage Agentic Workflow**
   - **Stage 1**: AI generates search queries based on the user's message.
   - **Stage 2**: Brave Search API (with DuckDuckGo fallback) executes the generated queries.
   - **Stage 3**: AI synthesizes a response using `copilot_chat_pre` (system prompt) and `copilot_chat_post` (analysis prompt) from user settings.

4. **Logging**
   - User message logged with `prompt_type='manual'`, `sender='user'`.
   - AI response logged with `prompt_type='manual'`, `sender='ai'`.

5. **Response Returned**
   - AI response displayed in the sidebar.
   - Conversation appears in sidebar history.

### Key Points
- Customizable prompts via `copilot_chat_pre` and `copilot_chat_post` in Settings.
- All conversation history retrieved using SQLAlchemy ORM (not legacy SQLite).
- Web search is ALWAYS performed to provide up-to-date market context.
