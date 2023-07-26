import copy
import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

from src.strategies.strategy import Pilot
from src.utilities.utils.utils import PerpBitget, ValueAtRisk, utils

sys.path.append("./src")
load_dotenv("./env/.env")

params_coin = utils.loadJson("./src/coins/coins.json")


def positions_funct(bitget, df_list):
    positions_data = bitget.get_open_position()
    position_list = [
        {
            "pair": d["symbol"],
            "side": d["side"],
            "size": float(d["contracts"]) * float(d["contractSize"]),
            "market_price": d["info"]["marketPrice"],
            "usd_size": float(d["contracts"])
            * float(d["contractSize"])
            * float(d["info"]["marketPrice"]),
            "open_price": d["entryPrice"],
        }
        for d in positions_data
        if d["symbol"] in df_list
    ]

    positions = {}
    for pos in position_list:
        positions[pos["pair"]] = {
            "side": pos["side"],
            "size": pos["size"],
            "market_price": pos["market_price"],
            "usd_size": pos["usd_size"],
            "open_price": pos["open_price"],
        }
    return positions


def postions_delete_funct(bitget, df_list, positions, production):
    # Check for closing positions...
    positions_to_delete = []
    for pair in positions:
        row = df_list[pair].iloc[-2]
        last_price = float(df_list[pair].iloc[-1]["close"])
        position = positions[pair]

        if position["side"] == "long" and Pilot.close_long(row):
            close_long_market_price = last_price
            close_long_quantity = float(
                bitget.convert_amount_to_precision(pair, position["size"])
            )
            exchange_close_long_quantity = close_long_quantity * close_long_market_price
            print(
                f"Place Close Long Market Order: {close_long_quantity} {pair[:-5]} at the price of {close_long_market_price}$ ~{round(exchange_close_long_quantity, 2)}$"
            )
            if production:
                bitget.place_market_order(
                    pair, "sell", close_long_quantity, reduce=True
                )
                positions_to_delete.append(pair)

        elif position["side"] == "short" and Pilot.close_short(row):
            close_short_market_price = last_price
            close_short_quantity = float(
                bitget.convert_amount_to_precision(pair, position["size"])
            )
            exchange_close_short_quantity = (
                close_short_quantity * close_short_market_price
            )
            print(
                f"Place Close Short Market Order: {close_short_quantity} {pair[:-5]} at the price of {close_short_market_price}$ ~{round(exchange_close_short_quantity, 2)}$"
            )
            if production:
                bitget.place_market_order(
                    pair, "buy", close_short_quantity, reduce=True
                )
                positions_to_delete.append(pair)

    for pair in positions_to_delete:
        del positions[pair]
    return positions


def check_var_risk(bitget, var, usd_balance, df_list):
    positions_exposition = {}
    long_exposition = 0
    short_exposition = 0
    for pair in df_list:
        positions_exposition[pair] = {"long": 0, "short": 0}

    positions_data = bitget.get_open_position()
    for pos in positions_data:
        if pos["symbol"] in df_list and pos["side"] == "long":
            pct_exposition = (
                float(pos["contracts"])
                * float(pos["contractSize"])
                * float(pos["info"]["marketPrice"])
            ) / usd_balance
            positions_exposition[pos["symbol"]]["long"] += pct_exposition
            long_exposition += pct_exposition
        elif pos["symbol"] in df_list and pos["side"] == "short":
            pct_exposition = (
                float(pos["contracts"])
                * float(pos["contractSize"])
                * float(pos["info"]["marketPrice"])
            ) / usd_balance
            positions_exposition[pos["symbol"]]["short"] += pct_exposition
            short_exposition += pct_exposition

    current_var = var.get_var(positions=positions_exposition)
    print(
        f"Current VaR rsik 1 period: - {round(current_var, 2)}%, LONG exposition {round(long_exposition * 100, 2)}%, SHORT exposition {round(short_exposition * 100, 2)}%"
    )

    return positions_exposition, long_exposition, short_exposition, current_var


def bot(config):
    now = datetime.now()
    current_time = now.strftime("%d/%m/%Y %H:%M:%S")
    print("--- Start Execution Time :", current_time, "---")

    account_to_select = config["account_to_select"]
    production = config["production"]
    timeframe = config["timeframe"]
    type = config["type"]
    leverage = config["leverage"]
    max_var = config["max_var"]
    max_side_exposition = config["max_side_exposition"]

    print(
        f"--- Bollinger Trend on {account_to_select} -- {len(params_coin)} tokens {timeframe} Leverage x{leverage} ---"
    )

    bitget = PerpBitget(
        apiKey=os.environ["apiKey"],
        secret=os.environ["secret"],
        password=os.environ["password"],
    )

    df_list = utils.get_data(bitget, timeframe, params_coin)

    var = ValueAtRisk(df_list=df_list.copy())

    var.update_cov(current_date=df_list["BTC/USDT:USDT"].index[-1], occurance_data=999)
    print("Value At Risk loaded 100%")

    usd_balance = float(bitget.get_usdt_equity())
    print("USD balance :", round(usd_balance, 2), "$")

    positions = positions_funct(bitget, df_list)
    print(f"{len(positions)} active positions ({list(positions.keys())})")

    # Check for closing positions...
    positions = postions_delete_funct(bitget, df_list, positions, production)

    # Check current VaR risk
    (
        positions_exposition,
        long_exposition,
        short_exposition,
        current_var,
    ) = check_var_risk(bitget, var, usd_balance, df_list)

    for pair in df_list:
        if pair not in positions:
            try:
                row = df_list[pair].iloc[-2]
                last_price = float(df_list[pair].iloc[-1]["close"])
                pct_sizing = params_coin[pair]["wallet_exposure"]
                if Pilot.open_long(row) and "long" in type:
                    long_market_price = float(last_price)
                    long_quantity_in_usd = usd_balance * pct_sizing * leverage
                    temp_positions = copy.deepcopy(positions_exposition)
                    temp_positions[pair]["long"] += long_quantity_in_usd / usd_balance
                    temp_long_exposition = long_exposition + (
                        long_quantity_in_usd / usd_balance
                    )
                    temp_var = var.get_var(positions=temp_positions)
                    if temp_var > max_var or temp_long_exposition > max_side_exposition:
                        print(
                            f"Blocked open LONG on {pair}, because next VaR: - {round(current_var, 2)}%"
                        )
                    else:
                        long_quantity = float(
                            bitget.convert_amount_to_precision(
                                pair,
                                float(
                                    bitget.convert_amount_to_precision(
                                        pair, long_quantity_in_usd / long_market_price
                                    )
                                ),
                            )
                        )
                        exchange_long_quantity = long_quantity * long_market_price
                        print(
                            f"Place Open Long Market Order: {long_quantity} {pair[:-5]} at the price of {long_market_price}$ ~{round(exchange_long_quantity, 2)}$"
                        )
                        if production:
                            bitget.place_market_order(
                                pair, "buy", long_quantity, reduce=False
                            )
                            positions_exposition[pair]["long"] += (
                                long_quantity_in_usd / usd_balance
                            )
                            long_exposition += long_quantity_in_usd / usd_balance

                elif Pilot.open_short(row) and "short" in type:
                    short_market_price = float(last_price)
                    short_quantity_in_usd = usd_balance * pct_sizing * leverage
                    temp_positions = copy.deepcopy(positions_exposition)
                    temp_positions[pair]["short"] += short_quantity_in_usd / usd_balance
                    temp_short_exposition = short_exposition + (
                        short_quantity_in_usd / usd_balance
                    )
                    temp_var = var.get_var(positions=temp_positions)
                    if (
                        temp_var > max_var
                        or temp_short_exposition > max_side_exposition
                    ):
                        print(
                            f"Blocked open SHORT on {pair}, because next VaR: - {round(current_var, 2)}%"
                        )
                    else:
                        short_quantity = float(
                            bitget.convert_amount_to_precision(
                                pair,
                                float(
                                    bitget.convert_amount_to_precision(
                                        pair, short_quantity_in_usd / short_market_price
                                    )
                                ),
                            )
                        )
                        exchange_short_quantity = short_quantity * short_market_price
                        print(
                            f"Place Open Short Market Order: {short_quantity} {pair[:-5]} at the price of {short_market_price}$ ~{round(exchange_short_quantity, 2)}$"
                        )
                        if production:
                            bitget.place_market_order(
                                pair, "sell", short_quantity, reduce=False
                            )
                            positions_exposition[pair]["short"] += (
                                short_quantity_in_usd / usd_balance
                            )
                            short_exposition += short_quantity_in_usd / usd_balance

            except Exception as e:
                print(f"Error on {pair} ({e}), skip {pair}")

    now = datetime.now()
    current_time = now.strftime("%d/%m/%Y %H:%M:%S")
    print("--- End Execution Time :", current_time, "---")
