"""本机会话仓库。读取历史不调用模型，依据只存有限聚合快照。"""
import json
import time
from datetime import datetime
from uuid import uuid4

from bill_pipeline.migrations import data_revision
from bill_pipeline.assistant_state import Answer,Step,Turn,clipped

INSTANCE_ID=uuid4().hex


def _now():return datetime.now().isoformat(timespec='microseconds')


def _rows(cursor):
    names=[c[0] for c in cursor.description]
    return [dict(zip(names,r)) for r in cursor.fetchall()]


def _existing(conn,cid,*,deleted=False):
    row=conn.execute('SELECT id FROM conversations WHERE id=?'+('' if deleted else ' AND deleted_at IS NULL'),(cid,)).fetchone()
    if not row:raise ValueError('会话不存在或已删除')


def create_conversation(conn,title=''):
    cid=uuid4().hex
    with conn:conn.execute('INSERT INTO conversations VALUES(?,?,?,?,NULL)',(cid,clipped(title.strip() or '新对话',80),_now(),_now()))
    return cid


def list_conversations(conn,*,deleted=False):
    return _rows(conn.execute('SELECT * FROM conversations WHERE deleted_at IS '+('NOT NULL' if deleted else 'NULL')+' ORDER BY updated_at DESC,id'))


def rename_conversation(conn,cid,title):
    if not title or not title.strip() or len(title.strip())>80:raise ValueError('标题须为1—80个字符')
    _existing(conn,cid)
    with conn:conn.execute('UPDATE conversations SET title=?,updated_at=? WHERE id=?',(title.strip(),_now(),cid))


def set_deleted(conn,cid,deleted):
    _existing(conn,cid,deleted=True)
    with conn:
        conn.execute('UPDATE conversations SET deleted_at=?,updated_at=? WHERE id=?',(_now() if deleted else None,_now(),cid))
        if deleted:conn.execute("UPDATE messages SET status='interrupted',reason='会话已删除',finished_at=? WHERE conversation_id=? AND status='running'",(_now(),cid))


def purge_conversation(conn,cid):
    _existing(conn,cid,deleted=True)
    if not conn.execute('SELECT 1 FROM conversations WHERE id=? AND deleted_at IS NOT NULL',(cid,)).fetchone():
        raise ValueError('请先将会话移入回收站')
    with conn:conn.execute('DELETE FROM conversations WHERE id=?',(cid,))


def register_instance(conn,instance_id,*,now=None):
    with conn:conn.execute('INSERT INTO runtime_instances VALUES(?,?) ON CONFLICT(id) DO UPDATE SET heartbeat_at=excluded.heartbeat_at',(instance_id,time.time() if now is None else now))


def heartbeat_instance(conn,instance_id):register_instance(conn,instance_id)


def interrupt_owned_messages(conn,owner_instance,*,now=None):
    until=(time.time() if now is None else now)-30
    with conn:
        return conn.execute("UPDATE messages SET status='interrupted',reason='上次运行已中断，不会自动重新调用模型',finished_at=? WHERE status='running' AND owner_instance!=? AND NOT EXISTS(SELECT 1 FROM runtime_instances i WHERE i.id=messages.owner_instance AND i.heartbeat_at>=?)",(_now(),owner_instance,until)).rowcount


def begin_message(conn,cid,question,month,mode,run_id,owner_instance):
    _existing(conn,cid)
    mid=uuid4().hex
    with conn:
        conn.execute('INSERT INTO messages(id,conversation_id,question,default_month,mode,status,start_revision,run_id,owner_instance,created_at) VALUES(?,?,?,?,?,\'running\',?,?,?,?)',
                     (mid,cid,question,month,mode,data_revision(conn),run_id,owner_instance,_now()))
        conn.execute("UPDATE conversations SET title=CASE WHEN title='新对话' THEN ? ELSE title END,updated_at=? WHERE id=?",(clipped(question,80),_now(),cid))
    return mid


def _safe_evidence(step):
    allowed=('month','base_month','target_month','base','target','expense','income','total','totals','count','delta','change_percent','start_date','end_date','group_by','coverage','note')
    data={k:v for k,v in step.result.items() if k in allowed}
    # 输入由本机工具产生，嵌套字段仍做键白名单，而不是保存全部SDK对象。
    def clean(value):
        if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if k not in ('rows','tx_id','merchant_order','note','counterparty','item','reasoning_content','api_key','key')}
        if isinstance(value,list):return [clean(v) for v in value[:24]]
        if isinstance(value,str):return clipped(value,500)
        return value
    data=clean(data)
    while len(json.dumps(data,ensure_ascii=False))>3500:
        data.pop(next(reversed(data)))
    data['history_snapshot']=True
    return data


def finish_message(conn,mid,run_id,answer:Answer):
    with conn:
        row=conn.execute("SELECT m.conversation_id FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE m.id=? AND m.run_id=? AND m.status='running' AND c.deleted_at IS NULL",(mid,run_id)).fetchone()
        if not row:
            old=conn.execute('SELECT m.status,m.answer FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE m.id=? AND m.run_id=? AND c.deleted_at IS NULL',(mid,run_id)).fetchone()
            return bool(old and old==(answer.status,answer.text))
        conn.execute('UPDATE messages SET status=?,answer=?,reason=?,batches=?,elapsed=?,end_revision=?,finished_at=? WHERE id=?',
                     (answer.status,answer.text,answer.reason,answer.batches,answer.elapsed,data_revision(conn),_now(),mid))
        # 单组证据总大小最多4000字符，避免多步骤累积成大明细档案。
        remaining=4000
        for i,step in enumerate(answer.steps):
            if 'error' in step.result:continue
            text=json.dumps(_safe_evidence(step),ensure_ascii=False)
            if len(text)>remaining:break
            conn.execute('INSERT INTO evidence VALUES(?,?,?,?)',(mid,i,step.tool,text));remaining-=len(text)
        conn.execute('UPDATE conversations SET updated_at=? WHERE id=?',(_now(),row[0]))
    return True


def load_turns(conn,cid):
    _existing(conn,cid)
    rows=_rows(conn.execute('SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at,id',(cid,)))
    for row in rows:
        row['evidence']=[{'tool':tool,'result':json.loads(text)} for tool,text in conn.execute('SELECT tool,summary_json FROM evidence WHERE message_id=? ORDER BY position',(row['id'],))]
    return rows


def is_stale(message,current_revision):
    return message['start_revision']!=current_revision or message['end_revision'] not in (None,message['start_revision'])


def as_turn(message):
    status=message['status']
    if status in ('running','interrupted'):
        text=message['answer'] or '上次提问未完成；如需继续，请重新提问。'
        status='partial'
    else:text=message['answer']
    return Turn(message['question'],message['default_month'],Answer(text,[Step(s['tool'],{},s['result']) for s in message['evidence']],status,message['reason'],message['batches'],message['elapsed']))
