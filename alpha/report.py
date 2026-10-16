"""Build a standalone local HTML inspection report from JSONL observations."""
import html
import json
from collections import Counter
from pathlib import Path


def render_report(ledger_path, output_path):
    p=Path(ledger_path)
    records=[]
    if p.exists():
        for row in p.read_text(encoding='utf-8').splitlines():
            if row.strip(): records.append(json.loads(row))
    counts=Counter(r.get('engine','unknown') for r in records)
    rows='\n'.join('<tr>'+''.join('<td>'+html.escape(str(r.get(k,'')))+'</td>' for k in
                ('timestamp','engine','key','classification','estimated_net_usd'))+'</tr>' for r in records[-500:][::-1])
    notes='<p>All observations are read-only estimates or diagnostics, not executable orders or guaranteed profits.</p>'
    body=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Automated Alpha | Observation Ledger</title><style>body{{background:#111827;color:#e5e7eb;font:15px system-ui;margin:0;padding:32px}}main{{max-width:1200px;margin:auto}}h1{{color:#fff}}p{{color:#9ca3af}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{border-bottom:1px solid #374151;text-align:left;padding:12px 8px;vertical-align:top;overflow-wrap:anywhere}}th{{color:#93c5fd}}.stats{{background:#1f2937;padding:16px;border-radius:12px;margin:20px 0}}.pill{{color:#fbbf24}}@media(max-width:700px){{body{{padding:14px}}table{{font-size:11px}}th,td{{padding:6px}}}}</style></head><body><main>
<h1>⚡ Automated Alpha</h1><p class="pill">READ-ONLY · RESEARCH ONLY · NO ORDERS</p>
<div class="stats">{len(records)} observations · {html.escape(', '.join(f'{name}: {n}' for name,n in counts.items()) or 'No observations yet')}</div>
{notes}<table><thead><tr><th>Observed UTC</th><th>Engine</th><th>Target</th><th>Status</th><th>Indicative USD net</th></tr></thead><tbody>{rows}</tbody></table>
</main></body></html>'''
    out=Path(output_path);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(body,encoding='utf-8')
    return len(records)
