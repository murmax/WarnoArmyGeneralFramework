"""Offline integration checks against the local licensed game corpus."""
import json
import zipfile
from pathlib import Path
from .archives import read_directory
from .cndf import decode,encode_objects,inspect_pack
from .marshal26 import loads,dumps
from .scriptgraph import decode_script
from .storage import sha256,write_json,safe_child
from .xyz import XYZ


def audit_corpus(game_root, artifacts):
    game_root,artifacts = Path(game_root),Path(artifacts)
    report = {"runtime_verified":False,"xyz":[],"campaign_graphs":[],"native":[],"errors":[]}
    xyz_root = artifacts/'recovered'/'xyz'
    corpus = sorted(xyz_root.rglob('*.xyz'))
    if not corpus:
        raise ValueError('Missing recovered XYZ corpus; run recovery first')
    report['scope'] = 'Recovered local XYZ corpus and AG Definition packs from latest top-level numeric revision only'
    for path in corpus:
        try:
            raw=path.read_bytes(); xyz=XYZ.read(raw); tree=loads(xyz.payload)
            if dumps(tree)!=xyz.payload:raise ValueError('Marshal round-trip mismatch')
            report['xyz'].append({'path':str(path),'sha256':sha256(raw),'marshal_roundtrip':True})
            if '/Map/Scenario/CampagneStrat_' in path.as_posix() and path.name=='effetmap.xyz':
                graph=decode_script(tree)
                name=path.parts[-3]
                write_json(artifacts/'graphs'/f'{name}.json',graph)
                report['campaign_graphs'].append({'campaign':name,'objects':len(graph['objects']),
                                                 'edges':len(graph['edges']),'stack_verified':True})
        except Exception as e:report['errors'].append({'path':str(path),'error':str(e)})
    revisions=sorted([p for p in (game_root/'Data'/'PC').iterdir() if p.is_dir() and p.name.isdecimal()],key=lambda p:int(p.name))
    if not revisions:
        raise ValueError('Missing game revision corpus')
    latest= revisions[-1]
    report['latest_revision']=latest.name
    packs=sorted((latest/'Scenarios').glob('CampagneStrat_*_Definition.dat'))
    if not packs:
        raise ValueError('Missing native Definition corpus')
    for pack in packs:
        try:
            dest=artifacts/'native'/pack.stem
            manifest=inspect_pack(pack,dest)
            for item in manifest:
                path=safe_child(dest,item['path'])
                doc,decoded=decode(path.read_bytes())
                section=next(s for s in doc.sections if s.name=='OBJE')
                if encode_objects(decoded['objects'])!=doc.full_data[section.offset:section.offset+section.size]:
                    raise ValueError(f'Native object round-trip mismatch: {path}')
                report['native'].append({'path':str(path),'objects':decoded['object_count'],
                                         'sha256':decoded['sha256'],
                                         'roundtrip':True,'imports':len(decoded['imports']),
                                         'exports':len(decoded['exports'])})
        except Exception as e:report['errors'].append({'path':str(pack),'error':str(e)})
    selected = [
        'GameData/Gameplay/Constantes/Strategic/GDConstants.ndf',
        'GameData/Gameplay/Constantes/Strategic/IAStratConstantes.ndf',
        'GameData/Gameplay/Constantes/Strategic/StrategicFatigueConstants.ndf',
        'GameData/Gameplay/Constantes/ActionPointConsumptionGrid.ndf',
        'GameData/Gameplay/Constantes/ActionPointConsumptionGridRefs.ndf',
        'GameData/UserInterface/Use/Strategic/UISpecificStrategicEndGamePanelView.ndf',
        'GameData/UserInterface/Use/Strategic/UIStrategicLabelsOnMapResources.ndf',
        'GameData/UserInterface/Use/OutGame/UISpecificTacticalEndGameView.ndf',
    ]
    archive=game_root/'Mods'/'ModData'/'base.zip'
    report['current_mod_sources']={'archive':str(archive),'sha256':sha256(archive.read_bytes()),'files':[]}
    with zipfile.ZipFile(archive) as z:
        for name in selected:
            if name not in z.namelist():
                report['errors'].append({'path':name,'error':'Missing current mod source'})
                continue
            data=z.read(name);target=safe_child(artifacts/'current_sources',name)
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            report['current_mod_sources']['files'].append({'path':name,'sha256':sha256(data)})
    report['summary']={'xyz_roundtrips':len(report['xyz']),'campaign_graphs':len(report['campaign_graphs']),
                       'native_roundtrips':len(report['native']),'errors':len(report['errors'])}
    write_json(artifacts/'audit.json',report)
    print(json.dumps(report['summary']))
    return report
