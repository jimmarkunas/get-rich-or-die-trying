"""Durable GitHub-branch history and bounded, deduplicated candidate alerts.

Data is PUBLIC research metadata; never store secrets or private account data.
"""
import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ALERT_CLASS = 'candidate_rule_review_required'


def read_jsonl(path, max_bytes=30_000_000):
    p=Path(path)
    if not p.exists(): return []
    if p.stat().st_size > max_bytes: raise ValueError('history exceeds size cap')
    return [json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s.strip()]


def merge(previous, current, previous_state=None, now=None, history_limit=15000, cooldown_hours=24):
    now=now or datetime.now(timezone.utc)
    state = dict(previous_state or {})
    old_alerted = state.get('last_alert_utc',{})
    if not isinstance(old_alerted,dict): old_alerted={}
    # Bound both history and state to avoid unbounded GitHub repo storage.
    records=(previous+current)[-history_limit:]
    alerts=[]
    for row in current:
        if row.get('classification') != ALERT_CLASS: continue
        net = row.get('estimated_net_usd')
        if net is None: continue
        from decimal import Decimal, InvalidOperation
        try:
            if not Decimal(str(net)).is_finite() or Decimal(str(net))<=0: continue
        except (InvalidOperation,ValueError): continue
        details=row.get('details',{})
        if not details.get('exchange_mutually_exclusive') or details.get('kind')!='two_no_mutually_exclusive_lower_bound':continue
        tickers=details.get('tickers',[])
        if not isinstance(tickers,list) or len(tickers)!=2 or any(not isinstance(t,str) for t in tickers): continue
        key=row.get('key')
        if not isinstance(key,str): continue
        last=old_alerted.get(key)
        if last:
            try:
                prior=datetime.fromisoformat(last.replace('Z','+00:00'))
                if prior > now-timedelta(hours=cooldown_hours): continue
            except (ValueError,TypeError): pass
        old_alerted[key]=now.isoformat()
        alerts.append(row)
    limit_date=now-timedelta(days=45)
    retained={}
    for k,v in old_alerted.items():
        try:
            if datetime.fromisoformat(str(v).replace('Z','+00:00'))>=limit_date:retained[k]=v
        except (ValueError,TypeError):pass
    return records,{'last_alert_utc':retained},alerts


def alert_issue_payload(alerts, run_url):
    if not alerts: return None
    import re
    lines=['Automated Alpha read-only **review alert**. This is NOT an executable trade, a guaranteed payout, or verified profit.',
           '', 'Exchange event mutual-exclusivity metadata + standard binary contract screening passed. Full market contract rulebook review, fee-schedule verification, atomicity, order execution and settlement exceptions are **not verified**.',
           '', 'Source run: '+run_url, '']
    for a in alerts[:5]:
        d=a['details']
        event=re.sub(r'[^A-Z0-9._-]','',str(d.get('event_ticker','')))
        tickers=[re.sub(r'[^A-Z0-9._-]','',str(t)) for t in d['tickers']]
        lines.extend(['- Event: `'+event+'`; NO '+', '.join('`'+t+'`' for t in tickers),
                      '  - Indicative net after assumed fees and buffer: **$'+str(a['estimated_net_usd'])+'** for '+str(d['quantity'])+' contracts per leg.',
                      '  - Rule-metadata fingerprint: `'+str(d['metadata_sha256'])+'`'])
    lines.extend(['', '**No orders were placed.** This signal can disappear before any order fills.'])
    return {'title':f'[REVIEW REQUIRED] {len(alerts)} Kalshi indicative signal(s)', 'body':'\n'.join(lines)}


def cli(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--previous',required=True)
    p.add_argument('--current',required=True)
    p.add_argument('--previous-state',required=True)
    p.add_argument('--history-out',required=True)
    p.add_argument('--state-out',required=True)
    p.add_argument('--issue-out',required=True)
    p.add_argument('--run-url',required=True)
    args=p.parse_args(argv)
    old=read_jsonl(args.previous)
    new=read_jsonl(args.current)
    try: state=json.loads(Path(args.previous_state).read_text(encoding='utf-8'))
    except FileNotFoundError:state={}
    records,updated,alerts=merge(old,new,state)
    for f in (args.history_out,args.state_out,args.issue_out):Path(f).parent.mkdir(parents=True,exist_ok=True)
    Path(args.history_out).write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in records),encoding='utf-8')
    Path(args.state_out).write_text(json.dumps(updated,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    payload=alert_issue_payload(alerts,args.run_url)
    Path(args.issue_out).write_text(json.dumps(payload or {},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'old_count':len(old),'current_count':len(new),'history_count':len(records),'new_alerts':len(alerts)}))

if __name__=='__main__':cli()
