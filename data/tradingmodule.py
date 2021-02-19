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
    past_ticks = []
    closed_trades = []
    open_trades = []
    max_drawdown = 0
    strategy = None

    open_order_value_per_timestamp = {}
    budget_per_timestamp = {}

    last_closed_trade = None
    temp_realized_drawdown = 0
    realized_drawdown = 0

    def __init__(self, config):
        print("[INFO] Initializing trading-module")
        self.config = config
        self.strategy = Strategy()
        self.budget = float(self.config['starting-capital'])
        self.fee = float(self.config['fee']) / 100
        self.max_open_trades = int(self.config['max-open-trades'])

    def tick(self, ohlcv: OHLCV):
        self.past_ticks.append(ohlcv)
        trade = self.find_open_trade(ohlcv.pair)
        if trade:
            trade.update_stats(ohlcv)
            self.open_trade_tick(ohlcv, trade)
        else:
            self.no_trade_tick(ohlcv)
        self.budget_per_timestamp[ohlcv.time] = self.budget

    def no_trade_tick(self, ohlcv: OHLCV):
        indicators = self.strategy.populate_indicators(self.past_ticks, ohlcv)
        buy = self.strategy.populate_buy_signal(indicators, ohlcv)
        if buy:
            self.open_trade(ohlcv)

    def open_trade_tick(self, ohlcv: OHLCV, trade: Trade):
        self.update_value_per_timestamp_tracking(trade, ohlcv)  # update total value tracking

        # if current profit is below 0, update drawdown / check SL
        stoploss = self.check_stoploss_open_trade(trade, ohlcv)
        roi = self.check_roi_open_trade(trade, ohlcv)
        if stoploss or roi:
            return

        indicators = self.strategy.populate_indicators(self.past_ticks, ohlcv)
        sell = self.strategy.populate_sell_signal(indicators, ohlcv, trade)

        if sell:
            self.close_trade(trade, reason="Sell signal", ohlcv=ohlcv)

    def close_trade(self, trade: Trade, reason: str, ohlcv: OHLCV):
        date = datetime.fromtimestamp(ohlcv.time / 1000)
        trade.close_trade(reason, date)
        earnings = (trade.close * trade.currency_amount)
        self.budget += earnings - (earnings * self.fee)
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
        spend_amount = (1. / available_spaces) * self.budget
        trade_amount = spend_amount - (spend_amount * self.fee)
        new_trade = Trade(ohlcv, trade_amount, date)
        self.budget -= spend_amount
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

    def find_open_trade(self, pair: str):
        for trade in self.open_trades:
            if trade.pair == pair:
                return trade
        return None

    def get_total_value_of_open_trades(self):
        return_value = 0
        for trade in self.open_trades:
            return_value += (trade.currency_amount * trade.current)
        return return_value

    def update_value_per_timestamp_tracking(self, trade: Trade, ohlcv: OHLCV):
        current_total_price = (trade.currency_amount * trade.current)
        self.open_order_value_per_timestamp[ohlcv.time] = current_total_price

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
