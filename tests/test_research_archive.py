import json
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from alpha.research_archive import append_bounded,cli

class ArchiveTests(unittest.TestCase):
    def test_bounded_append(self):
        self.assertEqual(append_bounded([1,2,3],[4,5],limit=3),[3,4,5])
    def test_no_incomplete_three_way_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); (p/'downloads'/'base').mkdir(parents=True)
            (p/'downloads'/'base'/'research.jsonl').write_text('{}\n')
            with self.assertRaisesRegex(ValueError,'incomplete research matrix'):
                cli(['--previous',str(p/'none'), '--current-dir',str(p/'downloads'),
                     '--history-out',str(p/'history'), '--scoreboard-out',str(p/'board')])
            self.assertFalse((p/'history').exists())
    def test_merge_writes_scoreboard_without_profit_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            for n in ('base','arbitrum','aave'):
                d=p/'snap'/n;d.mkdir(parents=True)
                d.joinpath('research.jsonl').write_text(json.dumps({
                    'timestamp':datetime.now(timezone.utc).isoformat(),'engine':n,
                    'classification':'no_positive_margin','estimated_net_usd':None})+'\n')
            cli(['--previous',str(p/'none'),'--current-dir',str(p/'snap'),
                 '--history-out',str(p/'history.jsonl'),'--scoreboard-out',str(p/'board.json')])
            board=json.loads((p/'board.json').read_text())
            self.assertEqual(board['observations'],3)
            self.assertTrue(board['real_profit_or_trade_fills_not_proven'])
            self.assertEqual(board['sampled_sources_this_run'],3)

if __name__=='__main__':unittest.main()
