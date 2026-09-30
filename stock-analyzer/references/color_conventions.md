# Chinese Stock Market Color Conventions

## Core Rule

Chinese stock market convention is the **opposite** of US/European convention:
- **涨 (price increase) = Red (红色)**
- **跌 (price decrease) = Green (绿色)**

This applies universally across all charts, metric cards, and text formatting in the report.

## CSS Color Palette

### Primary Colors
| Usage | Hex Code | CSS Class Suffix |
|-------|----------|-----------------|
| Price up / Bullish / Positive change | `#e94560` | `.up`, `.pos` |
| Price down / Bearish / Negative change | `#00c853` | `.down`, `.neg` |
| Neutral / Informational | `#2196f3` | `.neutral` |
| Warning / Caution | `#ff9800` | (inline style) |
| Highlight / Gold | `#ffd700` | (inline style) |

### Metric Card Classes
- `.m-val.up` → `color: #e94560` (for "涨" or positive absolute values)
- `.m-val.down` → `color: #00c853` (for "跌" or negative absolute values)
- `.m-val.neutral` → `color: #2196f3` (for informational metrics)
- `.m-change.pos` → `color: #e94560` (↑ arrows in change text)
- `.m-change.neg` → `color: #00c853` (↓ arrows in change text)
- `.m-change.neutral` → `color: #888`

### Tag Colors (Sentiment News Tags)
| Tag | CSS Class | Background | Text Color |
|-----|-----------|------------|------------|
| 负面 | `.tag-red` | `#fde8ea` | `#e94560` |
| 正面 | `.tag-green` | `#e8f5e9` | `#2e7d32` |
| 政策/行业 | `.tag-blue` | `#e3f2fd` | `#1565c0` |
| 风险/注意 | `.tag-orange` | `#fff3e0` | `#e65100` |
| 中性/其他 | `.tag-gray` | `#f5f5f5` | `#555` |

### Risk Severity Colors
| Level | CSS Class | Background | Text Color |
|-------|-----------|------------|------------|
| 高风险 | `.risk-high` | `#fde8ea` | `#e94560` |
| 中风险 | `.risk-mid` | `#fff3e0` | `#e65100` |
| 低风险 | `.risk-low` | `#e8f5e9` | `#2e7d32` |

### Chart Color Palette (for multi-series charts)
Use these hex values in order when creating charts with multiple categories/series:
1. `#e94560` (红 — primary)
2. `#2196f3` (蓝 — secondary)
3. `#00c853` (绿 — tertiary)
4. `#ffd700` (金 — quaternary)
5. `#ff9800` (橙 — quinary)
6. `#9c27b0` (紫)
7. `#999` (灰 — "other" category)

## Signal Indicators
- `.signal-buy` → `background: #fde8ea; color: #e94560` (bullish signal)
- `.signal-sell` → `background: #e8f5e9; color: #2e7d32` (bearish signal)
- `.signal-neutral` → `background: #f5f5f5; color: #888` (neutral)

## Visual Cues
- Bullish conclusion boxes: `border-left: 4px solid #e94560`
- Bearish conclusion boxes: `border-left: 4px solid #00c853`
- Support level boxes: green-tinted background
- Resistance level boxes: red-tinted background
- Current price box: blue-tinted background

## Important
Never swap red/green meanings for Chinese stocks. This applies regardless of what Western financial conventions dictate. If the user explicitly asks for US-style coloring, comply with their request.
