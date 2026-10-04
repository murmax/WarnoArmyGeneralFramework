"""Public campaign briefing and ending-slide schema."""
from __future__ import annotations

import copy
import math


END_VARIANTS = {
    'result': ('victory', 'stagnation', 'defeat'),
    'sevastopol': ('taken', 'surrounded', 'held'),
    'invasion': ('lost', 'beachhead', 'breakthrough'),
}


def compile_cinematics(document, event_images):
    if document is None:
        return None
    if (not isinstance(document, dict) or not {'schema', 'intro', 'endings'} <= set(document)
            or set(document) - {'schema', 'intro', 'endings', 'start_camera', 'layout', 'layout_version', 'encirclement_flags'}
            or document['schema'] != 1):
        raise ValueError('cinematics.yaml must define schema, intro and endings')

    def slide(value, where):
        if (not isinstance(value, dict)
                or not {'title', 'text', 'image'} <= set(value)
                or set(value) - {'title', 'text', 'image', 'voice_script'}):
            raise ValueError(where + ' must define title, text and image')
        result = copy.deepcopy(value)
        for field in ('title', 'text', 'voice_script'):
            if field not in result:
                continue
            translation = result[field]
            if (not isinstance(translation, dict) or set(translation) != {'ru', 'en'}
                    or any(not isinstance(item, str) or not item.strip()
                           for item in translation.values())):
                raise ValueError(where + '.' + field + ' needs RU/EN text')
        if result['image'] not in event_images:
            raise ValueError(where + '.image is missing from the event image catalog')
        result['adapter_image'] = event_images[result['image']]
        return result

    if (not isinstance(document['intro'], dict)
            or not isinstance(document['endings'], dict)
            or set(document['intro']) != {'nato', 'pact'}
            or set(document['endings']) != {'nato', 'pact'}):
        raise ValueError('Cinematics require NATO and PACT variants')
    intro, endings = {}, {}
    for side in ('nato', 'pact'):
        source = document['intro'][side]
        if not isinstance(source, list) or len(source) != 4:
            raise ValueError('Each side needs exactly four introduction slides')
        intro[side] = [slide(value, f'intro.{side}[{index}]')
                       for index, value in enumerate(source)]
        side_ending = document['endings'][side]
        if not isinstance(side_ending, dict) or set(side_ending) != set(END_VARIANTS):
            raise ValueError('Endings require result, Sevastopol and invasion axes')
        endings[side] = {}
        for axis, variants in END_VARIANTS.items():
            choices = side_ending[axis]
            if not isinstance(choices, dict) or set(choices) != set(variants):
                raise ValueError(f'Ending {side}.{axis} has missing variants')
            endings[side][axis] = {
                variant: slide(choices[variant], f'endings.{side}.{axis}.{variant}')
                for variant in variants}
    result = {'intro': intro, 'endings': endings}
    if 'layout' in document:
        if document['layout'] != 'briefing':
            raise ValueError('Unknown cinematic layout')
        result['layout'] = 'briefing'
    if 'encirclement_flags' in document:
        flags = document['encirclement_flags']
        if not isinstance(flags, list) or not flags or any(not isinstance(x, str) for x in flags) or len(flags) != len(set(flags)):
            raise ValueError('Encirclement needs distinct objective ids')
        result['encirclement_flags'] = list(flags)
    if 'start_camera' in document:
        camera = document['start_camera']
        if (not isinstance(camera, dict) or not {'focus','altitude'}<=set(camera) or set(camera)-{'focus','altitude','north_up'}
                or not isinstance(camera['focus'], str) or not camera['focus']
                or type(camera['altitude']) not in (int, float)
                or not math.isfinite(camera['altitude'])
                or not 100000 <= camera['altitude'] <= 2000000):
            raise ValueError('start_camera needs an objective focus and a finite overview altitude')
        result['start_camera'] = copy.deepcopy(camera)
    if 'layout_version' in document:
        if document['layout_version'] not in (1,2):raise ValueError('Unknown briefing layout version')
        result['layout_version']=document['layout_version']
    return result
