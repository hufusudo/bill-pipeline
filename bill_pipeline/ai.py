"""连大模型：读配置、建客户端、给交易对方建议分类。设计见设计文档第 15 节。"""
import json
import os
from pathlib import Path

from openai import OpenAI

from bill_pipeline.db import Card

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
# 交易对方最近一笔是这些类型的，多半是真人：分类建议不发，问答里名字换成“个人收款”
PERSON_TYPES = {"扫二维码付款", "转账", "微信红包", "转账红包"}

SUGGEST_PROMPT = """你帮用户给记账里的交易对方归类。
只能从这些分类里选一个：{categories}。
用户会给你一组交易对方，每个带着一些线索，比如平台自带的分类、买了什么。
只返回 JSON，格式是 {{"suggestions": [{{"name": "交易对方的原名", "category": "分类"}}]}}。
拿不准的交易对方就不要放进去。"""


class AIError(Exception):
    """AI 没能给出结果的原因，直接显示给用户。"""


def load_env(path: Path) -> None:
    """读 .env 里的 KEY=VALUE；环境变量里已经有的不覆盖。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def make_client() -> tuple[OpenAI, str]:
    load_env(ENV_FILE)
    if not os.environ.get("OPENAI_API_KEY"):
        raise AIError("AI 还没配置：在项目的 .env 里填好 OPENAI_API_KEY、OPENAI_BASE_URL、AGENT_MODEL")
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=os.environ.get("OPENAI_BASE_URL"))
    return client, os.environ.get("AGENT_MODEL", "deepseek-chat")


def is_person(tx_type: str) -> bool:
    return tx_type in PERSON_TYPES


def _hints(card: Card) -> list[str]:
    hints = [f"支付宝分类：{card.tx_type}"] if card.source == "支付宝" else []
    if card.item not in ("", "/"):
        hints.append(f"买了：{card.item}")
    return hints


def suggest_categories(client, model: str, cards: list[Card], categories: list[str]) -> dict[str, str]:
    """返回 {交易对方: 建议的分类}。只发商户，不发个人；不在分类表里的建议一律丢掉。"""
    items = [{"name": card.counterparty, "hints": _hints(card)} for card in cards if not is_person(card.tx_type)]
    if not items:
        return {}
    try:
        response = client.chat.completions.create(
            model=model, temperature=0, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": SUGGEST_PROMPT.format(categories="、".join(categories))},
                      {"role": "user", "content": json.dumps(items, ensure_ascii=False)}])
        data = json.loads(response.choices[0].message.content)
    except json.JSONDecodeError:
        raise AIError("模型返回的不是 JSON") from None
    except Exception as e:  # 网络、key、额度等接口错误都转成原因；只报类型，不带出可能含 key 的原始消息
        raise AIError(f"调用模型出错（{type(e).__name__}）") from e
    names = {item["name"] for item in items}
    entries = data.get("suggestions", []) if isinstance(data, dict) else []
    return {s["name"]: s["category"] for s in entries
            if isinstance(s, dict) and s.get("name") in names and s.get("category") in categories}
