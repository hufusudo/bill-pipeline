import json
import os

import pytest

from bill_pipeline import ai
from bill_pipeline.ai import AIError, load_env, suggest_categories
from bill_pipeline.db import ai_accuracy, connect, save_suggestions, set_category, suggestions, unmapped_counterparties
from bill_pipeline.pipeline import import_bill
from bill_pipeline.rules import DEFAULT_CATEGORIES
from tests.fakes import FakeLLM, write_wechat_xlsx


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    import_bill(c, write_wechat_xlsx(tmp_path / "b.xlsx"), "b.xlsx")
    return c


def _reply(suggestions_list):
    return {"content": json.dumps({"suggestions": suggestions_list}, ensure_ascii=False)}


def test_load_env(tmp_path, monkeypatch):
    for key in ("AGENT_MODEL", "OPENAI_BASE_URL"):
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)
    monkeypatch.setenv("EXISTING", "old")
    env = tmp_path / ".env"
    env.write_text('# 注释\nAGENT_MODEL="model-a"\nOPENAI_BASE_URL=https://example.test\n\nEXISTING=new\n',
                   encoding="utf-8")
    load_env(env)
    assert os.environ["AGENT_MODEL"] == "model-a"
    assert os.environ["OPENAI_BASE_URL"] == "https://example.test"
    assert os.environ["EXISTING"] == "old"


def test_make_client_without_key():
    with pytest.raises(AIError, match="还没配置"):
        ai.make_client()


def test_suggest_skips_people(conn):
    llm = FakeLLM([_reply([{"name": "星光球馆", "category": "运动"}])])
    assert suggest_categories(llm, "fake", unmapped_counterparties(conn), DEFAULT_CATEGORIES) == {"星光球馆": "运动"}
    sent = llm.sent_text()
    assert "星光球馆" in sent
    assert "张阿姨" not in sent


def test_suggest_drops_invalid(conn):
    llm = FakeLLM([_reply([{"name": "星光球馆", "category": "零食"}, {"name": "不存在的店", "category": "吃饭"},
                           {"name": "食堂一楼", "category": "吃饭"}])])
    assert suggest_categories(llm, "fake", unmapped_counterparties(conn), DEFAULT_CATEGORIES) == {"食堂一楼": "吃饭"}


def test_suggest_bad_json_raises(conn):
    with pytest.raises(AIError, match="不是 JSON"):
        suggest_categories(FakeLLM([{"content": "不是 JSON"}]), "fake", unmapped_counterparties(conn),
                           DEFAULT_CATEGORIES)


def test_suggest_api_error_raises(conn):
    with pytest.raises(AIError, match="调用模型出错"):
        suggest_categories(FakeLLM([]), "fake", unmapped_counterparties(conn), DEFAULT_CATEGORIES)


def test_accuracy(conn):
    save_suggestions(conn, {"星光球馆": "运动", "食堂一楼": "娱乐"}, "fake")
    assert suggestions(conn) == {"星光球馆": "运动", "食堂一楼": "娱乐"}
    set_category(conn, "星光球馆", "运动")
    set_category(conn, "食堂一楼", "吃饭")
    assert ai_accuracy(conn) == (1, 2)
    assert suggestions(conn) == {}
