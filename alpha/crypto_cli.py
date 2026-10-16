"""Read-only CLI entrypoint for 90d backtests and forward paper portfolios."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from .crypto_data import SYMBOLS, fetch_candles
from .crypto_strategy import backtest
from .crypto_forward import paper_cycle


def save_json(path, content):
    target=Path(path)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(content, indent=2, sort_keys=True, allow_nan=False)+'\n',encoding='utf-8')


def main(argv=None):
    p=argparse.ArgumentParser(description='Automated Alpha public-data paper trading. NO ORDERS.')
    sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('backtest',help='at least 90 days hourly candles, untouched last 30d holdout')
    a.add_argument('--days',type=int,default=90)
    a.add_argument('--out',default='output/crypto-backtest.json')
    a.add_argument('--symbols',default=','.join(SYMBOLS))
    f=sub.add_parser('forward',help='forward-only paper positions using public bid/ask')
    f.add_argument('--state-in',default='output/previous-paper-state.json')
    f.add_argument('--state-out',default='output/new-paper-state.json')
    f.add_argument('--observations',default='output/crypto-paper-observations.jsonl')
    f.add_argument('--symbols',default=','.join(SYMBOLS))
    args=p.parse_args(argv)
    symbols=tuple(args.symbols.split(','))
    if not symbols or len(set(symbols))!=len(symbols) or not set(symbols).issubset(SYMBOLS):
        p.error('symbols must be unique allowed USD spot tickers: '+','.join(SYMBOLS))
    if args.command=='backtest':
        if not 90 <= args.days <= 120:p.error('days must be 90–120')
        studies=[]
        # A missing market or history explicitly fails the research job; no fabricated result.
        for symbol in symbols:
            bars=fetch_candles(symbol,args.days*24)
            studies.append(backtest(bars,symbol,args.days))
        output={'generated_at_utc':datetime.now(timezone.utc).isoformat(),
                'source':'Binance.US public GET /api/v3/klines','studies':studies,
                'symbol_count':len(studies),'historical_execution_only':True,
                'live_trades':0,'live_earnings_usd':0,'live_trading_authorized':False}
        save_json(args.out,output)
        print(json.dumps({'study_count':len(studies),'holdout_net_usd':{
            s['symbol']:{k:v['holdout']['net_pnl_usd'] for k,v in s['strategies'].items()} for s in studies},
            'output':args.out,'live_trades':0}))
        return 0
    previous_path=Path(args.state_in)
    prev=json.loads(previous_path.read_text(encoding='utf-8')) if previous_path.exists() and previous_path.stat().st_size else None
    next_state,observations=paper_cycle(prev,symbols)
    save_json(args.state_out,next_state)
    dest=Path(args.observations)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(''.join(json.dumps(x,sort_keys=True,allow_nan=False)+'\n' for x in observations),encoding='utf-8')
    print(json.dumps({'observations':len(observations),
        'paper_fills':sum(o.get('paper_trades',0) for o in observations),
        'symbols':symbols,'live_trades':0,'simulated_only':True,
        'state_out':args.state_out}))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
