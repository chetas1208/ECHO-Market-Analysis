# ECHO UI Specification

> **Status:** Locked UI/UX contract for implementation  
> **Purpose:** Define the complete interface system for ECHO so frontend work stays coherent across all milestones.  
> **Reference direction:** Dark financial-intelligence terminal inspired by the supplied dashboard image, but simplified into a cleaner, more focused product with **a maximum of five primary tabs** and a single overlay navigation drawer.

---

# 1. Product UI Goal

ECHO should feel like a serious real-time financial intelligence system, not a generic stock dashboard and not an AI chatbot.

The interface must make this flow obvious:

```text
REAL-WORLD EVENT / MARKET SHOCK
            ↓
      CAUSAL EXPLANATION
            ↓
      AFFECTED COMPANIES
            ↓
   FORECAST DISTRIBUTION
            ↓
     PREDICTION LEDGER
            ↓
    SIMULATION / STRATEGY
            ↓
       REALITY CHECK
```

The user should be able to answer, with minimal navigation:

1. What happened?
2. Why does it matter?
3. Which companies are affected?
4. What does ECHO predict?
5. How confident is the forecast?
6. What has actually happened so far?
7. How would the prediction have performed as a simulated trade?
8. How has the strategy performed historically?

---

# 2. Non-Negotiable Navigation Rule

ECHO has **at most five primary tabs**.

No sixth primary tab may be added without explicitly revisiting this specification.

The five tabs are:

1. **Dashboard**
2. **Events**
3. **Graph**
4. **Forecasts**
5. **Strategy**

Everything else is a sub-view, detail page, modal, drawer, panel, or secondary route inside one of these five sections.

Do **not** create separate primary tabs for:

- Analytics
- Backtest
- Trades
- Portfolio
- Research
- Settings
- Companies
- News
- Simulator
- Prediction Ledger

Those functions belong inside the five primary sections.

---

# 3. Global Navigation Pattern

## 3.1 Top Bar

The top bar remains visible across the application.

It contains only:

- hamburger button
- ECHO logo / wordmark
- contextual page title or breadcrumb
- optional global search
- LIVE / DATA STATUS indicator
- local time / market state
- profile avatar

Example:

```text
☰   ECHO       Dashboard                   Search...       ● LIVE     11:24 UTC    CP
```

Do not place the five primary tabs horizontally in the top bar.

The top bar must stay visually clean.

---

## 3.2 Overlay Vertical Navigation Drawer

The main navigation is hidden by default.

Pressing the hamburger icon opens a **vertical navigation drawer** from the left.

### Drawer behavior

- opens above page content
- does not push content horizontally
- overlays approximately `280–320px` of the viewport on desktop
- overlays approximately `85–90vw` on small mobile screens
- background content receives blur and dimming
- body interaction behind the drawer is disabled while open
- `Esc` closes the drawer on desktop
- clicking/tapping outside the drawer closes it
- selecting a navigation item closes the drawer
- drawer animation should take roughly `180–240ms`
- use smooth ease-out movement

### Backdrop

When drawer is open:

```css
background: rgba(2, 8, 18, 0.55);
backdrop-filter: blur(8px);
```

Do not blur the drawer itself.

Do not use an opaque black backdrop that destroys context.

---

## 3.3 Drawer Layout

The drawer has three vertical regions.

### Header

- ECHO logo
- optional environment label: `LIVE`, `PAPER`, `DEMO`
- close button

### Primary navigation

Only the five tabs:

```text
Dashboard
Events
Graph
Forecasts
Strategy
```

### Footer utilities

These are **not tabs**:

- Data Sources
- Model Status
- Settings
- Documentation
- About / Build version
- Sign out

These can appear as compact links or be opened from the profile area.

---

# 4. Primary Navigation Information Architecture

```text
ECHO
│
├── Dashboard
│   ├── Global overview
│   ├── Active shocks
│   ├── Current opportunities
│   ├── Forecast accuracy snapshot
│   └── Paper portfolio snapshot
│
├── Events
│   ├── Live event feed
│   ├── World-event detail
│   ├── Market shock investigator
│   ├── Source evidence
│   └── Historical analogues
│
├── Graph
│   ├── ShockGraph explorer
│   ├── Company exposure
│   ├── Causal paths
│   ├── Relationship inspector
│   └── Impact propagation
│
├── Forecasts
│   ├── Stock forecast
│   ├── Prediction vs reality
│   ├── Prediction ledger
│   ├── Forecast vintages
│   └── Trade simulator
│
└── Strategy
    ├── Strategy builder
    ├── Backtest
    ├── Event replay
    ├── Paper execution
    ├── Portfolio
    └── Analytics
```

---

# 5. Global Visual Direction

ECHO should look like a modern intelligence terminal.

## 5.1 Style

Use:

- near-black navy background
- thin low-contrast borders
- slightly elevated cards
- restrained glow only for meaningful status
- highly legible typography
- dense but not cramped layouts
- green/red only when directionality matters
- blue/cyan for system/navigation states
- amber for warning / medium confidence
- purple only for graph/relationship accents when useful

Avoid:

- excessive gradients
- giant hero sections
- oversized illustrations inside core workflow
- glowing borders everywhere
- excessive rounded cards
- meaningless animation
- cryptocurrency-dashboard aesthetics
- gamification

---

# 6. Design Tokens

These are implementation defaults, not immutable exact values.

## 6.1 Color system

```text
Background / App      #06111B
Background / Deep     #030A12
Surface / Primary     #0B1824
Surface / Secondary   #0E1D2B
Surface / Hover       #122538
Border / Default      #193247
Border / Strong       #28506B

Text / Primary        #F4F8FB
Text / Secondary      #A9B8C5
Text / Muted          #6F8495

Accent / Blue         #2196F3
Accent / Cyan         #24D7F0
Positive              #2FE29A
Negative              #FF5A67
Warning               #F5B84C
Purple                #A778FF
```

Never encode meaning by color alone.

Pair important colors with:

- labels
- arrows
- icons
- +/- signs
- badges

---

## 6.2 Typography

Preferred:

```text
Inter
Geist
IBM Plex Sans
```

Optional mono font for market values:

```text
IBM Plex Mono
JetBrains Mono
```

Suggested scale:

```text
Page title             24–28px / 700
Section title          16–18px / 650
Card title             14–16px / 600
Body                   13–14px / 400–500
Metadata               11–12px / 400–500
Critical metric        22–30px / 650–750
Ticker / numeric       mono optional
```

---

## 6.3 Radius

```text
Cards       10–12px
Inputs       8–10px
Buttons      8–10px
Badges       full/pill where appropriate
```

Do not turn every surface into a pill.

---

## 6.4 Spacing

Use an 8px base grid.

```text
4px
8px
12px
16px
24px
32px
48px
```

Desktop dashboard should feel dense but readable.

---

# 7. Global Layout Rules

## Desktop

Target widths:

```text
1280
1440
1600+
```

Rules:

- use full viewport width intelligently
- primary content can be multi-column
- maximum readable content width may be ~1800px
- cards should not become excessively wide on ultrawide displays
- no permanent left sidebar
- no horizontal body scrolling

## Tablet

- reduce grid column count
- use cards in 1–2 columns
- graph can become full width
- secondary panels can move below primary content

## Mobile

- one primary content column
- hamburger drawer becomes near-full-width overlay
- tables should convert to card rows or horizontally scroll inside their own controlled container
- charts remain interactive
- no impossible tiny multi-panel layouts

---

# 8. Global Header

Height target:

```text
56–64px
```

Left:

- hamburger
- logo
- current section

Center, when space permits:

- universal search

Right:

- data status
- market status
- UTC/local time
- avatar

## Universal search

Search:

- ticker
- company
- event
- geography
- topic

Example placeholder:

```text
Search events, companies, tickers...
```

Command-style shortcut may be added later:

```text
⌘K / Ctrl+K
```

---

# 9. Tab 1 — Dashboard

## Purpose

Give the user the state of the world, market, forecasts, and ECHO performance in one screen.

The dashboard should not expose every feature. It should answer:

> What requires my attention right now?

---

## 9.1 Dashboard structure

### Row A — Key metrics

Maximum 5 cards.

Suggested:

1. Active Events
2. Market Shocks
3. Forecast Opportunities
4. Prediction Accuracy
5. Paper Portfolio P&L

Example:

```text
12 Active Events
5 Market Shocks
8 Forecast Opportunities
71% Directional Accuracy
+2.4% Paper P&L
```

Avoid fake metrics in production.

If data is unavailable, show a proper unavailable state rather than fabricated values.

---

## 9.2 Dashboard main grid

Recommended desktop grid:

```text
┌────────────────────┬───────────────────────────────┬────────────────────┐
│ Live Events        │ Global Shock Map              │ Highest Opportunity│
│                    │                               │                    │
├────────────────────┼───────────────────────┬───────┴────────────────────┤
│ Market Shocks      │ Affected Equities     │ Forecast Accuracy         │
├────────────────────┴───────────────────────┴────────────────────────────┤
│ Prediction vs Reality / Strategy Performance                            │
└─────────────────────────────────────────────────────────────────────────┘
```

Do not make every panel equal size.

The most time-sensitive information receives the most visual weight.

---

## 9.3 Live Events widget

Display 4–6 latest/highest-priority events.

Each event row:

```text
[icon/image optional]
Title
Category badge
Age
Severity
Confidence
1-line summary
```

Click opens the event detail inside **Events**.

---

## 9.4 Global Shock Map

Purpose:

- spatial context
- active world shocks
- approximate propagation regions

Rules:

- map should not dominate every workflow
- use clusters where events overlap
- marker color maps to event class or severity, not arbitrary decoration
- hover reveals compact tooltip
- click opens event detail
- map supports zoom and pan

Do not overload the map with every graph edge.

---

## 9.5 Highest Opportunity widget

Show the strongest currently valid forecast opportunity.

Must show:

```text
Ticker
Direction
Forecast horizon
Expected abnormal return
q10 / q50 / q90
Probability positive
Confidence
Current actual move
Residual
Primary cause
```

CTA:

```text
Open Forecast
Simulate
```

Do not show `BUY NOW` language.

---

## 9.6 Market Shocks widget

Shows detected anomalies from market feed.

Columns/data:

```text
Ticker
Move
Window
Volume z
Volatility z
Sector residual
Cause status
```

Cause statuses:

```text
Attributed
Probable
Unknown
Investigating
```

Click goes to **Events → Market Shock Investigator**.

---

## 9.7 Prediction performance widget

Show recent integrity metrics:

- directional accuracy
- MAE
- interval coverage
- calibration
- number of matured predictions

Do not only display P&L.

---

# 10. Tab 2 — Events

This tab owns all incoming world and market events.

It contains three primary internal views:

```text
Live Feed
Event Detail
Shock Investigator
```

These are not top-level application tabs.

Use sub-navigation within the Events page.

---

# 11. Events — Live Feed

## Layout

Desktop:

```text
Filters / event list             Context panel
```

or full-width list with detail drawer.

Recommended top controls:

- search
- event category filters
- severity
- confidence
- time window
- source

Categories may include:

```text
Geopolitics
Earnings
Supply Chain
Energy
Technology
Cyber
Macro
Market Shock
```

Avoid displaying 20 filter chips simultaneously.

Use a compact filter popover when needed.

---

## Event row/card

Must include:

```text
Title
Event type
Timestamp / age
Source type
Severity
Confidence
Corroboration
1–2 line summary
Affected industries or companies
```

Optional:

- thumbnail
- location

No fabricated photography.

---

# 12. Events — Event Detail

This is one of the most important screens.

## Header

```text
Back to Events

[Category] [Severity]
Event Title
Summary
Timestamp
Location
Source count
Confidence
```

Primary actions:

```text
View Graph
View Forecasts
Watch
```

No redundant `Share`, `Export`, or social buttons unless genuinely needed.

---

## Detail sections

### A. Event Summary

- concise description
- event state
- detection time
- latest update time

### B. Economic Channels

Show signed impact bars:

```text
Oil Supply            -0.82
Shipping Costs        +0.77
Energy Prices         +0.73
Global Trade          -0.61
```

### C. Evidence

Every important claim should be traceable.

Show:

- source
- timestamp
- confidence / corroboration
- source URL when allowed

### D. Affected Companies

Table:

```text
Ticker
Company
Exposure
Expected impact
Observed move
Residual
Confidence
```

### E. Historical Analogues

Show comparable events when available.

### F. Forecast preview

Top 3 affected assets and current forecast summaries.

---

# 13. Events — Market Shock Investigator

This screen begins from the market rather than the world.

Example:

```text
NVDA -4.18% in 7m
Volume 6.4σ
Volatility 4.9σ
Sector residual -2.8%
```

## Layout

### Left / primary

Large market chart with event detection marker.

Show:

- price
- volume
- event detection timestamp
- market/sector baseline

### Right / analysis

Probable causes ranked by confidence:

```text
87% TSMC production interruption
41% Taiwan earthquake aftershock
12% broad semiconductor selloff
```

Never force a cause.

`Unknown` is a valid result.

### Bottom

- propagation graph
- related stocks
- underreaction candidates
- overreaction candidates

---

# 14. Tab 3 — Graph

The Graph tab is the ShockGraph workspace.

It must not become a decorative network visualization.

Its purpose is to answer:

> Why is this company exposed to this event?

---

# 15. Graph Main Layout

Desktop:

```text
┌───────────────────────────────┬──────────────────────┐
│                               │ Inspector            │
│        ShockGraph             │                      │
│                               │ selected node/edge   │
│                               │ relationship         │
│                               │ evidence             │
└───────────────────────────────┴──────────────────────┘
```

Graph receives most space.

Inspector width around `320–380px`.

---

# 16. Graph Nodes

Node classes:

- event
- company
- commodity
- geography
- sector
- infrastructure
- macro factor

Do not represent every entity with the same shape.

Suggested:

```text
Event        hex / emphasized circle
Company      circle
Commodity    diamond
Geography    rounded square
Sector       pill node
```

Keep shapes simple.

---

# 17. Graph Edges

Supported economic relationships:

```text
supplier
customer
competitor
substitute
complement
commodity exposure
geographic exposure
regulatory exposure
technology dependency
risk similarity
```

Every graph edge must be capable of displaying:

```text
relationship type
sign
weight
confidence
provenance
```

Positive / negative sign should be visually obvious.

Do not use thickness alone to communicate meaning.

---

# 18. Graph Interaction Rules

User can:

- pan
- zoom
- select node
- select edge
- expand neighbors
- collapse branch
- isolate path
- filter relation type
- filter confidence threshold
- reset view

On selecting a company:

show:

```text
Ticker
Name
Current price
Observed event move
Graph exposure
Forecast residual
Confidence
```

CTA:

```text
Open Forecast
```

---

# 19. Causal Path Explanation

This is critical.

When user selects an affected company, show the best causal path.

Example:

```text
Strait of Hormuz disruption
        ↓
Oil supply risk
        ↓
Brent crude price pressure
        ↓
Airline fuel cost
        ↓
DAL
```

Each hop should expose evidence and confidence.

This is more useful than showing a giant unreadable graph.

---

# 20. Tab 4 — Forecasts

This is the core analytical product.

The Forecasts tab owns:

- asset forecast view
- prediction vs reality
- immutable prediction ledger
- forecast vintages
- trade simulator

---

# 21. Forecast Workspace Header

Controls:

```text
Ticker selector
Current event selector
Forecast vintage selector
Horizon selector
```

Horizons:

```text
1D
2D
5D
10D
20D
30D visualization
```

Remember:

The core forecast target is abnormal return, not raw future price.

UI may convert abnormal-return forecasts into an implied price path for visual comprehension, but the underlying model output must remain clearly labeled.

---

# 22. Forecast Main Chart

This chart is mandatory.

## Historical side

Show up to 30 days of actual market data before forecast creation.

## Forecast side

At forecast timestamp, plot:

- q10
- q50
- q90
- actual realized price/return as it becomes available

Visual structure:

```text
HISTORICAL                            FORECAST WINDOW

actual ───────────────●.............. q50
                      │ \           /
                      │  \ q90     /
                      │   █████████
                      │   █████████ uncertainty
                      │  / q10     \
                      │ /
                forecast issued
```

The forecast line must never move retrospectively.

---

# 23. Prediction vs Reality

Two clearly differentiated series:

```text
Frozen Prediction
Actual Reality
```

Metrics:

```text
Predicted abnormal return
Actual abnormal return
Absolute error
Directional correctness
Inside interval?
Probability assigned
```

For example:

```text
5D prediction      +2.2%
5D actual          +1.7%
Absolute error      0.5pp
Direction           Correct
Inside 80% band     Yes
```

---

# 24. Prediction Ledger

This section proves forecast integrity.

Table columns:

```text
Forecast ID
Created
Ticker
Event
Model Version
Data Cutoff
Horizon
q10
q50
q90
P(+)
Status
```

Statuses:

```text
Open
Partially Matured
Matured
Invalidated by data issue
```

There is no Edit button.

There is no Delete button for normal users.

The UI should reinforce immutability.

Badge:

```text
LOCKED FORECAST
```

---

# 25. Forecast Vintages

If new information arrives, create a new vintage.

The UI should allow side-by-side comparison:

```text
Vintage 1 — Sep 20 10:42
Vintage 2 — Sep 20 14:18
Vintage 3 — Sep 21 09:31
```

Do not visually merge them into one rewritten forecast.

---

# 26. Trade Simulator

The simulator belongs inside Forecasts, not as a separate primary tab.

The simulator must have two modes:

```text
Prediction
Actual
```

or a split comparison.

---

# 27. Simulator — Prediction Mode

Inputs:

```text
Ticker
Forecast vintage
Direction
Entry time
Position size
Hedge
Stop loss
Time stop
Exit horizon
```

System-generated default values must be editable where appropriate.

Show:

- expected abnormal return
- expected absolute return
- uncertainty interval
- probability of positive return
- estimated downside

---

# 28. Simulator — Actual Mode

As reality occurs, append:

```text
Actual return
Actual P&L
Maximum adverse excursion
Maximum favorable excursion
Exit result
```

Never modify the original simulation assumptions.

---

# 29. Simulation Timeline

Support approximately:

```text
-30 days historical context
0 forecast issue
+30 days simulation/verification
```

The user's core requirement is preserved:

> Today's simulation must still be exactly visible tomorrow.

Therefore every simulated run gets a permanent timestamp and immutable assumptions.

---

# 30. Tab 5 — Strategy

The Strategy tab combines research, backtesting, paper execution, and analytics.

This avoids creating four more top-level tabs.

Internal sub-navigation:

```text
Builder
Backtest
Replay
Paper
Analytics
```

These are local sub-tabs only.

---

# 31. Strategy — Builder

Purpose:

Turn ECHO signals into a formal strategy.

Show sections:

### Event rules

```text
minimum event confidence
minimum graph confidence
allowed event classes
```

### Forecast rules

```text
minimum expected abnormal return
minimum probability positive
allowed horizons
minimum residual
```

### Market confirmation

```text
volume confirmation
volatility confirmation
sector-relative confirmation
liquidity requirement
```

### Risk

```text
max position size
max sector exposure
max simultaneous positions
stop loss
time stop
drawdown kill switch
```

Risk controls must visually look deterministic and locked from model overrides.

---

# 32. Strategy — Backtest

Main metrics:

```text
Total Return
Sharpe
Sortino
Max Drawdown
Win Rate
Turnover
Number of Trades
```

Main chart:

```text
ECHO strategy
benchmark
optional baseline
```

Include filters:

- date range
- event class
- sector
- horizon

Do not bury drawdown.

---

# 33. Strategy — Event Replay

This is one of the strongest demo experiences.

Allow user to replay a historical event step by step.

Timeline example:

```text
10:14 Event detected
10:15 Event normalized
10:16 Graph exposure calculated
10:16 Forecast generated
10:17 Simulated trade opened
10:18 Market reaction begins
+1D   Outcome
+5D   Outcome
```

Show the information state as it existed at that moment.

Never show future evidence early in the replay.

---

# 34. Strategy — Paper

Show:

- open positions
- pending orders
- completed paper trades
- cash
- buying power
- unrealized P&L
- realized P&L

Columns:

```text
Ticker
Direction
Entry
Current
P&L
Forecast ID
Confidence
Time remaining
Status
```

Execution actions should require confirmation.

---

# 35. Strategy — Analytics

Keep analytics focused on model and strategy evaluation.

Views:

### Forecast quality

- MAE
- directional accuracy
- pinball loss
- interval coverage
- calibration

### Strategy quality

- Sharpe
- Sortino
- max drawdown
- hit rate
- turnover

### Attribution

- performance by event type
- horizon
- sector
- confidence bucket
- graph path length

### Ablation

Compare:

```text
Random walk
Chronos only
Event features only
Graph + event
Full ECHO
```

---

# 36. Settings

Settings is not a primary tab.

Access from:

- avatar menu
- drawer footer

Settings sections:

```text
Profile
Data Sources
API Connections
Model Status
Notifications
Display
Developer
```

---

# 37. Data Sources Screen

Show status for:

```text
World Monitor
Massive
Alpaca
Conviction
Optional JEV
```

Each source:

```text
Connected / disconnected
Last heartbeat
Latency
Last event received
Credential status
```

Never reveal API secrets.

---

# 38. Model Status Screen

Show currently loaded/configured models:

```text
ModernFinBERT
Chronos-2-Small
LightGBM
GARCH/HAR
Conformal calibrator
JEV optional
```

Display:

- version
- loaded/unloaded
- inference device
- last inference latency
- last successful run

This is operational transparency, not model marketing.

---

# 39. Confidence UI Rules

ECHO has multiple confidence dimensions.

Do not collapse everything into a magical single 97% number without context.

Important confidence categories:

```text
Event Confidence
Causal Confidence
Forecast Confidence
Market Confirmation
```

Overall confidence may be shown only when the components are accessible nearby.

Example:

```text
Overall                 82%

Event Confidence         91%
Causal Confidence        84%
Market Confirmation      77%
Forecast Calibration     79%
```

---

# 40. Status Vocabulary

Use consistent labels.

## Event status

```text
Detected
Corroborating
Confirmed
Resolved
```

## Cause status

```text
Unknown
Candidate
Probable
Attributed
```

## Forecast status

```text
Open
Partially Matured
Matured
```

## Strategy action

```text
IGNORE
WATCH
FORECAST
SIMULATE
PAPER TRADE
```

Do not invent synonyms across screens.

---

# 41. Empty States

Every major view must have a designed empty state.

Examples:

## No events

```text
No active events match these filters.
Change filters or wait for new events.
```

## No forecasts

```text
No forecast has been generated for this asset and event yet.
```

## No mature predictions

```text
Prediction evaluation will appear as forecast horizons mature.
```

No empty white boxes.

---

# 42. Loading States

Use skeletons for:

- event lists
- cards
- charts
- tables

Use progress indicators for:

- historical replay
- forecast generation
- graph expansion

Do not block the whole application unless necessary.

---

# 43. Error States

Errors must state:

1. what failed
2. whether existing data remains valid
3. what the user can do

Example:

```text
Live market feed unavailable.
Historical data remains available.
Retrying automatically...
```

Avoid:

```text
Something went wrong.
```

when more information is known.

---

# 44. Freshness Rules

Time-sensitive data must display freshness.

Examples:

```text
Updated 4 sec ago
Market feed delayed 15 sec
World event updated 3 min ago
Forecast issued Sep 20, 10:42 UTC
```

Never let stale information look live.

---

# 45. Live Indicator Rules

`LIVE` may only appear if required live sources are healthy.

Possible states:

```text
LIVE
DELAYED
PARTIAL
OFFLINE
PAPER
DEMO
```

Color and icon should match state.

---

# 46. Number Formatting

Use consistent financial formatting.

Examples:

```text
+2.14%
-0.84%
$183.24
1.7σ
0.82 confidence
```

Large values:

```text
$1.2B
$842M
```

Avoid excessive decimal precision.

---

# 47. Tables

Tables are appropriate for dense financial information.

Rules:

- sticky headers where useful
- sortable columns
- clear row hover
- right-align numeric values
- ticker on left
- do not use zebra striping unless subtle
- important cells may use badges, but not every cell

On mobile, convert critical tables into stacked rows/cards rather than making users inspect 12 tiny columns.

---

# 48. Charts

Use charts only where they answer a question.

Primary chart types:

```text
line
area
candlestick where appropriate
confidence band
bar
calibration plot
scatter for forecast vs actual
```

Avoid 3D charts.

Avoid pie charts for core quantitative analysis.

---

# 49. Chart Interaction

Charts should support:

- hover/crosshair
- timestamp tooltip
- zoom where useful
- event markers
- forecast issuance marker
- clear legend

Forecast charts must clearly distinguish:

```text
historical observed data
forecast distribution
subsequent realized data
```

---

# 50. Event Images

Images are optional.

If used:

- they provide context only
- they must not dominate the interface
- they must be sourced properly
- a missing image must never break layout

Financial intelligence should remain useful without imagery.

---

# 51. Accessibility

Minimum:

- keyboard navigation
- visible focus states
- semantic headings
- ARIA labels for controls
- contrast suitable for dark mode
- chart information available through tooltips/text summaries
- status not communicated by color alone

Drawer must be focus-trapped while open.

On close, focus returns to hamburger button.

---

# 52. Keyboard Interaction

Recommended:

```text
Esc            close drawer/modal
/ or Ctrl+K    search
← →            event replay navigation where safe
```

Do not implement dozens of hidden shortcuts during the hackathon.

---

# 53. Motion Rules

Animations should communicate state, not decorate.

Allowed:

- navigation drawer slide
- card hover
- data update pulse
- graph node expansion
- subtle chart transitions

Avoid:

- constant glowing
- floating cards
- bouncing icons
- looping decorative motion

Respect reduced-motion preference.

---

# 54. Responsive Navigation

## Desktop

Hamburger → 300px overlay drawer.

## Tablet

Hamburger → 320px or ~45vw drawer.

## Mobile

Hamburger → 88–92vw drawer.

Backdrop blur always applies.

Do not maintain a permanent collapsed rail on small screens.

---

# 55. URL / Routing Rules

Suggested structure:

```text
/dashboard
/events
/events/:eventId
/events/shocks/:shockId
/graph
/graph/:eventId
/forecasts
/forecasts/:symbol
/forecasts/:symbol/:forecastId
/strategy
/strategy/backtest
/strategy/replay
/strategy/paper
/strategy/analytics
/settings
```

Even when screens are internal sub-tabs, routes should be shareable where useful.

---

# 56. State Preservation

When switching sections, preserve reasonable UI state:

- selected event
- selected ticker
- graph filters
- selected forecast vintage
- backtest date range

Do not preserve stale transient modals.

---

# 57. Selected Context Pattern

ECHO frequently has an active event and active ticker.

Use a lightweight global context state such as:

```text
Active Event: Strait of Hormuz disruption
Active Asset: LNG
```

Do not force the user to repeatedly reselect the same event when navigating:

```text
Events → Graph → Forecasts
```

---

# 58. Cross-Screen Navigation

Important cross-links:

### Event Detail

```text
View Graph
Open Forecast
```

### Graph

```text
Open Company Forecast
Open Event
```

### Forecast

```text
View Causal Path
Simulate Trade
Open Strategy
```

### Simulator

```text
View Original Forecast
View Realized Outcome
```

Avoid forcing navigation back through Dashboard.

---

# 59. AI Explanation Rules

If ECHO generates natural-language explanation, separate it visually from verified data.

Use label:

```text
ECHO Analysis
```

Never present model-generated explanation as raw source fact.

Each explanation should be concise and traceable to structured evidence.

---

# 60. No Chat-First UI

ECHO may later include an analyst assistant, but the primary product is **not a chat window**.

Do not put a chatbot input at the center of every screen.

Structured intelligence should remain primary.

---

# 61. Trade Language Rules

Because this is a forecasting/research system, use language such as:

```text
Forecast Opportunity
Simulated Position
Paper Trade
Expected Move
Residual
```

Avoid manipulative language such as:

```text
Guaranteed Winner
Strong Buy Now
Can't Miss
```

---

# 62. Data Integrity UI

Where forecasts are immutable, display evidence of integrity:

```text
Forecast issued
Data cutoff
Model version
Feature version
Graph snapshot
```

These may be collapsed behind a `Details` control but must be accessible.

---

# 63. Demo Mode Rules

If demo/mock data is used:

Label the whole environment clearly:

```text
DEMO DATA
```

Never let simulated/demo metrics appear as live market results.

---

# 64. Production vs Paper Mode

Execution mode must always be visible in Strategy/Paper views.

Possible badge:

```text
PAPER MODE
```

Never allow paper execution to look identical to live brokerage execution.

---

# 65. Dashboard Density Rule

The supplied reference image is useful for visual direction but is too dense in places.

ECHO should keep the same intelligence-terminal feel while reducing unnecessary simultaneous panels.

Rule:

> A screen may be information-dense, but each visible panel must answer a distinct user question.

If two panels answer the same question, merge or remove one.

---

# 66. No Duplicate Navigation

Do not simultaneously show:

- left permanent sidebar
- horizontal primary tabs
- secondary duplicate menu

There is exactly one primary navigation mechanism:

```text
Hamburger → overlay vertical drawer
```

Sub-tabs are allowed only inside the active primary section.

---

# 67. Five-Tab Contract

Final primary tabs:

| Tab | Core Question |
|---|---|
| Dashboard | What matters right now? |
| Events | What happened and why? |
| Graph | How does the shock propagate? |
| Forecasts | What does ECHO predict and was it right? |
| Strategy | How does this become a testable trading strategy? |

This table defines the product's primary navigation indefinitely for the initial version.

---

# 68. Recommended Desktop Wireframes

## Dashboard

```text
┌──────────────────────────────────────────────────────────────────────┐
│ ☰ ECHO        Dashboard         Search...       ● LIVE     CP        │
├──────────────────────────────────────────────────────────────────────┤
│ Active Events │ Shocks │ Opportunities │ Accuracy │ Paper P&L       │
├──────────────────────┬─────────────────────────────┬─────────────────┤
│ Live Events          │ Global Shock Map            │ Top Opportunity │
│                      │                             │                 │
├──────────────────────┼─────────────────────────────┼─────────────────┤
│ Market Shocks        │ Affected Equities           │ Accuracy        │
├──────────────────────┴─────────────────────────────┴─────────────────┤
│ Prediction vs Reality / Strategy performance                         │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Events Detail

```text
┌──────────────────────────────────────────────────────────────────────┐
│ ☰ ECHO      Events / Event Detail                    ● LIVE          │
├──────────────────────────────────────────────────────────────────────┤
│ Back    Category  HIGH                                                   │
│ Strait of Hormuz — Increased Naval Activity                         │
│ summary ...                                      Confidence 91%      │
├────────────────────────────────────────────┬─────────────────────────┤
│ Economic Channels                          │ Event Metadata          │
│ Oil Supply             -0.82               │ sources                 │
│ Shipping Costs         +0.77               │ geography               │
│ Energy Prices          +0.73               │ timestamps              │
├────────────────────────────────────────────┴─────────────────────────┤
│ Affected Companies                                                   │
├──────────────────────────────────────────────────────────────────────┤
│ Historical Analogues / Sources / Forecast Preview                    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Graph

```text
┌──────────────────────────────────────────────────────────────────────┐
│ ☰ ECHO      ShockGraph                               ● LIVE          │
├───────────────────────────────────────────────┬──────────────────────┤
│                                               │ Inspector            │
│                                               │                      │
│              CAUSAL GRAPH                     │ Selected: DAL        │
│                                               │ Exposure -0.65       │
│                                               │ Confidence 0.79      │
│                                               │ Causal Path          │
│                                               │ Evidence             │
├───────────────────────────────────────────────┴──────────────────────┤
│ Relationship filters / confidence threshold / reset                 │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Forecasts

```text
┌──────────────────────────────────────────────────────────────────────┐
│ ☰ ECHO   Forecasts   NVDA   Vintage #3   5D             ● LIVE      │
├──────────────────────────────────────────────────────────────────────┤
│ HISTORICAL ACTUAL        │ FORECAST q10/q50/q90 + REALITY           │
│                          │                                          │
│                          │                                          │
├──────────────────────────┴───────────────────────────────────────────┤
│ Expected +2.2% │ P(+) 74% │ 80% band [-0.6,+4.7] │ Horizon 5D      │
├─────────────────────────────────┬────────────────────────────────────┤
│ Prediction Ledger               │ Trade Simulator                    │
│ immutable vintages              │ Prediction / Actual                │
└─────────────────────────────────┴────────────────────────────────────┘
```

---

## Strategy

```text
┌──────────────────────────────────────────────────────────────────────┐
│ ☰ ECHO    Strategy                                      PAPER       │
├──────────────────────────────────────────────────────────────────────┤
│ Builder | Backtest | Replay | Paper | Analytics                      │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│                ACTIVE STRATEGY SUB-VIEW                              │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

# 69. Implementation Priority

Build UI in this order:

## Phase 1

- global shell
- hamburger
- overlay drawer
- backdrop blur
- top bar
- Dashboard shell
- Events list/detail shell

## Phase 2

- live market widgets
- ShockGraph
- event detail tables
- source/evidence UI

## Phase 3

- Forecast chart
- prediction ledger
- prediction-vs-reality view
- simulator

## Phase 4

- Strategy builder
- backtest
- event replay
- paper portfolio
- analytics

## Phase 5

- responsive polish
- keyboard accessibility
- error/loading states
- animation polish
- performance optimization

---

# 70. Frontend Technical Guidance

Recommended stack:

```text
Next.js
React
TypeScript
Tailwind CSS or CSS Modules
React Query / TanStack Query
React Flow or Cytoscape
TradingView Lightweight Charts
MapLibre / deck.gl
```

Do not add libraries without need.

For charts and maps, lazy-load heavier components.

---

# 71. Component Boundaries

Suggested reusable components:

```text
AppShell
TopBar
NavigationDrawer
Backdrop
PageHeader
MetricCard
StatusBadge
ConfidenceBar
EventCard
EventTable
MarketShockRow
SourceEvidenceList
EconomicChannelBar
AffectedCompanyTable
ShockGraphCanvas
NodeInspector
ForecastChart
ForecastMetricStrip
PredictionLedgerTable
VintageSelector
TradeSimulatorPanel
BacktestChart
PaperPositionTable
EmptyState
ErrorState
LoadingSkeleton
```

Do not create enormous page components.

---

# 72. Navigation Drawer Detailed States

## Closed

Only hamburger visible.

## Opening

- drawer slides from `translateX(-100%)` to `0`
- backdrop fades in
- background begins blur

## Open

- focus locked inside drawer
- page scroll disabled
- background interaction disabled

## Closing

Reverse animation.

Focus returns to hamburger.

---

# 73. Drawer Item Design

Each primary item:

```text
[icon] Dashboard
```

Active item:

- subtle blue/cyan background
- brighter text
- left indicator or icon highlight

Avoid giant glowing active states.

---

# 74. Profile Menu

Avatar click opens compact menu:

```text
Profile
Data Sources
Model Status
Settings
Documentation
Sign Out
```

No permanent Settings tab.

---

# 75. Global Search Results

Search result groups:

```text
Companies
Events
Tickers
Topics
```

Selecting result should deep-link into the correct primary tab.

Examples:

```text
NVDA → Forecasts/NVDA
Hormuz event → Events/:id
TSMC relationship → Graph
```

---

# 76. Performance Rules

ECHO is real-time.

The UI must remain responsive while streams update.

Rules:

- do not rerender entire dashboard on every tick
- batch high-frequency market updates
- virtualize long feeds/tables where needed
- lazy-load heavy graph/map/chart modules
- memoize expensive graph transformations
- avoid huge client-side state trees

---

# 77. Live Update Rules

New data should not cause layout jumping.

Use:

- stable card sizes
- value transitions
- subtle pulse for fresh updates
- preserve user's scroll position

If user is reading an older event, do not force-scroll them to newest event.

---

# 78. Notification Rules

Notifications are secondary.

Only notify for:

- high-confidence new event
- major market shock
- forecast maturity
- paper-trade execution
- data-source failure

Do not spam on every market tick.

---

# 79. Trust Rules

Every critical forecast must provide access to:

```text
Input event
Evidence
Graph path
Forecast vintage
Model version
Prediction timestamp
Actual outcome
```

ECHO should always make it possible to ask:

> Why did the system believe this at that time?

---

# 80. Final Design Principle

The product should visually communicate this sentence:

> **ECHO watches reality, understands propagation, forecasts the remaining move, freezes the prediction, and lets the user verify whether it was right.**

Every screen should support that story.

If a UI element does not contribute to:

- situational awareness
- causal understanding
- forecast interpretation
- prediction verification
- strategy evaluation

remove it.

---

# 81. Locked UI Decisions Summary

The following are considered locked for the initial product:

1. Maximum **five primary tabs**.
2. Primary tabs are **Dashboard, Events, Graph, Forecasts, Strategy**.
3. Primary navigation is a **hidden vertical drawer**.
4. Drawer opens from the hamburger button.
5. Drawer **overlays** the page; it does not push content.
6. Background becomes **blurred and dimmed** while drawer is open.
7. No permanent desktop sidebar.
8. No duplicate horizontal primary navigation.
9. Analytics, Backtest, Paper Trading, Simulator, Settings, etc. are nested under the five primary sections.
10. Forecasts are probabilistic and show q10/q50/q90.
11. Predictions are immutable and visually distinguish prediction from actual reality.
12. Trade simulation preserves original assumptions permanently.
13. ECHO must make source evidence and causal paths inspectable.
14. Confidence components must remain interpretable.
15. Demo data and live data must be visually distinguishable.
16. The UI is information-dense but not cluttered.
17. The product is not chat-first.
18. No decorative component is allowed to outrank decision-relevant information.

---

# 82. Definition of UI Done

The first complete ECHO frontend is considered successful when a user can perform this workflow without confusion:

```text
Open ECHO
   ↓
Dashboard shows an important event
   ↓
Open Event
   ↓
Understand evidence and economic channels
   ↓
Open ShockGraph
   ↓
Understand why a company is affected
   ↓
Open Forecast
   ↓
See q10/q50/q90 and recommended horizon
   ↓
See immutable prediction vintage
   ↓
Run trade simulation
   ↓
Return later
   ↓
Compare original prediction against reality
   ↓
Open Strategy
   ↓
Inspect backtest / replay / paper result
```

If that flow is coherent, ECHO has the right interface.

If the UI instead feels like a collection of unrelated dashboards, the design has failed.
