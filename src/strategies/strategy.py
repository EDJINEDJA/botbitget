class Pilot:
    def __init__(self) -> None:
        pass

    @staticmethod
    def open_long(row):
        if (
            row["n1_close"] < row["n1_higher_band"]
            and (row["close"] > row["higher_band"])
            and (row["close"] > row["long_ma"])
        ):
            return True
        else:
            return False

    @staticmethod
    def close_long(row):
        if row["close"] < row["ma_band"]:
            return True
        else:
            return False

    @staticmethod
    def open_short(row):
        if (
            row["n1_close"] > row["n1_lower_band"]
            and (row["close"] < row["lower_band"])
            and (row["close"] < row["long_ma"])
        ):
            return True
        else:
            return False

    @staticmethod
    def close_short(row):
        if row["close"] > row["ma_band"]:
            return True
        else:
            return False
