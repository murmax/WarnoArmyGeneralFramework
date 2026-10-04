"""Create private stock-derived pawn/deck descriptors for edited native formations."""
import copy
import hashlib
import re
import uuid

from .cndf import decode
from .native_graph import NativeGraphEditor
from .visual_catalog import current_visual_catalog


NAMESPACE = uuid.UUID('73e4d730-69a8-56e8-a3ae-9d705c15bc29')


def _scalar(editor, obj, field, default=None):
    prop = editor.property(obj, field)
    return default if prop is None else prop['value'].get('value', prop['value'].get('value_hex', default))


def build_private_rosters(pawn_raw, deck_raw, edits, bindings, target, depiction_raw=None, division_raw=None):
    pawn, deck = NativeGraphEditor(pawn_raw), NativeGraphEditor(deck_raw)
    depiction = NativeGraphEditor(depiction_raw) if depiction_raw is not None else None
    division = NativeGraphEditor(division_raw) if division_raw is not None else None
    index = {(row['kind'], row['id']): row['objectId'] for row in bindings}
    replacements, localized, reports, deck_identifiers, created = {}, {}, [], [], {}
    localized_translations = {}
    private_unit_imports = {}
    private_depiction_imports = {}
    private_division_imports = {}
    visual_changes = []
    division_changes = []
    private_packs = {}

    def pack_for_tactical_unit(unit_id):
        if not isinstance(unit_id, str) or re.fullmatch(r'[A-Za-z0-9_]+', unit_id) is None:
            raise ValueError('Invalid tactical unit id for a native pack')
        expected = '$/GFX/Unit/Descriptor_Unit_' + unit_id
        stock = [obj for obj in deck.objects[:deck.original_count]
                 if obj['class'] == 'TDeckPackDescriptor' and _scalar(deck, obj, 'UnitDescriptor') == expected]
        if stock:
            return min(stock, key=lambda obj: (
                _scalar(deck, obj, 'TransporterDescriptor') is not None,
                _scalar(deck, obj, 'ExperienceLevel', 0) != 0,
                _scalar(deck, obj, 'Number', 1) != 1))['id']
        if unit_id in private_packs:
            return private_packs[unit_id]
        template = next((obj for obj in deck.objects[:deck.original_count]
                         if obj['class'] == 'TDeckPackDescriptor'
                         and _scalar(deck, obj, 'TransporterDescriptor') is None
                         and _scalar(deck, obj, 'Number', 1) == 1), None)
        if template is None:
            raise ValueError('No valid native pack template for a tactical unit')
        new_id, _ = deck.clone(template['id'])
        pack = deck.objects[new_id]
        import_index = next((number for number, path in deck.imports.items() if path == expected), None)
        if import_index is None:
            import_index = max(deck.imports, default=-1) + 1
            deck.imports[import_index] = expected
            private_unit_imports[import_index] = expected
        wire = deck.property(pack, 'UnitDescriptor')['value'].copy()
        wire.update(index=import_index, value=expected)
        deck.set_value(pack, 'UnitDescriptor', wire)
        deck.set_scalar(pack, 'ExperienceLevel', 0, kind='int32')
        deck.set_scalar(pack, 'Number', 1, kind='int32')
        private_packs[unit_id] = new_id
        return new_id

    def rename(editor, obj, property_name, value, old_value, role,
               translated=None, old_translated=None):
        if value == old_value and translated == old_translated:
            return
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Native formation names must not be empty')
        key = hashlib.sha256((target + ':' + role).encode()).digest()[:8].hex()
        localized[key] = value
        if translated is not None:
            localized_translations[key] = translated
        editor.set_scalar(obj, property_name, key, kind='loc_hash')

    for edit in edits:
        before, after, binding = edit['before'], edit['after'], edit['binding']
        organization_label = (after.get('organization') or after['name']) if (
            after.get('organization') != before.get('organization')
            or after.get('localizedOrganization') is not None) else after['name']
        source_export = binding['export']
        original_pawn = pawn.named(source_export)
        is_new = edit.get('is_new', False)
        suffix = hashlib.sha256((target + ':' + source_export + (':' + after['id'] if is_new else '')).encode()).hexdigest()[:16]
        private_id = 'AGFN_' + suffix
        private_export = '$/GFX/Pawn/Descriptor_Unit_' + private_id
        pawn_id, pawn_mapping = pawn.clone(original_pawn['id'], export=private_export)
        copied_pawn = pawn.objects[pawn_id]
        pawn.set_scalar(copied_pawn, 'DescriptorId', uuid.uuid5(NAMESPACE, private_export).hex, kind='guid')
        pawn.set_scalar(copied_pawn, 'ClassNameForDebug', 'Pawn_' + private_id)
        modules = [pawn.objects[ref['object_id']] for ref in pawn.property(copied_pawn, 'ModulesDescriptors')['value']['items']]
        deck_module = next(module for module in modules if module['class'] == 'TDeckModuleDescriptor')
        ui_module = next(module for module in modules if module['class'] == 'TPawnUIModuleDescriptor')
        rename(pawn, ui_module, 'NameToken', after['name'], before['name'], private_id + ':name',
               after.get('localizedName'), before.get('localizedName'))
        if after['country'] != before['country'] or after['side'] != before['side']:
            if not is_new:
                raise ValueError('Stock native formation country and coalition cannot be changed in place')
            unit_type = next(module for module in modules if module['class'] == 'TTypeUnitModuleDescriptor')
            pawn.set_scalar(unit_type, 'MotherCountry', after['country'])
            pawn.set_scalar(unit_type, 'Coalition', 0 if after['side'] == 'nato' else 1, kind='int32')
        if after.get('supportRadiusAp') != before.get('supportRadiusAp'):
            battle = next(module for module in modules if module['class'] == 'TStrategicBattleModuleDescriptor')
            field = {'air_defence': 'AirDenyRadiusInAPCase',
                     'artillery': 'BattleSupportRadiusInAPCase'}.get(before.get('supportKind'))
            if field is None or _scalar(pawn, battle, field) is None:
                raise ValueError('Native support radius has no verified source field')
            pawn.set_scalar(battle, field, float(after['supportRadiusAp']), kind='float32')
        if before['strategicVisualUnitId'] != after['strategicVisualUnitId']:
            if depiction is None:
                raise ValueError('Native strategic visual edit requires captured depiction definitions')
            visual_id = after['strategicVisualUnitId']
            visual = current_visual_catalog().get(visual_id)
            country = after['country']
            if visual is None or visual['category'] not in {'infantry', 'vehicle', 'helicopter', 'airplane'}:
                raise ValueError('Native strategic visual is absent from the verified game catalog')
            if not visual_id.endswith('_' + ('DDR' if country == 'RDA' else country)):
                raise ValueError('Native strategic visual country differs from its formation')
            appearance = next(module for module in modules if module['class'] == 'TApparenceModuleDescriptor')
            source_depiction = _scalar(pawn, appearance, 'Depiction')
            private_depiction = '$/GFX/Depiction/Gfx_' + private_id
            root = depiction.named(source_depiction)
            _, depiction_mapping = depiction.clone(root['id'], export=private_depiction)
            body_mesh = '$/GFX/DepictionResources/' + visual['mesh']
            body_candidates = []
            for new_id in depiction_mapping.values():
                obj = depiction.objects[new_id]
                if obj['class'] != 'TDepictionVisual':
                    continue
                prop = depiction.property(obj, 'MeshDescriptor')
                if prop is not None and prop['value'].get('type') == 'trans_ref':
                    path = prop['value'].get('value', '')
                    if (path.startswith('$/GFX/DepictionResources/Modele_')
                            and not path.startswith('$/GFX/DepictionResources/Modele_Missile_')):
                        body_candidates.append(obj)
            if len(body_candidates) != 1:
                raise ValueError('Native strategic depiction has no unique unit body mesh')
            mesh_index = next((number for number, path in depiction.imports.items() if path == body_mesh), None)
            if mesh_index is None:
                mesh_index = max(depiction.imports, default=-1) + 1
                depiction.imports[mesh_index] = body_mesh
                private_depiction_imports[mesh_index] = body_mesh
            body = body_candidates[0]
            body_descriptors = [depiction.objects[new_id] for new_id in depiction_mapping.values()
                                if depiction.objects[new_id]['class'] == 'TDepictionDescriptor'
                                and any(item.get('object_id') == body['id'] for item in
                                        (depiction.property(depiction.objects[new_id], 'DepictionAlternatives') or
                                         {'value': {'items': []}})['value'].get('items', []))]
            if len(body_descriptors) != 1:
                raise ValueError('Native strategic depiction has no unique unit body descriptor')
            generators = depiction.property(body_descriptors[0], 'SubDepictionGenerators')
            removed_generators = 0
            if generators is not None:
                wire = copy.deepcopy(generators['value'])
                remaining = [item for item in wire['items'] if item.get('type') != 'obj_ref'
                             or depiction.objects[item['object_id']]['class'] != 'TShowroomMissileCarriageSubDepictionGenerator']
                removed_generators = len(wire['items']) - len(remaining)
                if removed_generators:
                    wire.update(items=remaining, length=len(remaining))
                    depiction.set_value(body_descriptors[0], 'SubDepictionGenerators', wire)
            wire = depiction.property(body, 'MeshDescriptor')['value'].copy()
            wire.update(index=mesh_index, value=body_mesh)
            depiction.set_value(body, 'MeshDescriptor', wire)
            if after['country'] != before['country']:
                stand_candidates = [depiction.objects[new_id] for new_id in depiction_mapping.values()
                                    if depiction.objects[new_id]['class'] == 'TDepictionVisual'
                                    and (prop := depiction.property(depiction.objects[new_id], 'MeshDescriptor')) is not None
                                    and prop['value'].get('value', '').startswith('$/GFX/DepictionResources/MeshModele_Socle_')]
                if len(stand_candidates) != 1:
                    raise ValueError('Native strategic depiction has no unique country stand')
                stand_mesh = '$/GFX/DepictionResources/MeshModele_Socle_' + (
                    'DDR' if after['country'] == 'RDA' else after['country'])
                stand_index = next((number for number, path in depiction.imports.items() if path == stand_mesh), None)
                if stand_index is None:
                    stand_index = max(depiction.imports, default=-1) + 1
                    depiction.imports[stand_index] = stand_mesh
                    private_depiction_imports[stand_index] = stand_mesh
                stand = stand_candidates[0]
                stand_wire = depiction.property(stand, 'MeshDescriptor')['value'].copy()
                stand_wire.update(index=stand_index, value=stand_mesh)
                depiction.set_value(stand, 'MeshDescriptor', stand_wire)
            depiction_index = next((number for number, path in pawn.imports.items() if path == private_depiction), None)
            if depiction_index is not None:
                raise ValueError('Private depiction export unexpectedly exists in stock pawn imports')
            depiction_index = max(pawn.imports, default=-1) + 1
            pawn.imports[depiction_index] = private_depiction
            appearance_wire = pawn.property(appearance, 'Depiction')['value'].copy()
            appearance_wire.update(index=depiction_index, value=private_depiction)
            pawn.set_value(appearance, 'Depiction', appearance_wire)
            private_texture = visual['texture']
            pawn.set_scalar(ui_module, 'ProdMenuTexture', private_texture)
            visual_changes.append({'formation_id': after['id'], 'unit_id': visual_id,
                                   'source_depiction': source_depiction, 'private_depiction': private_depiction,
                                   'body_mesh': body_mesh, 'cloned_objects': len(depiction_mapping),
                                   'country_stand': stand_mesh if after['country'] != before['country'] else None,
                                   'removed_source_missile_generators': removed_generators})
        changed_deck = is_new or before['companies'] != after['companies']
        if changed_deck:
            deck_identifier = _scalar(pawn, deck_module, 'DeckIdentifier')
            original_decks = [obj for obj in deck.objects[:deck.original_count]
                              if obj['class'] == 'TDeckDescriptor' and _scalar(deck, obj, 'DeckIdentifier') == deck_identifier]
            if len(original_decks) != 1:
                raise ValueError('Native source deck is missing or ambiguous')
            private_deck_export = '$/GFX/Deck/Descriptor_Deck_' + private_id
            deck_id, deck_mapping = deck.clone(original_decks[0]['id'], keep_classes={'TDeckPackDescriptor'}, export=private_deck_export)
            copied_deck = deck.objects[deck_id]
            deck.set_scalar(copied_deck, 'DeckIdentifier', private_id)
            pawn.set_scalar(deck_module, 'DeckIdentifier', private_id)
            if is_new and division is not None:
                source_division = _scalar(deck, copied_deck, 'DeckDivision')
                template_division = source_division
                if after['country'] != before['country']:
                    prefix = '$/GFX/Division/Descriptor_Deck_Division_' + after['country'] + '_'
                    options = [path for path in division.exports.values()
                               if path.startswith(prefix) and path.endswith('_solo')]
                    if options:
                        category = current_visual_catalog().get(after['strategicVisualUnitId'], {}).get('category')
                        strategic_type = ('helicopter' if category == 'helicopter' else
                                          'airplane' if category == 'airplane' else after['strategicType'])
                        marker = ('Avia', 'Heli') if strategic_type == 'helicopter' else (
                            'Air', 'Avia') if strategic_type == 'airplane' else ()
                        template_division = min(options, key=lambda path: (
                            not any(word.lower() in path.lower() for word in marker), path))
                template = division.named(template_division)
                if template['class'] != 'TDeckDivisionDescriptor':
                    raise ValueError('Native private deck has no valid division template')
                private_division = '$/GFX/Division/Descriptor_Deck_Division_' + private_id
                division_id, division_mapping = division.clone(template['id'], export=private_division)
                copied_division = division.objects[division_id]
                division.set_scalar(copied_division, 'DescriptorId', uuid.uuid5(NAMESPACE, private_division).hex, kind='guid')
                division.set_scalar(copied_division, 'CfgName', private_id)
                division.set_scalar(copied_division, 'DivisionCoalition', 0 if after['side'] == 'nato' else 1, kind='int32')
                tags = division.property(copied_division, 'DivisionTags')
                if tags is not None:
                    wire = copy.deepcopy(tags['value'])
                    for item in wire['items']:
                        if item.get('value') in {'NATO', 'PACT'}:
                            side_tag = 'NATO' if after['side'] == 'nato' else 'PACT'
                            item.update(index=division.string(side_tag), value=side_tag)
                    division.set_value(copied_division, 'DivisionTags', wire)
                division_name = hashlib.sha256((target + ':' + private_id + ':division-name').encode()).digest()[:8].hex()
                localized[division_name] = organization_label
                if after.get('localizedOrganization') is not None:
                    localized_translations[division_name] = after['localizedOrganization']
                elif after.get('localizedName') is not None:
                    localized_translations[division_name] = after['localizedName']
                division.set_scalar(copied_division, 'DivisionName', division_name, kind='loc_hash')
                import_index = max(deck.imports, default=-1) + 1
                deck.imports[import_index] = private_division
                private_division_imports[import_index] = private_division
                wire = deck.property(copied_deck, 'DeckDivision')['value'].copy()
                wire.update(index=import_index, value=private_division)
                deck.set_value(copied_deck, 'DeckDivision', wire)
                division_changes.append({'formation_id': after['id'], 'private_division': private_division,
                                         'template_division': template_division, 'cloned_objects': len(division_mapping)})
            identity = {'source': deck_identifier, 'target': private_id,
                        'formation_id': after['id'], 'new_formation': is_new,
                        'parent_formation_id': after.get('parentFormationId')}
            if identity['parent_formation_id'] is not None:
                order_name = hashlib.sha256((target + ':' + private_id + ':order-name').encode()).digest()[:8].hex()
                localized[order_name] = organization_label
                if after.get('localizedOrganization') is not None:
                    localized_translations[order_name] = after['localizedOrganization']
                elif after.get('localizedName') is not None:
                    localized_translations[order_name] = after['localizedName']
                identity['order_name_token'] = order_name
            deck_identifiers.append(identity)
            original_companies = {row['id']: row for row in before['companies']}
            if len({row['id'] for row in after['companies']}) != len(after['companies']):
                raise ValueError('Native company ids must be unique')
            if not original_companies or not after['companies']:
                raise ValueError('Native formation requires a company and an original deck template')
            prototype_company = next(iter(original_companies.values()))
            platoon_prototypes = [(company, platoon) for company in before['companies'] for platoon in company['platoons']]
            if not platoon_prototypes:
                raise ValueError('Native deck has no platoon template')
            slots, companies = [], []
            for company in after['companies']:
                old_company = original_companies.get(company['id'])
                template_company = old_company or prototype_company
                source_id = index['company', before['id'] + '/' + template_company['id']]
                if old_company is None:
                    copied_id, _ = deck.clone(source_id, keep_classes={'TDeckPackDescriptor'})
                    copied_company = deck.objects[copied_id]
                else:
                    copied_company = deck.objects[deck_mapping[source_id]]
                companies.append(deck.reference(copied_company['id']))
                rename(deck, copied_company, 'Name', company['name'], old_company['name'] if old_company else None, private_id + ':' + company['id'])
                deck.set_scalar(copied_company, 'IsHQ', company['isHeadquarters'], kind='bool')
                original_platoons = {row['id']: row for row in old_company['platoons']} if old_company else {}
                desired_platoons = company['platoons']
                if company['units']:
                    if desired_platoons or company['hasExplicitPlatoons']:
                        raise ValueError('Native company cannot mix direct units and explicit platoons')
                    desired_platoons = [{'id': company['id'] + '_platoon', 'name': company['name'],
                                         'isHeadquarters': company['isHeadquarters'], 'units': company['units']}]
                if len({row['id'] for row in desired_platoons}) != len(desired_platoons):
                    raise ValueError('Native platoon ids must be unique inside a company')
                platoons = []
                for platoon in desired_platoons:
                    old_platoon = original_platoons.get(platoon['id'])
                    if old_platoon is None:
                        pc, pp = platoon_prototypes[0]
                        source_id = index['platoon', before['id'] + '/' + pc['id'] + '/' + pp['id']]
                        copied_id, _ = deck.clone(source_id, keep_classes={'TDeckPackDescriptor'})
                        copied_platoon = deck.objects[copied_id]
                    else:
                        source_id = index['platoon', before['id'] + '/' + company['id'] + '/' + platoon['id']]
                        copied_platoon = deck.objects[deck_mapping[source_id]]
                    platoons.append(deck.reference(copied_platoon['id']))
                    rename(deck, copied_platoon, 'Name', platoon['name'], old_platoon['name'] if old_platoon else None,
                           private_id + ':' + company['id'] + ':' + platoon['id'])
                    deck.set_scalar(copied_platoon, 'IsHQ', platoon['isHeadquarters'], kind='bool')
                    ranges = []
                    for stack in platoon['units']:
                        pack_id = stack['strategicPackId']
                        match = re.fullmatch(r'native_pack_(\d+)', pack_id or '')
                        if match:
                            pack_index = int(match[1])
                            if not 0 <= pack_index < deck.original_count or deck.objects[pack_index]['class'] != 'TDeckPackDescriptor':
                                raise ValueError('Native roster references an unknown pack')
                        elif pack_id:
                            # StrategicPacks.ndf names are compiler locals, not
                            # native exports. Match the verified public catalog
                            # signature against the actual captured pack objects.
                            from .modgen import strategic_pack_signatures
                            signature = strategic_pack_signatures().get('Descriptor_StrategicPack_' + str(pack_id))
                            if signature is None:
                                raise ValueError('Unknown verified strategic pack: ' + str(pack_id))
                            expected_unit = signature['unit'] if signature['unit'].startswith('$/') else '$/GFX/Unit/' + signature['unit']
                            expected_transport = (signature['transport'] if signature['transport'].startswith('$/')
                                                  else '$/GFX/Unit/' + signature['transport']) if signature['transport'] else None
                            matches = [obj['id'] for obj in deck.objects[:deck.original_count]
                                       if obj['class'] == 'TDeckPackDescriptor'
                                       and _scalar(deck, obj, 'UnitDescriptor') == expected_unit
                                       and _scalar(deck, obj, 'TransporterDescriptor') == expected_transport
                                       and _scalar(deck, obj, 'ExperienceLevel', 0) == signature['experience']
                                       and _scalar(deck, obj, 'Number', 1) == signature['number']]
                            if not matches:
                                raise ValueError('Verified strategic pack is absent from captured native data: ' + str(pack_id))
                            pack_index = matches[0]
                        else:
                            pack_index = pack_for_tactical_unit(stack['unitId'])
                        pack = deck.objects[pack_index]
                        expected_unit = '$/GFX/Unit/Descriptor_Unit_' + stack['unitId']
                        if _scalar(deck, pack, 'UnitDescriptor') != expected_unit:
                            raise ValueError('Native pack does not match the declared tactical unit')
                        count = stack['count']
                        if type(count) is not int or not 1 <= count <= 100:
                            raise ValueError('Native roster counts must be integers in 1..100')
                        ranges.append({'type_id': 34, 'type': 'map', 'reference_prefix': False,
                                       'key': {'type_id': 3, 'type': 'uint32', 'reference_prefix': False, 'value': len(slots)},
                                       'value': {'type_id': 2, 'type': 'int32', 'reference_prefix': False, 'value': count}})
                        slots.extend(deck.reference(pack_index) for _ in range(count))
                    deck.set_value(copied_platoon, 'PackIndexUnitNumberList', deck.sequence(ranges))
                deck.set_value(copied_company, 'SmartGroupList', deck.sequence(platoons))
            if not slots:
                raise ValueError('Native formation must contain at least one tactical pack')
            deck.set_value(copied_deck, 'DeckPackList', deck.sequence(slots))
            deck.set_value(copied_deck, 'DeckCombatGroupList', deck.sequence(companies))
        if is_new:
            created[after['id']] = private_export
        else:
            replacements[source_export] = private_export
        reports.append({'source': source_export, 'target': private_export, 'pawn_objects': len(pawn_mapping), 'deck_changed': changed_deck,
                        'new_formation': is_new, 'formation_id': after['id']})
    new_pawn, new_deck = pawn.save(), deck.save()
    new_depiction = depiction.save() if depiction is not None and visual_changes else None
    new_division = division.save() if division is not None and division_changes else None
    checks = [(pawn_raw, new_pawn, {index: path for index, path in pawn.imports.items()
                                   if index not in pawn.original_imports}),
              (deck_raw, new_deck, {**private_unit_imports, **private_division_imports})]
    if new_depiction is not None:
        checks.append((depiction_raw, new_depiction, private_depiction_imports))
    if new_division is not None:
        checks.append((division_raw, new_division, {}))
    for original, changed, allowed_imports in checks:
        _, old = decode(original)
        _, new = decode(changed)
        if old['objects'] != new['objects'][:len(old['objects'])]:
            raise ValueError('Native roster build changed an original shared descriptor')
        if any(new['imports'].get(index) != path for index, path in old['imports'].items()):
            raise ValueError('Native roster build changed original shared import links')
        if {index: path for index, path in new['imports'].items() if index not in old['imports']} != allowed_imports:
            raise ValueError('Native roster build added an unexpected shared import')
    return {'pawn': new_pawn, 'deck': new_deck, 'replacements': replacements, 'localized': localized,
            'localized_translations': localized_translations,
            'deck_identifiers': deck_identifiers, 'created': created, 'report': reports,
            'depiction': new_depiction, 'visual_changes': visual_changes,
            'division': new_division, 'division_changes': division_changes}


def register_private_decks(components_raw, identities):
    if not identities:
        return components_raw
    editor = NativeGraphEditor(components_raw)
    roots = [obj for obj in editor.objects if obj['class'] == 'TStrategicBattleOrderResources']
    if len(roots) != 1:
        raise ValueError('Native battle-order registry is missing or ambiguous')
    root = roots[0]
    import copy
    mapping = copy.deepcopy(editor.property(root, 'DeckSuperiors')['value'])
    for identity in identities:
        matches = [pair for pair in mapping['items'] if pair['key'].get('value') == identity['source']]
        if len(matches) != 1 or any(pair['key'].get('value') == identity['target'] for pair in mapping['items']):
            raise ValueError('Native deck organization binding is missing, ambiguous or already used')
        new = copy.deepcopy(matches[0])
        new['key'].update(index=editor.string(identity['target']), value=identity['target'])
        mapping['items'].append(new)
    mapping['length'] = len(mapping['items'])
    editor.set_value(root, 'DeckSuperiors', mapping)
    result = editor.save()
    _, after = decode(result)
    actual = next(obj for obj in after['objects'] if obj['class'] == 'TStrategicBattleOrderResources')
    entries = next(prop['value']['items'] for prop in actual['properties'] if prop['property_name'] == 'DeckSuperiors')
    for identity in identities:
        old = next(pair['value'] for pair in entries if pair['key'].get('value') == identity['source'])
        new = next(pair['value'] for pair in entries if pair['key'].get('value') == identity['target'])
        if old != new:
            raise ValueError('Private native deck organization changed unexpectedly')
    return result


def register_private_battle_orders(components_raw, battle_order_raw, pawn_raw, identities, bindings):
    """Register private decks and optional map-command parents without editing stock nodes."""
    if not any(row.get('parent_formation_id') is not None for row in identities):
        return {'components': register_private_decks(components_raw, identities),
                'battle_order': None, 'report': []}
    components = NativeGraphEditor(components_raw)
    battle = NativeGraphEditor(battle_order_raw)
    pawn = NativeGraphEditor(pawn_raw)
    roots = [obj for obj in components.objects if obj['class'] == 'TStrategicBattleOrderResources']
    if len(roots) != 1:
        raise ValueError('Native battle-order registry is missing or ambiguous')
    root = roots[0]
    mapping = copy.deepcopy(components.property(root, 'DeckSuperiors')['value'])
    old_mapping = copy.deepcopy(mapping)
    binding_by_id = {row['id']: row for row in bindings if row['kind'] == 'battalion'}

    def order_for_deck(deck_identifier):
        matches = [pair['value'].get('value') for pair in old_mapping['items']
                   if pair['key'].get('value') == deck_identifier]
        if len(matches) != 1:
            raise ValueError('Native map-command organization is missing or ambiguous: ' + deck_identifier)
        return matches[0]

    def deck_for_formation(formation_id):
        binding = binding_by_id.get(formation_id)
        if binding is None or not binding.get('export'):
            raise ValueError('Native parent formation has no stock pawn binding')
        source = pawn.named(binding['export'])
        modules = [pawn.objects[item['object_id']] for item in
                   pawn.property(source, 'ModulesDescriptors')['value']['items']]
        deck_modules = [item for item in modules if item['class'] == 'TDeckModuleDescriptor']
        if len(deck_modules) != 1:
            raise ValueError('Native parent formation has no unique deck')
        return _scalar(pawn, deck_modules[0], 'DeckIdentifier')

    changes = []
    for identity in identities:
        matches = [pair for pair in old_mapping['items'] if pair['key'].get('value') == identity['source']]
        if len(matches) != 1 or any(pair['key'].get('value') == identity['target'] for pair in mapping['items']):
            raise ValueError('Native private deck organization binding is missing or duplicated')
        pair = copy.deepcopy(matches[0])
        pair['key'].update(index=components.string(identity['target']), value=identity['target'])
        parent_id = identity.get('parent_formation_id')
        if parent_id is not None:
            if not identity.get('new_formation') or 'order_name_token' not in identity:
                raise ValueError('Only a new private formation can select a map-command parent')
            original_path = order_for_deck(identity['source'])
            source_order = battle.named(original_path)
            parent_path = order_for_deck(deck_for_formation(parent_id))
            parent = battle.named(parent_path)
            private_path = '$/UI/BattleOrder/' + identity['target'] + '_Subordination'
            created = battle.add('TBattleOrderSubordination', export=private_path)
            created['properties'] = copy.deepcopy(source_order['properties'])
            battle.set_scalar(created, 'NameToken', identity['order_name_token'], kind='loc_hash')
            battle.set_value(created, 'Superior', battle.reference(parent['id']))
            index = max(components.imports, default=-1) + 1
            components.imports[index] = private_path
            pair['value'].update(index=index, value=private_path)
            changes.append({'formation_id': identity['formation_id'], 'parent_formation_id': parent_id,
                            'private_order': private_path, 'parent_order': parent_path})
        mapping['items'].append(pair)
    mapping['length'] = len(mapping['items'])
    components.set_value(root, 'DeckSuperiors', mapping)
    new_components, new_battle = components.save(), battle.save()
    _, old_battle = decode(battle_order_raw)
    _, written_battle = decode(new_battle)
    if (old_battle['objects'] != written_battle['objects'][:len(old_battle['objects'])]
            or old_battle['imports'] != {index: written_battle['imports'].get(index) for index in old_battle['imports']}
            or old_battle['exports'] != {index: written_battle['exports'].get(index) for index in old_battle['exports']}):
        raise ValueError('Private native battle order changed an original node')
    _, old_components = decode(components_raw)
    _, written_components = decode(new_components)
    if (old_components['exports'] != written_components['exports']
            or old_components['imports'] != {index: written_components['imports'].get(index) for index in old_components['imports']}):
        raise ValueError('Private native deck mapping changed original imports or exports')
    written_root = written_components['objects'][root['id']]
    written_mapping = next(prop['value'] for prop in written_root['properties'] if prop['property_name'] == 'DeckSuperiors')
    if written_mapping['items'][:len(old_mapping['items'])] != old_mapping['items']:
        raise ValueError('Private native deck mapping changed an original organization binding')
    return {'components': new_components, 'battle_order': new_battle, 'report': changes}
