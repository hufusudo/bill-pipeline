"""金额换算成分、时间换算成文字、分显示成元。"""
import math
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from bill_pipeline.model import BillError

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
EXCEL_EPOCH = datetime(1899, 12, 30)


def to_cents(value) -> int:
    """把金额换算成整数分。不是非负数、或者小数超过两位，就拒收。"""
    # bool 是 int 的子类，True 会被当成 1，必须先排除
    if isinstance(value, bool):
        raise BillError(f"金额不是有效数字：{value!r}")
    if isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, float):
        # 先转成字符串：Decimal(0.1) 会带出二进制误差，Decimal("0.1") 不会
        number = Decimal(str(value))
    elif isinstance(value, str):
        try:
            number = Decimal(value.strip().replace(",", ""))
        except InvalidOperation:
            raise BillError(f"金额不是有效数字：{value!r}") from None
    else:
        raise BillError(f"金额不是有效数字：{value!r}")
    cents = number * 100
    if not cents.is_finite() or cents < 0 or cents != cents.to_integral_value():
        raise BillError(f"金额不是有效数字：{value!r}")
    return int(cents)


def to_time_text(value) -> str:
    """把交易时间统一成 YYYY-MM-DD HH:MM:SS。Excel 里存成日期数字的也能换算。"""
    if isinstance(value, datetime):
        try:
            return value.strftime(TIME_FORMAT)
        except ValueError:  # pandas 的空时间 NaT 也算 datetime，但不能格式化
            pass
    elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return (EXCEL_EPOCH + timedelta(seconds=round(value * 86400))).strftime(TIME_FORMAT)
    elif isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), TIME_FORMAT).strftime(TIME_FORMAT)
        except ValueError:
            pass
    raise BillError(f"交易时间认不出来：{value!r}")


def yuan(cents: int) -> str:
    """整数分显示成元，保留两位小数。"""
    return f"{Decimal(int(cents)) / 100:.2f}"
