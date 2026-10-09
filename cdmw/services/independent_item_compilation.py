"""Capture actual retained package artifacts for compiler provenance."""
from cdmw.domain.new_item.compilation import compilation_record
from cdmw.services.independent_item_package import digest, package_metadata


def package_record(package, retained_bytes):
    manifest = package_metadata(package)
    return {'identity': package.identity, 'content': package.digest,
            'artifact': package.artifact_digest or digest(retained_bytes), 'retained_artifact': digest(retained_bytes),
            'version': manifest['version'], 'features': dict(manifest.get('requires', {'item.legacy': 1})),
            'modules': [{key: module[key] for key in ('id', 'type', 'version')}
                        for module in manifest.get('modules', [{'id': 'item', 'type': 'item.legacy', 'version': 1}])]}


def contribution_record(package, changes, resolved):
    retained = resolved.pending[f'.cdmw/independent-items/{package.identity}-{package.digest}.cditem']
    return compilation_record(scope='archive-contribution', packages=[package_record(package, retained)],
        sources=dict(package.dependencies),
        allocations={identity: row['binding_hash'] for identity, row in resolved.registry['items'].items()},
        order=[layer.get('independent_identity', layer['id']) for layer in resolved.state['layers'] if layer['active']]
              + [p.identity for p, _ in resolved.contributions],
        runtime_abi=None,
        outputs={path: digest(row['after']) if row['after'] is not None else None for path, row in changes.items()},
        providers={path: digest(row['before']) if row['before'] is not None else None for path, row in changes.items()})
