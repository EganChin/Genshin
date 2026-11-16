import contextlib, hashlib, io, json, sqlite3, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import genshin_text as index

class QueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); root=Path(self.tmp.name); raw=root/'raw'; raw.mkdir(); db=root/'db.sqlite'
        files={'ExcelBinOutput/DocumentExcelConfigData.json':[{'id':7,'titleTextMapHash':11,'PLOJOMIPJGH':[9]}], 'ExcelBinOutput/LocalizationExcelConfigData.json':[{'id':9,'chs':'ART/UI/Readable/CHS/Book7'}]}
        records=[]
        for name,obj in files.items():
            path=raw/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(obj),encoding='utf-8'); data=path.read_bytes(); records.append({'path':name,'sha256':hashlib.sha256(data).hexdigest()})
        path=raw/'Readable/CHS/Book7.txt'; path.parent.mkdir(parents=True,exist_ok=True); path.write_text('正文样例',encoding='utf-8'); records.append({'path':'Readable/CHS/Book7.txt','sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        (raw/'manifest.json').write_text(json.dumps({'commit':'fixture','files':records}),encoding='utf-8')
        con=sqlite3.connect(db); con.executescript('create table metadata(key text,value text);create table texts(hash text,text text);'); con.execute('insert into metadata values (?,?)',('commit',json.dumps('fixture'))); con.execute('insert into texts values (?,?)',('11','书名样例'));con.commit();con.close()
        self.old=(index.RAW,index.DB);index.RAW=raw;index.DB=db;self.raw=raw
    def tearDown(self):
        index.RAW,index.DB=self.old;self.tmp.cleanup()
    def test_book_resolves_explicit_title_to_body(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out): index.books('书名样例',1)
        result=json.loads(out.getvalue()); self.assertEqual(result['document_id'],7);self.assertEqual(result['localization_id'],9);self.assertEqual(result['source'],'Readable/CHS/Book7.txt');self.assertEqual(result['text'],'正文样例')
    def test_source_rejects_modified_file(self):
        (self.raw/'Readable/CHS/Book7.txt').write_text('改动',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'differs from indexed manifest'):index.source_file('Readable/CHS/Book7.txt')

if __name__=='__main__':unittest.main()
