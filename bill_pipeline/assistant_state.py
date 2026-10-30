"""问答运行状态：每个页面独立，工作线程只通过队列发布进度。"""
import json
import queue
import threading
from dataclasses import dataclass, field
from typing import NamedTuple
from uuid import uuid4


@dataclass(frozen=True)
class Budget:
    max_batches: int
    query_seconds: float
    summary_seconds: float = 30
    max_tools: int = 6


BUDGETS = {'quick': Budget(5, 60), 'deep': Budget(15, 180)}


def get_budget(mode: str) -> Budget:
    if mode not in BUDGETS:
        raise ValueError('未知问答模式')
    return BUDGETS[mode]


class Step(NamedTuple):
    tool: str
    args: dict
    result: dict


@dataclass
class Answer:
    text: str
    steps: list[Step]
    status: str = 'complete'
    reason: str = ''
    batches: int = 0
    elapsed: float = 0


@dataclass
class Turn:
    question: str
    default_month: str
    answer: Answer


@dataclass
class Progress:
    run_id: str
    kind: str
    batch: int = 0
    tool: str = ''
    detail: dict | None = None


@dataclass
class RunState:
    run_id: str = field(default_factory=lambda: uuid4().hex)
    cancel: threading.Event = field(default_factory=threading.Event)
    events: queue.Queue = field(default_factory=queue.Queue)

    def publish(self, kind: str, batch: int = 0, tool: str = '', detail: dict | None = None):
        self.events.put(Progress(self.run_id, kind, batch, tool, detail))


def clipped(text: str, limit: int) -> str:
    marker = '…[已截断]'
    return text if len(text) <= limit else text[:limit-len(marker)] + marker


def evidence_summary(steps: list[Step]) -> str:
    # 不传行级数据或搜索词，避免让历史无限增长或重复发出个人字段。
    keys = ('month', 'base_month', 'target_month', 'base', 'target', 'delta',
            'start_date', 'end_date', 'totals', 'expense', 'income', 'count', 'total', 'coverage')
    return clipped(json.dumps([{'tool': s.tool, 'result': {k: v for k, v in s.result.items() if k in keys}}
                               for s in steps if 'error' not in s.result], ensure_ascii=False), 4000)


def history_messages(turns) -> list[dict]:
    messages = []
    for turn in list(turns)[-6:]:
        messages.append({'role': 'user', 'content': clipped(turn.question, 2000)})
        messages.append({'role': 'assistant', 'content':
                         f'当时默认月份：{turn.default_month}\n{clipped(turn.answer.text, 6000)}\n'
                         f'历史依据（仅供理解上下文，数值须重新查询）：{evidence_summary(turn.answer.steps)}'})
    return messages
