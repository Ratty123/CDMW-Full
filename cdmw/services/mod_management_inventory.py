"""Read-only metadata for the Mods page's item packages."""


def item_package_details(path, *, stop_event=None):
    from cdmw.services.independent_item_package import read_package, package_metadata
    package = read_package(path, stop_event=stop_event)
    metadata = package_metadata(package)
    return package.title, package.identity, metadata['version'], len(package.blobs), package.digest
