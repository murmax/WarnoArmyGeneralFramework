"""Import installed Army General source data without executing campaign scripts.

The projection exposes editable data with native bindings. The complete source
resources accompany it so unsupported script/scene constructs are preserved and
can be independently compared after building a new campaign.
"""
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import tempfile

from PIL import Image

from .cndf import decode
from .full_campaign import _trad_data
from .label_tokens import label_token_key
from .game_resources import GameResources, _revision
from .items import spawn_inventory
from .storage import safe_child, sha256
from .strategic_grid_binary import read_grid
from .world_source import NATIVE_RENDER_CASE_SIZE


def fields(obj):
    return {prop['property_name']: prop['value'] for prop in obj['properties']}


def scalar(obj, name, default=None):
    value = fields(obj).get(name)
    return default if value is None else value.get('value', value.get('value_hex', default))


def simplify(value):
    if value['type'] == 'obj_ref':
        return {'object_id': value['object_id']}
    if value['type'] == 'map':
        return {'key': simplify(value['key']), 'value': simplify(value['value'])}
    if value['type'] == 'map_list':
        return [{'key': simplify(pair['key']), 'value': simplify(pair['value'])} for pair in value['items']]
    if value['type'] == 'list':
        return [simplify(item) for item in value['items']]
    if 'value' in value:
        return value['value']
    if 'value_hex' in value:
        return {'hex': value['value_hex'], 'type': value['type']}
    return value.copy()


def properties(obj):
    return {name: simplify(value) for name, value in fields(obj).items()}


class NativeCampaignReader:
    def __init__(self, game):
        self.game = game if isinstance(game, GameResources) else GameResources(game)
        self._graphs = {}
        self._worlds = {}
        self._translations = {}
        self._rosters = {}

    def catalog(self):
        result = []
        for scenario in self.game.campaigns():
            definition = self.game.scenario(scenario, 'Definition')
            _, info = decode(definition.read(f'NDF/Scenarios/ScenarioInfo/{scenario}.ndfbin'))
            _, config = decode(definition.read(f'NDF/Scenarios/MapConfiguration/{scenario}.ndfbin'))
            source_info = next(obj for obj in info['objects'] if obj['class'] == 'TScenarioLoadInfo')
            map_info = next(obj for obj in config['objects'] if obj['class'] == 'TStrategicMapInfo')
            result.append({'scenario': scenario, 'title': self.text(scenario, scalar(map_info, 'Name'), scenario, domain='/Core/MAPS-'),
                           'map_name': scalar(source_info, 'RootDatapackName'), 'guid': scalar(source_info, 'GUID')})
        return {'format': 'agf-native-campaign-catalog/v1', 'game_root': str(self.game.root), 'campaigns': result}

    def graph(self, path):
        if path not in self._graphs:
            _, self._graphs[path] = decode(self.game.definitions().read(path))
        return self._graphs[path]

    def translations(self, scenario):
        if scenario in self._translations:
            return self._translations[scenario]
        sets = [self.game.shared(), self.game.scenario(scenario, 'Assets')]
        selected = {}
        for resources in sets:
            for entry in resources.entries:
                if not entry.path.endswith(('-RU.dic', '-US.dic')):
                    continue
                canonical = entry.path.removeprefix('AllPlatforms/')
                previous = selected.get(canonical.casefold())
                if previous is None or _revision(entry.archive, self.game.data_root) > _revision(previous.archive, self.game.data_root):
                    selected[canonical.casefold()] = entry
        output = {'ru': {}, 'en': {}}
        for entry in sorted(selected.values(), key=lambda item: _revision(item.archive, self.game.data_root)):
            language = 'ru' if entry.path.endswith('-RU.dic') else 'en'
            for key, text in _trad_data(entry.read()).items():
                output[language].setdefault(key.hex(), []).append({'text': text, 'resource': entry.path})
        self._translations[scenario] = output
        return output

    def text(self, scenario, token, fallback='', *, domain=None):
        if not token:
            return {'ru': fallback, 'en': fallback}
        translations = self.translations(scenario)
        result = {}
        for language in ('ru', 'en'):
            candidates = translations[language].get(token, [])
            preferred = [item for item in candidates if domain and domain in item['resource']]
            values = preferred or candidates
            result[language] = values[-1]['text'] if values else (fallback or '#' + token)
        return result

    def read(self, scenario):
        definition = self.game.scenario(scenario, 'Definition')
        _, info_graph = decode(definition.read(f'NDF/Scenarios/ScenarioInfo/{scenario}.ndfbin'))
        info = [obj for obj in info_graph['objects'] if obj['class'] == 'TScenarioLoadInfo']
        if len(info) != 1 or scalar(info[0], 'Name') != scenario or scalar(info[0], 'Path') != scenario:
            raise ValueError('Source scenario identity is inconsistent')
        _, config_graph = decode(definition.read(f'NDF/Scenarios/MapConfiguration/{scenario}.ndfbin'))
        configs = [obj for obj in config_graph['objects'] if obj['class'] == 'TStrategicMapInfo']
        if len(configs) != 1 or scalar(configs[0], 'GUID') != scalar(info[0], 'GUID'):
            raise ValueError('Source strategic map and scenario GUIDs differ')
        config = configs[0]
        map_name = scalar(info[0], 'RootDatapackName')
        script_path = f'NDF/Scenarios/GDScript/{scenario}.ndfbin'
        script_raw = definition.read(script_path)
        _, script = decode(script_raw)
        detail_set = self.game.scenario(scenario, 'Details')
        level_raw = detail_set.read('out/LevelDesign.ndfbin')
        _, level = decode(level_raw)
        placements = spawn_inventory(level_raw)
        for row in placements:
            addon = level['objects'][row['object_id']]
            row['guid'] = scalar(addon, 'GUID')
            row['ranking'] = scalar(addon, 'Ranking')
            row['source_properties'] = properties(addon)
        points = []
        for obj in level['objects']:
            if obj['class'] != 'TGameDesignItem':
                continue
            props = fields(obj)
            reference = props.get('AddOn')
            if not reference or reference.get('type') != 'obj_ref':
                continue
            addon = level['objects'][reference['object_id']]
            point = {'object_id': obj['id'], 'addon_id': addon['id'], 'kind': addon['class'],
                     'name': scalar(addon, 'Name'), 'position': scalar(obj, 'Position'),
                     'item_properties': properties(obj), 'addon_properties': properties(addon)}
            if addon['class'] == 'TGameDesignAddOn_LabelOnMap' and (token := point['addon_properties'].get('Token')):
                key = label_token_key(token)
                translations = self.translations(scenario)
                point['label_key'] = key
                point['label_text'] = self.text(scenario, key, token, domain='/Core/MAPS-')
                point['label_verified'] = all(any('/Core/MAPS-' in row['resource'] for row in translations[language].get(key, []))
                                              for language in ('ru', 'en'))
            points.append(point)
        pawn_exports = {row['class_name'] for row in placements}
        pawn_exports.update(path for path in script['imports'].values() if path.startswith('$/GFX/Pawn/Descriptor_Unit_'))
        battalions = [self.battalion(scenario, export) for export in sorted(pawn_exports)]
        rules = []
        for object_id, export in script['exports'].items():
            obj = script['objects'][object_id]
            if obj['class'] in {'TGDVariableInteger', 'TGDVariableFloat', 'TGDVariableBoolean'}:
                rules.append({'export': export, 'object_id': object_id, 'class': obj['class'],
                              'value': scalar(obj, 'Value', 0), 'explicit_value': 'Value' in fields(obj)})
        _, playable = decode(detail_set.read('out/PlayableZone.ndfbin'))
        polygons = [simplify(fields(obj)['BasePolygon2D']) for obj in playable['objects']
                    if obj['class'] == 'TMapArea' and 'BasePolygon2D' in fields(obj)]
        world = {**self.world(map_name), 'playable_polygons': polygons}
        return {'format': 'agf-native-campaign-projection/v1', 'scenario': scenario,
                'guid': scalar(info[0], 'GUID'), 'title_token': scalar(config, 'Name'),
                'title': self.text(scenario, scalar(config, 'Name'), scenario, domain='/Core/MAPS-'),
                'scenario_properties': properties(info[0]), 'configuration_properties': properties(config),
                'rules': rules, 'initial_dates': [properties(obj) for obj in script['objects'] if obj['class'] == 'TGDDescriptorSetInitialDate'],
                'camps': [{'object_id': obj['id'], **properties(obj)} for obj in script['objects'] if obj['class'] == 'TGDVariableCamp'],
                'script': {'path': script_path, 'sha256': sha256(script_raw), 'object_count': len(script['objects']),
                           'classes': dict(Counter(obj['class'] for obj in script['objects'])),
                           'preservation': 'complete native graph retained; script is not executed by importer'},
                'map': world, 'placements': placements, 'map_points': points, 'battalions': battalions,
                'runtime_verified': False}

    def world(self, name):
        if name in self._worlds:
            return self._worlds[name]
        details = self.game.map(name, 'Details')
        source = details.read('Map.ndf').decode('utf-8-sig')
        def number(key):
            matches = re.findall(r'(?m)^\s*' + re.escape(key) + r'\s+is\s+([-+0-9.eE]+)\s*$', source)
            if len(matches) != 1:
                raise ValueError('Map source requires one numeric ' + key)
            return float(matches[0])
        width, height = number('NbCaseX'), number('NbCaseY')
        if not width.is_integer() or not height.is_integer() or min(width, height) <= 0:
            raise ValueError('Invalid native map render-case dimensions')
        raw_height = details.read('HeightMap.png')
        with Image.open(io.BytesIO(raw_height)) as image:
            height_size, height_mode = list(image.size), image.mode
            if image.format != 'PNG' or height_mode not in ('I;16', 'I;16L', 'I;16B'):
                raise ValueError('Stock source heightmap is not a 16-bit PNG')
        surface = details.read('Div_map.webp')
        with Image.open(io.BytesIO(surface)) as image:
            surface_size = list(image.size)
        _, scene = decode(details.read('Items.sav'))
        scene_items = [{'object_id': obj['id'], 'kind': obj['class'], 'properties': properties(obj)}
                       for obj in scene['objects'] if obj['class'].startswith('TSaveDescriptorItem')]
        grid = read_grid(self.game.map(name, 'baked').read('Output/StrategicGridData.ndfbin'))
        grid_constants = [obj for obj in self.graph('NDF/GFX/Constantes.ndfbin')['objects']
                          if obj['class'] == 'TActionPointConsumptionGridConstantsDescriptor']
        units = [obj for obj in self.graph('NDF/InitialisationGameDistanceUnits.ndfbin')['objects']
                 if obj['class'] == 'TInitialisationGameDistanceUnits']
        if len(grid_constants) != 1 or len(units) != 1:
            raise ValueError('Missing native strategic grid or unit conversion constants')
        f32 = lambda value: struct.unpack('<f', struct.pack('<f', value))[0]
        cell_gru = scalar(grid_constants[0], 'TailleDeCaseApproximativeGRU')
        factor = scalar(units[0], 'LBUToGRUConversionFactor')
        step = f32(f32(cell_gru / factor) * 215)
        grid.update(origin=[0.0, 0.0], step_native=step,
                    source_case_size_gru=cell_gru, source_lbu_to_gru=factor)
        result = {'name': name, 'bounds': [0, 0, int(width) * NATIVE_RENDER_CASE_SIZE, int(height) * NATIVE_RENDER_CASE_SIZE],
                  'render_cases': {'width': int(width), 'height': int(height)},
                  'max_altitude_lbu': number('MaxAltitudeInLBU'), 'water_height_lbu': number('WaterHeightInLBU'),
                  'heightmap_source': 'HeightMap.png', 'heightmap_size': height_size, 'heightmap_sha256': sha256(raw_height),
                  'surface_source': 'Div_map.webp', 'surface_size': surface_size, 'surface_sha256': sha256(surface),
                  'grid': grid, 'scene_items': scene_items, 'scene_class_counts': dict(Counter(obj['class'] for obj in scene['objects']))}
        self._worlds[name] = result
        return result

    def battalion(self, scenario, export):
        key = (scenario, export)
        if key in self._rosters:
            return self._rosters[key]
        graph = self.graph('NDF/GFX/Pawn.ndfbin')
        matches = [identifier for identifier, value in graph['exports'].items() if value == export]
        if len(matches) != 1:
            raise ValueError('Unresolved native strategic pawn: ' + export)
        obj = graph['objects'][matches[0]]
        references = fields(obj).get('ModulesDescriptors', {}).get('items', [])
        modules = [graph['objects'][reference['object_id']] for reference in references if reference.get('type') == 'obj_ref']
        def module(name):
            matches = [item for item in modules if item['class'] == name]
            if len(matches) > 1:
                raise ValueError('Ambiguous strategic pawn module: ' + export + ': ' + name)
            return matches[0] if matches else {'properties': []}
        unit_type = module('TTypeUnitModuleDescriptor')
        ui = module('TPawnUIModuleDescriptor')
        appearance = module('TApparenceModuleDescriptor')
        deck_id = scalar(module('TDeckModuleDescriptor'), 'DeckIdentifier')
        result = {'export': export, 'object_id': obj['id'], 'guid': scalar(obj, 'DescriptorId'),
                  'country': scalar(unit_type, 'MotherCountry'), 'coalition': scalar(unit_type, 'Coalition', 0),
                  'name_token': scalar(ui, 'NameToken'),
                  'name': self.text(scenario, scalar(ui, 'NameToken'), deck_id or export.rsplit('/', 1)[-1], domain='/Core/UNITS-'),
                  'icon_token': scalar(ui, 'ProdMenuTexture'), 'depiction': scalar(appearance, 'Depiction'),
                  'module_classes': [item['class'] for item in modules],
                  'modules': [{'object_id': item['id'], 'class': item['class'], 'properties': properties(item)} for item in modules],
                  'deck': self.deck(scenario, deck_id) if deck_id else None}
        self._rosters[key] = result
        return result

    def deck(self, scenario, identifier):
        graph = self.graph('NDF/GFX/Deck.ndfbin')
        matches = [obj for obj in graph['objects'] if obj['class'] == 'TDeckDescriptor' and scalar(obj, 'DeckIdentifier') == identifier]
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous native deck: ' + identifier)
        obj = matches[0]
        slots = []
        for reference in fields(obj).get('DeckPackList', {}).get('items', []):
            pack = graph['objects'][reference['object_id']]
            slots.append({'object_id': pack['id'], 'export': graph['exports'].get(pack['id']),
                          'properties': properties(pack)})
        companies = []
        used = []
        for company_ref in fields(obj).get('DeckCombatGroupList', {}).get('items', []):
            company = graph['objects'][company_ref['object_id']]
            platoons = []
            for platoon_ref in fields(company).get('SmartGroupList', {}).get('items', []):
                platoon = graph['objects'][platoon_ref['object_id']]
                stacks = []
                for pair in fields(platoon).get('PackIndexUnitNumberList', {}).get('items', []):
                    start, count = pair['key']['value'], pair['value']['value']
                    if type(start) is not int or type(count) is not int or start < 0 or count < 0 or start + count > len(slots):
                        raise ValueError('Native deck group references invalid slot range: ' + identifier)
                    stacks.append({'first_slot': start, 'count': count})
                    used.extend(range(start, start + count))
                platoons.append({'object_id': platoon['id'], 'name_token': scalar(platoon, 'Name'),
                                 'name': self.text(scenario, scalar(platoon, 'Name'), domain='/Core/UNITS-'),
                                 'is_hq': scalar(platoon, 'IsHQ', False), 'stacks': stacks,
                                 'properties': properties(platoon)})
            companies.append({'object_id': company['id'], 'name_token': scalar(company, 'Name'),
                              'name': self.text(scenario, scalar(company, 'Name'), domain='/Core/UNITS-'),
                              'is_hq': scalar(company, 'IsHQ', False), 'platoons': platoons,
                              'properties': properties(company)})
        return {'object_id': obj['id'], 'identifier': identifier, 'division': scalar(obj, 'DeckDivision'),
                'pack_slots': slots, 'companies': companies,
                'unassigned_slots': sorted(set(range(len(slots))) - set(used)),
                'overlapping_slots': sorted(index for index, count in Counter(used).items() if count > 1)}

    def resource_sets(self, scenario, map_name):
        sets = {f'scenario_{kind.lower()}': self.game.scenario(scenario, kind) for kind in ('Definition', 'Details', 'Assets', 'GameData')}
        sets.update({f'map_{kind.lower()}': self.game.map(map_name, kind) for kind in ('Definition', 'Details', 'Assets', 'baked', 'Shooting', 'Stickers')})
        sets['shared_definitions'] = self.game.definitions()
        return sets


def capture_native_campaign(reader, scenario, destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    projection = reader.read(scenario)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.native-import-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'source'
        (staged / 'resources').mkdir(parents=True)
        resources = []
        for scope, resource_set in reader.resource_sets(scenario, projection['map']['name']).items():
            for entry in resource_set.entries:
                raw = entry.read()
                digest = sha256(raw)
                relative = 'resources/' + digest + '.bin'
                path = staged / relative
                if not path.exists():
                    path.write_bytes(raw)
                resources.append({'scope': scope, 'path': entry.path, 'file': relative,
                                  'sha256': digest, 'size': len(raw), 'origin': entry.origin()})
        projection_raw = json.dumps(projection, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        (staged / 'campaign.json').write_bytes(projection_raw)
        (staged / 'preview').mkdir()
        with Image.open(io.BytesIO(reader.game.map(projection['map']['name'], 'Details').read('Div_map.webp'))) as surface:
            surface.convert('RGB').save(staged / 'preview/surface.png')
        preview = {'file': 'preview/surface.png', 'sha256': sha256((staged / 'preview/surface.png').read_bytes()),
                   'source_scope': 'map_details', 'source_path': 'Div_map.webp', 'role': 'surface-preview'}
        manifest = {'format': 'agf-native-campaign-source/v1', 'scenario': scenario,
                    'projection_file': 'campaign.json', 'projection_sha256': sha256(projection_raw),
                    'game_root': str(reader.game.root), 'resources': resources, 'previews': [preview], 'runtime_verified': False}
        (staged / 'native-source.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        verify_native_snapshot(staged)
        staged.rename(destination)
    return manifest


def verify_native_snapshot(root):
    root = Path(root).resolve()
    manifest = json.loads((root / 'native-source.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 'agf-native-campaign-source/v1':
        raise ValueError('Unsupported native source snapshot')
    projection = safe_child(root, manifest['projection_file'])
    if sha256(projection.read_bytes()) != manifest['projection_sha256']:
        raise ValueError('Native source projection hash changed')
    seen = set()
    checked = {}
    for resource in manifest['resources']:
        key = (resource['scope'], resource['path'].casefold())
        if key in seen:
            raise ValueError('Duplicate native source resource')
        seen.add(key)
        path = safe_child(root, resource['file'])
        if path not in checked:
            with path.open('rb') as stream:
                checked[path] = (path.stat().st_size, hashlib.file_digest(stream, 'sha256').hexdigest())
        if checked[path] != (resource['size'], resource['sha256']):
            raise ValueError('Native source resource hash changed: ' + resource['path'])
    if not seen:
        raise ValueError('Native source resource inventory is empty')
    for preview in manifest.get('previews', []):
        if sha256(safe_child(root, preview['file']).read_bytes()) != preview['sha256']:
            raise ValueError('Native source preview hash changed')
    return {'format': 'agf-native-source-verification/v1', 'resources_verified': len(seen),
            'unique_payloads': len(checked), 'runtime_verified': False}
