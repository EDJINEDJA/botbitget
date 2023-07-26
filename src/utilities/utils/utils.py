import json
import math
import time
from multiprocessing.pool import ThreadPool as Pool

import ccxt
import numpy as np
import pandas as pd
import ta
from scipy.stats import norm
from tqdm import tqdm


class utils:
    def __init__(self) -> None:
        pass

    @staticmethod
    def loadJson(file: str):
        assert type(file) == str, "issue in loadjson, please file must be in str format"
        f = open(
            file,
        )
        data = json.load(f)
        f.close()
        return data

    @staticmethod
    def get_data(bitget, timeframe, params_coin):
        # Get data
        df_list = {}
        for pair in tqdm(params_coin):
            temp_data = bitget.get_more_last_historical_async(pair, timeframe, 1000)
            if len(temp_data) == 1000:
                df_list[pair] = temp_data
            else:
                print(f"Pair {pair} not loaded, length: {len(temp_data)}")
        print("Data OHLCV loaded 100%")

        for pair in tqdm(df_list):
            df = df_list[pair]
            params = params_coin[pair]
            bol_band = ta.volatility.BollingerBands(
                close=df["close"],
                window=params["bb_window"],
                window_dev=params["bb_std"],
            )
            df["lower_band"] = bol_band.bollinger_lband()
            df["higher_band"] = bol_band.bollinger_hband()
            df["ma_band"] = bol_band.bollinger_mavg()

            df["long_ma"] = ta.trend.sma_indicator(
                close=df["close"], window=params["long_ma_window"]
            )

            df["n1_close"] = df["close"].shift(1)
            df["n1_lower_band"] = df["lower_band"].shift(1)
            df["n1_higher_band"] = df["higher_band"].shift(1)

            df["iloc"] = range(len(df))

        print("Indicators loaded 100%")

        return df_list


class PerpBitget:
    def __init__(self, apiKey=None, secret=None, password=None):
        bitget_auth_object = {
            "apiKey": apiKey,
            "secret": secret,
            "password": password,
            "options": {
                "defaultType": "swap",
            },
        }
        if bitget_auth_object["secret"] is None:
            self._auth = False
            self._session = ccxt.bitget()
        else:
            self._auth = True
            self._session = ccxt.bitget(bitget_auth_object)
        self.market = self._session.load_markets()

    def authentication_required(fn):
        """Annotation for methods that require auth."""

        def wrapped(self, *args, **kwargs):
            if not self._auth:
                # print("You must be authenticated to use this method", fn)
                raise Exception("You must be authenticated to use this method")
            else:
                return fn(self, *args, **kwargs)

        return wrapped

    def get_last_historical(self, symbol, timeframe, limit):
        result = pd.DataFrame(
            data=self._session.fetch_ohlcv(symbol, timeframe, None, limit=limit)
        )
        result = result.rename(
            columns={
                0: "timestamp",
                1: "open",
                2: "high",
                3: "low",
                4: "close",
                5: "volume",
            }
        )
        result = result.set_index(result["timestamp"])
        result.index = pd.to_datetime(result.index, unit="ms")
        del result["timestamp"]
        return result

    def get_more_last_historical_async(self, symbol, timeframe, limit):
        max_threads = 4
        # pool_size = round(limit / 100)  # your "parallelness"
        round(limit / 100)

        # define worker function before a Pool is instantiated
        full_result = []

        def worker(i):

            try:
                return self._session.fetch_ohlcv(
                    symbol,
                    timeframe,
                    round(time.time() * 1000) - (i * 1000 * 60 * 60),
                    limit=100,
                )
            except Exception as err:
                raise Exception(
                    "Error on last historical on " + symbol + ": " + str(err)
                )

        pool = Pool(max_threads)

        full_result = pool.map(worker, range(limit, 0, -100))
        full_result = np.array(full_result).reshape(-1, 6)
        result = pd.DataFrame(data=full_result)
        result = result.rename(
            columns={
                0: "timestamp",
                1: "open",
                2: "high",
                3: "low",
                4: "close",
                5: "volume",
            }
        )
        result = result.set_index(result["timestamp"])
        result.index = pd.to_datetime(result.index, unit="ms")
        del result["timestamp"]
        return result.sort_index()

    def get_bid_ask_price(self, symbol):
        try:
            ticker = self._session.fetchTicker(symbol)
        except BaseException as err:
            raise Exception(err)
        return {"bid": ticker["bid"], "ask": ticker["ask"]}

    def get_min_order_amount(self, symbol):
        return self._session.markets_by_id[symbol]["info"]["minProvideSize"]

    def convert_amount_to_precision(self, symbol, amount):
        return self._session.amount_to_precision(symbol, amount)

    def convert_price_to_precision(self, symbol, price):
        return self._session.price_to_precision(symbol, price)

    @authentication_required
    def place_limit_order(self, symbol, side, amount, price, reduce=False):
        try:
            return self._session.createOrder(
                symbol,
                "limit",
                side,
                self.convert_amount_to_precision(symbol, amount),
                self.convert_price_to_precision(symbol, price),
                params={"reduceOnly": reduce},
            )
        except BaseException as err:
            raise Exception(err)

    @authentication_required
    def place_limit_stop_loss(
        self, symbol, side, amount, trigger_price, price, reduce=False
    ):

        try:
            return self._session.createOrder(
                symbol,
                "limit",
                side,
                self.convert_amount_to_precision(symbol, amount),
                self.convert_price_to_precision(symbol, price),
                params={
                    "stopPrice": self.convert_price_to_precision(
                        symbol, trigger_price
                    ),  # your stop price
                    "triggerType": "market_price",
                    "reduceOnly": reduce,
                },
            )
        except BaseException as err:
            raise Exception(err)

    @authentication_required
    def place_market_order(self, symbol, side, amount, reduce=False):
        try:
            return self._session.createOrder(
                symbol,
                "market",
                side,
                self.convert_amount_to_precision(symbol, amount),
                None,
                params={"reduceOnly": reduce},
            )
        except BaseException as err:
            raise Exception(err)

    @authentication_required
    def place_market_stop_loss(self, symbol, side, amount, trigger_price, reduce=False):

        try:
            return self._session.createOrder(
                symbol,
                "market",
                side,
                self.convert_amount_to_precision(symbol, amount),
                self.convert_price_to_precision(symbol, trigger_price),
                params={
                    "stopPrice": self.convert_price_to_precision(
                        symbol, trigger_price
                    ),  # your stop price
                    "triggerType": "market_price",
                    "reduceOnly": reduce,
                },
            )
        except BaseException as err:
            raise Exception(err)

    @authentication_required
    def get_balance_of_one_coin(self, coin):
        try:
            allBalance = self._session.fetchBalance()
        except BaseException as err:
            raise Exception("An error occured", err)
        try:
            return allBalance["total"][coin]
        except Exception:
            return 0

    @authentication_required
    def get_all_balance(self):
        try:
            allBalance = self._session.fetchBalance()
        except BaseException as err:
            raise Exception("An error occured", err)
        try:
            return allBalance
        except Exception:
            return 0

    @authentication_required
    def get_usdt_equity(self):
        try:
            usdt_equity = self._session.fetchBalance()["info"][0]["usdtEquity"]
        except BaseException as err:
            raise Exception("An error occured", err)
        try:
            return usdt_equity
        except Exception:
            return 0

    @authentication_required
    def get_open_order(self, symbol, conditionnal=False):
        try:
            return self._session.fetchOpenOrders(symbol, params={"stop": conditionnal})
        except BaseException as err:
            raise Exception("An error occured", err)

    @authentication_required
    def get_my_orders(self, symbol):
        try:
            return self._session.fetch_orders(symbol)
        except BaseException as err:
            raise Exception("An error occured", err)

    @authentication_required
    def get_open_position(self, symbol=None):
        try:
            positions = self._session.fetchPositions(symbol)
            truePositions = []
            for position in positions:
                if float(position["contracts"]) > 0:
                    truePositions.append(position)
            return truePositions
        except BaseException as err:
            raise TypeError("An error occured in get_open_position", err)

    @authentication_required
    def cancel_order_by_id(self, id, symbol, conditionnal=False):
        try:
            if conditionnal:
                return self._session.cancel_order(
                    id, symbol, params={"stop": True, "planType": "normal_plan"}
                )
            else:
                return self._session.cancel_order(id, symbol)
        except BaseException as err:
            raise Exception("An error occured in cancel_order_by_id", err)


class ValueAtRisk:
    def __init__(self, df_list):
        self.df_list = df_list
        self.cov = None
        self.avg_return = None
        self.conf_level = 0.05
        self.usd_balance = 1

    def update_cov(self, current_date, occurance_data=1000):
        returns = pd.DataFrame()
        returns["temp"] = [0] * (occurance_data)
        for pair in self.df_list:
            temp_df = self.df_list[pair].copy()
            try:
                # print(int(temp_df.loc[current_date]["iloc"]))
                # print(current_date)
                iloc_date = int(temp_df.loc[current_date]["iloc"])
                if math.isnan(iloc_date) or iloc_date - occurance_data < 0:
                    returns["long_" + pair] = -1
                    returns["short_" + pair] = -1
                else:
                    returns["long_" + pair] = (
                        temp_df.iloc[iloc_date - occurance_data : iloc_date]
                        .reset_index()["close"]
                        .pct_change()
                    )
                    returns["short_" + pair] = (
                        -temp_df.iloc[iloc_date - occurance_data : iloc_date]
                        .reset_index()["close"]
                        .pct_change()
                    )
            except Exception:
                returns["long_" + pair] = -1
                returns["short_" + pair] = -1
        # Generate Var-Cov matrix
        del returns["temp"]
        returns = returns.iloc[:-1]
        self.cov = returns.cov()
        self.cov = self.cov.replace(0.0, 1.0)
        # Calculate mean returns for each stock
        self.avg_return = returns.mean()
        return returns

    def get_var(self, positions):
        usd_in_position = 0
        for pair in list(positions.keys()):
            usd_in_position += positions[pair]["long"] + positions[pair]["short"]
        weights = []
        if usd_in_position == 0:
            return 0
        for pair in list(positions.keys()):
            weights.append(positions[pair]["long"] / usd_in_position)
            weights.append(positions[pair]["short"] / usd_in_position)

        weights = np.array(weights)

        port_mean = self.avg_return.dot(weights)

        # Calculate portfolio standard deviation
        port_stdev = np.sqrt(weights.T.dot(self.cov).dot(weights))

        # Calculate mean of investment
        mean_investment = (1 + port_mean) * usd_in_position

        # Calculate standard deviation of investmnet
        stdev_investment = usd_in_position * port_stdev

        # Using SciPy ppf method to generate values for the
        # inverse cumulative distribution function to a normal distribution
        # Plugging in the mean, standard deviation of our portfolio
        # as calculated above
        cutoff1 = norm.ppf(self.conf_level, mean_investment, stdev_investment)

        # Finally, we can calculate the VaR at our confidence interval
        var_1d1 = usd_in_position - cutoff1

        return var_1d1 / self.usd_balance * 100
