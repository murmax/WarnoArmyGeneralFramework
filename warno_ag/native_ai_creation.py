"""Pinned startup AI-order shapes shared by compiler and candidate verifier."""

from .native_frozen import SOURCE_ADAPTERS


AI_CREATION_ADAPTERS = {
    'CampagneStrat_Highway': {
        'sha256': SOURCE_ADAPTERS['CampagneStrat_Highway']['sha256'],
        'parent': 352, 'parent_export': None,
        'attack': 948, 'defend': 1262,
        'source_actions': [723],
    },
    'CampagneStrat_FuldaGap': {
        'sha256': SOURCE_ADAPTERS['CampagneStrat_FuldaGap']['sha256'],
        'parent': 306, 'parent_export': SOURCE_ADAPTERS['CampagneStrat_FuldaGap']['content'],
        'attack': 810, 'defend': 999,
        'source_action_count': 11,
    },
    'CampagneStrat_Hanovre': {
        'sha256': SOURCE_ADAPTERS['CampagneStrat_Hanovre']['sha256'],
        'parent': 235, 'parent_export': SOURCE_ADAPTERS['CampagneStrat_Hanovre']['content'],
        'attack': 1536, 'defend': 1264,
        'source_action_count': 13,
    },
    'CampagneStrat_Luneburg': {
        'sha256': SOURCE_ADAPTERS['CampagneStrat_Luneburg']['sha256'],
        'parent': 337, 'parent_export': SOURCE_ADAPTERS['CampagneStrat_Luneburg']['content'],
        'attack': 882, 'defend': 1104,
        'source_action_count': 9,
    },
    'CampagneStrat_Airborne': {
        'sha256': '9162e80687c2ed9b901f1bbc964c2e8e03cf4f30e93a50c037b8c8cc5ac68104',
        'parent': 329,
        'parent_export': '$/GDScript/partie_1/Script/Launch_Main_Script_Sequence',
        'attack': 574, 'defend': 434,
        'source_actions': list(range(338, 347)),
    },
    'CampagneStrat_Baor': {
        'sha256': 'f58c2dea42f1a78aec4dda051acd7e372bede1b18d685f2c27e80a7914c2e894',
        'parent': 238,
        'parent_export': '$/GDScript/partie_1/Script/Launch_Main_Script_Sequence',
        'attack': 673, 'defend': 919,
        'source_actions': list(range(393, 401)),
    },
    'CampagneStrat_Bruderkrieg': {
        'sha256': '3892070a2757f3e4b1457e32e3554374bd8e6bb2954e90c300b8624099d3d223',
        'parent': 353,
        'parent_export': '$/GDScript/partie_OTAN/Script/Launch_Main_Script_Sequence',
        'attack': None, 'defend': 537,
        'source_actions': list(range(384, 392)),
    },
    'CampagneStrat_ClosingTheTrap': {
        'sha256': 'ec8e8db24ec58b6cf7942fcfe08669a8ed43815970578a8356abaa9b33e29d90',
        'parent': 207, 'parent_export': None,
        'attack': 689, 'defend': 567,
        'source_actions': list(range(260, 265)),
    },
    'CampagneStrat_HoldingAttack': {
        'sha256': '9d0e6e18956528a9043701d515eef1b244f681267ad38feb564397705c0649f8',
        'parent': 189, 'parent_export': None,
        'attack': 931, 'defend': 796,
        'source_actions': list(range(220, 225)),
    },
}


def source_order_tag_ids(graph):
    """Tags already consumed by a source strategic move/defence order."""
    objects = graph['objects']
    groups = set()
    for obj in objects:
        if obj['class'] not in {'TGDDescriptorStrategicMoveAndAttack',
                                'TGDDescriptorStrategicDefend'}:
            continue
        group = [prop['value'] for prop in obj['properties'] if prop['property_name'] == 'Group']
        if len(group) == 1 and group[0]['type'] == 'obj_ref':
            groups.add(group[0]['object_id'])
    result = set()
    for obj in objects:
        if obj['class'] != 'TGDDescriptorAddUnitGroupListToUnitGroup':
            continue
        props = {prop['property_name']: prop['value'] for prop in obj['properties']}
        dest = props.get('GroupDestination')
        sources = props.get('ListGroupSource')
        if (dest is None or dest['type'] != 'obj_ref' or dest['object_id'] not in groups
                or sources is None or sources['type'] != 'list'):
            continue
        for item in sources['items']:
            index = item.get('object_id') if item.get('type') == 'obj_ref' else None
            if (index is not None and 0 <= index < len(objects)
                    and objects[index]['class'] == 'TGDTagUnitGroup'):
                result.add(index)
    return result
