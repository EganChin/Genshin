"""Check offline search and trace selected results back to raw source pointers."""
import json
import argparse
from pathlib import Path
import sqlite3
import subprocess
import sys
from genshin_text import DB, ROOT, RAW, read

def run(*args):
    return subprocess.check_output([sys.executable,'-X','utf8',str(ROOT/'tools/genshin_text.py'),'--raw',str(RAW),'--database',str(DB),*args],encoding='utf-8')

def main(report_path):
    con = sqlite3.connect(DB)
    assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert con.execute('SELECT count(*) FROM lines l LEFT JOIN texts t ON l.hash=t.hash WHERE t.hash IS NULL').fetchone()[0] == 0
    tests = []
    for query in ('世界树','派蒙'):
        results = [json.loads(x) for x in run('search',query,'--limit','3').splitlines()]
        assert results
        for result in results:
            assert query in result.get('text',result.get('excerpt',''))
            for ref in result.get('references',[]):
                obj = read(RAW/ref['source'])
                for part in ref['pointer'].split('/')[1:]:
                    part = part.replace('~1','/').replace('~0','~')
                    obj = obj[int(part)] if isinstance(obj,list) else obj[part]
                assert str(obj)==result['hash']
        tests.append({'query':query,'returned':len(results),'source_pointers_checked':sum(len(r.get('references',[])) for r in results)})
    quest = json.loads(run('quest','1000'))
    assert quest['data']['mainQuestTitle']['resolvedText']
    assert quest['data']['mainQuestId']==1000
    assert any(d.get('text',{}).get('resolvedText') for s in quest['data']['subQuests'] for i in s.get('items',[]) for d in i.get('dialogs',[]))
    counts = {table:con.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('texts','refs','quests','lines','documents')}
    report = {'integrity':'ok','offline_search_tests':tests,'quest_1000_title':quest['data']['mainQuestTitle']['resolvedText'],
              'counts':counts,'database_bytes':DB.stat().st_size,
              'commit':json.loads(con.execute("SELECT value FROM metadata WHERE key='commit'").fetchone()[0])}
    con.close()
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw',type=Path,default=RAW)
    parser.add_argument('--database',type=Path,default=DB)
    parser.add_argument('--report',type=Path,default=ROOT/'databases/genshin-text-validation.json')
    args = parser.parse_args()
    RAW, DB = args.raw.resolve(), args.database.resolve()
    main(args.report.resolve())
