import pytest
from bill_pipeline.db import connect
from bill_pipeline.assistant_state import Answer,Step


def test_conversations_persist_restore_and_soft_delete(tmp_path):
    from bill_pipeline.conversations import create_conversation,begin_message,finish_message,load_turns,list_conversations,set_deleted
    path=tmp_path/'c.db';c=connect(path)
    cid=create_conversation(c)
    mid=begin_message(c,cid,'问题','2026-10','quick','run1','instance1')
    finish_message(c,mid,'run1',Answer('回答',[Step('search_transactions',{}, {'count':1,'totals':{'消费':'10.00'},'rows':[{'counterparty':'不应存入证据的名字'}]})]))
    c.close();c=connect(path)
    turns=load_turns(c,cid)
    assert turns[0]['answer']=='回答'
    assert '不应存入证据的名字' not in str(turns)
    set_deleted(c,cid,True)
    assert not list_conversations(c)
    assert not finish_message(c,mid,'run1',Answer('迟到',[]))
    set_deleted(c,cid,False)
    assert len(list_conversations(c))==1


def test_revision_and_foreign_live_instances():
    from bill_pipeline.conversations import create_conversation,begin_message,finish_message,load_turns,is_stale,register_instance,interrupt_owned_messages
    from bill_pipeline.migrations import bump_revision,data_revision
    c=connect(':memory:');cid=create_conversation(c)
    register_instance(c,'owner',now=100)
    mid=begin_message(c,cid,'问题','2026-10','quick','r','owner')
    assert interrupt_owned_messages(c,'other',now=110)==0
    with c:bump_revision(c)
    assert finish_message(c,mid,'r',Answer('回答',[]))
    assert is_stale(load_turns(c,cid)[0],data_revision(c))


def test_interrupted_runs_no_automatic_resume():
    from bill_pipeline.conversations import create_conversation,begin_message,register_instance,interrupt_owned_messages,load_turns
    c=connect(':memory:');cid=create_conversation(c);register_instance(c,'old',now=100)
    begin_message(c,cid,'问题','2026-10','quick','r','old')
    assert interrupt_owned_messages(c,'new',now=131)==1
    assert load_turns(c,cid)[0]['status']=='interrupted'


def test_completed_save_retry_is_idempotent():
    from bill_pipeline.conversations import create_conversation,begin_message,finish_message
    c=connect(':memory:');cid=create_conversation(c);mid=begin_message(c,cid,'q','2026-10','quick','r','owner')
    answer=Answer('saved',[])
    assert finish_message(c,mid,'r',answer)
    assert finish_message(c,mid,'r',answer)
    assert not finish_message(c,mid,'r',Answer('different late result',[]))
