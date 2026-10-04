"""Compact release scripts; verify remapping against the authored reference."""
from pathlib import Path

from .cndf import decode
from .script_compaction import compact_script, verify_compaction


def script_root(graph):
    matches = [index for index, path in graph['exports'].items()
               if path == '$/GDScript/RootDescriptor']
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous exported script root')
    return matches[0]


def release_roots(graph):
    databases = [obj for obj in graph['objects']
                 if obj['class'] == 'TCutsceneDescriptorDatabase']
    if len(databases) != 1 or not databases[0]['is_top_object']:
        raise ValueError('Release script requires one top-level cutscene database')
    lists = [prop['value'] for prop in databases[0]['properties']
             if prop['property_name'] == 'CutsceneDescriptorList']
    if len(lists) != 1 or lists[0].get('items') != [] or lists[0].get('length') != 0:
        raise ValueError('Authored cutscene database must not retain stock cinematics')
    return [script_root(graph), databases[0]['id']] + [
        obj['id'] for obj in graph['objects'] if obj['class'].startswith('TGDTag')]


def release_script(raw):
    _, graph = decode(raw)
    return compact_script(raw, release_roots(graph))


def validate_pawn_imports(graph, pawns):
    required = {path for path in graph['imports'].values() if path.startswith('$/GFX/Pawn/')}
    missing = required - set(pawns['exports'].values())
    if missing:
        raise ValueError('Unresolved script Pawn import: ' + sorted(missing)[0])
    return {'resolved_pawn_imports': len(required)}


def verify_release_script(raw, compiled):
    from .bruderkrieg import build_authored_definition, _payloads
    _, target = decode(raw)
    if set(target['imports']) != set(range(len(target['imports']))):
        raise ValueError('Compaction changed reference tables or non-dense import indices')
    release_roots(target)
    localisation = (Path(__file__).resolve().parents[1]
                    / 'artifacts/full-campaign-work/RedLine1989-v12/Gen/Localisation/Localisation')
    reference_definition, _ = build_authored_definition(compiled, localisation)
    reference = next(value for name, value in _payloads(reference_definition).items()
                     if '/GDScript/' in name and name.endswith('.ndfbin'))
    _, source = decode(reference)
    roots = release_roots(source)
    _, expected = compact_script(reference, roots)
    report = verify_compaction(reference, raw, roots, expected['object_map'])
    return reference, report
