"""在本机的账单库上评测 AI，只打印数字，不打印问题、回答和交易对方。

- ask（默认）：问一批程序能算出标准答案的问题，看回答里的金额对不对。
- suggest：把用户归过类的商户发给 AI，不带用户选的类别，看它猜对了几个。

会联网、会花钱，运行前先确认。在项目根目录运行：
    .venv/bin/python -m scripts.eval_ai [ask|suggest]
"""
import re
import sys
from decimal import Decimal

from bill_pipeline import ai, assistant
from bill_pipeline.db import (UNCATEGORIZED, Card, categories, connect, daily_expense, mapped_counterparties,
                              month_by_category, month_totals, months)
from web.pages import AI_BATCH, db_path


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


def run_ask(conn, client, model: str) -> str:
    questions = cases(conn)
    if not questions:
        return "库里还没有账单"
    latest = months(conn)[0]
    hits = errors = 0
    for i, (question, cents) in enumerate(questions, start=1):
        print(f"\r第 {i} / {len(questions)} 题", end="", file=sys.stderr, flush=True)
        try:
            hits += is_correct(assistant.ask(client, model, conn, question, latest).text, cents)
        except ai.AIError:
            errors += 1
    print(file=sys.stderr)
    return f"问答：问了 {len(questions)} 题，对了 {hits} 题，正确率 {hits / len(questions):.0%}；调用出错 {errors} 题"


def suggest_scores(client, model: str, labeled: list[tuple[Card, str]], names: list[str]) -> tuple[int, int, int]:
    """（AI 给了建议的个数, 猜对的个数, 出错的批数）。labeled 是 [(卡片, 用户选的类别)]，类别不发给 AI。"""
    guessed: dict[str, str] = {}
    failed = 0
    for start in range(0, len(labeled), AI_BATCH):
        batch = [card for card, _ in labeled[start:start + AI_BATCH]]
        try:
            guessed.update(ai.suggest_categories(client, model, batch, names))
        except ai.AIError:
            failed += 1
    hits = sum(guessed.get(card.counterparty) == category for card, category in labeled)
    return len(guessed), hits, failed


def run_suggest(conn, client, model: str) -> str:
    labeled = [(card, category) for card, category in mapped_counterparties(conn) if not ai.is_person(card.tx_type)]
    if not labeled:
        return "还没有归过类的商户"
    answered, hits, failed = suggest_scores(client, model, labeled, categories(conn))
    accuracy = f"{hits / answered:.0%}" if answered else "—"
    return (f"分类建议：商户 {len(labeled)} 个，AI 给了建议 {answered} 个，猜对 {hits} 个；"
            f"准确率 {accuracy}，覆盖率 {answered / len(labeled):.0%}；出错 {failed} 批")


def main() -> None:
    what = sys.argv[1] if len(sys.argv) > 1 else "ask"
    if what not in ("ask", "suggest"):
        sys.exit("用法：python -m scripts.eval_ai [ask|suggest]")
    conn = connect(db_path())
    try:
        client, model = ai.make_client()
    except ai.AIError as e:
        sys.exit(str(e))
    print((run_ask if what == "ask" else run_suggest)(conn, client, model))


if __name__ == "__main__":
    main()
