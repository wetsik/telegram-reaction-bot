import time

from settings import TZ_OFFSET


def get_local_hour() -> int:
    return (time.localtime().tm_hour + TZ_OFFSET) % 24


def get_activity_multiplier(hour: int | None = None) -> float:
    if hour is None:
        hour = get_local_hour()

    if 1 <= hour <= 6:
        return 0.05

    if 7 <= hour <= 11:
        return 0.45

    if 12 <= hour <= 18:
        return 0.75

    if 19 <= hour <= 23:
        return 1.0

    return 0.25
