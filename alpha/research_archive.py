"""Merge bounded DeFi research snapshots into long-lived research observations.

Never infers execution success, actual P&L or completeness from absent data.
"""
import argparse
import json
from pathlib import Path
from .scoreboard import summarize

MAX_BYTES=15_000_000


def load_rows(path):
    file=Path(path)
    if not file.exists():return []
    if file.stat().st_size>MAX_BYTES:raise ValueError('history exceeds safety cap')
    return [json.loads(s) for s in file.read_text(encoding='utf-8').splitlines() if s.strip()]


def append_bounded(previous, current, limit=6000):
    if not 1<=limit<=30000:raise ValueError('bad history limit')
    return (previous+current)[-limit:]


def cli(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--previous',required=True)
    p.add_argument('--current-dir',required=True)
    p.add_argument('--history-out',required=True)
    p.add_argument('--scoreboard-out',required=True)
    p.add_argument('--expected-sources',type=int,default=3)
    args=p.parse_args(argv)
    old=load_rows(args.previous)
    files=sorted(Path(args.current_dir).rglob('research.jsonl'))
    if len(files)!=args.expected_sources:
        raise ValueError(f'incomplete research matrix: {len(files)}/{args.expected_sources} files')
    new=[]
    for file in files:new.extend(load_rows(file))
    if not new:raise ValueError('zero observations; refusing empty archive')
    historical=append_bounded(old,new)
    for filename in (args.history_out,args.scoreboard_out):Path(filename).parent.mkdir(parents=True,exist_ok=True)
    Path(args.history_out).write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in historical),encoding='utf-8')
    board=summarize(historical,days=7)
    board['sampled_sources_this_run']=len(files)
    board['incomplete_history_possible']=True
    Path(args.scoreboard_out).write_text(json.dumps(board,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps({'previous':len(old),'new':len(new),'history':len(historical),
                      'sources':len(files),'read_only':True}))

if __name__=='__main__':cli()
