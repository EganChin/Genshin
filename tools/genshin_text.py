"""Build and query the offline Chinese Genshin corpus. Standard library only."""
import argparse
import collections
from contextlib import closing
import datetime
import hashlib
import html
import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'public-data/genshin-text'
DB = ROOT / 'databases/genshin-text.sqlite'

def wanted_source(path):
    return (path == 'README.md' or path.startswith('ExcelBinOutput/')
            or path in ('TextMap/TextMapCHS.json', 'TextMap/TextMap_MediumCHS.json')
            or path.startswith(('Readable/CHS/', 'Subtitle/CHS/'))
            or any(path.startswith('BinOutput/' + name + '/') for name in
                   ('Quest', 'QuestBrief', 'Talk', 'CodexQuest', 'Coop', 'Story', 'Cutscene', 'NPC', 'Npc')))

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def references(obj, pointer=''):
    if isinstance(obj, dict):
        for key, value in obj.items():
            loc = pointer + '/' + key.replace('~', '~0').replace('/', '~1')
            if ('textmaphash' in key.lower() or key == 'textId') and isinstance(value, (int, str)):
                yield str(value), loc
            elif isinstance(value, (dict, list)):
                yield from references(value, loc)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from references(value, pointer + '/' + str(i))

def plain(text):
    return html.unescape(re.sub(r'<[^>]+>', '', text)).replace('\\n', '\n')

def build():
    manifest = read(RAW / 'manifest.json')
    # Verify the complete download before constructing a new index.
    for item in manifest['files']:
        path = RAW / item['path']
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Missing or damaged source: ' + item['path'])
    texts = {}
    for name in ('TextMap_MediumCHS.json', 'TextMapCHS.json'):
        texts.update(read(RAW / 'TextMap' / name))
    tmp = DB.with_suffix('.building.sqlite')
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.executescript('''
        CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE texts(hash TEXT PRIMARY KEY, text TEXT NOT NULL);
        CREATE VIRTUAL TABLE search USING fts5(hash UNINDEXED, text, tokenize='trigram');
        CREATE TABLE refs(hash TEXT, source TEXT, pointer TEXT);
        CREATE TABLE quests(id TEXT PRIMARY KEY, title TEXT, source TEXT);
        CREATE TABLE lines(hash TEXT, speaker TEXT, quest_id TEXT, source TEXT, pointer TEXT, next_ids TEXT);
        CREATE TABLE documents(source TEXT PRIMARY KEY, text TEXT);
    ''')
    con.executemany('INSERT INTO texts VALUES (?,?)', ((str(k), v) for k,v in texts.items()))
    con.executemany('INSERT INTO search VALUES (?,?)', ((str(k), plain(v)) for k,v in texts.items()))
    counts = collections.Counter()
    resolve = lambda x: texts.get(str(x.get('textId', '')), '') if isinstance(x, dict) else ''
    npc_names = {}
    npc_file = RAW / 'ExcelBinOutput/NpcExcelConfigData.json'
    if npc_file.exists():
        for npc in read(npc_file):
            npc_names[str(npc.get('id'))] = texts.get(str(npc.get('nameTextMapHash')), '')
    for item in manifest['files']:
        rel = item['path']
        path = RAW / rel
        if rel.startswith('TextMap/'):
            continue
        if path.suffix == '.json':
            data = read(path)
            batch = [(h, rel, ptr) for h,ptr in references(data) if h in texts]
            con.executemany('INSERT INTO refs VALUES (?,?,?)', batch)
            counts['references'] += len(batch)
            if rel.startswith('BinOutput/CodexQuest/'):
                qid = str(data.get('mainQuestId', path.stem))
                con.execute('INSERT INTO quests VALUES (?,?,?)', (qid, resolve(data.get('mainQuestTitle')), rel))
                for si, sub in enumerate(data.get('subQuests', [])):
                    for ii, entry in enumerate(sub.get('items', [])):
                        speaker = resolve(entry.get('speakerText'))
                        for di, dialog in enumerate(entry.get('dialogs', [])):
                            h = str(dialog.get('text', {}).get('textId', ''))
                            if h in texts:
                                ptr = f'/subQuests/{si}/items/{ii}/dialogs/{di}'
                                con.execute('INSERT INTO lines VALUES (?,?,?,?,?,?)', (h,speaker,qid,rel,ptr,json.dumps(dialog.get('nextItemId', entry.get('nextItemId')))))
                                counts['codex_lines'] += 1
            elif rel.startswith('BinOutput/Talk/'):
                for i, dialog in enumerate(data.get('dialogList', [])):
                    h = str(dialog.get('talkContentTextMapHash', ''))
                    role = dialog.get('talkRole', {})
                    speaker = npc_names.get(str(role.get('id')), '')
                    if not speaker:
                        speaker = role.get('type', '') + ':' + str(role.get('id', ''))
                    if h in texts:
                        con.execute('INSERT INTO lines VALUES (?,?,?,?,?,?)', (h,speaker,None,rel,f'/dialogList/{i}',json.dumps(dialog.get('nextDialogs', []))))
                        counts['talk_lines'] += 1
        elif rel.startswith(('Readable/CHS/', 'Subtitle/CHS/')):
            value = path.read_text(encoding='utf-8-sig')
            con.execute('INSERT INTO documents VALUES (?,?)', (rel, plain(value)))
            counts['documents'] += 1
    con.executescript('CREATE INDEX refs_hash ON refs(hash); CREATE INDEX lines_hash ON lines(hash); CREATE INDEX lines_quest ON lines(quest_id);')
    counts['texts'] = len(texts)
    counts['quests'] = con.execute('SELECT count(*) FROM quests').fetchone()[0]
    metadata = {'commit': manifest['commit'], 'source': manifest['source'], 'downloaded_at': manifest['downloaded_at'],
                'built_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'counts': dict(counts)}
    con.executemany('INSERT INTO metadata VALUES (?,?)', ((k,json.dumps(v,ensure_ascii=False)) for k,v in metadata.items()))
    con.commit()
    assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    con.close()
    tmp.replace(DB)
    print(json.dumps(metadata,ensure_ascii=False,indent=2))

def search(query, limit):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    if len(query) >= 3:
        rows = con.execute('SELECT search.hash,texts.text FROM search JOIN texts ON texts.hash=search.hash WHERE search MATCH ? LIMIT ?', ('"'+query.replace('"','""')+'"',limit)).fetchall()
    else:
        rows = con.execute('SELECT hash,text FROM texts WHERE instr(text,?)>0 LIMIT ?', (query,limit)).fetchall()
    for row in rows:
        result = dict(row)
        result['dialogue'] = [dict(x) for x in con.execute('SELECT l.speaker,l.quest_id,q.title,l.source,l.pointer,l.next_ids FROM lines l LEFT JOIN quests q ON l.quest_id=q.id WHERE l.hash=? LIMIT 8',(row['hash'],))]
        result['references'] = [dict(x) for x in con.execute('SELECT source,pointer FROM refs WHERE hash=? LIMIT 8',(row['hash'],))]
        print(json.dumps(result,ensure_ascii=False))
    for row in con.execute('SELECT source,text FROM documents WHERE instr(text,?)>0 LIMIT ?', (query,limit)):
        at = row['text'].find(query)
        print(json.dumps({'source':row['source'],'excerpt':row['text'][max(0,at-100):at+len(query)+300]},ensure_ascii=False))
    con.close()

def quest(qid):
    con = sqlite3.connect(DB)
    row = con.execute('SELECT source FROM quests WHERE id=?',(qid,)).fetchone()
    if row is None:
        raise SystemExit('No CodexQuest record for this ID; search the raw Quest/Talk data instead.')
    data = read(RAW / row[0])
    texts = dict(con.execute('SELECT hash,text FROM texts'))
    def resolve(obj):
        if isinstance(obj, dict):
            result = {k: resolve(v) for k,v in obj.items()}
            if 'textId' in obj:
                result['resolvedText'] = texts.get(str(obj['textId']))
            return result
        if isinstance(obj,list):
            return [resolve(v) for v in obj]
        return obj
    print(json.dumps({'source': row[0], 'data': resolve(data)},ensure_ascii=False,indent=2))

def books(query, limit):
    """Resolve the current source's explicit document → localization → CHS path chain."""
    manifest=read(RAW/'manifest.json')
    entries={x['path']:x for x in manifest['files']}
    con=sqlite3.connect(f'file:{DB.as_posix()}?mode=ro',uri=True)
    try:
        indexed=json.loads(con.execute("SELECT value FROM metadata WHERE key='commit'").fetchone()[0])
        if indexed != manifest['commit']:
            raise ValueError('Index and manifest commits differ; update the index first')
        def verified(rel):
            if rel not in entries: raise ValueError('Source not in manifest: '+rel)
            data=(RAW/rel).read_bytes()
            if hashlib.sha256(data).hexdigest()!=entries[rel]['sha256']: raise ValueError('Source differs from manifest: '+rel)
            return data.decode('utf-8-sig')
        docs=json.loads(verified('ExcelBinOutput/DocumentExcelConfigData.json'))
        locs=json.loads(verified('ExcelBinOutput/LocalizationExcelConfigData.json'))
        if not any('PLOJOMIPJGH' in row for row in docs):
            raise ValueError('Document localization field not recognized; inspect this upstream version')
        by_id={str(row.get('id')):(i,row) for i,row in enumerate(locs)}
        found=0
        for di,doc in enumerate(docs):
            h=str(doc.get('titleTextMapHash',''))
            row=con.execute('SELECT text FROM texts WHERE hash=?',(h,)).fetchone()
            title=row[0] if row else ''
            for li,locid in enumerate(doc.get('PLOJOMIPJGH',[])):
                entry=by_id.get(str(locid))
                if not entry: continue
                loc_index,loc=entry
                fields=[(key,val) for key,val in loc.items() if isinstance(val,str) and val.startswith('ART/UI/Readable/CHS/')]
                paths={val for _,val in fields}
                if len(paths)!=1: continue
                value=next(iter(paths)); rel='Readable/CHS/'+value.rsplit('/',1)[-1]+'.txt'
                if rel not in entries: continue
                body=verified(rel)
                if query not in title and query not in plain(body) and query != str(doc.get('id')): continue
                print(json.dumps({'document_id':doc.get('id'),'title':title,'title_hash':h,'document_source':'ExcelBinOutput/DocumentExcelConfigData.json','document_pointer':f'/{di}','localization_id':locid,'localization_source':'ExcelBinOutput/LocalizationExcelConfigData.json','localization_pointer':f'/{loc_index}','localization_fields':[key for key,_ in fields],'source':rel,'text':body},ensure_ascii=False))
                found+=1
                if found>=limit: return
    finally:
        con.close()

def source_file(name):
    manifest=read(RAW/'manifest.json')
    entries={item['path']:item for item in manifest['files']}
    if name not in entries or not name.endswith(('.json','.txt','.srt')):
        raise ValueError('Source is not a verified indexed file: '+name)
    data=(RAW/name).read_bytes()
    if hashlib.sha256(data).hexdigest()!=entries[name]['sha256']:
        raise ValueError('Source differs from indexed manifest: '+name)
    with closing(sqlite3.connect(f'file:{DB.as_posix()}?mode=ro',uri=True)) as con:
        row=con.execute("SELECT value FROM metadata WHERE key='commit'").fetchone()
        if not row or json.loads(row[0])!=manifest['commit']:
            raise ValueError('Index and source manifest commits differ')
    value=data.decode('utf-8-sig')
    print(json.dumps({'source':name,'data':json.loads(value) if name.endswith('.json') else value},ensure_ascii=False))

def subtitles(name):
    entries=read(RAW/'manifest.json')['files']
    paths=sorted(item['path'] for item in entries if item['path'].startswith('Subtitle/CHS/') and item['path'].endswith('.srt'))
    if not name:
        for path in paths: print(path)
        return
    matches=[path for path in paths if path==name or Path(path).name==name or Path(path).stem==name]
    if len(matches)!=1: raise ValueError('Unknown or ambiguous subtitle source: '+name)
    source_file(matches[0])

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', type=Path, default=RAW)
    parser.add_argument('--database', type=Path, default=DB)
    subs = parser.add_subparsers(dest='command', required=True)
    subs.add_parser('build')
    s = subs.add_parser('search')
    s.add_argument('query')
    s.add_argument('--limit',type=int,default=10)
    q = subs.add_parser('quest')
    q.add_argument('id')
    b = subs.add_parser('books')
    b.add_argument('query')
    b.add_argument('--limit',type=int,default=10)
    src = subs.add_parser('source')
    src.add_argument('path')
    sub = subs.add_parser('subtitles')
    sub.add_argument('name',nargs='?')
    args = parser.parse_args()
    RAW, DB = args.raw.resolve(), args.database.resolve()
    if args.command == 'build': build()
    elif args.command == 'search': search(args.query, args.limit)
    elif args.command == 'quest': quest(args.id)
    elif args.command == 'books': books(args.query,args.limit)
    elif args.command == 'source': source_file(args.path)
    elif args.command == 'subtitles': subtitles(args.name)
