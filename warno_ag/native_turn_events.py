"""Pinned source chains for a small, safe native turn-dialog creation adapter."""

from .native_frozen import SOURCE_ADAPTERS


TURN_EVENT_ADAPTERS = {
    'CampagneStrat_Highway': {
        'sha256': SOURCE_ADAPTERS['CampagneStrat_Highway']['sha256'],
        'turn_variable': 305,
        'sides': {
            'nato': {
                'parent': 353, 'source_actions': list(range(724, 732)),
                'template': 724, 'compare': 1334, 'text': 1335, 'camp': 240,
                'variable': 1202, 'player': 1203,
                'speaker': 'major_US',
                'subtree': [724, 949, 1076, 1202, 1334, 1203, 950, 1077, 1204, 1335],
            },
            'pact': {
                'parent': 350, 'source_actions': list(range(709, 721)),
                'template': 709, 'compare': 1311, 'text': 1312, 'camp': 241,
                'variable': 1156, 'player': 1157,
                'speaker': 'major_SOV',
                'subtree': [709, 918, 1047, 1156, 1311, 1157, 919, 1048, 1158, 1312],
            },
        },
    },
    'CampagneStrat_FuldaGap': {
        'sha256': SOURCE_ADAPTERS['CampagneStrat_FuldaGap']['sha256'],
        'turn_variable': 393,
        'sides': {
            'nato': {
                'parent': 306, 'source_action_count': 11,
                'template': 708, 'compare': 1279, 'text': 1280, 'camp': 282,
                'variable': 1190, 'player': 1191,
                'speaker': 'major_US',
                'subtree': [708, 880, 1038, 1190, 1279, 1191, 881, 1039, 1192, 1280],
            },
            'pact': {
                'parent': 306, 'source_action_count': 11,
                'template': 708, 'compare': 1279, 'text': 1280, 'camp': 283,
                'variable': 1190, 'player': 1191,
                'speaker': 'major_SOV',
                'subtree': [708, 880, 1038, 1190, 1279, 1191, 881, 1039, 1192, 1280],
            },
        },
    },
    'CampagneStrat_Airborne': {
        'sha256': '9162e80687c2ed9b901f1bbc964c2e8e03cf4f30e93a50c037b8c8cc5ac68104',
        'turn_variable': 335,
        'sides': {
            'nato': {
                'parent': 329, 'source_actions': list(range(338, 347)),
                'template': 629, 'compare': 1074, 'text': 1075, 'camp': 267,
                'variable': 1022, 'player': 1021,
                'condition_order': ['player', 'variable'],
                'speaker': 'major_RFA',
                'subtree': [629, 792, 932, 1021, 1022, 1074, 793, 933, 1023, 1075],
            },
            'pact': {
                'parent': 329, 'source_actions': list(range(338, 347)),
                'template': 629, 'compare': 1074, 'text': 1075, 'camp': 268,
                'variable': 1022, 'player': 1021,
                'condition_order': ['player', 'variable'],
                'speaker': 'major_SOV',
                'subtree': [629, 792, 932, 1021, 1022, 1074, 793, 933, 1023, 1075],
            },
        },
    },
    'CampagneStrat_Baor': {
        'sha256': 'f58c2dea42f1a78aec4dda051acd7e372bede1b18d685f2c27e80a7914c2e894',
        'turn_variable': 390,
        'sides': {
            'nato': {
                'parent': 238, 'source_actions': list(range(393, 401)),
                'template': 519, 'compare': 899, 'text': 900, 'camp': 190,
                'variable': 790, 'player': 791,
                'speaker': 'major_UK',
                'subtree': [519, 604, 687, 790, 899, 791, 605, 688, 792, 900],
            },
            'pact': {
                'parent': 238, 'source_actions': list(range(393, 401)),
                'template': 537, 'compare': 938, 'text': 939, 'camp': 191,
                'variable': 846, 'player': 847,
                'speaker': 'major_SOV',
                'subtree': [537, 636, 717, 846, 938, 847, 637, 718, 848, 939],
            },
        },
    },
    'CampagneStrat_Bruderkrieg': {
        'sha256': '3892070a2757f3e4b1457e32e3554374bd8e6bb2954e90c300b8624099d3d223',
        'turn_variable': 381,
        'sides': {
            'nato': {
                'synthetic': True,
                'parent': 353, 'source_actions': list(range(384, 392)),
                'template': 302, 'compare': 662, 'text': 693, 'camp': 284,
                'variable': 570, 'player': 620,
                'speaker': 'major_RFA',
                'subtree': [302, 489, 566, 570, 662, 620, 447, 314, 592, 693],
            },
            'pact': {
                'synthetic': True,
                'parent': 353, 'source_actions': list(range(384, 392)),
                'template': 302, 'compare': 662, 'text': 692, 'camp': 283,
                'variable': 570, 'player': 620,
                'speaker': 'major_DDR',
                'subtree': [302, 489, 566, 570, 662, 620, 447, 314, 591, 692],
            },
        },
    },
    'CampagneStrat_ClosingTheTrap': {
        'sha256': 'ec8e8db24ec58b6cf7942fcfe08669a8ed43815970578a8356abaa9b33e29d90',
        'turn_variable': 259,
        'max_rule': 'Nb_Tour_Max',
        'sides': {
            'nato': {
                'synthetic': True, 'parent': 207,
                'source_actions': list(range(260, 265)),
                'template': 171, 'compare': 695, 'text': 457,
                'secondary_text': 458, 'texture': 459,
                'camp': 167, 'variable': 450, 'player': 698,
                'speaker': 'Steelman_LDHint_Portrait', 'portrait': 'general_nato',
                'subtree': [171, 408, 442, 450, 695, 698, 185, 200,
                            419, 457, 458, 459],
            },
            'pact': {
                'synthetic': True, 'parent': 207,
                'source_actions': list(range(260, 265)),
                'template': 171, 'compare': 695, 'text': 475,
                'secondary_text': 476, 'texture': 477,
                'camp': 168, 'variable': 450, 'player': 698,
                'speaker': 'Steelman_LDHint_Portrait', 'portrait': 'general_pact',
                'subtree': [171, 408, 442, 450, 695, 698, 185, 200,
                            425, 475, 476, 477],
            },
        },
    },
    'CampagneStrat_HoldingAttack': {
        'sha256': '9d0e6e18956528a9043701d515eef1b244f681267ad38feb564397705c0649f8',
        'turn_variable': 227,
        'max_rule': 'Nb_Tour_Max',
        'sides': {
            'nato': {
                'synthetic': True, 'parent': 189,
                'source_actions': list(range(220, 225)),
                'template': 146, 'compare': 294, 'text': 334,
                'secondary_text': 335, 'texture': 336,
                'camp': 142, 'variable': 369, 'player': 649,
                'speaker': 'Steelman_LDHint_Portrait', 'portrait': 'general_rfa',
                'subtree': [146, 316, 359, 369, 294, 649, 155, 163,
                            301, 334, 335, 336],
            },
            'pact': {
                'synthetic': True, 'parent': 189,
                'source_actions': list(range(220, 225)),
                'template': 146, 'compare': 294, 'text': 350,
                'secondary_text': 351, 'texture': 352,
                'camp': 143, 'variable': 369, 'player': 649,
                'speaker': 'Steelman_LDHint_Portrait', 'portrait': 'general_cz',
                'subtree': [146, 316, 359, 369, 294, 649, 155, 163,
                            313, 350, 351, 352],
            },
        },
    },
    'CampagneStrat_Hanovre': {
        'sha256': 'c58e22d1b93e19dccad0c59227eec370594f9b95d88046dd9a28b025dd9396b8',
        'turn_variable': 261,
        'sides': {
            'nato': {
                'synthetic': True, 'parent': 235,
                'source_actions': list(range(243, 256)),
                'template': 225, 'compare': 1643, 'text': 1103,
                'secondary_text': 1104, 'texture': 1105,
                'camp': 223, 'variable': 445, 'player': 869,
                'speaker': 'Steelman_LDHint_Portrait', 'portrait': 'major_uk',
                'subtree': [225, 504, 322, 445, 1643, 869, 238, 260,
                            870, 1103, 1104, 1105],
            },
            'pact': {
                'synthetic': True, 'parent': 235,
                'source_actions': list(range(243, 256)),
                'template': 225, 'compare': 1643, 'text': 1135,
                'secondary_text': 1136, 'texture': 1137,
                'camp': 224, 'variable': 445, 'player': 869,
                'speaker': 'Steelman_LDHint_Portrait', 'portrait': 'major_sov',
                'subtree': [225, 504, 322, 445, 1643, 869, 238, 260,
                            915, 1135, 1136, 1137],
            },
        },
    },
    'CampagneStrat_Luneburg': {
        'sha256': '9406997355b250d497aba0265c8a3e4c120b04e7cb7ac9f709223c4664e495af',
        'turn_variable': 486,
        'sides': {
            'nato': {
                'synthetic': True, 'parent': 337,
                'source_actions': list(range(381, 390)),
                'template': 317, 'compare': 1288, 'text': 1243,
                'secondary_text': 1244, 'texture': 1245,
                'camp': 315, 'variable': 598, 'player': 971,
                'speaker': 'Steelman_LDHint_Portrait', 'portrait': 'major_nl',
                'subtree': [317, 617, 506, 598, 1288, 971, 325, 371,
                            972, 1243, 1244, 1245],
            },
            'pact': {
                'synthetic': True, 'parent': 337,
                'source_actions': list(range(381, 390)),
                'template': 317, 'compare': 1288, 'text': 1289,
                'secondary_text': 1290, 'texture': 1291,
                'camp': 316, 'variable': 598, 'player': 971,
                'speaker': 'Steelman_LDHint_Portrait', 'portrait': 'major_ddr',
                'subtree': [317, 617, 506, 598, 1288, 971, 325, 371,
                            1040, 1289, 1290, 1291],
            },
        },
    },
}


def property_wire(obj, name):
    matches = [prop['value'] for prop in obj['properties'] if prop['property_name'] == name]
    return matches[0] if len(matches) == 1 else None


def source_dialog_turns(graph, turn_variable, camp_object, rule_values=None):
    """Conservatively reserve turns used by source player-side wait conditions."""
    objects = graph['objects']
    occupied = set()
    for wait in objects:
        if wait['class'] != 'TGDDescriptorWaitCondition':
            continue
        condition_ref = property_wire(wait, 'Condition')
        if condition_ref is None or condition_ref.get('type') != 'obj_ref':
            continue
        condition = objects[condition_ref['object_id']]
        sub = property_wire(condition, 'SousConditions')
        if condition['class'] != 'TGDConditionAnd' or sub is None or sub['type'] != 'list':
            continue
        parts = [objects[item['object_id']] for item in sub['items']
                 if item.get('type') == 'obj_ref' and item['object_id'] < len(objects)]
        player = [part for part in parts if part['class'] == 'TGDConditionStrategicIsPlayerTurn'
                  and (camp := property_wire(part, 'Camp')) is not None
                  and camp.get('object_id') == camp_object]
        if not player:
            continue
        for part in parts:
            if part['class'] != 'TGDConditionVariable':
                continue
            variable = property_wire(part, 'Variable')
            operator_ref = property_wire(part, 'Operator')
            if (variable is None or variable.get('object_id') != turn_variable
                    or operator_ref is None or operator_ref.get('type') != 'obj_ref'):
                continue
            operator = objects[operator_ref['object_id']]
            if operator['class'] != 'TGDOperatorIntegerCompare':
                continue
            immediate = property_wire(operator, 'Value')
            linked = property_wire(operator, 'Variable')
            if immediate is not None:
                turn = immediate.get('value')
            elif linked is not None and linked.get('type') == 'obj_ref':
                reference = linked['object_id']
                fallback = property_wire(objects[reference], 'Value')
                turn = (rule_values or {}).get(reference,
                    fallback.get('value') if fallback is not None else None)
            else:
                turn = None
            if type(turn) is int and turn > 0:
                occupied.add(turn)
    return occupied
