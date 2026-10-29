import pytest

pytest_plugins = ["nicegui.testing.user_plugin"]


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch, tmp_path):
    # 项目里的 .env 有真 key：测试一律看不到它，也看不到环境变量里的 key，所以绝不会联网
    monkeypatch.setattr("bill_pipeline.ai.ENV_FILE", tmp_path / "no.env")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.delenv("OPENAI_API_KEY")
