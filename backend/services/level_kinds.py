"""The kinds of level Q DATA draws: name, color and line style per category, and what each means in plain words.
Shared by the tab indicators (api_tabs) and the Key levels indicator (pine.py)."""
from __future__ import annotations

# category -> (show/hide group name, color, line style). Colors match the Key levels indicator.
CAT = {
    "gamma_flip": ("Gamma flip", "#ffc400", "solid"), "gex0_flip": ("0DTE gamma flip", "#ffdd00", "dashed"),
    "gex0_call_wall": ("0DTE call wall", "#00e5ff", "solid"), "gex0_put_wall": ("0DTE put wall", "#ff1f7a", "solid"),
    "gex_concentration": ("Biggest GEX strikes", "#1e7bff", "solid"),
    "gex_call_zone": ("GEX call wall zones", "#00d65c", "solid"), "gex_put_zone": ("GEX put wall zones", "#ff3b30", "solid"),
    "gex_pos_zone": ("Positive GEX zones", "#1e7bff", "solid"), "gex_neg_zone": ("Negative GEX zones", "#a64dff", "solid"),
    "open_interest": ("Open interest strikes", "#ff6a00", "solid"), "oi_by_expiry": ("Open interest by expiry", "#ff6a00", "dashed"),
    "oi_mid": ("Open interest midpoints", "#ffa04d", "dotted"), "oi_call_zone": ("Call open interest", "#ff9500", "solid"),
    "oi_put_zone": ("Put open interest", "#ff4500", "solid"),
    "volume": ("Volume strikes", "#00d65c", "solid"), "volume_by_expiry": ("Volume by expiry", "#00d65c", "dashed"),
    "volume_mid": ("Volume midpoints", "#4dff91", "dotted"), "volume_call_zone": ("Call volume", "#00e0c6", "solid"),
    "volume_put_zone": ("Put volume", "#ff4fa3", "solid"),
    "expected_move": ("Expected move", "#4da6ff", "dotted"), "expected_move_ext": ("Expected move (wider)", "#7a5cff", "dotted"),
    "charm_sell_zone": ("Charm: dealers sell", "#ff5a36", "solid"), "charm_buy_zone": ("Charm: dealers buy", "#00c9a7", "solid"),
    "vanna_pos_zone": ("Vanna positive", "#c34dff", "solid"), "vanna_neg_zone": ("Vanna negative", "#ffb300", "solid"),
    "dex_pos_zone": ("Dealer delta: long", "#29d3ff", "solid"), "dex_neg_zone": ("Dealer delta: short", "#ff0a78", "solid"),
    "new_call_zone": ("New call positions", "#9dff4d", "solid"), "new_put_zone": ("New put positions", "#ff4d4d", "solid"),
    "custom": ("Your levels", "#ffffff", "solid"),
}


# What each kind of level means, in plain words: (short meaning shown next to the label, longer help shown in the settings tooltip)
HELP_RULES = [
    ("High of day so far", "today's high", "The session's high so far. Above it, price is making a new high of day."),
    ("Low of day so far", "today's low", "The session's low so far. Below it, price is making a new low of day."),
    ("HOD ladder", "HOD target", "The 9:30 open plus k standard deviations of the day: where the high of day usually lands. Hover for the chance of reaching it."),
    ("LOD ladder", "LOD target", "The 9:30 open minus k standard deviations of the day: where the low of day usually lands. Hover for the chance of reaching it."),
    ("Projected HOD", "projected high", "Projected high of the day from here: 50/80/95% of random-walk paths top out at or below it, using the move left in the day."),
    ("Projected LOD", "projected low", "Projected low of the day from here: 50/80/95% of random-walk paths bottom out at or above it, using the move left in the day."),
    ("Stacked areas: HOLD", "stack, should hold", "Several different kinds of levels in one area, and the call is HOLD: price should stall and reject there. Fade it with a stop just past the area."),
    ("Stacked areas: CHOP", "stack, two-way", "Several kinds stacked, but the call is CHOP: expect back-and-forth around it. No edge either way; wait for price to leave it."),
    ("Stacked areas: BREAK", "stack, likely breaks", "Several kinds stacked, but the call is BREAK: in this gamma regime price tends to push through. Trade the break, not the fade."),
    ("HOLD levels", "should hold", "Price should respect this level: stall and reject, wicks through but closes back."),
    ("CHOP levels", "two-way trade", "Expect chop around this level: no clean hold or break."),
    ("BREAK levels", "likely breaks", "Price is likely to disrespect this level and push through it."),
    ("long entries", "buy here", "A Game plan long setup: the entry price. Hover the label for the grade and the team vote."),
    ("short entries", "sell here", "A Game plan short setup: the entry price. Hover the label for the grade and the team vote."),
    ("stops", "stop", "Where the setup is wrong: just past the far side of the area."),
    ("targets", "target", "The setup's target, at the R the Monte Carlo liked best."),
    ("Stay away", "no edge", "A CHOP area or a setup the team voted down: no edge, stay out."),
    ("0DTE gamma flip", "0DTE regime line", "Where today's-expiry dealer gamma flips sign. Above it moves get absorbed; below it moves get chased."),
    ("0DTE flip", "0DTE regime line", "Where today's-expiry dealer gamma flips sign. Above it moves get absorbed; below it moves get chased."),
    ("Gamma flip", "regime line", "Where total dealer gamma flips sign. Above it dealers dampen moves (range day); below it they add to moves (trend day)."),
    ("0DTE call wall", "0DTE ceiling", "Today's-expiry strike with the most positive gamma: a magnet and a ceiling while gamma is positive."),
    ("0DTE put wall", "0DTE floor", "Today's-expiry strike with the most negative gamma: a floor that can give way hard if broken."),
    ("Call wall", "ceiling", "The biggest call positioning: the main ceiling. Accepted above it, the ceiling is gone."),
    ("Put wall", "floor", "The biggest put positioning: the main floor. Accepted below it, the floor is gone."),
    ("Top + 0DTE", "+gamma strike", "Big positive 0DTE gamma: dealers sell rallies and buy dips around it, so price tends to stick."),
    ("Top - 0DTE", "-gamma strike", "Big negative 0DTE gamma: dealers hedge with the move, so price can speed up through it."),
    ("Biggest GEX", "big gamma strike", "Strikes with the most dealer gamma. Price often pauses or pins at them."),
    ("GEX call wall zones", "call wall zone", "Band around the call-side gamma wall: resistance while gamma is positive."),
    ("GEX put wall zones", "put wall zone", "Band around the put-side gamma wall: support, weaker if gamma turns negative."),
    ("Positive GEX zones", "+GEX, dampens", "Dealers long gamma here: they dampen moves, so expect slower, mean-reverting trade."),
    ("Negative GEX zones", "-GEX, speeds up", "Dealers short gamma here: they add to moves, so expect faster trade through it."),
    ("Call open interest", "call OI", "Heavy call open interest: often resistance."),
    ("Put open interest", "put OI", "Heavy put open interest: often support."),
    ("Call volume", "call volume", "Heavy call trading today at this strike."),
    ("Put volume", "put volume", "Heavy put trading today at this strike."),
    ("Open interest", "open interest", "Strikes with the most open contracts: positions people care about, often reaction points."),
    ("Volume", "today's volume", "Strikes trading the most today: where today's money is."),
    ("Expected move (wider)", "outer move", "The wider expected-move band: price gets here on bigger days only."),
    ("Expected move", "expected move", "The move options price for the day: about 2 days in 3 stay inside."),
    ("Straddle", "straddle move", "Spot +/- the at-the-money straddle: the market's price for the move to that expiry."),
    ("1 sd", "1 sd move", "1 standard deviation from implied volatility: about 68% of the time price stays inside."),
    ("2 sd", "2 sd move", "2 standard deviations: about 95% of the time price stays inside. Rarely reached."),
    ("Charm: dealers sell", "charm selling", "Charm makes dealers sell here as time passes: a drift lower into the close."),
    ("Charm: dealers buy", "charm buying", "Charm makes dealers buy here as time passes: a drift higher into the close."),
    ("Vanna positive", "vanna +", "If volatility falls, dealers buy here (vanna)."),
    ("Vanna negative", "vanna -", "If volatility rises, dealers sell here (vanna)."),
    ("Dealer delta: long", "dealers long delta", "Dealers net long delta here: they sell into rallies to hedge."),
    ("Dealer delta: short", "dealers short delta", "Dealers net short delta here: they buy dips to hedge."),
    ("New call", "new calls", "Fresh call positions since the last session."),
    ("New put", "new puts", "Fresh put positions since the last session."),
    ("9:30 open", "the open", "Today's 9:30 open: the anchor for the expected move and the cone."),
    ("Playbook range", "range edge", "The gamma playbook's range: fade failed auctions at the edges, the middle is the first target."),
    ("Playbook targets", "playbook target", "Targets from the gamma playbook for today's regime."),
    ("Monte Carlo high", "simulated HOD", "Where simulated paths put today's high: e.g. 80% means 4 paths in 5 top out at or below it."),
    ("Monte Carlo low", "simulated LOD", "Where simulated paths put today's low."),
    ("Typical day", "VIX day range", "The 9:30 open +/- the typical day priced by the VIX family: +/-1 holds about 2 days in 3, +/-2 about 19 in 20."),
    ("Your levels", "your level", "A level you typed into Q DATA."),
]


def help_for(name):
    for key, short, long_ in HELP_RULES:
        if key.lower() in name.lower():
            return short, long_
    return "", name


