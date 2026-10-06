"""Conservative pass-through ownership of unchanged template collision/cloth."""
import xml.etree.ElementTree as ET
import re

from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.services.new_item_variants import xml_path


def _material_binding(data):
    # Render materials can change (for example glove emission). Everything
    # outside their Material blocks, including cloth assignments, must survive.
    if len(data) > 4 * 1024 * 1024:
        raise ValueError('The model property file exceeds the physics audit limit.')
    text = data.decode('utf-8-sig')
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.I):
        raise ValueError('Unsupported XML declaration.')
    root = ET.fromstring('<Model>' + text + '</Model>')
    pending, count = [(root, 0, False)], 0
    while pending:
        node, depth, material = pending.pop()
        count += 1
        if depth > 64 or count > 32768:
            raise ValueError('The model property file exceeds the physics audit limit.')
        material = material or node.tag == 'Material'
        if material and any(re.search('physics|pbd|jiggle|cloth', key, re.I) for key in node.attrib):
            raise ValueError('Physics settings inside a render material are unverified.')
        pending.extend((child, depth + 1, material) for child in node)

    def value(node):
        return (node.tag, tuple(sorted(node.attrib.items())), (node.text or '').strip(), (node.tail or '').strip(),
                tuple(value(child) for child in node if child.tag != 'Material'))
    return value(root)


def audit_physics_copy(path, data, outputs, mesh_bindings, snapshot, require, *, stop_event=None):
    """Keep the original physics graph together; never apply it to a new mesh."""
    from cdmw.core.archive_hkx_copy import validate_hkx_copy_source
    from cdmw.models import PbdProfileContext
    from cdmw.services.mesh_physics_profiles import _capture_document, _resolve_documents

    prefix = 'character/bin__/meshphysics/'
    if not path.startswith(prefix):
        raise IndependentItemError('Owned physics must accompany its exact model path.')
    model = 'character/model/' + path[len(prefix):-4] + '.pac'
    bindings = mesh_bindings.get(model, ())
    originals = {source for source, _prefab in bindings}
    if len(originals) != 1 or model not in outputs:
        raise IndependentItemError('Owned physics has no unambiguous template mesh binding.')
    source = originals.pop()
    physics = source.replace('character/model/', prefix, 1).removesuffix('.pac') + '.hkx'
    require(physics)
    if data != snapshot.payload(physics):
        raise IndependentItemError('Independent packages can only copy unchanged template physics.')
    if outputs[model] != snapshot.payload(source):
        raise IndependentItemError('Copied template physics requires unchanged mesh geometry and skin/cloth bindings. Disable template physics for a replacement model.')
    try:
        validate_hkx_copy_source(data)
        old_xml, new_xml = xml_path(source), xml_path(model)
        if new_xml not in outputs or _material_binding(outputs[new_xml]) != _material_binding(snapshot.payload(old_xml)):
            raise ValueError('Copied template physics requires unchanged cloth and model-property bindings.')
        budget = [16 * 1024 * 1024]

        def load_document(resource):
            resource = resource.lower()
            require(resource)
            return _capture_document(snapshot.entry(resource), snapshot.payload(resource), budget, stop_event)

        context = _resolve_documents(PbdProfileContext(snapshot.entry(source).identity), load_document, stop_event)
        problem = context.problem or next((binding.problem for binding in context.bindings if binding.problem), '')
        if problem:
            raise ValueError('The template cloth dependency could not be verified: ' + problem)
    except (UnicodeError, ET.ParseError, ValueError) as exc:
        raise IndependentItemError(f'{path}: {exc}') from exc
