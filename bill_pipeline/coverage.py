"""来源导出区间与缺口，不从无交易日推断缺数据。"""
import calendar
import json
from datetime import datetime,timedelta

from bill_pipeline.adjustments import list_review_issues,writing
from bill_pipeline.migrations import data_revision


def _time(value):
    return datetime.fromisoformat(value if len(value)>10 else value+' 00:00:00')


def set_expected_sources(conn,sources):
    if not sources or any(s not in ('微信','支付宝') for s in sources):raise ValueError('请选择账单来源')
    with writing(conn):
        conn.execute("INSERT INTO preferences VALUES('expected_sources',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",(json.dumps(sorted(set(sources))),))


def coverage(conn,start,end,expected_sources=None):
    a,b=_time(start),_time(end)
    if a>b:raise ValueError('范围起止顺序不正确')
    if expected_sources is None:
        saved=conn.execute("SELECT value FROM preferences WHERE name='expected_sources'").fetchone()
        expected_sources=json.loads(saved[0]) if saved else [r[0] for r in conn.execute('SELECT DISTINCT source FROM imports')]
    sources={}
    for source in expected_sources:
        intervals=[];unknown=False
        for x,y,exported,scope in conn.execute('SELECT period_start,period_end,exported_at,export_scope FROM imports WHERE source=?',(source,)):
            try:
                x,y=_time(x),_time(y)
                if y<a or x>b:continue
                if not exported or not scope or '全部' not in scope:
                    unknown=True
                    continue
                y=min(y,_time(exported))
                x,y=max(a,x),min(b,y)
                if x<=y:intervals.append((x,y))
            except (ValueError,TypeError):unknown=True
        merged=[]
        for x,y in sorted(intervals):
            if merged and x<=merged[-1][1]+timedelta(seconds=1):merged[-1]=(merged[-1][0],max(merged[-1][1],y))
            else:merged.append((x,y))
        gaps=[];cursor=a
        for x,y in merged:
            if cursor<x:gaps.append((cursor,x-timedelta(seconds=1)))
            cursor=max(cursor,y+timedelta(seconds=1))
        if cursor<=b:gaps.append((cursor,b))
        fmt=lambda pairs:[[x.isoformat(sep=' '),y.isoformat(sep=' ')] for x,y in pairs]
        sources[source]={'intervals':fmt(merged),'gaps':fmt(gaps),'unknown_metadata':unknown,
                         'complete':not gaps and not unknown}
    return {'start':start,'end':end,'sources':sources,'complete':bool(sources) and all(v['complete'] for v in sources.values())}


def trust_info(conn,month):
    year,mon=map(int,month.split('-'))
    start=f'{month}-01 00:00:00';end=f'{month}-{calendar.monthrange(year,mon)[1]:02d} 23:59:59'
    covered=coverage(conn,start,end)
    pending=len(list_review_issues(conn,month))
    return {'coverage':covered,'pending_reviews':pending,'revision':data_revision(conn),
            'provisional':pending>0 or not covered['complete']}
