"""Read-only metadata and ordinary launch for the combined mod list."""
import subprocess

from cdmw.domain.cancellation import raise_if_cancelled


def item_package_details(path, *, stop_event=None):
    from cdmw.services.independent_item_package import read_package, package_metadata
    package = read_package(path, stop_event=stop_event)
    metadata = package_metadata(package)
    return package.title, package.identity, metadata['version'], len(package.blobs), package.digest


def mod_sources(root, *, stop_event=None):
    from cdmw.services.independent_item_install import load_registry
    from cdmw.services.overlay_inventory_details import mounted_archive_status
    from cdmw.services.virtual_loader_state import target

    raise_if_cancelled(stop_event)
    if target(root, '.cdmw/virtual-loader/transaction.json').exists():
        raise ValueError('Recover the interrupted virtual profile transaction first.')
    registry = load_registry(root)
    identities = {row['layer']: (identity, row['title'])
                  for identity, row in registry['items'].items() if row['layer']}
    mounts = mounted_archive_status(root, stop_event=stop_event)
    return identities, mounts, target(root, 'bin64/CrimsonDesert.exe').is_file()


def launch_installed_game(root, *, stop_event=None):
    """Start the selected installation when no virtual profile is active."""
    from cdmw.services.installation_lane import installation_lane
    from cdmw.services.new_item_service import game_is_running
    from cdmw.services.process_job_service import breakaway_creation_flags
    from cdmw.services.virtual_loader_state import load_profile, target

    with installation_lane(root):
        raise_if_cancelled(stop_event)
        if target(root, '.cdmw/virtual-loader/transaction.json').exists() or load_profile(root) is not None:
            raise ValueError('The saved profile changed. Refresh the mod list before launching.')
        if game_is_running():
            raise ValueError('Crimson Desert is already running.')
        executable = target(root, 'bin64/CrimsonDesert.exe')
        if not executable.is_file():
            raise ValueError('Choose the installed Crimson Desert game folder.')
        raise_if_cancelled(stop_event)
        return subprocess.Popen([str(executable)], cwd=str(executable.parent),
                                creationflags=breakaway_creation_flags(), close_fds=True).pid
