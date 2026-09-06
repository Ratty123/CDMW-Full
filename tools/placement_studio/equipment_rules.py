"""Installed shrink and alignment settings, distinct from preview simulation."""
from dataclasses import dataclass
import math
from xml.etree import ElementTree as ET

SHRINK_PATH = 'character/descriptors/partshrinkdesc.xml'
RETARGET_PATH = 'character/descriptors/animationretargetting/animationretargettingdefaultdata.xml'
ANALYSIS_FILES = (SHRINK_PATH, RETARGET_PATH)


@dataclass(frozen=True)
class ShrinkRules:
    biases: tuple
    socket_tags: tuple
    receivers: tuple

    def setting(self, tag, socket):
        tag = dict(self.socket_tags).get(socket, tag)
        if tag == 'Zero':
            return tag, 0., False, ()
        bias, custom = dict(self.biases).get(tag, (None, None))
        return tag, bias, custom, dict(self.receivers).get(tag, ())


def shrink_rules(data):
    # This descriptor is an XML fragment with several top-level elements.
    text = data.decode('utf-8-sig').strip()
    if text.startswith('<?xml'):
        text = text[text.index('?>') + 2:]
    try:
        root = ET.fromstring('<Rules>' + text + '</Rules>')
    except ET.ParseError as error:
        raise ValueError(f'Invalid shrink descriptor: {error}') from error
    biases = []
    for row in root.findall('./GlobalSetting/ShrinkDepthBias/*'):
        value = float(row.attrib['Value'])
        if not math.isfinite(value) or value < 0:
            raise ValueError('Invalid shrink depth bias')
        biases.append((row.tag, (value, row.get('UseCustomVolume', 'False').lower() == 'true')))
    sockets = tuple((r.tag, r.attrib['toTag']) for r in root.findall('./GlobalSetting/SocketToShrinkTag/*'))
    receivers = tuple((r.attrib['Name'], tuple(c.text.strip() for c in r.findall('Shrink') if c.text))
                      for r in root.findall('./Shrink/ShrinkTag'))
    return ShrinkRules(tuple(biases), sockets, receivers)


def alignment_bones(data):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError(f'Invalid alignment descriptor: {error}') from error
    mapping = root.find("BoneMapping[@Name='InterimToGame']")
    bones = root.find("BoneNameList[@Name='BonesForAlignment']")
    if mapping is None or bones is None:
        raise ValueError('Missing explicit alignment mapping')
    names = {r.attrib['InterimBone']: r.attrib['MappedBone'] for r in mapping}
    if len(names) != len(mapping):
        raise ValueError('Duplicate alignment mapping')
    return tuple(names[r.attrib['Name']] for r in bones)
