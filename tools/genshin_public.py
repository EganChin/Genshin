"""Offline public configuration queries from the same Git source as the story index."""
import argparse
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from genshin_text import ROOT, RAW, read

class Corpus:
    def __init__(self):
        self.manifest = read(RAW/'manifest.json')
        head = subprocess.check_output(['git','-C',str(RAW),'rev-parse','HEAD'],text=True).strip()
        if self.manifest['commit'] != head:
            raise ValueError('Git HEAD and manifest differ; run tools/update_genshin_text.py first')
        self.files = {x['path']:x for x in self.manifest['files']}
        self.texts = {}
        for name in ('TextMap_MediumCHS.json','TextMapCHS.json'):
            self.texts.update(self.load('TextMap/'+name))

    @lru_cache(maxsize=None)
    def load(self, path):
        if path not in self.files:
            raise ValueError('File is not in the verified snapshot: '+path)
        data = (RAW/path).read_bytes()
        if hashlib.sha256(data).hexdigest() != self.files[path]['sha256']:
            raise ValueError('Source changed since manifest verification: '+path)
        return json.loads(data)

    def table(self, name):
        if '/' in name or '\\' in name or name in ('.','..'):
            raise ValueError('Use an exact ExcelBinOutput table stem')
        return self.load('ExcelBinOutput/'+name+'.json')

    def text(self, key):
        return self.texts.get(str(key))

    def record(self, table, row):
        # Preserve every upstream field; keep localized text separate from numeric data.
        localized = {k:self.text(v) for k,v in row.items() if 'textmaphash' in k.lower() and isinstance(v,(int,str))}
        if 'paramDescList' in row:
            localized['paramDescList'] = [self.text(x) for x in row['paramDescList']]
        return {'source':'ExcelBinOutput/'+table+'.json','raw':row,'localized':localized}

    def find(self, table, query, field='id'):
        matches = [x for x in self.table(table) if str(x.get(field))==query or self.text(x.get('nameTextMapHash'))==query
                   or str(x.get('iconName','')).removeprefix('UI_AvatarIcon_').lower()==query.lower()]
        if len(matches)!=1:
            raise ValueError(f'Expected one {table} record for {query!r}; got {len(matches)}. Use its numeric ID.')
        return matches[0]

    def character(self, query, level, depot_id=None):
        avatar = self.find('AvatarExcelConfigData',query)
        depot_id = depot_id if depot_id is not None else avatar['skillDepotId']
        allowed = {avatar['skillDepotId'], *avatar.get('candSkillDepotIds',[])}
        if depot_id not in allowed:
            raise ValueError('Skill depot is not listed for this avatar')
        depot = self.find('AvatarSkillDepotExcelConfigData',str(depot_id))
        skills = {x['id']:x for x in self.table('AvatarSkillExcelConfigData')}
        proud = self.table('ProudSkillExcelConfigData')
        output = []
        ids = [*depot.get('skills',[]),depot.get('energySkill'),*depot.get('subSkills',[])]
        for sid in dict.fromkeys(x for x in ids if x):
            if sid not in skills:
                raise ValueError(f'Skill {sid} referenced by depot {depot_id} is missing')
            skill = skills[sid]
            group = skill.get('proudSkillGroupId')
            group_rows = [x for x in proud if group and x.get('proudSkillGroupId')==group]
            params = [x for x in group_rows if x.get('level')==level]
            output.append({'skill':self.record('AvatarSkillExcelConfigData',skill),'level':level,
                           'available_levels':sorted({x.get('level',1) for x in group_rows}),
                           'parameters':[self.record('ProudSkillExcelConfigData',x) for x in params],
                           'parameter_status':'found' if params else 'no row at requested level; do not infer values'})
        talents = {x['talentId']:x for x in self.table('AvatarTalentExcelConfigData')}
        missing_talents = [t for t in depot.get('talents',[]) if t and t not in talents]
        if missing_talents:
            raise ValueError('Missing constellation records: '+str(missing_talents))
        passives = []
        for entry in depot.get('inherentProudSkillOpens',[]):
            group = entry.get('proudSkillGroupId')
            if group:
                passives.append({'unlock':entry,'records':[self.record('ProudSkillExcelConfigData',x) for x in proud if x.get('proudSkillGroupId')==group]})
        return {'avatar':self.record('AvatarExcelConfigData',avatar),'depot':self.record('AvatarSkillDepotExcelConfigData',depot),
                'skills':output,'passives':passives,
                'constellations':[self.record('AvatarTalentExcelConfigData',talents[t]) for t in depot.get('talents',[]) if t in talents]}

    def weapon(self, query, refine):
        weapon = self.find('WeaponExcelConfigData',query)
        effects = [x for x in self.table('EquipAffixExcelConfigData') if x.get('id') in weapon.get('skillAffix',[]) and x.get('level',0)==refine-1]
        return {'weapon':self.record('WeaponExcelConfigData',weapon),'refinement':refine,
                'effects':[self.record('EquipAffixExcelConfigData',x) for x in effects]}

    def artifact(self, query):
        row = self.find('ReliquarySetExcelConfigData',query,'setId')
        effects = [x for x in self.table('EquipAffixExcelConfigData') if x.get('id')==row.get('equipAffixId')]
        return {'set':self.record('ReliquarySetExcelConfigData',row),
                'effects':[self.record('EquipAffixExcelConfigData',x) for x in effects]}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command',required=True)
    c = subs.add_parser('character'); c.add_argument('query'); c.add_argument('--level',type=int,choices=range(1,16),default=10); c.add_argument('--depot',type=int)
    w = subs.add_parser('weapon'); w.add_argument('query'); w.add_argument('--refine',type=int,choices=range(1,6),default=1)
    a = subs.add_parser('artifact'); a.add_argument('id')
    t = subs.add_parser('table'); t.add_argument('name'); t.add_argument('--field',default='id'); t.add_argument('--value'); t.add_argument('--limit',type=int,default=10)
    args = parser.parse_args(); corpus = Corpus()
    if args.command=='character': result=corpus.character(args.query,args.level,args.depot)
    elif args.command=='weapon': result=corpus.weapon(args.query,args.refine)
    elif args.command=='artifact': result=corpus.artifact(args.id)
    else:
        rows=corpus.table(args.name)
        if args.value is not None: rows=[x for x in rows if str(x.get(args.field))==args.value]
        result=[corpus.record(args.name,x) for x in rows[:args.limit]]
    print(json.dumps({'commit':corpus.manifest['commit'],'result':result},ensure_ascii=False,indent=2))

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
