"""Independent MVP client of module builders. Builds research data, never deploys."""
import copy
import json
from pathlib import Path
import re
from .modules import assemble_module
from .ndfsource import verify_ndf_profile
from .storage import safe_child, sha256


# Gameplay acceptance scope, not a list of capabilities already implemented.
# Adding a supported gameplay feature requires adding its acceptance case here.
FEATURES = {
    'campaign-registration': 'Independent selectable Army General campaign',
    'pawn-placement': 'Four pawns at controlled strategic positions',
    'battalion-composition': 'A battalion with an independently checked roster',
    'division-assignment': 'Controlled division membership',
    'strategic-map-edit': 'One edited map area and its navigation',
    'strategic-map-new': 'A new minimal strategic map',
    'radiation-overlay': 'One visible radiation zone',
    'radiation-effects': 'One battalion affected, a control battalion unaffected',
    'action-points': 'A controlled change to pawn action points',
    'battle-eligibility': 'A positive and a negative battle admission case',
    'battle-participant-limit': 'A changed limit with an excess participant rejected',
    'tactical-map-selection': 'Different tactical maps for two strategic locations',
    'turn-limit': 'An independently changed campaign turn limit',
    'victory-conditions': 'An independently changed score threshold',
    'victory-result': 'A scripted result distinct from score-derived result',
    'victory-panel': 'Exactly one correct results panel and continuation action',
    'event-trigger': 'One controlled event with a negative control',
    'event-ui': 'One controlled event text or UI element',
    'save-load': 'Campaign and extension state survives save/reload',
    'module-lifecycle': 'Version-checked loading, isolation and clean disabling',
}


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch('[a-z][a-z0-9-]{0,63}', value):
        raise ValueError('Invalid MVP identifier')
    return value


def load_campaign(path):
    path = Path(path).resolve()
    spec = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(spec, dict) or set(spec) != {'schema','id','baseline','cases'}:
        raise ValueError('Unknown or missing MVP manifest fields')
    if type(spec['schema']) is not int or spec['schema'] != 1:
        raise ValueError('Unsupported MVP schema')
    identifier(spec['id'])
    if not isinstance(spec['baseline'], str) or not spec['baseline'].strip():
        raise ValueError('MVP baseline is required')
    if not isinstance(spec['cases'], list) or not spec['cases']:
        raise ValueError('MVP requires at least one case')
    identifiers, cases = set(), []
    for case in spec['cases']:
        if not isinstance(case, dict) or set(case) != {'id','modules','evidence','features','steps','expected'}:
            raise ValueError('Unknown or missing MVP case fields')
        key = identifier(case['id'])
        if key == 'combined' or key in identifiers:
            raise ValueError('Reserved or duplicate MVP case')
        identifiers.add(key)
        features = case['features']
        if not isinstance(features, list) or not features or any(
                not isinstance(f,str) or f not in FEATURES for f in features) or len(set(features)) != len(features):
            raise ValueError('Unknown or duplicate MVP feature')
        if not isinstance(case['steps'],list) or not case['steps'] or any(
                not isinstance(s,str) or not s.strip() for s in case['steps']):
            raise ValueError('MVP case needs explicit reproduction steps')
        if not isinstance(case['expected'],str) or not case['expected'].strip():
            raise ValueError('MVP case needs an expected runtime observation')
        module_names=case['modules']
        if (not isinstance(module_names,list) or not module_names or
                any(not isinstance(name,str) for name in module_names) or len(set(module_names))!=len(module_names)):
            raise ValueError('MVP modules must be unique relative paths')
        modules=[]
        for name in module_names:
            module_path = safe_child(path.parent, name)
            modules.append(json.loads(module_path.read_text(encoding='utf-8')))
        evidence_names=case['evidence']
        if (not isinstance(evidence_names,list) or
                any(not isinstance(name,str) for name in evidence_names) or
                len(set(evidence_names))!=len(evidence_names)):
            raise ValueError('MVP evidence must be unique relative paths')
        evidence=[]
        for name in evidence_names:
            evidence_path=safe_child(path.parent,name)
            raw=evidence_path.read_bytes()
            evidence.append({'profile':name,'profile_sha256':sha256(raw),
                             'spec':json.loads(raw.decode('utf-8'))})
        cases.append((case, modules, evidence))
    return spec, cases


def compose_modules(modules, identity):
    """Merge data operations once; shared targets are rejected by existing editors."""
    combined = copy.deepcopy(modules[0])
    combined['id'] = identifier(identity)
    combined['resources'] = []
    clones=[m for m in modules if 'entry_renames' in m]
    if clones:
        metadata={(m['output_name'],json.dumps(m['entry_renames'],sort_keys=True)) for m in clones}
        if len(metadata)!=1: raise ValueError('MVP cloned archive metadata conflict')
        combined['output_name']=clones[0]['output_name']
        combined['entry_renames']=copy.deepcopy(clones[0]['entry_renames'])
    resources = {}
    for module in modules:
        if (module['source_sha256'] != combined['source_sha256'] or
                Path(module['source_pack']).resolve() != Path(combined['source_pack']).resolve()):
            raise ValueError('MVP composition requires one identical source pack')
        for resource in module['resources']:
            name = resource['path']
            if name not in resources:
                resources[name] = copy.deepcopy(resource)
                combined['resources'].append(resources[name])
            else:
                existing = resources[name]
                if (existing['backend'] != resource['backend'] or
                        existing['spec']['source_sha256'] != resource['spec']['source_sha256']):
                    raise ValueError('MVP resource backend/fingerprint conflict')
                existing['spec']['operations'].extend(copy.deepcopy(resource['spec']['operations']))
    return combined


def compose_module_sets(modules, identity):
    groups={}
    for module in modules:
        key=(str(Path(module['source_pack']).resolve()),module['source_sha256'])
        groups.setdefault(key,[]).append(module)
    return [compose_modules(group,identity+('-'+str(index) if len(groups)>1 else ''))
            for index,group in enumerate(groups.values(),1)]


def assemble_campaign(path, require_complete=False):
    spec, cases = load_campaign(path)
    if require_complete:
        # No runtime acceptance ingestion/verification exists yet. Even all data
        # cases cannot pass this gate; manifest assertions cannot override it.
        raise ValueError('MVP is not runtime-accepted; deployment, engine adapters and gameplay verification remain open')
    products, all_modules, results = {}, [], []
    for case, modules, evidence in cases:
        verified_evidence=[{'profile':item['profile'],'profile_sha256':item['profile_sha256'],
                            'result':verify_ndf_profile(item['spec'])} for item in evidence]
        packages=[]
        for module in modules:
            output, report = assemble_module(module)
            if report['source_sha256'] == report['output_sha256']:
                raise ValueError('A no-op package cannot demonstrate an MVP feature')
            packages.append((output,report,module))
            all_modules.append(module)
        products[case['id']]=packages
        results.append({**case,
                        'package_sha256':[result[1]['output_sha256'] for result in packages],
                        'evidence_results':verified_evidence,
                        'offline_status':'data-verified', 'runtime_status':'not-run',
                        'module_sha256':[sha256(json.dumps(result[2],sort_keys=True).encode()) for result in packages]})
    combined_modules=compose_module_sets(all_modules,spec['id'])
    combined_packages=[(*assemble_module(module),module) for module in combined_modules]
    products['combined'] = combined_packages
    coverage = []
    for feature, description in FEATURES.items():
        linked = [c['id'] for c in results if feature in c['features']]
        coverage.append({'feature':feature, 'description':description, 'cases':linked,
                         'offline_status':'data-case-present' if linked else 'not-implemented',
                         'runtime_status':'not-run' if linked else 'blocked'})
    report = {'schema':1, 'id':spec['id'], 'baseline':spec['baseline'],
              'manifest_sha256':sha256(json.dumps(spec,sort_keys=True).encode()),
              'cases':results, 'coverage':coverage,
              'combined_output_sha256':[result[1]['output_sha256'] for result in combined_packages],
              'ready':False, 'installable':False, 'runtime_verified':False,
              'limitations':[
                  'Research packages only: the cloned Definition has not been runtime-discovered or launched',
                  'Cases modify existing baseline descriptors; runtime reachability is not proven',
                  'Combined data compatibility does not prove gameplay ordering or lack of interference',
                  'Native/Python load precedence and save compatibility remain unresolved',
                  'No game launch, injection, installation or manual acceptance was performed']}
    return products, report


def write_campaign(path, require_complete=False):
    products, report = assemble_campaign(path, require_complete)
    root = Path(__file__).resolve().parents[1]/'artifacts'/'mvp-builds'
    if root.is_symlink() or root.resolve() != root.absolute():
        raise ValueError('MVP output root must not be redirected')
    digest = sha256(json.dumps(report,sort_keys=True).encode())
    target = safe_child(root, report['id']+'-'+digest[:16])
    if Path(path).resolve().is_relative_to(target) or any(
            Path(module['source_pack']).resolve().is_relative_to(target)
            for packages in products.values() for _,_,module in packages):
        raise ValueError('MVP input overlaps output')
    target.mkdir(parents=True,exist_ok=False)
    for identity, packages in products.items():
        folder = safe_child(target, identity)
        folder.mkdir(exist_ok=False)
        for index,(output,module_report,module) in enumerate(packages,1):
            package=safe_child(folder,f'{index:02d}-{module["id"]}')
            package.mkdir(exist_ok=False)
            output_name=module_report.get('output_name','package.edat')+'-research'
            with (package/output_name).open('xb') as stream:
                stream.write(output)
            for name, data in [('module.json',module), ('report.json',module_report)]:
                with (package/name).open('x',encoding='utf-8',newline='\n') as stream:
                    json.dump(data,stream,ensure_ascii=False,indent=2)
                    stream.write('\n')
    # Last file is the completion marker for all isolated and combined products.
    with (target/'report.json').open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    return target, report
