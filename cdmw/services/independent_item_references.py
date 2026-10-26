"""Verified reference boundaries for resources an independent item adds.

Unchanged game resources remain dependencies. Physics copies require an unchanged
verified template binding; partially decoded reflection objects remain unsupported.
"""
import xml.etree.ElementTree as ET
import struct
from dataclasses import dataclass
from hashlib import sha256

from cdmw.domain.new_item.effect_authoring import split_effect_reference
from cdmw.domain.new_item.independent import IndependentItemError


# Diagnostics must not turn a bounded source walk into an unbounded edge graph.
# Overflow makes the report partial while the original audit continues in full.
MAX_ASSESSMENT_EDGES = 16384


@dataclass(frozen=True, slots=True)
class ReferenceEdge:
    source: str
    target: str
    role: str
    evidence: str


@dataclass(frozen=True, slots=True)
class ResourceOwnership:
    symbol: str
    path: str
    ownership: str
    reachability: tuple[str, ...]
    source_paths: tuple[str, ...]
    source_evidence: tuple[str, ...]
    layout: str
    byte_size: int
    sha256: str
    outgoing_references: tuple[str, ...]
    lifetime: str


@dataclass(frozen=True, slots=True)
class ReferenceAssessment:
    """A compiler resource graph, never proof of native lookup or detachment.

    Contribution reachability starts at compiled additions and decoded added
    PAPPT records. Authoring reachability starts at the retained template and
    physics-validation inputs. These roles do not relax source requirements.
    """

    resources: tuple[ResourceOwnership, ...]
    edges: tuple[ReferenceEdge, ...]
    unresolved: tuple[str, ...]
    reference_closure_complete: bool
    graph_complete: bool


def rename_effect_references(data, renames):
    """Rename complete reflected values and declared header strings only."""
    from cdmw.core.effect_binary import decode_effect_binary, write_value, KIND_STRING
    document = decode_effect_binary(data)
    if not document.walk_complete:
        raise IndependentItemError('The effect reference graph did not decode completely.')
    prefixes = (
        ('emitter/', ('',)),
        ('/effect/binary__/emitter/', ('', '.paem')),
        ('effect/binary__/emitter/', ('', '.paem')),
        ('fx/materialfx/', ('',)),
        ('effect/binary__/releasebin/', ('', '.pae')),
    )
    def changed(text):
        for old, new in renames.items():
            if len(old.encode()) != len(new.encode()):
                raise IndependentItemError('An effect reference requires a fixed-length name.')
            for prefix, suffixes in prefixes:
                for suffix in suffixes:
                    if text == prefix + old + suffix:
                        return prefix + new + suffix
        return text
    output = bytes(data)
    for value in document.root.all_values():
        if value.kind == KIND_STRING:
            before = str(value.value)
            after = changed(before)
            if after != before:
                output = write_value(output, value, after.encode('utf-8'))
    # Reflection type names and the string pool use declared length-prefixed
    # strings before blob_offset. Check every occurrence against that inventory.
    header_strings = [row.type_name for row in document.types] + list(document.string_pool)
    for before in dict.fromkeys(header_strings):
        after = changed(before)
        if after == before:
            continue
        token = before.encode('utf-8')
        needle = struct.pack('<I', len(token)) + token
        header = data[document.container_offset:document.blob_offset]
        positions, start = [], 0
        while (found := header.find(needle, start)) >= 0:
            positions.append(document.container_offset + found + 4)
            start = found + len(needle)
        if len(positions) != header_strings.count(before):
            raise IndependentItemError('An effect type-name boundary is ambiguous.')
        for offset in positions:
            output = output[:offset] + after.encode('utf-8') + output[offset + len(token):]
    if not decode_effect_binary(output).walk_complete:
        raise IndependentItemError('The renamed effect failed its structural check.')
    return output


def audit_references(plan, snapshot, *, stop_event=None):
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.services.independent_item_package import virtual_path
    outputs = {request.path.lower(): bytes(request.payload_data) for request in plan.additions}
    pending, visited = dict(outputs), set()
    reference_closure_complete = True
    edges, metadata, source_paths = set(), {}, {}
    graph_complete = True
    unresolved = {
        'Engine lookup aliases, caches, and resource lifetimes are not proven by compiler reference traversal.',
        'Final ItemInfo-to-resource reachability is not decoded here; template roots are not proven authoring-only.',
        'ItemInfo and auxiliary registry references remain covered by their existing source guards.',
    }

    def record_edge(edge):
        nonlocal graph_complete
        if edge in edges:
            return
        if len(edges) >= MAX_ASSESSMENT_EDGES:
            graph_complete = False
            unresolved.add('The resource edge inventory limit was reached; reachability is partial and cannot establish isolation.')
            return
        edges.add(edge)

    source = f'template:{plan.spec.template_key}'
    for path in outputs:
        raise_if_cancelled(stop_event)
        record_edge(ReferenceEdge('compiled-additions', path, 'contribution-root', 'Compiled owned resource output'))

    def require(raw, *, role='resource-reference', evidence='Decoded resource reference'):
        raise_if_cancelled(stop_event)
        path = str(raw).replace('\\', '/').lower()
        if not path:
            return
        if path.endswith('.effect') and '/' not in path:
            path = 'effect/binary__/releasebin/' + split_effect_reference(path)[0] + '.pae'
        path = virtual_path(path)
        # Record even an already visited edge. A shared dependency may be both
        # an authoring input and reachable from the compiled contribution.
        record_edge(ReferenceEdge(source, path, role, evidence))
        if path in outputs or path in visited or path in pending:
            return
        if not snapshot.has_entry(path):
            raise IndependentItemError(f'Unresolved item dependency: {path}')
        # Reading pins the dependency to the exported package's compatibility
        # graph, so another machine cannot silently borrow a modded resource.
        pending[path] = snapshot.payload(path)
        if len(pending) + len(visited) > 4096:
            raise IndependentItemError('The item dependency graph exceeds the supported size.')

    family = snapshot.family(plan.spec.template_key)
    mesh_bindings = {}
    if any(path.endswith('.pac') for path in outputs):
        if plan.spec.variants is not None:
            for variant in plan.manifest.get('variants', ()):
                if 'output_model' in variant:
                    mesh_bindings.setdefault(variant['output_model'].lower(), []).append(
                        (variant['model_path'].lower(), variant['prefab_path'].lower()))
        else:
            for role, original, target in family.renamed(plan.spec.stem):
                if target in outputs:
                    source_paths.setdefault(target, set()).add(original)
                if role == 'pac':
                    mesh_bindings[target] = [(original, part.prefab_path) for part in family.parts
                                             if original in part.pac_paths]
    for resource in family.files:
        if resource.exists:
            require(resource.path, role='authoring-root', evidence='Retained template-family validation input')
    for part in family.parts:
        if part.record is None:
            raise IndependentItemError(f'The template has an unresolved part binding: {part.stem}')
        require(part.prefab_path, role='authoring-root', evidence='Retained template part binding')
        if part.record.sockets_path:
            require(part.record.sockets_path, role='authoring-root', evidence='Retained template socket binding')

    from cdmw.core.pappt_format import parse_pappt
    pappt_path = snapshot.pappt_entry.path.lower()
    if pappt_path in plan.loose_files:
        original = snapshot.pappt.index()
        for record in parse_pappt(plan.loose_files[pappt_path]).records:
            if record.stem not in original:
                source = f'partprefab:{record.stem}'
                require(record.prefab_path, role='contribution-root', evidence='Decoded added PAPPT prefab binding')
                if record.sockets_path:
                    require(record.sockets_path, role='contribution-root', evidence='Decoded added PAPPT socket binding')

    # Qualify roots from the actual final ItemInfo row, rather than assuming
    # every retained template input remains a resource of the authored item.
    from cdmw.core.item_layout import read_item_layout, hash_reference_spans
    from cdmw.core.new_item_record import RecordError
    from cdmw.core.stringinfo_table import stringinfo_key
    from cdmw.core.structured_binary_editor import parse_pabgh_table
    item_pair = snapshot.iteminfo
    final_body = plan.loose_files.get(item_pair.payload_entry.path, item_pair.payload)
    final_header = plan.loose_files.get(item_pair.header_entry.path, item_pair.header)
    final_row = next((final_body[start:end] for directory, start, end in
        parse_pabgh_table(final_header, payload=final_body).row_spans(len(final_body))
        if directory.row_id == int(plan.spec.item_key)), None)
    try:
        layout = read_item_layout(final_row)
    except RecordError:
        layout = None
    if layout is not None:
        strings = dict(snapshot.stringinfo_texts)
        strings.update({stringinfo_key(text): text for text in plan.manifest.get('stringinfo_texts', ())})
        parts = parse_pappt(plan.loose_files[pappt_path]).index() if pappt_path in plan.loose_files else snapshot.pappt.index()
        source = f'iteminfo:{plan.spec.item_key}'
        for role, span in hash_reference_spans(layout):
            key = int.from_bytes(layout.raw[span.start:span.end], 'little')
            if key == 0:
                continue
            text = strings.get(key)
            if role == 'prefab' and text in parts:
                require(parts[text].prefab_path, role='contribution-root', evidence='Declared final ItemInfo prefab field')
            elif role == 'animation' and text and '/' in text:
                require(text, role='contribution-root', evidence='Declared final ItemInfo animation field')
            elif role == 'icon' and text and text.startswith('ItemIcon_Prefab_'):
                from cdmw.core.item_icon_addition import icon_target_path
                require(icon_target_path(text), role='contribution-root', evidence='Declared final ItemInfo icon field')
            else:
                unresolved.add(f'An ItemInfo {role} hash has no supported resource binding: {key}')
        unresolved.discard('Final ItemInfo-to-resource reachability is not decoded here; template roots are not proven authoring-only.')
        unresolved.add('Declared ItemInfo icon/prefab/animation roots are decoded; other table references and engine aliases remain baseline dependencies.')

    if layout is None and not outputs and pappt_path not in plan.loose_files:
        unresolved.add('This contribution retains template resource bindings; final ItemInfo resource roots are not independently decoded here.')

    while pending:
        raise_if_cancelled(stop_event)
        path, data = pending.popitem()
        source = path
        visited.add(path)
        owned = path in outputs
        metadata[path] = [len(data), '', 'unverified-borrowed-layout']
        # Sources with provenance already have an exact-byte digest. Reuse it
        # below instead of hashing large borrowed textures a second time.
        if owned or snapshot.provenance is None:
            metadata[path][1] = sha256(data).hexdigest()
        if path.endswith('.hkx'):
            if owned:
                from cdmw.services.independent_item_physics import audit_physics_copy
                audit_physics_copy(path, data, outputs, mesh_bindings, snapshot,
                    lambda raw: require(raw, role='authoring-validation',
                                        evidence='Unchanged template physics and mesh binding validation'),
                    stop_event=stop_event)
                metadata[path][2] = 'unchanged-template-physics-copy'
                unresolved.add(f'Private physics outgoing runtime references and lifetime remain unverified: {path}')
            else:
                # An unchanged borrowed file is a valid package dependency, but
                # its unparsed outgoing references cannot narrow launch guards.
                reference_closure_complete = False
                metadata[path][2] = 'unverified-borrowed-physics'
                unresolved.add(f'Borrowed physics outgoing references remain unverified: {path}')
            continue
        if path.endswith('.prefab'):
            from cdmw.core.prefab_binary import decode_prefab_binary
            document = decode_prefab_binary(data)
            if not document.walk_complete or document.inferred_objects or document.blob_offset + document.blob_length != len(data):
                raise IndependentItemError(f'The complete prefab reference layout is unverified: {path}')
            metadata[path][2] = 'complete-prefab-reference-layout'
            for resource in document.resource_strings():
                require(resource.text, evidence='Decoded prefab resource string')
        elif path.endswith('.pac_xml'):
            try:
                text = data.decode('utf-8-sig')
                if '<!DOCTYPE' in text or '<!ENTITY' in text:
                    raise ValueError('XML entities are unsupported')
                tree = ET.fromstring('<IndependentModel>' + text.lstrip('\ufeff') + '</IndependentModel>')
                if not len(tree) or any(child.tag not in {'SkinnedMeshPropertyCommon', 'ModelPropertyList'} for child in tree):
                    raise ValueError('Unknown model property root')
            except (UnicodeError, ET.ParseError, ValueError) as exc:
                raise IndependentItemError(f'Unverified model property layout: {path}') from exc
            metadata[path][2] = 'model-property-resource-fields'
            for node in tree.iter():
                if owned and '}' in node.tag and node.tag.rsplit('}', 1)[-1].startswith('ResourceReferencePath'):
                    reference_closure_complete = False
                    unresolved.add(f'Namespace-qualified material resource lookup remains unverified: {path} {node.tag}')
                if node.tag.startswith('ResourceReferencePath'):
                    if set(node.attrib) - {'Name', '_path'}:
                        raise IndependentItemError(f'Unknown model resource boundary: {path}')
                    resource = node.attrib.get('_path', '')
                    require(resource, evidence=f'Model property {node.tag}._path')
                    if owned and resource and (node.tag != 'ResourceReferencePath_ITexture' or not resource.lower().endswith('.dds')):
                        unresolved.add(f'Owned material resource remains outside the private DDS lookup scope: {path} {node.tag} {resource}')
        elif path.endswith(('.pae', '.paem', '.parg', '.pasg')):
            from cdmw.core.effect_binary import decode_effect_binary
            from cdmw.core.effect_edit import emitter_paths_of, preset_names_of, preset_path
            document = decode_effect_binary(data)
            if not document.walk_complete or document.blob_offset + document.blob_length != len(data):
                raise IndependentItemError(f'The complete effect reference layout is unverified: {path}')
            metadata[path][2] = 'complete-effect-reference-layout'
            # An embedded emitter override inherits the file named by its type,
            # independently of the ordinary _emitterDataName string. Walk used
            # nodes only: removed emitter slots may leave unused declarations.
            embedded_emitters = tuple(node.type_name.lstrip('/') for node in document.root.walk()
                                      if node.type_name.lower().endswith('.paem'))
            for resource in (*document.resources(), *emitter_paths_of(document), *embedded_emitters,
                             *(preset_path(kind, name) for kind, name in preset_names_of(document))):
                require(resource, evidence='Decoded effect resource, emitter type, or preset reference')
        elif path.endswith('.pac'):
            if owned:
                from cdmw.services.new_item_variants import validate_variant_rig
                bindings = mesh_bindings.get(path)
                if not bindings:
                    raise IndependentItemError(f'The owned mesh has no verified target binding: {path}')
                # Validate the actual output, including prepared imports and
                # companion meshes, without baking authoring settings again.
                for target, prefab in bindings:
                    source_paths.setdefault(path, set()).add(target)
                    try:
                        validate_variant_rig(snapshot, target, data, prefab_path=prefab)
                    except ValueError as exc:
                        raise IndependentItemError(f'Incompatible owned mesh {path}: {exc}') from exc
            metadata[path][2] = 'verified-owned-mesh-rig' if owned else 'borrowed-mesh-with-sidecar'
            unresolved.add(f'Mesh skeleton, animation, and implicit physics runtime lookup remain unverified: {path}')
            from cdmw.services.new_item_variants import xml_path
            sidecar = xml_path(path)
            if sidecar in outputs or snapshot.has_entry(sidecar):
                if owned and sidecar in outputs:
                    for target, _prefab in bindings:
                        original_sidecar = xml_path(target)
                        if snapshot.has_entry(original_sidecar):
                            source_paths.setdefault(sidecar, set()).add(original_sidecar)
                require(sidecar, role='implicit-sidecar', evidence='PAC basename resolves its model-property sidecar')
        elif path.endswith('.dds'):
            if not data.startswith(b'DDS ') or len(data) < 128:
                raise IndependentItemError(f'The owned texture format is unverified: {path}')
            metadata[path][2] = 'dds-header'
            if owned:
                from cdmw.core.pathc_format import PathcError, validate_dds_payload
                try:
                    validate_dds_payload(data)
                except PathcError as exc:
                    raise IndependentItemError(f'Invalid owned texture {path}: {exc}') from exc
                metadata[path][2] = 'validated-owned-dds-layout'
        elif owned:
            raise IndependentItemError(f'Unsupported independent resource format: {path}')
        else:
            # Retain accepted borrowed resources without claiming their unknown
            # formats are terminal. Only parsed closures can omit carrier hashes.
            reference_closure_complete = False
            unresolved.add(f'Borrowed resource outgoing references have no supported decoder: {path}')

    source_digests = {path: value[1] for path, value in metadata.items() if path not in outputs}
    if snapshot.provenance is not None:
        snapshot.provenance.record_reference_closure(reference_closure_complete)
        digests = {row.entry.path.lower(): row.sha256 for row in snapshot.provenance.capture().payloads}
        source_digests = digests
        for path, value in metadata.items():
            raise_if_cancelled(stop_event)
            if not value[1]:
                value[1] = digests.get(path, '')
                if not value[1]:
                    unresolved.add(f'No retained source digest was available for the traversed resource: {path}')

    # Automatic copies have a stable source-to-destination adapter. Derive this
    # evidence from actual owned bytes and retained source digests, not metadata
    # supplied by a package. Imported replacements can intentionally differ.
    exact_texture_copies = set()
    if plan.spec.stem:
        from cdmw.services.new_item_resource_copies import private_texture_path
        for original, checksum in source_digests.items():
            raise_if_cancelled(stop_event)
            if not original.endswith('.dds') or not checksum:
                continue
            target = private_texture_path(plan.spec.stem, original)
            if target in outputs and metadata[target][1] == checksum:
                source_paths.setdefault(target, set()).add(original)
                exact_texture_copies.add(target)

    outgoing = {}
    for edge in edges:
        raise_if_cancelled(stop_event)
        outgoing.setdefault(edge.source, []).append(edge)
    reachability = {path: set() for path in visited}
    for kind, roles in (
        ('contribution', {'contribution-root'}),
        ('authoring', {'authoring-root', 'authoring-validation'}),
    ):
        todo = [edge.target for edge in edges if edge.role in roles]
        while todo:
            raise_if_cancelled(stop_event)
            path = todo.pop()
            if path not in reachability or kind in reachability[path]:
                continue
            reachability[path].add(kind)
            todo.extend(edge.target for edge in outgoing.get(path, ())
                        if edge.role in {'resource-reference', 'implicit-sidecar'})

    resources = []
    for path in sorted(visited):
        raise_if_cancelled(stop_event)
        owned = path in outputs
        size, checksum, layout = metadata[path]
        originals = tuple(sorted(source_paths.get(path, ())))
        evidence = ('Compiled owned output bytes',) if owned else ('Retained exact-source dependency bytes',)
        if originals:
            evidence += ('Source paths identify template or target bindings; imported output bytes can differ.',)
        if path in exact_texture_copies:
            evidence += ('Stable private texture binding and owned payload digest match the retained DDS source.',)
        roles = tuple(sorted(reachability[path])) or ('unclassified',)
        if not graph_complete:
            roles += ('partial',)
        resources.append(ResourceOwnership(
            symbol='resource:' + path, path=path, ownership='owned' if owned else 'borrowed',
            reachability=roles,
            source_paths=originals or (() if owned else (path,)), source_evidence=evidence,
            layout=layout, byte_size=size, sha256=checksum,
            outgoing_references=tuple(sorted({edge.target for edge in outgoing.get(path, ())})),
            lifetime='Compiled package output; native lifetime unverified' if owned else
                     'Retained source dependency; native lifetime unverified',
        ))
    return ReferenceAssessment(tuple(resources), tuple(sorted(edges,
        key=lambda edge: (edge.source, edge.target, edge.role, edge.evidence))),
        tuple(sorted(unresolved)), reference_closure_complete, graph_complete)
