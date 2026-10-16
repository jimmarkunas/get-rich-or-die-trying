"""CLI entrypoint. All network traffic is GET and JSON-RPC read-only eth_call."""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from .common import write_observations
from .defi import scan_aave, scan_flash_amm
from .kalshi import scan_kalshi
from .report import render_report


def run(config,engine):
    records=[];errors=[]
    if engine in ('all','kalshi'):
        k=config.get('kalshi',{})
        if k.get('enabled'):
            try:
                items,market_errors=scan_kalshi(series=k.get('series'),tickers=k.get('tickers',[]),
                    groups=k.get('groups',[]),quantity=int(k.get('quantity',10)),
                    fee_rate=k.get('taker_fee_rate_assumption','0.07'),
                    buffer_usd=k.get('buffer_usd','0.25'),max_markets=int(k.get('max_markets',15)))
                records+=items
                errors.extend(f'kalshi:{ticker}:{err}' for ticker,err in market_errors.items())
            except Exception as ex: errors.append(f'kalshi: {type(ex).__name__}: {ex}')
    d=config.get('aave',{})
    if engine in ('all','aave') and d.get('enabled'):
        if d.get('users') and not d.get('rpc_url'):
            errors.append('aave: RPC required: configure aave.rpc_url (HTTPS)')
        elif d.get('users'):
            try: records+=scan_aave(d['rpc_url'],d['users'],d.get('pool','0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2'),d.get('chain_id',1))
            except Exception as ex:errors.append(f'aave: {type(ex).__name__}: {ex}')
    f=config.get('flash_amm',{})
    if engine in ('all','flash_amm') and f.get('enabled'):
        if f.get('pairs') and not f.get('rpc_url'):
            errors.append('flash_amm: RPC required: configure flash_amm.rpc_url (HTTPS)')
        elif f.get('pairs'):
            try: records+=scan_flash_amm(f['rpc_url'],f['pairs'],f.get('chain_id',1))
            except Exception as ex: errors.append(f'flash_amm: {type(ex).__name__}: {ex}')
    return records,errors


def main(argv=None):
    parser=argparse.ArgumentParser(description='Automated Alpha read-only opportunity observatory')
    sub=parser.add_subparsers(dest='command',required=True)
    scan=sub.add_parser('scan',help='one live read-only scan; no order placement')
    scan.add_argument('--config',default='config.json')
    scan.add_argument('--engine',choices=['all','kalshi','aave','flash_amm'],default='all')
    scan.add_argument('--ledger',default='output/opportunities.jsonl')
    scan.add_argument('--interval-seconds',type=int,default=0,help='repeat; minimum 60 seconds')
    scan.add_argument('--cycles',type=int,default=1,help='number of scans when interval enabled; 0=infinite')
    report=sub.add_parser('report',help='produce local static HTML dashboard')
    report.add_argument('--ledger',default='output/opportunities.jsonl')
    report.add_argument('--out',default='output/dashboard.html')
    args=parser.parse_args(argv)
    if args.command=='report':
        n=render_report(args.ledger,args.out)
        print(f'Generated {args.out} ({n} observations)')
        return 0
    if args.interval_seconds and args.interval_seconds<60:
        parser.error('interval must be >= 60 seconds to minimize API pressure')
    with open(args.config,encoding='utf-8') as fh: cfg=json.load(fh)
    cycles=args.cycles if args.interval_seconds else 1
    i=0;num=0;error_count=0
    try:
        while not cycles or i<cycles:
            records,errors=run(cfg,args.engine)
            num+=write_observations(args.ledger,records)
            error_count+=len(errors)
            print(json.dumps({'cycle':i+1,'observations':len(records),'errors':errors,
                              'classification_counts':{x:sum(r.classification==x for r in records) for x in sorted({r.classification for r in records})}},indent=2))
            i+=1
            if args.interval_seconds and (not cycles or i<cycles):time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        print('Stopped safely. No trading actions exist.')
    print(f'Wrote {num} observations to {args.ledger}')
    return 1 if error_count else 0

if __name__=='__main__':
    sys.exit(main())
