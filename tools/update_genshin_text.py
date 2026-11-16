"""Pull the dedicated Git mirror, verify sources, build and validate its offline index."""
import argparse
from contextlib import closing
import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from genshin_text import ROOT, RAW, DB, wanted_source

REMOTE = 'https://github.com/DimbreathBot/AnimeGameData.git'

def git(*args):
    process = subprocess.Popen(['git','-C',str(RAW),*args],stdout=subprocess.PIPE)
    try:
        out, _ = process.communicate(timeout=180)
    except subprocess.TimeoutExpired:
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        process.communicate()
        raise
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode,process.args,output=out)
    return out

def write_manifest():
    entries = git('ls-files','--stage','-z').split(b'\0')
    active = {x[2:].decode('utf-8') for x in git('ls-files','-t','-z').split(b'\0') if x and x[:1] != b'S'}
    records = []
    for entry in entries:
        if not entry:
            continue
        meta, path_bytes = entry.split(b'\t',1)
        path = path_bytes.decode('utf-8')
        if path not in active or not wanted_source(path):
            continue
        mode, expected, stage = meta.split()
        if mode != b'100644' or stage != b'0':
            raise ValueError('Unexpected Git entry: '+path)
        data = (RAW/path).read_bytes()
        actual = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest().encode()
        if actual != expected:
            raise ValueError('Source differs from Git: '+path)
        if path.endswith('.json'):
            json.loads(data)
        records.append({'path':path,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    paths = {x['path'] for x in records}
    required = {'TextMap/TextMapCHS.json','TextMap/TextMap_MediumCHS.json','ExcelBinOutput/DocumentExcelConfigData.json','ExcelBinOutput/LocalizationExcelConfigData.json'}
    if not required <= paths or not any(x.startswith('BinOutput/Talk/') for x in paths) or not any(x.startswith('Readable/CHS/') for x in paths):
        raise ValueError('Sparse checkout is missing required corpus categories')
    manifest = {'source':REMOTE.removesuffix('.git'),'commit':git('rev-parse','HEAD').decode().strip(),
                'downloaded_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'verified_against':'Git index blob SHA-1; sparse checkout; core.autocrlf=false', 'files':records}
    temp = RAW/'manifest.json.pending'
    temp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(RAW/'manifest.json')
    print(f'Verified {len(records)} Git-managed source files',flush=True)
    return manifest

def cli(script,*args):
    subprocess.run([sys.executable,'-X','utf8',str(ROOT/'tools'/script),*map(str,args)],check=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline',action='store_true',help='Verify/reindex the current checkout without fetching')
    parser.add_argument('--rebuild',action='store_true',help='Rebuild even when the indexed commit is current')
    args = parser.parse_args()
    if not (RAW/'.git').is_dir() or git('rev-parse','--show-toplevel').decode().strip().replace('\\','/').lower() != RAW.as_posix().lower():
        raise SystemExit('Expected a dedicated Git repository at '+str(RAW))
    if git('remote','get-url','origin').decode().strip() != REMOTE:
        raise SystemExit('Unexpected origin; refusing to update')
    if git('status','--porcelain','--untracked-files=normal').strip():
        raise SystemExit('The data checkout has local changes; preserve them before updating.')
    lock = RAW/'.git/genshin-text-update.lock'
    with lock.open('x'):
        pass
    old_head = git('rev-parse','HEAD').decode().strip()
    old_manifest = (RAW/'manifest.json').read_bytes() if (RAW/'manifest.json').exists() else None
    candidate = DB.with_name('genshin-text.candidate.sqlite')
    backup = DB.with_name('genshin-text.previous.sqlite')
    report = ROOT/'databases/genshin-text-validation.candidate.json'
    report_target = ROOT/'databases/genshin-text-validation.json'
    old_report = report_target.read_bytes() if report_target.exists() else None
    if backup.exists():
        lock.unlink()
        raise SystemExit('A previous index backup exists; inspect it before updating: '+str(backup))
    installed = False
    merge_attempted = False
    try:
        if not args.offline:
            for attempt in range(3):
                try:
                    git('fetch','--filter=blob:none','origin','main')
                    break
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    if attempt == 2:
                        raise
                    print(f'Fetch interrupted; retrying ({attempt+2}/3)',flush=True)
                    time.sleep(2 ** (attempt+1))
            merge_attempted = True
            git('merge','--ff-only','origin/main')
        manifest = write_manifest()
        indexed = None
        if DB.exists():
            with closing(sqlite3.connect(DB)) as con:
                row = con.execute("SELECT value FROM metadata WHERE key='commit'").fetchone()
                indexed = json.loads(row[0]) if row else None
        # Rebuild on explicit request, new commit, or changed source selection.
        previous_files = json.loads(old_manifest)['files'] if old_manifest else []
        same_sources = {(x['path'],x['sha256']) for x in previous_files} == {(x['path'],x['sha256']) for x in manifest['files']}
        if indexed == manifest['commit'] and same_sources and not args.rebuild:
            print('Already current; source verification passed. Index unchanged.',flush=True)
            return
        cli('genshin_text.py','--database',candidate,'build')
        cli('verify_genshin_text.py','--database',candidate,'--report',report)
        if DB.exists():
            DB.replace(backup)
        candidate.replace(DB)
        installed = True
        report.replace(report_target)
        print('Git source and verified offline index are current: '+manifest['commit'],flush=True)
        backup.unlink(missing_ok=True)
    except BaseException:
        if backup.exists():
            backup.replace(DB)
        elif installed:
            DB.unlink(missing_ok=True)
        if old_report is not None:
            report_target.write_bytes(old_report)
        if merge_attempted:
            if git('rev-parse','HEAD').decode().strip() != old_head:
                git('reset','--keep',old_head)
        if old_manifest is not None:
            (RAW/'manifest.json').write_bytes(old_manifest)
        else:
            (RAW/'manifest.json').unlink(missing_ok=True)
        print('Update failed; previous checkout/manifest restored and previous index retained.',file=sys.stderr)
        raise
    finally:
        lock.unlink(missing_ok=True)

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
