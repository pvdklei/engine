from backtesting.strategy import Strategy
from models.ohlcv import OHLCV
from models.trade import Trade
from datetime import datetime

# ======================================================================
# TradingModule is responsible for tracking trades, calling strategy methods
# and virtually opening / closing trades based on strategies' signal.
#
# DataFrame parser is
#
# © 2021 DemaTrading.AI - Tijs Verbeek
# ======================================================================


class TradingModule:
    starting_budget = 0
    budget = 0
    max_open_trades = None

    config = None
    closed_trades = []
    open_trades = []
    max_drawdown = 0
    strategy = None

    value_per_timestamp = {}
    budget_per_timestamp = {}

    last_closed_trade = None
    temp_realized_drawdown = 0
    realized_drawdown = 0

    def __init__(self, config):
        print("[INFO] Initializing trading-module")
        self.config = config
        self.strategy = Strategy()
        self.budget = float(self.config['starting-capital'])
        self.max_open_trades = int(self.config['max-open-trades'])

    def tick(self, ohlcv: OHLCV, data: [OHLCV]):
        if self.has_open_trade(ohlcv.pair):
            self.open_trade_tick(ohlcv, data)
        else:
            self.no_trade_tick(ohlcv, data)
        self.update_budget_per_timestamp_tracking(ohlcv)

    def no_trade_tick(self, ohlcv: OHLCV, data: [OHLCV]):
        past_ticks = []
        past_ticks += data
        indicators = self.strategy.populate_indicators(past_ticks, ohlcv)
        buy = self.strategy.populate_buy_signal(indicators, ohlcv)
        if buy:
            self.open_trade(ohlcv)

    def open_trade_tick(self, ohlcv: OHLCV, data: [OHLCV]):
        # updating profit and other stats of open trade
        trade = self.update_opentrade_stats(ohlcv)
        # update total value tracking
        self.update_value_per_timestamp_tracking(trade, ohlcv)

        # if current profit is below 0, update drawdown / check SL
        stoploss = self.check_stoploss_open_trade(trade, ohlcv)
        roi = self.check_roi_open_trade(trade, ohlcv)
        if stoploss or roi:
            return

        past_ticks = []
        past_ticks += data
        indicators = self.strategy.populate_indicators(past_ticks, ohlcv)
        sell = self.strategy.populate_sell_signal(indicators, ohlcv, trade)

        if sell:
            self.close_trade(trade, reason="Sell signal", ohlcv=ohlcv)

    def close_trade(self, trade: Trade, reason: str, ohlcv: OHLCV):
        trade.status = 'closed'
        trade.sell_reason = reason
        trade.close = trade.current
        date = datetime.fromtimestamp(ohlcv.time / 1000)
        trade.closed_at = date
        self.budget += (trade.close * trade.amount)
        self.open_trades.remove(trade)
        self.closed_trades.append(trade)
        self.update_drawdowns_closed_trade(trade)

    def open_trade(self, ohlcv: OHLCV):
        if self.budget <= 0:
            print("[INFO] Budget is running low, cannot buy")
            return

        date = datetime.fromtimestamp(ohlcv.time / 1000)
        open_trades = len(self.open_trades)
        available_spaces = self.max_open_trades - open_trades
        amount = ((100 / available_spaces) / 100) * self.budget
        self.budget-=amount
        new_trade = Trade()
        new_trade.pair = ohlcv.pair
        new_trade.open = ohlcv.close
        new_trade.current = ohlcv.close
        new_trade.status = "open"
        new_trade.amount = (amount / ohlcv.close)
        new_trade.opened_at = date
        self.open_trades.append(new_trade)

    def check_roi_open_trade(self, trade: Trade, ohlcv: OHLCV) -> bool:
        if trade.profit_percentage > float(self.config['roi']):
            self.close_trade(trade, reason="ROI", ohlcv=ohlcv)
            return True
        return False

    def check_stoploss_open_trade(self, trade: Trade, ohlcv: OHLCV) -> bool:
        if trade.profit_percentage < 0:
            if trade.max_drawdown is None or trade.max_drawdown > trade.profit_percentage:
                trade.max_drawdown = trade.profit_percentage
            if trade.profit_percentage < float(self.config['stoploss']):
                self.close_trade(trade, reason="Stoploss", ohlcv=ohlcv)
                return True
        return False

    def has_open_trade(self, pair: str):
        if len(self.open_trades) == 0:
            return False
        for trade in self.open_trades:
            if trade.pair == pair:
                return True

    def find_open_trade_for_pair(self, pair: str):
        if not self.has_open_trade(pair):
            return
        for trade in self.open_trades:
            if trade.pair == pair:
                return trade

    def get_total_value_of_open_trades(self):
        if len(self.open_trades) == 0:
            return 0
        return_value = 0
        for trade in self.open_trades:
            return_value += (trade.amount * trade.current)
        return return_value

    def update_opentrade_stats(self, ohlcv: OHLCV) -> Trade:
        trade = self.find_open_trade_for_pair(ohlcv.pair)
        trade.current = ohlcv.close
        trade.profit_percentage = ((ohlcv.close - trade.open) / trade.open) * 100
        trade.profit_dollar = (trade.amount * trade.current) - (trade.amount * trade.open)
        return trade

    def update_value_per_timestamp_tracking(self, trade: Trade, ohlcv: OHLCV):
        current_total_price = (trade.amount * trade.current)
        try:
            var = self.value_per_timestamp[ohlcv.time]
        except KeyError:
            self.value_per_timestamp[ohlcv.time] = 0
        self.value_per_timestamp[ohlcv.time] += current_total_price

    def update_budget_per_timestamp_tracking(self, ohlcv: OHLCV):
        # track whether KeyError arose
        first = False
        try:
            var = self.budget_per_timestamp[ohlcv.time]
        except KeyError:
            self.budget_per_timestamp[ohlcv.time] = self.budget
            first = True

        # if KeyError didnt arise, update budget (since orders may have been placed)
        if not first:
            self.budget_per_timestamp[ohlcv.time] = self.budget

    def update_drawdowns_closed_trade(self, trade: Trade):
        if trade.profit_percentage < self.max_drawdown:
            self.max_drawdown = trade.profit_percentage

        if trade.profit_percentage < 0:
            print('!!!! closed trade with loss')
            if self.last_closed_trade is None:
                self.temp_realized_drawdown = trade.profit_percentage
                self.last_closed_trade = trade
                return
            if self.last_closed_trade.profit_percentage < 0:
                self.temp_realized_drawdown += trade.profit_percentage
            self.temp_realized_drawdown = trade.profit_percentage
        else:
            if self.temp_realized_drawdown < self.realized_drawdown:
                self.realized_drawdown = self.temp_realized_drawdown
            self.temp_realized_drawdown = 0

        self.last_closed_trade = trade
