"""Render static, escaped HTML for backtest and forward-only paper portfolios."""
import argparse
import html
import json
from pathlib import Path
from .crypto_forward import deserialize
from .crypto_strategy import snapshot
from .crypto_data import SYMBOLS


def cell(x):
    if isinstance(x,float): return html.escape(f'{x:,.3f}')
    return html.escape(str(x) if x is not None else '—')


def render(backtest_data, paper_state):
    historical=[];paper=[]
    for study in (backtest_data or {}).get('studies',[]):
        for strategy in ('momentum','grid'):
            tr=study['strategies'][strategy]['development'];ho=study['strategies'][strategy]['holdout']
            historical.append([study['symbol'],strategy,tr['net_pnl_usd'],ho['net_pnl_usd'],
                               ho['return_pct'],ho['max_drawdown_pct'],ho['trades'],
                               study['holdout_buy_hold_25pct_benchmark']['net_pnl_usd']])
    for symbol in SYMBOLS:
        e=(paper_state or {}).get('symbols',{}).get(symbol)
        if not e: continue
        for strategy in ('momentum','grid'):
            s=deserialize(e['portfolios'][strategy])
            # No price is stored as a durable portfolio field; omit mark-to-market
            # rather than pretending cash represents open-position equity.
            paper.append([symbol,strategy,cell(s['cash']),cell(s['units']),
                          s['trades'],s['wins'],s['losses'],e['last_closed_open_ms']])
    def table(headers, rows):
        return '<table><thead><tr>'+''.join('<th>'+html.escape(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join(
            '<tr>'+''.join('<td>'+cell(x)+'</td>' for x in row)+'</tr>' for row in rows) + '</tbody></table>'
    return '''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Automated Alpha v0.5 — spot paper research</title><style>body{font-family:system-ui,sans-serif;max-width:1200px;margin:40px auto;padding:0 18px;background:#111924;color:#ecf0f8}
h1{font-size:28px}h2{margin-top:30px}p{line-height:1.55;color:#b8c8df}table{width:100%;border-collapse:collapse;overflow-x:auto;display:block}th,td{text-align:left;border-bottom:1px solid #324052;padding:11px 9px;white-space:nowrap}th{color:#aad6ff} .note{padding:15px;border:1px solid #49566a;border-radius:10px}</style></head>
<body><h1>Automated Alpha — crypto paper research</h1><p class="note">READ ONLY. No live trades, no financial earnings, and no leverage. Historical performance is hypothetical; forward paper fills are simulated quotes, not guaranteed fills. Costs include assumed taker fees and slippage. The final 30d historical holdout is not a prediction.</p>
<h2>90-day historical backtest (USD, separate $1,000 portfolios)</h2>'''+table(
        ['Symbol','Strategy','Development P/L $','Holdout P/L $','Holdout return %','Holdout max DD %','Holdout fills','25% buy/hold P/L $'],historical
    )+'''<h2>Forward paper portfolio state (not cash profits)</h2>'''+table(
        ['Symbol','Strategy','Simulated cash $','Simulated coin units','Paper fills','Winning exits','Losing exits','Latest processed bar (ms UTC)'],paper
    )+'''<p>No real-money payout is established by any figure on this page. Ledger history is on a separate Git branch; never store API keys or account data there.</p></body></html>'''


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--backtest',default='output/crypto-backtest.json')
    p.add_argument('--state',default='output/new-paper-state.json')
    p.add_argument('--out',default='output/crypto-dashboard.html')
    a=p.parse_args(argv)
    path=Path(a.backtest)
    bt=json.loads(path.read_text(encoding='utf-8')) if path.exists() and path.stat().st_size else None
    state=json.loads(Path(a.state).read_text(encoding='utf-8'))
    dest=Path(a.out);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(render(bt,state),encoding='utf-8')
    print('Wrote static research dashboard: '+str(dest))

if __name__=='__main__':main()
