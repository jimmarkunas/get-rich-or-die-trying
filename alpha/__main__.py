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
from .discovery import scan_exclusive_events
from .dex import scan_factories
from .aave_discovery import scan_borrowers
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
    discover=sub.add_parser('discover',help='automatic read-only exclusive-event NO/NO research')
    discover.add_argument('--ledger',default='output/discovery.jsonl')
    discover.add_argument('--quantity',type=int,default=10)
    discover.add_argument('--pages',type=int,default=2)
    discover.add_argument('--max-events',type=int,default=12)
    discover.add_argument('--max-pairs-per-event',type=int,default=2)
    discover.add_argument('--series',default=None)
    discover.add_argument('--quantities',default=None,help='comma-separated sizes, max five')
    research=sub.add_parser('research',help='bounded public RPC research; no signing')
    research.add_argument('--config',default='config.research.example.json')
    research.add_argument('--engine',choices=['dex','aave'],required=True)
    research.add_argument('--chain',default=None,help='chain key from research config')
    research.add_argument('--ledger',default='output/research.jsonl')
    report=sub.add_parser('report',help='produce local static HTML dashboard')
    report.add_argument('--ledger',default='output/opportunities.jsonl')
    report.add_argument('--out',default='output/dashboard.html')
    args=parser.parse_args(argv)
    if args.command=='research':
        try:
            cfg=json.loads(Path(args.config).read_text(encoding='utf-8'))
            if args.engine=='dex':
                chains=cfg.get('dex',{})
                chosen=[args.chain] if args.chain else list(chains)
                if not chosen or len(chosen)>3: raise ValueError('select up to three known chains')
                records=[];errors={}
                for name in chosen:
                    if name not in chains:raise ValueError('unknown chain '+str(name))
                    c=chains[name]
                    part,err=scan_factories(c['rpc_url'],int(c['chain_id']),c['factories'],c['pairs'],
                        c['sizes_token0_base_units'],
                        gas_cost_token0_base_units=int(c['gas_cost_token0_base_units_assumption']),
                        flash_premium_bps=int(c['flash_premium_bps_assumption']),
                        fee_bps=int(c['pool_fee_bps_assumption']))
                    records+=part;errors.update({name+':'+k:v for k,v in err.items()})
            else:
                a=cfg['aave']
                records,errors=scan_borrowers(a['rpc_url'],a['pool'],int(a['chain_id']),
                    lookback=int(a.get('lookback',400)),max_users=int(a.get('max_users',25)))
            write_observations(args.ledger,records)
            print(json.dumps({'observations':len(records),'errors':errors,
                'read_only':True,'real_money_trades':0},indent=2))
            return 1 if errors else 0
        except Exception as exc:
            print(f'research: {type(exc).__name__}: {exc}',file=sys.stderr);return 1
    if args.command=='discover':
        try:
            records,errors=scan_exclusive_events(quantity=args.quantity,max_pages=args.pages,
                max_events=args.max_events,max_pairs_per_event=args.max_pairs_per_event,series=args.series,
                quantities=[int(v) for v in args.quantities.split(',')] if args.quantities else None)
            write_observations(args.ledger,records)
            print(json.dumps({'observations':len(records),'errors':errors,
                'review_candidates':sum(o.classification=='candidate_rule_review_required' for o in records)},indent=2))
            return 1 if errors else 0
        except Exception as exc:
            print(f'discover: {type(exc).__name__}: {exc}',file=sys.stderr)
            return 1
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
