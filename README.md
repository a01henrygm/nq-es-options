# NQ / ES options analytics (local, Windows and Mac)

A personal options-analytics dashboard that runs on your own PC. A Python backend downloads options data from
Cboe's free delayed quotes (or from Massive, formerly Polygon.io, if you switch), calculates exposure levels, stores history in SQLite, and serves a browser dashboard.

## Quick start (Windows)

1. Install Python 3.12 or 3.13 (3.11 to 3.14 also work; a brand-new release may lack ready-made packages) from https://www.python.org/downloads/ and tick **Add python.exe to PATH** on the first
   installer screen. (The Microsoft Store shortcut named `python` that comes with Windows is not a real Python. Downloading the installer is
   not enough; you must run it to the end.)
2. **Extract** the zip (right-click it, **Extract All...**). Do not double-click files while still inside the zip; Windows
   would copy only that one file and the setup would fail. Put the extracted folder anywhere, for example `C:\nq-es-options`.
3. Double-click **diagnose.bat**. It sets itself up on the first run, downloads Cboe's files, and tells you in plain
   English what they contain (underlying price, timestamp, which fields are filled). It saves a sample to
   `logs\diagnose_sample.json`.
4. Double-click **start.bat**. The dashboard opens at http://127.0.0.1:8000 and refreshes by itself every 2 minutes.

No account and no API key are needed for the default data source (Cboe delayed quotes). Stop with Ctrl+C in the
window, or run **stop.bat**. Run the tests with **run_tests.bat**. Logs: `logs\app.log`.

### Using both Cboe and your Massive/Polygon key

Both sources can run at the same time, and the dashboard has a **Data source** dropdown (top left) to switch between them.
Each source keeps its own data and history, so nothing is mixed. Your choice is remembered.

1. Open `.env` in Notepad. Paste your key after `MASSIVE_API_KEY=` and save. Never paste the key into a chat or email.
2. Double-click **diagnose.bat**. For your key it reports whether the key is accepted, whether the options chain is on your
   plan, and whether trades and quotes are available (a true net drift needs both).
3. Close any open start.bat window and run **start.bat** again. Massive appears in the dropdown once a key is present;
   until then it shows as "not set up".

Symbols differ by source: Cboe uses `_NDX` and `_SPX`; Massive uses `QQQ` and `SPY` (or `I:NDX` and `I:SPX` if your plan covers
index options). Set them with `CBOE_UNDERLYINGS` and `MASSIVE_UNDERLYINGS` in `.env`. Futures prices and the basis you type
on the Levels tab are shared by both sources.

## New in 1.9

- **HOD / LOD: moves we may encounter.** The path up and the path down through the key levels, each with its respect / chop / disrespect call, the chance of a touch and why; the chance of staying between the nearest levels until the close; and the data behind it (gamma regime, range used, time left, charm into the close, vanna, dealer delta, scheduled events) with what each means for the move.
- **Charm and vanna in NQ points.** Every bar's hover shows the NQ price, the NDX strike and the size; the zones table has an NQ column. With no NQ price or basis saved, NQ prices are the fair value implied by the option chain (put-call parity carried to the futures expiry). The same conversion now feeds the HOD / LOD, Level map, Quant lab and Chart read tabs.
- **Tap to control the charm and vanna charts.** They start locked so scrolling the page never gets caught by a chart; tap a chart to zoom or drag it, tap outside to lock it again. Hover works either way.
- **Monte Carlo fan.** The Quant lab now draws the simulated paths to the close, the 5/25/50/75/95% bands, the stop and 3 R lines, and where all the paths finished.

## New in 1.8

- **Chart read tab**: paste (Ctrl+V), drop or choose a screenshot of your TradingView chart and get it back marked up: every Q DATA level tagged RESPECT, CHOP or DISRESPECT, what your candles already did at each one, and projected candles after your last candle acting the calls out, plus a downloadable marked-up image. Claude reads the picture through your own Anthropic API key (add it once on the tab; it is stored only in your .env as ANTHROPIC_API_KEY, a few cents per read; CHART_READ_MODEL picks the model). Q DATA makes the calls from today's options data, the same way as the Level map.

## New in 1.7

- **Level map tab**: a candle chart of the session (built from the prices the app stores) with every key level tagged RESPECT, CHOP or DISRESPECT, and projected candles after the last real one acting the calls out, plus a faded alternate path where the first level goes the other way. The call comes from the 0DTE gamma regime and the dealer gamma at each level; the table shows why, how strong, and how often that level type held in the app's own touch log. Scenarios, not forecasts.

## New in 1.6

- **HOD / LOD tab**: the projected high and low of the day. A ladder from the 9:30 open at 0.5 to 2.5 standard deviations of the day's expected move (priced near the open, so the levels stay put), the chance each level gets touched at the open and now, the 0DTE walls, and the 50% / 80% / 95% projected high and low for the rest of the session.
- **HOD/LOD TradingView indicator** (Copy HOD/LOD indicator): the same ladder anchored to your chart's real 9:30 open with live chances, the gamma-regime playbook and regime flips, the 0DTE walls and flip, a mean-reversion test, a Monte Carlo of targets against your stop, and an ES/NQ principal-component split. The expected move is pasted as a share of price, so it works on NQ, MNQ, ES and MES without a basis. Re-copy each session.
- **Quant lab tab**: take profit by gamma regime (short gamma = trend day, aim far, one trade; long gamma = range day, fade failed auctions, 1 to 3 R), the mean-reversion test (t statistic must be below -2.9, half life in minutes), a Monte Carlo of target-before-stop-before-the-close for 1 to 12 R, and NQ against ES from the eigenvectors of their return covariance.
- None of it is backtested; each view says what it assumed.

## New in 1.4

* **Q DATA for Mac:** Apple Silicon and Intel builds in every release, with a menu bar icon, open at login, and the same automatic
  updates. See *Desktop app (Mac)* below.

## New in 1.3

* **Activity heatmap** (replaces the old Heatmap tab): strike by expiry for new positions (open interest change since the last
  session), volume, open interest, modeled GEX, charm, vanna or dealer delta. It shows where the activity is concentrated: hot-spot
  bands, the activity center, and how much sits above or below price, each with its NQ / ES price once a basis is saved.
* **Charm and vanna** tab: modeled dealer flows by strike, how much dealers would need to buy or sell by the close from time
  passing alone, and what a 1-point IV drop would force. All labelled as estimates.
* **New level types:** charm zones, vanna zones, dealer delta zones and new-position zones. Each has its own count on Key levels and
  its own settings group (show, max levels, colors, width, style) in the TradingView indicator. Re-paste the indicator code once.
* The app now stores each day's per-contract open interest, so new positions fill in from the next session on.

## New in 1.1

* **0DTE GEX** tab and level types: gamma from today's expiry only, with its call wall, put wall and flip (also in the paste text
  and the TradingView indicator, with their own colors in the GEX settings group).
* **Session charts:** net GEX by strike through the day with price on top, price inside the expected-move cone, dealer gamma at
  the current price, and cumulative call vs put volume.
* **Before the open:** the gamma curve (all expiries and 0DTE), overnight change in GEX and open interest by strike, and IV / skew
  across sessions.
* **Scorecard:** how often each level type held after a touch and by how much, and each day's opening regime against its real range.
* **Daily bias** now opens with the written case: why the day may go up, why it may go down, the context, and a bullish and a bearish
  plan (trigger, targets, what proves it wrong).
* **Journal:** log trades; the app records the nearest level, regime, bias and gamma side, and groups your results by them.
* **Phone access** tab: turn on password-protected access, with a QR code, and Tailscale for access from anywhere.
* The Q DATA loading window, your icons on the tabs, and the Q DATA icon on the desktop shortcut, tray and taskbar.

## Desktop app (Windows)

The same dashboard as a normal Windows program: its own window, an icon in the system tray, optional start with Windows,
and automatic updates. No Python, no .bat files.

* **Install:** run `NQ-ES-Options-<version>-Setup.exe` from the GitHub release. It installs for your user only (no admin). Windows
  may show "Windows protected your PC" the first time because the installer is not code-signed: click **More info**, then **Run anyway**.
* **Window and tray:** closing the window keeps the app running in the tray, still collecting data. Right-click the tray icon for
  Open, updates, **Start with Windows**, the settings folder, and **Quit**.
* **Your files:** settings (`.env`), the database and logs are in `%LOCALAPPDATA%\NQ-ES Options` (tray: *Open settings folder*).
  Updates never touch that folder. To keep your old data, close the app and copy `.env` and the `data` folder from the old project
  folder into it.
* **Updates:** the app checks GitHub when it starts and every 4 hours. A new version downloads in the background and installs by itself
  when the app starts, or after 16:30 ET on weekdays and any time on weekends, so it never restarts during the session. A bar at the
  top of the page and the tray menu also offer **Restart and update** right away. Set `AUTO_UPDATE=0` in `.env` to only be told.
  A private repository needs `UPDATE_TOKEN=<token>` in `.env` (a fine-grained GitHub token with read access to that repo's contents).
* **Making a release:** raise `__version__` in `backend/version.py` and push to main. GitHub Actions runs the tests and, when that
  version has no release yet, builds the installer on Windows (`installer/build.ps1`: PyInstaller, then Inno Setup) and the Mac
  apps (`installer/build_mac.sh`), and publishes release `v<version>` with all of them, which the apps update from.
* **The old .bat version still works** from the project folder and keeps its files there. The desktop app removes the old
  "start at sign-in" task the first time it runs, so the two do not both start.


## Desktop app (Mac)

The same app for macOS 11 or newer, on Apple Silicon (M1 and later) and Intel Macs: its own window, an icon in the menu bar,
optional open at login, and automatic updates. No Python needed.

* **Install:** from the GitHub release download `Q-DATA-<version>-macOS-arm64.dmg` (Apple Silicon: Apple menu > About This Mac
  shows an "Apple M..." chip) or `...-macOS-x86_64.dmg` (Intel). Open it and drag **Q DATA** onto **Applications**. Open it from
  Applications, not from the download window, or updates can't replace it.
* **The first time you open it** macOS says it can't verify the developer, because the app is not signed with a paid Apple
  developer account. Click **Done**, then go to **System Settings > Privacy & Security**, scroll down, and click **Open Anyway** next to
  Q DATA (once). Or in Terminal: `xattr -dr com.apple.quarantine "/Applications/Q DATA.app"`. After that it opens normally, and the
  updates it downloads itself don't ask again.
* **Window and menu bar:** closing the window (or Cmd+Q) keeps the app running in the menu bar, still collecting data. Click the
  menu bar icon for Open, updates, **Open at login**, the settings folder, and **Quit**. Clicking the Dock icon brings the window back.
* **Your files:** settings (`.env`), the database and logs are in `~/Library/Application Support/Q DATA` (menu bar: *Open settings
  folder*). Updates never touch that folder.
* **Updates:** the same schedule as on Windows. The app downloads the `.zip` for its chip, waits until it has quit, puts the new
  Q DATA in place of the old one in Applications, and opens it again.
* **Phone access:** when you turn it on, macOS may ask whether Q DATA may accept incoming network connections: click **Allow**.
* **Building:** `installer/build_mac.sh` (PyInstaller, then a `.dmg` and an update `.zip`). The release workflow runs it on an Apple
  Silicon and an Intel Mac, opens each built app once with `--smoke-test` to check it starts, and adds the files to the release.

## What each part does

| Part | File(s) | Job |
|---|---|---|
| Providers | `backend/providers/cboe.py`, `massive.py` | Cboe (default, free, no key) downloads a public JSON file per underlying. Massive uses your key. Both return the same normalized chain. |
| Collector | `backend/collector.py` | One background thread polls the provider, stores a new snapshot only if the content changed, then recalculates. |
| Freshness | `backend/services/freshness.py`, `market.py` | Judges age from the provider's own timestamps against the NYSE calendar (weekends, holidays, early closes, daylight saving). |
| Analytics | `backend/services/analytics.py` | GEX, gamma flip, delta exposure, open interest, volume, IV, expected move. Pure functions, easy to test. |
| Mapping | `backend/services/mapping.py` | Converts ETF or index levels to futures estimates with a ratio or basis and reports warnings. |
| Database | `backend/database.py` | SQLite file in `data\`. Keeps snapshots, prices, metrics, and provider errors. |
| API | `backend/api.py` | The only thing the browser talks to. Interactive docs at http://127.0.0.1:8000/api/docs |
| Dashboard | `frontend\` | HTML, CSS, JavaScript. It never sees the provider key. |

Data path: Massive -> provider -> collector -> SQLite -> analytics -> FastAPI -> dashboard.

## IV by strike and the volatility surface

* **IV by strike** draws one cleaned line per expiry. It uses out-of-the-money options only (puts below the price,
  calls above), drops zero-bid and wide-spread quotes, averages duplicate strikes, and removes isolated spikes.
  A note under the chart counts exactly what was dropped. Untick the boxes to see the raw picture.
* **Vol surface** shows the same cleaned IV as a rainbow 3D surface (with term-structure and skew lines on the walls) or
  as a heatmap. Gaps are filled by straight lines between neighbouring strikes of the same expiry; nothing is extrapolated.
* To see more expirations or a wider strike range, raise `MAX_DTE` and `STRIKE_WINDOW` in `.env` (defaults: 30 days, 12%).

## Reading the numbers

* **Every panel shows** provider, symbol, source time (when the provider says the data was made), retrieved time
  (when this app received it), calculated time, and a status: live, delayed, closed last session, stale,
  daily snapshot (open interest), or no source time. Refreshing the page never makes old data look new.
* **Open interest** is the end-of-previous-day figure. It does not change during the session.
* **GEX and delta exposure are modeled.** Open interest does not reveal who owns contracts. The sign comes from the
  scenario you pick (standard: calls +, puts -). Formula: gamma x open interest x multiplier x spot^2 x 0.01.
* **Gamma flip** re-prices gamma at hypothetical prices and looks for a zero crossing. If none exists, it says so.
* **Expected move** is a statistical estimate: the ATM straddle price and spot x ATM IV x sqrt(time).
* **Getting NQ numbers fast:** on the Levels tab type the **basis** once (NQ minus NDX, read from TradingView at the same
  moment) and press Save basis. Every level then shows as an NQ number, and **Copy NQ levels as text** copies them. The
  basis drifts by a few points during a session, so retype it now and then (a warning appears after 6 hours).
  Typing an NQ price instead also works; whichever you typed last is used.
* **Mapped futures levels are estimates.** The futures price is typed in by you on the Levels tab (this version has
  no futures data feed). If your options data is 15 minutes delayed, enter the futures price **as of the ETF
  timestamp** (shown on the tab) or the mapping will be flagged asynchronous. Mapping error is measured
  automatically once at least 11 paired observations are stored.

## Provider notes

* **Cboe (default).** Free delayed quotes, about 15 minutes behind, one file per underlying. `_NDX` (Nasdaq-100 index
  options) maps to NQ and `_SPX` maps to ES using a basis between the index and the futures price. `QQQ` and `SPY`
  also work (use a ratio). Open interest is the previous day's figure. The snapshot's own timestamp is read as
  Eastern Time and used for freshness; if it is missing the panel says "no source time". Check Cboe's terms for
  their data before sharing or redistributing it. This app is local and personal.
* **Massive.** The option chain snapshot is documented as not included in the free Options Basic plan. Index options
  need the `I:` prefix. Verify plans on massive.com/pricing. Trades and quotes (needed for a true net drift) are separate
  entitlements; diagnose.bat tests them for your key.
* **Cboe does not offer futures options.** NQ and ES option chains (CME) are not part of this free source.
* Add another provider by writing a class like `CboeProvider` that implements `fetch_chain`.

## Daily tools

* **Daily bias** tab: a plain-English bullish / bearish / mixed reading built from the walls, put/call volume, skew change and term
  structure, with a confidence rating, what would change the view, and cautions. It is context, not a forecast; the thresholds
  are rough rules I chose and have not been tested against outcomes.
* **Pre-market sheet** tab: one page with the verdict, every level in NQ estimates (with distance from price), unusual volume
  and signals. Use **Print / save as PDF**.
* **Pine export** (Levels tab): **Copy Pine code** or **Download .pine** gives a TradingView Pine v6 indicator with today's levels
  in NQ points. Paste it into the Pine Editor, add it to the chart, and repeat each session. It was not compiled by TradingView
  from here; if TradingView shows an error, send it to me.
* **TradingView indicator** (`tradingview\\options_levels_indicator.pine`): paste it into the Pine Editor once. After that, each
  session open the Levels tab, copy the text from the box under the table (headed "Paste into the TradingView indicator") and paste it into the indicator's settings
  (Levels box). No code editing. Each line starts when THAT level first appeared (the Levels tab shows it in the "Shown since"
  column) and ends in a small block at the current candle; nothing extends to infinity. A level that is still there keeps its
  start time as its value drifts a little; a level that moves a long way starts a new line. Times are when this app first saw the
  level, so they begin when you first run it each session. There are checkboxes per level type and a distance filter.
* **Open interest and volume by expiry:** on the Levels tab, **Open interest and volume strikes by expiry** adds, for each of the next
  1 to 5 expirations on its own, the biggest call and put open-interest strikes and the biggest total, call and put volume strikes.
  They are labeled with the expiry date (for example "OI call 10/18") and drawn dashed in the TradingView indicator, using the
  open interest and volume colors and checkboxes. Turn it off with Off.
* **GEX call-wall and put-wall ZONES:** the old "Largest call/put GEX strike" lines are now bands. A strike is a wall strike when its
  bigger side (call or put gamma) is at least 30% of the biggest single-side GEX. Wall strikes next to each other (no more than one strike
  skipped) become ONE band, and the side with MORE wall strikes in it decides its type, so call wall, put wall, call wall is a call-wall
  zone (a tie goes to the larger total GEX). The band runs from the lowest to the highest wall strike, widened by half the local strike gap,
  and never reaches more than 0.3% of price either side of its strongest strike (a bigger run is split into several zones). **Strikes kept
  per type** sets how many zones per side (up to 3). Zones show as a range in the table, a shaded band on the price chart, and a shaded
  box in the TradingView indicator (green call-wall zones, red put-wall zones, with a checkbox). Plain levels inside a band are listed
  under it in key-level mode instead of being drawn again.
* **Open interest and volume are zones too:** the single "High call/put open interest" and "High session volume" lines are now call-side and
  put-side ZONES built exactly like the GEX wall zones (strikes at least 30% of the biggest, neighbours merged with at most one strike skipped,
  more strikes on one side wins the type, a zone starts and ends on its own side, width capped near 0.3% of price either side of its
  strongest strike). Colors: call OI light orange, put OI dark orange, call volume teal, put volume pink. The same applies to the per-expiry
  levels (one call and one put zone per expiry for open interest and for volume, labelled with the date) and to mid-size levels (zones whose
  total is 25% to 70% of the biggest zone on their side, at least 300 contracts of open interest or 50 of volume at their peak strike).
  Per-expiry total volume is now split into its call and put zones. In key-level mode, bands that overlap by half or more are merged into one
  that shows every name ("Call wall zone / Call OI zone / +GEX zone") with a bonus for the agreement. The gamma flip, expected-move
  edges and levels you type stay single lines (they are not built from strikes); the flip and your own levels are never hidden inside a band.
* **Positive and negative GEX zones:** built the same way from the NET gamma at each strike (calls minus puts under the chosen sign
  scenario): strikes next to each other form one band, the sign with more strikes decides positive or negative, and a band starts and ends
  on a strike of its own sign (an opposite strike sandwiched inside is absorbed; one at the edge forms its own zone). Blue = positive GEX zone,
  violet = negative GEX zone, in the table, on the chart and in the indicator (own checkbox). Same width cap as the wall zones.
* **Market overview tab:** the daily bias for EVERY symbol in `CBOE_UNDERLYINGS` side by side, using the same rules as the Daily bias tab:
  verdict, score, confidence, day type, gamma flip, call/put wall zones, positive/negative GEX zones, expected move, and an
  "Open full daily bias" button. It also says whether related symbols agree (NDX with QQQ, SPX with SPY, and the Nasdaq group against the
  S&P group); symbols with stale data are left out of those checks. Agreement between NDX and QQQ is a consistency check, not independent
  confirmation, because they are highly correlated. To add QQQ and SPY, set `CBOE_UNDERLYINGS=_NDX,_SPX,QQQ,SPY` in `.env` and restart
  (each symbol is one more download per cycle; ETFs map to futures with the ratio method, which needs a typed futures price).
* **Change it in TradingView:** the indicator has a settings group per kind (Gamma flip, GEX, Open interest, Volume, Expected move,
  Levels you typed in) with Show, **Max levels**, color(s), width and line style. Max levels keeps the highest-scoring levels of that kind
  (0 = all). Each pasted row now ends with its score and kind (`..., score, family`), which the indicator uses for this. Older pasted text
  still works (no score: nearest to price first). Pick **Send extra, trim in TradingView** in the app's Show menu so the indicator has
  enough levels to choose from.
* **Far zones become lines:** in both indicators, a zone (expected move, call/put, GEX) whose nearest edge is farther than the
  **Zones farther than this % from price are drawn as a line** setting (default 1%) is drawn as one line at its main price, without the band.
* **Per-type counts:** the **Show** menu also has **GEX-heavy** (GEX 8, open interest 2, volume 1, expected move 2), **Balanced** (3/3/2/2) and
  **Custom counts...**, which shows a number box for each kind (0 to 20). Within each kind the highest-scoring zones are kept. A zone where several
  kinds line up uses one slot. The gamma flip and levels you typed in are always shown and use no slot. With a GEX count set, the app also builds
  more GEX candidates (about half the count per side) so there is enough to fill it. The paste text, Pine export, chart, pre-market sheet and
  alerts follow it, and your counts are saved in the browser.
* **Nearest N:** the **Show** menu on the Levels tab also has **Nearest 8 / 14 / 20 / 30**, which keeps the N zones closest to price (a band price
  is inside counts as distance 0). It changes the table, the price chart, the paste text, the pre-market sheet, the alerts and the TradingView
  export together; a line above the table says how many are showing out of how many exist. If you ask for more than exist (for example Nearest
  30 when only 15 zones exist), you get all of them: raise **Strikes kept per type**, **Mid-size levels** or the by-expiry and move menus to
  create more. The old chart-only selector is gone because it did not change the paste text.
* **Key levels only (default):** the Levels tab **Show** menu defaults to the top 10 zones instead of every level. Each level gets an
  importance score (size compared with the biggest level of its kind, times a type weight, times closeness to price: full inside about
  one expected move, fading to 35% beyond two). Levels within 0.10% of price of each other merge into one **zone** named for what lines
  up there (for example "Gamma flip / Put GEX / GEX-"), and agreement between different kinds of level adds to the score. The score is
  shown, and the table lists every member of each zone. The weights are my own judgement, not tested evidence; they decide what is
  shown first. Choose **All levels** for the full list. The paste text, price chart, pre-market sheet and alerts all follow this setting.
* **Mid-size levels (variety):** the **Mid-size levels** menu on the Levels tab (default 2 per type) adds strikes that are clearly
  meaningful but not the biggest: at least 25% and at most 70% of the biggest strike in their group, a local peak, at least 300
  contracts of open interest or 50 of volume, and at least 0.15% of price away from other chosen strikes of the same type. They exist
  for combined expirations and for each expiry on its own (labels end in "mid"), have their own checkboxes, and are drawn lighter
  and dashed in the TradingView indicator. Set it to Off for just the top levels.
* **Missing a level you can see in another app?** The Levels tab keeps the top 2 strikes per type by default. Raise **Strikes kept
  per type** (up to 10), and note that GEX now also lists the biggest call-side and put-side strikes separately (a strike with
  huge call AND put gamma nets to almost zero, so the net list hides it). **Add your own level** types in any price you want to
  see (in index units, or in NQ points once a basis is saved); it appears in the table, chart and indicator text and can be removed
  with its x button. Other apps also differ in expiration (for example today's expiry only), dealer-sign assumption, and weighting:
  use the Expiration box at the top to limit the levels to chosen expirations.
* **Scenarios side by side** (Gamma flip tab): flip from open interest versus today's volume. Flipping the dealer sign does NOT
  move the flip level; it only changes which side is calmer, so the comparison that matters is the weighting.
* **Level reactions** tab: the first levels of each session are kept, and the app records what price did after touching them.
  It needs weeks of running to say anything; samples under 10 touches are marked "too few to conclude".
* **Levels through the day** (History tab): price with the flip, walls and expected-move edges as they changed.
* **Alerts** (button at the top): a banner, optional sound and optional desktop notification when price comes within a set
  percentage of a level. The page must be open in a browser tab; alerts use delayed data and pause when the market is closed.

### Regime

* **Regime tab** (also a line on every Market overview card and on the pre-market sheet): is today a pinned, mean-reverting day or one that can
  trend and expand? A visible scorecard, not a forecast, with my own thresholds and not backtested. Each measure gets a lean from unstable to calm:
  **gamma** (price above or below the estimated flip; within 0.25% of it the label is "Transition"), **volatility level** (3-week at-the-money IV
  against its own stored history once about 10 sessions exist, otherwise rough fixed ranges for the Nasdaq 100 and S&P 500), **term shape**
  (contango is calm, backwardation is stress or an event), **skew change** (a rise of more than 1 point), **range so far today** versus the
  expected move, and a **scheduled event** today. Total 3 or more: Pinned and calm; 1 to 2: Calm; 0 or a split: Mixed; -1 to -2: Leaning unstable;
  -3 or less: Trending, expansion risk. Confidence depends on how many measures are available and agree, and is held down when total gamma and the
  flip disagree or the data is stale. The tab also lists which zones price is inside and what would change the label. The volatility history
  (a 3-week IV figure) is stored every cycle, so the comparison gets better as sessions accumulate.

### Reading, zooming and remembering

* **Every tab has a "What is this tab?" line** under its title: what it shows and how to read it, in plain English. Tabs are grouped (Today,
  Options data, Volatility, Review).
* **Zoom:** every chart has Zoom +, Zoom -, Reset and Full screen buttons above it, plus the mouse wheel (zoom), dragging (select an area) and
  double-click (reset). 3D views rotate with a drag. Your zoom and rotation are kept when the page refreshes by itself every 20 seconds, and
  the refresh waits while you are typing, have the paste box selected, or have just used a chart. **A- / A+** at the top change the text size
  of the whole page (Ctrl and + also work).
* **Settings are remembered** in your browser: the tab and symbol, the Levels Show menu and level families, the by-expiry, mid-size and
  expected-move menus, the heatmap and IV settings, the text size and which sections are open. **Vol surface** starts on **Both** (3D and
  heatmap together) and keeps whatever you pick. The published web page also keeps its volume window and heatmap choices, and its charts zoom
  with the mouse wheel.
* **If the page looks old after an update:** press Ctrl+F5 once. From then on the app tells the browser to re-check the page files every load.
  A menu change made while the page is still loading is queued and applied afterwards instead of being lost.
* **Levels tab:** one toolbar (Show, plus six on/off chips for families of levels instead of nineteen boxes), then collapsible sections for the
  extra settings, your own levels, the NQ conversion and the paste box, then the table with a score bar.

### Expected moves, events and phone access

* **Expected move tab:** a plain-English explanation written with today's real numbers, a cone chart, and a table for the next 6
  expiries showing the straddle move, 1 sigma and 2 sigma, and the price levels UP and DOWN for each (plus your futures estimate
  once a basis is saved). The straddle is what the market charges for a move either way; 1 sigma is spot x ATM implied volatility x
  the square root of the time left, and under the bell-curve assumption price ends inside it about 68% of the time (2 sigma about 95%).
  Real markets have fatter tails, so 2 sigma means "unusual", not "impossible". On the Levels tab, **Expected-move ranges by expiry**
  adds them as ZONES, not lines: for each expiry and each direction an **Expected move zone** (the band between the straddle price and the
  1 sigma move, which are two estimates of the same expected move; widened to 5% of the distance if they nearly agree) and an **Extended
  move zone** (the band from 1 sigma out to 2 sigma, unusual territory). Labels look like "Expected move zone up 10/18" and "Extended move zone
  down 10/18". They are drawn as shaded boxes on the chart and in the TradingView indicator (own light-blue colors, "Expected move" checkbox).
  Several expiries stack as nested bands; use 1 or 2 expiries, or key-level mode, if it gets busy.
* **Events tab:** a list you maintain. A banner on every screen warns when a high-importance event is today, and the pre-market sheet,
  the daily bias (as a caution, never a change to the verdict) and the expected-move table mention events. The starter list (FOMC
  decisions, CPI, jobs, PPI, options expirations) came from published calendars on 2026-10-16: check it against federalreserve.gov
  and bls.gov. Removed events do not come back.
* **Phone access (same Wi-Fi):** in `.env` set `HOST=0.0.0.0` and `ACCESS_PASSWORD=` to a password of 8+ characters, then restart. The
  app refuses to start with an open HOST and no password. When Windows asks, allow Python on PRIVATE networks only. The black window
  prints the phone address (for example http://192.168.1.20:8000); open it on the phone and sign in once (stays signed in 30 days). This
  PC is not asked for the password (set `ACCESS_LOCAL_BYPASS=0` to ask here too). After 5 wrong passwords an address is locked out for
  5 minutes. Traffic on your Wi-Fi is plain http, so use it only on your home network and never forward the port on your router.

### Start automatically

Double-click **install_autostart.bat** to start the app silently (no window, no browser) each time you sign in to Windows. Your PC
must be on and awake during market hours for data to be collected. **remove_autostart.bat** undoes it and **stop.bat** stops it
right now. The log is `logs\background.log`.

## Also included

* **Heatmap** tab: strike by expiry grid of volume or open interest (calls + puts, calls, puts, or calls minus puts), with a
  price line. Colors are compressed so one huge cell does not hide the rest; hover shows exact contract counts.
* **Open interest** by strike with call and put bars, plus the change between stored sessions.
* **Volume** by strike with an "unusual volume" flag. The flag compares each strike with the rest of today's chain (robust
  z-score); it is not a comparison with past days.
* **Levels** table (mapped to futures) and a chart of this session's price with the key levels drawn over it.
* **Expected move** with the actual move so far, as a share of the expected move.
* **Delta exposure** by strike and at hypothetical prices.

## Not included (honest list)

Trade-level options flow (Cboe's free files have the last trade per contract, not a trade tape), a historical volume baseline
and IV percentile (they fill in after the app has run for days), historical volatility, session highs/lows, a futures price
feed, price-reaction studies, and any probability or scenario scoring. Each is shown as unavailable instead of faked.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Python is not installed" / "Python was not found; run without arguments to install from the Microsoft Store" | Install Python from python.org (tick Add python.exe to PATH), close the window, and run the file again. |
| Massive says "not set up" in the dropdown | There is no key in `.env` yet, or `PROVIDERS` does not list `massive`. |
| "No data has been received yet for this underlying" | Read the line under it: it says whether the first download is still running (Cboe's files are big; wait up to a minute), the last download failed (the error is shown), or a file arrived without a usable price. Then open the Status tab and `logs\\app.log`, and run diagnose.bat. |
| Dashboard says no data | Open the Status tab and run diagnose.bat. `network` means Cboe could not be reached from your PC (firewall or internet). |
| Status "stale" while the market is open | The provider stopped returning new data, or your plan setting does not match (delayed vs realtime). |
| Charts missing | The chart script loads from the internet; check your connection. |
| "Address already in use" / port 8000 busy | The app now handles this itself: if the dashboard is already running it just opens it, and if another program holds the port it uses the next free one. To fully restart, run stop.bat first. |
