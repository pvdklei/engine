# ======================================================================
# Trade class is used by TradingModule for registering trades and tracking
# stats while ticks pass.
#
# © 2021 DemaTrading.AI - Tijs Verbeek
# ======================================================================

class Trade:
    pair = None
    open = None
    current = None
    close = None
    status = None
    currency_amount = None
    profit_dollar = None
    profit_percentage = None
    max_drawdown = None
    sell_reason = None
    opened_at = None
    closed_at = None

    def __init__(self, ohlcv, trade_amount, date):
        self.status = 'open'
        self.pair = ohlcv.pair
        self.open = ohlcv.close
        self.current = ohlcv.close
        self.currency_amount = (trade_amount / ohlcv.close)
        self.opened_at = date

    def close_trade(self, reason, date):
        self.status = 'closed'
        self.sell_reason = reason
        self.close = self.current
        self.closed_at = date

    def update_stats(self, ohlcv):
        self.current = ohlcv.close
        self.profit_percentage = ((ohlcv.close - self.open) / self.open) * 100
        self.profit_dollar = (self.currency_amount * self.current) - (self.currency_amount * self.open)
