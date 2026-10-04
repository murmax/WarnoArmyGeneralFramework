"""WARNO localization token keys, verified against the official asset cooker.

The cooker encodes at most ten characters as nonzero base-64 digits. The
resulting integer is stored little-endian in .dic localization resources.
"""
import hashlib


ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz'
DIGITS = {character: index + 1 for index, character in enumerate(ALPHABET)}


def label_token_key(token):
    if not isinstance(token, str) or not 1 <= len(token) <= 10 or any(char not in DIGITS for char in token):
        raise ValueError('WARNO label token must contain 1..10 supported ASCII characters')
    value = 0
    for character in token:
        value = value * 64 + DIGITS[character]
    return value.to_bytes(8, 'little').hex()


def private_label_token(target_scenario, feature_guid):
    """Allocate a stable ten-character token for one private campaign label."""
    if not target_scenario or not feature_guid:
        raise ValueError('Private label requires campaign and feature identity')
    digest = hashlib.sha256((target_scenario + ':label:' + feature_guid).encode('utf-8')).digest()
    value = int.from_bytes(digest[:8], 'little') % (63 ** 7)
    suffix = []
    for unused in range(7):
        value, digit = divmod(value, 63)
        suffix.append(ALPHABET[digit])
    return 'AGF' + ''.join(reversed(suffix))
