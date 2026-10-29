import pytest

from bill_pipeline.model import BillError
from bill_pipeline.rules import apply_rules
from bill_pipeline.validate import ReconLine, check_summary, check_unique_ids, reconcile
from bill_pipeline.wechat import read_wechat
from tests.fakes import SAMPLE_ROWS, make_row, write_wechat_xlsx


def _bill(tmp_path, **kwargs):
    return read_wechat(write_wechat_xlsx(tmp_path / "b.xlsx", **kwargs))


def test_check_summary_passes(tmp_path):
    check_summary(_bill(tmp_path))


@pytest.mark.parametrize("override, message", [
    ({"expense": "支出：5笔 112.31元"}, "支出"),
    ({"income": "收入：4笔 1314.80元"}, "收入"),
    ({"count": "共10笔记录"}, "共"),
])
def test_check_summary_mismatch(tmp_path, override, message):
    with pytest.raises(BillError, match=message):
        check_summary(_bill(tmp_path, summary_override=override))


def test_check_summary_unknown_direction(tmp_path):
    rows = [dict(SAMPLE_ROWS[0], **{"收/支": "其他"})] + SAMPLE_ROWS[1:]
    with pytest.raises(BillError, match="收/支"):
        check_summary(_bill(tmp_path, rows=rows))


def test_check_unique_ids(tmp_path):
    with pytest.raises(BillError, match="交易单号重复"):
        check_unique_ids(_bill(tmp_path, rows=SAMPLE_ROWS + [dict(SAMPLE_ROWS[0])]))


def test_reconcile_sample(tmp_path):
    bill = _bill(tmp_path)
    assert reconcile(apply_rules(bill.rows), bill.summary) == [
        ReconLine("支出", "平台合计", 5, 11230),
        ReconLine("支出", "减：全额退款的原交易", 1, 2680),
        ReconLine("支出", "= 计入", 4, 8550),
        ReconLine("收入", "平台合计", 3, 131480),
        ReconLine("收入", "减：退款", 1, 2680),
        ReconLine("收入", "= 计入", 2, 128800),
        ReconLine("中性交易", "平台合计", 1, 5050),
        ReconLine("中性交易", "减：中性交易", 1, 5050),
        ReconLine("中性交易", "= 计入", 0, 0),
    ]


def test_reconcile_catches_rule_bug(tmp_path):
    bill = _bill(tmp_path)
    rows = apply_rules(bill.rows)
    rows.loc[rows.counterparty == "食堂一楼", "result"] = "收入"  # 支出行被错算成收入
    with pytest.raises(BillError, match="对账不平"):
        reconcile(rows, bill.summary)


def test_reconcile_lists_unknown_rows(tmp_path):
    rows = SAMPLE_ROWS + [make_row(10, 10, 10, "二手交易", "闲鱼买家", "收入", 30.0, "已收钱")]
    bill = _bill(tmp_path, rows=rows)
    lines = reconcile(apply_rules(bill.rows), bill.summary)
    assert ReconLine("收入", "减：未识别（二手交易/已收钱）", 1, 3000) in lines
    assert ReconLine("收入", "= 计入", 2, 128800) in lines
