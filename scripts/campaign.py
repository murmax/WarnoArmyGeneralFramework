"""Author-facing campaign commands. Run from the repository root."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def prepare(game):
    game = Path(game).resolve()
    for name in ('WARNO.exe', 'Mods/ModData/base.zip', 'Tools/AssetCooker.exe'):
        if not (game / name).is_file():
            raise FileNotFoundError('Choose the WARNO folder containing ' + name)
    os.environ['WARNO_GAME_ROOT'] = str(game)
    from prepare_game_template import prepare as extract
    template = ROOT / 'artifacts/modgen-201602-template'
    if not template.exists():
        print('Preparing the installed game catalog...', flush=True)
        extract(game)
    else:
        receipt = json.loads((template / 'agf-template-receipt.json').read_text(encoding='utf8'))
        checksum = hashlib.sha256((game / 'Mods/ModData/base.zip').read_bytes()).hexdigest()
        if receipt['source_sha256'] != checksum:
            raise ValueError('Prepared catalog is from another game build. Rename artifacts/modgen-201602-template, then prepare again.')
        # A copied installation can use the same verified catalog at a new path.
        receipt['source'] = str(game / 'Mods/ModData/base.zip')
        (template / 'agf-template-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf8')
    from bootstrap_authored_localisation import bootstrap
    compatibility = ROOT / 'artifacts/compatibility'
    if not compatibility.exists():
        bootstrap(compatibility)
    print('Game catalog and compatibility dictionaries ready.', flush=True)
    return game, template


def source_folder(value):
    source = Path(value).resolve()
    if source.is_file() and source.name == 'campaign.yaml':
        source = source.parent
    if not (source / 'campaign.yaml').is_file() or not (source / 'profile.yaml').is_file():
        raise ValueError('Campaign source must contain campaign.yaml and profile.yaml')
    return source


def clone(source, destination, identifier):
    source = source_folder(source)
    destination = Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(source):
        raise ValueError('Choose a new destination outside the original campaign')
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', identifier):
        raise ValueError('Campaign id needs 1–48 lowercase letters, digits or underscores, starting with a letter')
    import yaml
    campaign = yaml.safe_load((source / 'campaign.yaml').read_text(encoding='utf8'))
    profile = yaml.safe_load((source / 'profile.yaml').read_text(encoding='utf8'))
    previous = campaign['id']
    if identifier == previous:
        raise ValueError('A new campaign needs a different id')
    map_name = profile.get('strategic_map', {}).get('map_name')
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns('.git', '__pycache__'))
    for file in destination.rglob('*.yaml'):
        text = file.read_text(encoding='utf8').replace(previous, identifier)
        if map_name:
            text = text.replace(map_name, 'AGF_' + identifier)
        file.write_text(text, encoding='utf8')
    print(json.dumps({'source': str(destination), 'campaign_id': identifier,
                      'map_name': 'AGF_' + identifier if map_name else None,
                      'installed': False}, indent=2))


def inputs(source, game, output):
    from warno_ag.authoring import compile_campaign
    from warno_ag.event_images import compile_event_images
    from warno_ag.world_source import prepare_world_source
    from warno_ag.game_resources import GameResources
    from warno_ag.cndf import decode
    from warno_ag.native_campaign_source import scalar
    from warno_ag.stock_scenery import load_stock_scenery
    source = source_folder(source)
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('Choose a new output folder: ' + str(output))
    output.mkdir(parents=True)
    compiled, report = compile_campaign(source, source / 'profile.yaml', output / 'compiled')
    result = {'source': str(source), 'profile': str(source / 'profile.yaml'),
              'compile': report, 'compiled': str(output / 'compiled/campaign.compiled.json'),
              'world_source': None, 'event_images': None}
    if (source / 'event-images.yaml').is_file():
        compile_event_images(source / 'event-images.yaml', output / 'event-images')
        result['event_images'] = str(output / 'event-images')
    if (source / 'world.yaml').is_file():
        resources = GameResources(game)
        scenario = 'CampagneStrat_Bruderkrieg'
        _, info = decode(resources.scenario(scenario, 'Definition').read(
            f'NDF/Scenarios/ScenarioInfo/{scenario}.ndfbin'))
        load = next(o for o in info['objects'] if o['class'] == 'TScenarioLoadInfo')
        stock_map = scalar(load, 'RootDatapackName')
        scene_archive = resources.map(stock_map, 'Details').require('Items.sav').archive
        scenery_archive = game / 'Data/PC/201602/DecorsSets/Steelman_Definition.dat'
        from warno_ag.world_source import load_scene_template
        prepare_world_source(source / 'world.yaml', output / 'world-source',
                             scene_template=load_scene_template(scene_archive),
                             scenery_catalog=load_stock_scenery(scenery_archive))
        result['world_source'] = str(output / 'world-source')
    (output / 'inputs.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf8')
    return result


def catalog(game, template, output):
    from warno_ag.editor_catalog import discover_editor_catalog
    from warno_ag.game_resources import GameResources
    from warno_ag.native_campaign_source import NativeCampaignReader
    from warno_ag.label_tokens import label_token_key
    from warno_ag.modgen import strategic_pack_signatures
    from warno_ag.stock_scenery import load_stock_scenery
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    units = discover_editor_catalog(template)['base_game']
    if units['status'] != 'verified':
        raise ValueError(units.get('error', 'Unit catalog unavailable'))
    reader = NativeCampaignReader(GameResources(game))
    scenario = 'CampagneStrat_Bruderkrieg'
    raw = (template / 'GameData/Generated/Gameplay/Gfx/UniteDescriptor.ndf').read_text(encoding='utf-8-sig')
    blocks = re.split(r'\bexport\s+Descriptor_Unit_(\w+)\s+is\s+TEntityDescriptor\b', raw)
    tokens = {identifier: re.findall(r'\bNameToken\s*=\s*[\'\"](\w+)', block)
              for identifier, block in zip(blocks[1::2], blocks[2::2])}
    with (output / 'units.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['id', 'name_en', 'name_ru', 'category', 'tags'])
        writer.writeheader()
        for unit in units['entries']:
            token = tokens.get(unit['id'], [])
            names = reader.text(scenario, label_token_key(token[0]), unit['id'], domain='/Core/UNITS-') if len(token)==1 else {'en':unit['id'],'ru':unit['id']}
            writer.writerow({'id': unit['id'], 'name_en': names['en'], 'name_ru': names['ru'],
                             'category': unit['category'], 'tags': ','.join(unit['tags'])})
    with (output / 'packs.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['id', 'unit', 'transport', 'experience', 'number'])
        writer.writeheader()
        for name, pack in strategic_pack_signatures().items():
            writer.writerow({'id': name.removeprefix('Descriptor_StrategicPack_'),
                'unit': pack['unit'].rsplit('Descriptor_Unit_',1)[-1],
                'transport': pack['transport'].rsplit('Descriptor_Unit_',1)[-1] or '',
                'experience': pack['experience'], 'number': pack['number']})
    scenery = load_stock_scenery(game / 'Data/PC/201602/DecorsSets/Steelman_Definition.dat')
    with (output / 'scenery.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['asset', 'descriptor_class'])
        for name, row in sorted(scenery['registrations'].items()):
            writer.writerow([name, row['descriptor_class']])
    print('Catalogs: ' + str(output), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    command = sub.add_parser('clone', help='Copy a campaign with independent campaign/map identities')
    command.add_argument('source'); command.add_argument('destination'); command.add_argument('--id', required=True)
    for action in ('prepare', 'catalog', 'check', 'build'):
        command = sub.add_parser(action)
        if action in ('check', 'build'):
            command.add_argument('source')
        command.add_argument('--game', required=True, help='WARNO folder containing WARNO.exe')
        if action != 'prepare':
            command.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.command == 'clone':
        clone(args.source, args.destination, args.id)
        return
    game, template = prepare(args.game)
    if args.command == 'prepare':
        return
    if args.command == 'catalog':
        catalog(game, template, args.output)
        return
    result = inputs(args.source, game, args.output)
    if args.command == 'build':
        from warno_ag.editor_public_package import package_public_editor_campaign
        workspaces = ROOT / 'artifacts/compiler-workspaces'
        workspaces.mkdir(parents=True, exist_ok=True)
        build = package_public_editor_campaign(result['source'], result['profile'], game,
                    Path(args.output) / 'build', world_source=result['world_source'],
                    event_images=result['event_images'], workspace_parent=workspaces)
        result['package'] = {key: build['package'][key] for key in ('bundle', 'config', 'candidate')}
        result['installed'] = False
        (Path(args.output) / 'build-result.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf8')
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
