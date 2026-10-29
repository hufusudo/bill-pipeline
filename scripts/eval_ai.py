"""在本机的账单库上评测问答：问一批程序能算出标准答案的问题，只打印对了几题。

会联网、会花钱，运行前先确认。在项目根目录运行：
    .venv/bin/python -m scripts.eval_ai
"""
import re
import sys
from decimal import Decimal

from bill_pipeline import ai, assistant
from bill_pipeline.db import UNCATEGORIZED, connect, daily_expense, month_by_category, month_totals, months
from web.pages import db_path


def month_text(month: str) -> str:
    return f"{month[:4]} 年 {int(month[5:7])} 月"


def cases(conn) -> list[tuple[str, int]]:
    """（问题, 标准答案，单位是分）：每个月问一共花了多少、每一类花了多少、哪天花得最多。"""
    result = []
    for month in months(conn):
        name = month_text(month)
        result.append((f"{name}一共花了多少钱？", month_totals(conn, month)[0]))
        result += [(f"{name}{category}花了多少钱？", cents)
                   for category, cents in month_by_category(conn, month) if category != UNCATEGORIZED]
        busiest = max((cents for _, cents in daily_expense(conn, month)), default=0)
        if busiest:
            result.append((f"{name}哪天花得最多？", busiest))
    return result


def is_correct(answer: str, cents: int) -> bool:
    """回答里有没有这个金额：写成 1286.50 或 1,286.50 都算，但前后不能紧挨着别的数字。"""
    amount = Decimal(int(cents)) / 100
    return any(re.search(rf"(?<![\d.,]){re.escape(form)}(?!\d)", answer)
               for form in (f"{amount:.2f}", f"{amount:,.2f}"))


def main() -> None:
    conn = connect(db_path())
    questions = cases(conn)
    if not questions:
        sys.exit("库里还没有账单")
    try:
        client, model = ai.make_client()
    except ai.AIError as e:
        sys.exit(str(e))
    latest = months(conn)[0]
    hits = errors = 0
    for i, (question, cents) in enumerate(questions, start=1):
        print(f"\r第 {i} / {len(questions)} 题", end="", file=sys.stderr, flush=True)
        try:
            hits += is_correct(assistant.ask(client, model, conn, question, latest).text, cents)
        except ai.AIError:
            errors += 1
    print(file=sys.stderr)
    # 只打印数字，不打印问题和回答：里面有真实的金额和分类
    print(f"问了 {len(questions)} 题，对了 {hits} 题，正确率 {hits / len(questions):.0%}；调用出错 {errors} 题")


if __name__ == "__main__":
    main()
