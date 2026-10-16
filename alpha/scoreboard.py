"""Honest aggregate research metrics, never simulated fills or earned P&L."""
import argparse
import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path


def summarize(rows, *, days=7, now=None):
    now=now or datetime.now(timezone.utc)
    if not 1<=days<=90:raise ValueError('unsupported reporting horizon')
    earliest=now-timedelta(days=days)
    chosen=[]
    for row in rows:
        try:
            at=datetime.fromisoformat(row['timestamp'].replace('Z','+00:00'))
            if at.tzinfo is None:continue
            if earliest<=at<=now:chosen.append(row)
        except (KeyError,TypeError,ValueError):continue
    categories={}
    for engine in sorted({r.get('engine','unknown') for r in chosen}):
        sub=[r for r in chosen if r.get('engine','unknown')==engine]
        counts=Counter(r.get('classification','unknown') for r in sub)
        nets=[]
        for r in sub:
            try:
                n=Decimal(str(r.get('estimated_net_usd')))
                if n.is_finite():nets.append(n)
            except (InvalidOperation,ValueError,TypeError):pass
        categories[engine]={'observations':len(sub),'classes':dict(counts),
            'best_indicative_net_usd':str(max(nets)) if nets else None,
            'worst_indicative_net_usd':str(min(nets)) if nets else None,
            'proven_realized_profit_usd':None,'validated_atomic_fills':0,
            'positive_candidates_not_executable':sum(v for k,v in counts.items() if 'candidate' in k or 'indicative_positive' in k)}
    return {'lookback_days':days,'observations':len(chosen),'engines':categories,
        'real_profit_or_trade_fills_not_proven':True,'no_actual_trading_performed':True}


def cli(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--ledgers',nargs='+',required=True)
    p.add_argument('--days',type=int,default=7)
    p.add_argument('--out',default='output/scoreboard.json')
    a=p.parse_args(argv)
    rows=[]
    for file in a.ledgers:
        f=Path(file)
        if f.exists():
            if f.stat().st_size>30_000_000: raise ValueError('ledger exceeds size cap')
            rows.extend(json.loads(s) for s in f.read_text(encoding='utf-8').splitlines() if s.strip())
    result=summarize(rows,days=a.days)
    Path(a.out).parent.mkdir(parents=True,exist_ok=True)
    Path(a.out).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':cli()
