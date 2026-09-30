---
name: stock-analyzer
description: |-
  Comprehensive stock investment analysis with interactive HTML reports. This skill should be used when the user requests a full analysis of any publicly listed stock. Trigger phrases include: "分析XX股票", "XX公司全面分析", "帮我分析XX", "investment analysis for XX", "stock analysis", "股票分析报告", "对XX进行估值分析", "XX股票怎么样", "投资分析". The skill produces a polished 9-section interactive dashboard covering business overview, financials, technical analysis, market sentiment, competitor comparison, valuation & health, macro environment, risks, and investment recommendations — including portfolio position advice when the user provides their holdings.
agent_created: true
---

# Stock Analyzer

## Overview

Produce a comprehensive, interactive HTML investment report for any publicly listed stock. The report covers nine standardized analytical dimensions (eight company-level + one macro-level) and supports portfolio position advice. The output is a self-contained HTML file using Chart.js for data visualization and a responsive tabbed navigation UI.

## When to Use

Trigger this skill when the user asks for any kind of stock analysis — from a full deep-dive to a targeted question about valuation or risks. Common triggers:

- "分析分众传媒" / "全面分析XX" / "XX的投资分析报告"
- "XX股票怎么样" / "XX值得投资吗"
- "帮我看看XX的财务数据" / "XX的估值合理吗"
- "I want an analysis of Tesla stock"

If the user also mentions their holding position (e.g., "我持有3成仓位，成本5.3元"), append a personalized position advice section after the nine main sections.

## Workflow

### Phase 1: Research & Data Gathering

Use WebSearch to gather current data across all analysis dimensions. Execute multiple searches in parallel where possible. At minimum, cover:

**Financial Data:**
- Latest annual and quarterly reports (营收, 净利润, 扣非净利润, 毛利率, 净利率, ROE, EPS, 经营现金流)
- Multiple years of historical data for trend analysis
- Any one-time items (asset impairments, investment gains/losses) that distort net profit
- **DuPont decomposition data**: net margin, asset turnover ratio, equity multiplier (leverage) for at least 3 years — to decompose ROE into its driving factors and identify whether ROE changes are driven by profitability, efficiency, or leverage
- **Asset quality indicators**: goodwill as % of net assets, accounts receivable turnover, inventory turnover, other receivables ratio — to detect potential impairment risks and earnings manipulation signals
- **Growth drivers breakdown**: revenue CAGR (3yr & 5yr), net profit CAGR, and whether growth is organic (same-store / volume) or M&A-driven — distinguish sustainable growth from acquisition-driven growth

**Market Data:**
- Current stock price, 52-week high/low, market cap
- Recent price trends and technical indicators (moving averages, RSI, MACD, volume)
- Key support and resistance levels

**Industry & Competition:**
- Market share data (company vs competitors)
- Competitor financial metrics for comparison table
- Industry structure and the company's competitive position
- **Porter's Five Forces assessment**: rate each force (supplier power, buyer power, competitive rivalry, threat of new entrants, threat of substitutes) as High/Medium/Low with a one-sentence justification — this structures the industry analysis beyond simple market share
- **Industry chain analysis**: identify the company's position in the upstream/downstream value chain, key suppliers and major customers, and whether the company has pricing power
- **Industry lifecycle stage**: determine whether the industry is in growth, maturity, or decline phase, and the 5-year TAM (Total Addressable Market) outlook

**Sentiment & News:**
- Analyst ratings and target prices (number of analysts covering, buy/hold/sell breakdown)
- Recent significant news events (last 6 months)
- Market sentiment indicators

**Management & Governance (qualitative — do NOT skip):**
- **Management track record**: Has leadership historically delivered on guidance and promises? Look for consistency between past forecasts and actual results
- **Compensation alignment**: Are executive compensation structures tied to shareholder value (EPS, stock price, ROE)? Or are they fixed/entitlement-based?
- **Insider trading signals**: Any recent insider purchases (bullish signal) or large insider sales (caution signal)? Major shareholder pledging of shares?
- **Corporate governance**: Board independence, related-party transactions (especially large ones), auditor opinions (qualified/unqualified), any regulatory violations in the past 3 years
- **Capital allocation track record**: How does management deploy capital — dividends, buybacks, M&A, or capex? Is their M&A history value-accretive or value-destroying?

**Valuation:**
- Current PE (TTM), forward PE estimates, PB, dividend yield
- Historical PE range for context
- Consensus earnings estimates
- **PEG ratio** (PE-to-growth) — compare against the 3-year net profit CAGR; PEG < 1 generally indicates undervaluation for growth stocks
- **EV/EBITDA** — useful for cross-company comparison as it removes capital structure differences; especially relevant for capital-intensive or highly leveraged companies
- **PE historical percentile** — current PE's rank within the 5-year range (e.g., "15th percentile" means cheaper than 85% of the time)
- **FCF Yield** (Free Cash Flow / Market Cap) — measures the cash return relative to market value; useful for comparing against bond yields

**Macro Environment (critical — do NOT skip):**
- Global monetary policy: Fed funds rate, CPI/inflation trends, ECB/BOJ rate direction, whether rate cuts are expected or reversed. Determine if global liquidity is tightening or loosening.
- Geopolitics: US-China relations status (cooperation vs confrontation), trade tariff levels, Taiwan Strait risk, Middle East, Russia-Ukraine. Assess whether tensions are escalating or de-escalating.
- AI/tech bubble risk: Are AI/semiconductor stocks in bubble territory? Any recent crashes (e.g., Nvidia single-day drops)? Assess probability of structural vs systemic bubble burst.
- A-share market valuation context: Overall PE percentile (e.g., "85th percentile of 10-year range"), whether the market is structurally frothy or broadly cheap, sector rotation dynamics (growth vs value vs dividend).
- China domestic economy: Consumption recovery status, PMI trends, real estate sector health, export growth, RMB exchange rate trajectory, fiscal/monetary policy stance.
- Industry-specific macro factors: How do the above macro forces specifically transmit to this company's industry? (e.g., "advertising is a macro barometer — consumer weakness directly cuts ad budgets", "auto parts depend on vehicle sales cycle", "export-driven companies are directly exposed to tariff changes").
- Macro sensitivity assessment: Rate the company's sensitivity (high/medium/low) to each major macro risk factor, with a one-sentence explanation of the transmission path.

### Phase 2: Build the HTML Report

Copy the template from `assets/report_template.html` to the workspace, then customize it with the researched data. The template provides:

- A complete CSS framework with all component classes pre-defined
- Placeholder `<div>` structure for all 9 sections
- Chart.js integration with all canvas IDs pre-configured
- Tab navigation system with `showSection()` function

The 9 sections are:

1. **公司概况 (Company Overview)** — Business model, competitive moat assessment (scored 0-100), industry position with market share chart, revenue structure by client industry, **Porter's Five Forces & industry chain analysis card** (rate each force with one-line justification), **management & governance assessment card** (track record, compensation alignment, insider trading, capital allocation)
2. **财务数据 (Financial Data)** — Key metrics cards (revenue, net profit, operating cash flow, gross margin, net margin, ROE, EPS), trend charts (revenue & profit 2019-2025 bar+line combo, margin trend, cash flow comparison), **DuPont decomposition chart** (ROE split into net margin × asset turnover × leverage, 3-year trend), **asset quality panel** (goodwill ratio, AR turnover, inventory turnover), **growth analysis card** (CAGR, organic vs M&A growth), profit anomaly explanation section
3. **技术分析 (Technical Analysis)** — Price metrics cards (current price, 52-week high/low, capital flow), price trend chart with support/resistance annotation, support/resistance grid, technical indicator summary (MA5/MA20/MA60, RSI, MACD, Bollinger Bands, volume)
4. **市场情绪 (Market Sentiment)** — Analyst rating badge and coverage stats, target price range with progress bars, sentiment doughnut chart, recent news timeline with sentiment tags
5. **竞品对比 (Competitor Comparison)** — Market share before/after key events (stacked bar), revenue comparison bar chart, detailed financial metrics comparison table, strategic summary (threat analysis + synergy opportunities)
6. **估值与健康 (Valuation & Health)** — Valuation metrics cards (PE TTM, forward PE, PB, dividend yield, **PEG, EV/EBITDA, PE historical percentile, FCF Yield**), PE history trend chart with mean line, valuation scenarios (pessimistic/neutral/optimistic with implied prices), financial health dashboard (liquidity, leverage, earnings quality, dividend sustainability)
7. **宏观环境 (Macro Environment)** — Global macro overview cards (Fed rate, CPI, A-share PE percentile, geopolitical status), macro risk transmission bubble chart (probability × impact, bubble size = portfolio impact), macro-to-company transmission path analysis (how each macro force flows through to this specific company), macro sensitivity rating table (high/medium/low per risk factor with one-line reasoning), key macro signals to monitor with trigger actions. Structure macro analysis using **PEST framework**: Political/Policy, Economic, Social, Technological — each dimension gets at least one specific factor with transmission path to the company.
8. **主要风险 (Risk Analysis)** — Risk matrix bubble chart (probability × impact), detailed risk cards with severity badges (high/medium/low), **stress test table** (2-3 scenarios with quantified impact: e.g., "gross margin -5pct → net profit -X% → PE re-rating to Yx → implied price Z"). Risks here are company-specific; macro risks belong in section 7.
9. **结论建议 (Conclusion & Recommendations)** — Three-horizon investment recommendation cards (short/medium/long term), bull case logic, bear case logic, key monitoring indicators, **composite scoring matrix** with explicit grade definitions (see scoring rubric below). Recommendations must incorporate the macro outlook from section 7 — e.g., if macro sensitivity is high, the short-term recommendation should reflect added caution.

**Critical data-filling rules:**
- Color coding follows Chinese market convention: price UP = red (#e94560), price DOWN = green (#00c853)
- All monetary values use 亿 as the unit for Chinese stocks
- The template CSS already has all needed classes; do NOT alter the CSS structure
- Every numerical data point in the template must be replaced with actual researched data
- Chart datasets must be updated with real numbers; do not leave placeholder data
- The Chart.js CDN script tag must remain exactly as-is

### Phase 3: Portfolio Position Advice (Optional)

If the user provides their holding details, append a position advice block after the 9 main sections. Structure it as:

```
持仓现状：cost price, current price, floating P&L%, position weight
操作建议：
- 短期（1-3个月）：action + reasoning
- 中期（1-3个月）：conditional actions with catalysts
- 长期（半年+）：target price range and rationale
止损参考：specific price levels and conditions
```

Provide specific, actionable advice with concrete price levels, not vague recommendations.

### Phase 4: Quality Check & Present

Before finalizing:
1. Verify all Chart.js datasets match the text analysis — numbers must be internally consistent
2. Confirm the company name, stock code, and report date appear in the header
3. Ensure all 9 tab sections are populated with meaningful data (not placeholders)
4. Verify that the macro section (section 7) contains real, current macro data — not generic boilerplate. The macro risk transmission paths must be specific to this company.
5. Confirm that the conclusion section (section 9) incorporates the macro outlook — recommendations should not contradict the macro sensitivity assessment.
6. Add a disclaimer footer: "本报告仅供参考，不构成投资建议。股市有风险，投资需谨慎。"

Then use `present_files` to deliver the HTML report.

## Resources

### assets/report_template.html
A production-grade, fully-styled HTML template with:
- Complete CSS (dark header, card system, metric cards, tags, progress bars, tables, risk items, etc.)
- Full `<div>` structure for all 8 sections with proper IDs and grid layouts
- Chart.js integration with Canvas elements and pre-written `commonOpts` configuration
- Tab navigation JavaScript (`showSection` function)
- Responsive design breakpoints

Copy this template and replace all hardcoded data with the researched data. The template is a starting point, not the final output.

### references/color_conventions.md
Documents the color coding conventions for Chinese stock market analysis, including:
- Chinese market color rules (红涨绿跌)
- CSS class mappings for up/down/neutral values
- Tag color semantics
- Chart color palette reference
- Risk severity color mapping

## Important Notes

- **Always run multiple WebSearch calls in parallel** during Phase 1 to minimize turnaround time. Macro searches should be grouped into one batch alongside financial/market searches.
- **Macro analysis is mandatory, not optional.** A stock analysis that only covers company-level fundamentals without addressing the macro environment is incomplete. The macro section must answer: "What happens to this stock if X happens globally?"
- **Macro-to-company transmission must be specific.** Do not write generic "macro headwinds exist" statements. Instead, trace the exact path: e.g., "Fed high rates → global liquidity tightening → foreign capital outflows from A-shares → valuation compression for consumer stocks like this one." Each transmission path should be one sentence with a clear cause-effect chain.
- **Structure macro analysis using PEST framework**: Political/Policy (regulation, trade policy, industry support/restriction), Economic (GDP, rates, inflation, exchange rate), Social (demographics, consumption trends), Technological (disruption risk, tech advantage). Each dimension needs at least one specific factor with a clear transmission path to the company.
- **Distinguish one-time from recurring effects** — in the financial section, always explain whether profit changes are driven by core operations or non-recurring items (asset impairments, investment gains, etc.)
- **DuPont decomposition is mandatory** — always decompose ROE into net margin × asset turnover × equity multiplier for at least 3 years. This reveals whether ROE changes are driven by profitability, operational efficiency, or financial leverage — critically different signals for investors.
- **Asset quality must be checked** — report goodwill as % of net assets, accounts receivable turnover, and inventory turnover. High goodwill ratios or deteriorating receivables are early warning signals for impairment risks and earnings manipulation.
- **Growth analysis must separate organic from M&A-driven growth** — revenue CAGR alone is insufficient. If a company's growth is primarily acquisition-driven, the sustainability of that growth is fundamentally different from organic growth.
- **Use multiple valuation methods for cross-validation** — do not rely solely on PE. Always calculate PEG (especially for growth stocks), EV/EBITDA (for cross-capital-structure comparison), and FCF Yield. When the company has had recent one-time profit hits, use forward estimates rather than trailing data for valuation context.
- **Stress test is mandatory in the risk section** — provide at least 2-3 quantified scenarios (e.g., "gross margin -5pct", "key customer loss", "regulatory fine 10% of revenue") with the calculated impact on net profit, PE re-rating, and implied stock price. This transforms vague risk descriptions into concrete downside estimates.
- **Use the same year labels consistently** across all charts to avoid confusing the reader
- **Be conservative with valuation** — when the company has had recent one-time profit hits, use forward estimates rather than trailing data for valuation context
- **Risk analysis should be specific to the company**, not generic boilerplate. Each risk must explain why it matters to this particular business. Company-specific risks go in section 8; macro/systemic risks go in section 7.

## Scoring Rubric

The composite scoring matrix in section 9 must use the following standardized grade definitions:

| Dimension | A (Excellent) | B (Good) | C (Average) | D (Poor) |
|-----------|---------------|----------|-------------|----------|
| **Moat Quality** | Unassailable competitive position, multiple durable moats (network, scale, brand, switching cost) | Strong position with 1-2 durable moats, defendable | Moderate moat, eroding under pressure | No sustainable advantage, commoditizing |
| **Financial Health** | High cash generation (OCF > 2x NI), low debt, high ROIC, clean balance sheet | Profitable, adequate cash flow, manageable debt | Marginal profitability, cash flow concerns, rising debt | Loss-making, negative FCF, distressed balance sheet |
| **Growth Certainty** | High visibility 3yr+ growth (>15% CAGR), diversified drivers, secular tailwinds | Moderate growth (8-15% CAGR), some visibility | Low growth (0-8%), uncertain outlook | Declining revenue/profit, structural headwinds |
| **Valuation Attractiveness** | Significant discount to intrinsic value (>30% margin of safety), low PE percentile | Reasonably priced (10-30% margin of safety) | Fairly valued (<10% margin of safety) | Overvalued, trading at premium with no growth support |

## Data Source Guidance

When gathering data via WebSearch, prioritize these sources for reliability:

**A-shares (A股):**
1. Company annual reports / quarterly reports (巨潮资讯网 cninfo.com.cn, 上海证券交易所 sse.com.cn, 深圳证券交易所 szse.cn)
2. Wind / 同花顺 / 东方财富 (for financial data and peer comparison)
3. 中国证券投资者保护网 (for investor sentiment)

**US Stocks:**
1. SEC EDGAR filings (10-K, 10-Q, 8-K) — most authoritative
2. Company investor relations pages (for guidance and conference call transcripts)
3. Yahoo Finance / Seeking Alpha (for consensus estimates and analyst coverage)

**General:**
- Always prefer primary sources (filings, official announcements) over secondary sources (news articles, sell-side reports)
- For Chinese stocks, cross-reference between 巨潮 and 东方财富 for data accuracy
- For industry data, consult industry association reports (e.g., 国家统计局, 艾瑞咨询, IDC, Gartner)
