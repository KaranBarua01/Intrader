# Intrader 0.4.3 Visual Contract

This document is the visual acceptance contract for the approved Intrader desktop UI.

## Global identity

- Light editorial workstation aesthetic: Apple/Nothing restraint with technical trading density.
- No permanent left sidebar.
- No permanent top mode navigation.
- Top bar contains: Intrader vector mark + wordmark, Accent swatches, Refresh Data, Update.
- One fixed visual identity. There are no themes.
- Only the accent color is user-customizable.
- Accent options are matte/pastel presets.
- Bullish green and bearish red are semantic and never follow the accent.
- Background: warm off-white.
- Cards: near-white, soft border, 14px radius, restrained shadow.
- Halftone dot fields are decorative and sparse.
- Avoid neon, glossy gradients, gaming-terminal styling, and oversized empty cards.

## Navigation

- Navigation dock is hidden by default.
- Closed state: only a bottom-center equilateral triangle is visible.
- Closed triangle points up and uses bullish green.
- Open triangle points down and uses bearish red.
- Open dock is a black bottom bar with Intrader, Time Travel, Analysis, Strategy Lab, More, and the version at the right.

## Intrader Mode

One-screen workstation:
- Compact decision/status ribbon at the top.
- Left ~64%: NIFTY 50 chart with 1m/3m/5m/15m/30m/1H/Auto.
- Under chart: Why this action, Why not the opposite, Context.
- Right ~36%: Shadow Trade, Current Interpretation, Global News / Events.
- No duplicate page navigation.

## Time Travel

Default view is Range Analysis:
- Header: Time Travel + short research subtitle.
- Compact control card with From/To, Analyze Period, Fetch Missing, 1H/Today/5D/10D/30D.
- Compact metric ribbon.
- Main split: chart ~58%, analysis/opening intelligence ~42%.
- Opening intelligence includes Analysis Context, Bullish/Balanced/Bearish weights, Gap Risk, drivers, bias and evidence coverage.
- Bottom: Key Moments / Period Analysis / Data Coverage on the left; Decision Mix and Regime Mix on the right.
- 30m Replay remains available through the compact Replay switch.

## Strategy Lab

- Header: Strategy Lab + LAB ONLY badge.
- Single compact control card: range, 5D/10D/30D, Source, Analyze Strategies, Fetch Missing.
- Compact metric ribbon.
- Main split: strategy performance table ~72%, selected strategy detail ~28%.
- Strategy table columns: Source, Strategy, n, Bull, Bear, 5m, 15m, 30m, Avg30, MFE, MAE, Sample.
- Occurrences table spans the lower workspace.
- Strategy Lab remains isolated from Intrader Mode logic.

## Color behavior

Semantic market colors:
- Bullish: #2D8A60
- Bearish: #C64B4B

Default editorial accent:
- Matte Red: #D85C5C

Supported accent presets:
- Matte Red #D85C5C
- Pastel Peach #F2B894
- Matte Green #5E9B72
- Pastel Cyan #A6D7D8
- Matte Blue #5E7FAE
- Pastel Violet #C7B7DF
- Matte Orange #D9874E
- Pastel Pink #E3B5C4

The accent may affect the logo bar, tab underline, sliders, halftone decoration and editorial highlights. It must never redefine bullish/bearish meaning.
