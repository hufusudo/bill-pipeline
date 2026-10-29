"""连大模型：读配置、建客户端、给交易对方建议分类。设计见设计文档第 15 节。"""
import json
import os
from pathlib import Path

from openai import OpenAI

from bill_pipeline.db import Card
from bill_pipeline.rules import PERSON_TYPES

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"

SUGGEST_PROMPT = """你帮用户给记账里的交易对方归类。
只能从这些分类里选一个：{categories}。
用户会给你一组交易对方，每个带着一些线索，比如平台自带的分类、买了什么。
只有名字或线索能明确看出是哪一类时才给建议，比如名字里有“面馆”“球馆”“地铁”，或者平台分类是“餐饮美食”。
看不出卖什么的，比如只有公司名、店名或品牌名，就不要放进去。宁可少给，不要猜。
只返回 JSON，格式是 {{"suggestions": [{{"name": "交易对方的原名", "category": "分类"}}]}}；
一个都看不出来就返回 {{"suggestions": []}}。"""


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
        data = json.loads(response.choices[0].message.content or "")
    except json.JSONDecodeError:
        raise AIError("模型返回的不是 JSON") from None
    except Exception as e:  # 网络、key、额度等接口错误都转成原因；只报类型，不带出可能含 key 的原始消息
        raise AIError(f"调用模型出错（{type(e).__name__}）") from e
    names = {item["name"] for item in items}
    entries = data.get("suggestions", []) if isinstance(data, dict) else []
    return {s["name"]: s["category"] for s in entries
            if isinstance(s, dict) and s.get("name") in names and s.get("category") in categories}
