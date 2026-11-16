import contextlib, hashlib, io, json, sqlite3, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import update_genshin_text as update

def git(path,*args):
    return subprocess.check_output(['git','-C',str(path),*args],stderr=subprocess.STDOUT)

class UpdateTests(unittest.TestCase):
    def test_failed_candidate_restores_checkout_manifest_and_index(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); upstream=root/'upstream'; upstream.mkdir()
            git(upstream,'init','-q','-b','main'); git(upstream,'config','user.name','Fixture'); git(upstream,'config','user.email','fixture@example.invalid')
            files={'README.md':'fixture', 'TextMap/TextMapCHS.json':'{}','TextMap/TextMap_MediumCHS.json':'{}', 'ExcelBinOutput/DocumentExcelConfigData.json':'[]','ExcelBinOutput/LocalizationExcelConfigData.json':'[]','BinOutput/Talk/example.json':'{}','Readable/CHS/example.txt':'hello'}
            for name,value in files.items():
                p=upstream/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(value,encoding='utf-8')
            git(upstream,'add','.'); git(upstream,'commit','-qm','first')
            raw=root/'public-data/genshin-text'; raw.parent.mkdir(parents=True)
            subprocess.run(['git','clone','-q',str(upstream),str(raw)],check=True)
            with (raw/'.git/info/exclude').open('a',encoding='utf-8') as f: f.write('\n/manifest.json\n')
            dbdir=root/'databases'; dbdir.mkdir(); db=dbdir/'genshin-text.sqlite'
            old_commit=git(raw,'rev-parse','HEAD').decode().strip()
            con=sqlite3.connect(db); con.execute('create table metadata(key text,value text)'); con.execute('insert into metadata values (?,?)',('commit',json.dumps(old_commit))); con.commit(); con.close()
            with patch.object(update,'ROOT',root), patch.object(update,'RAW',raw), patch.object(update,'DB',db), patch.object(update,'REMOTE',str(upstream)):
                with contextlib.redirect_stdout(io.StringIO()): update.write_manifest()
                old_manifest=(raw/'manifest.json').read_bytes(); old_db=hashlib.sha256(db.read_bytes()).digest()
                (upstream/'README.md').write_text('updated',encoding='utf-8'); git(upstream,'add','.'); git(upstream,'commit','-qm','update')
                with patch.object(sys,'argv',['update_genshin_text.py']), patch.object(update,'cli',side_effect=RuntimeError('injected candidate failure')):
                    with self.assertRaisesRegex(RuntimeError,'injected candidate failure'): update.main()
                self.assertEqual(old_commit,git(raw,'rev-parse','HEAD').decode().strip())
                self.assertEqual(old_manifest,(raw/'manifest.json').read_bytes())
                self.assertEqual(old_db,hashlib.sha256(db.read_bytes()).digest())
                self.assertFalse(git(raw,'status','--porcelain').strip())

if __name__=='__main__': unittest.main()
