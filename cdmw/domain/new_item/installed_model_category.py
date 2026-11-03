"""Asset-part labels for the guided picker; never wearer or rig guarantees."""
from pathlib import Path

def character_model_category(path):
    """Describe the declared asset folder; never infer wearer or rig compatibility."""
    parts = str(path).replace('\\', '/').casefold().split('/')
    if not ({'1_pc', '3_npc'} & set(parts) or any('twofeet' in p for p in parts)):
        return 'other'
    folders = {part.split('_', 1)[-1] if part[:1].isdigit() else part for part in parts[:-1]}
    # Humanoid NPC pieces share a character folder; their part is in the model
    # name. This is categorisation only, never evidence of player compatibility.
    folders.update(Path(parts[-1]).stem.split('_'))
    for folder, category in (('upperbody', 'chest'), ('lowerbody', 'legs'), ('hand', 'gloves'),
                             ('ub', 'chest'), ('lb', 'legs'),
                             ('foot', 'boots'), ('hel', 'helmets'), ('sho', 'shoulders'),
                             ('cloak', 'cloaks'), ('acc', 'accessories'), ('mask', 'accessories'),
                             ('vest', 'chest'), ('jacket', 'chest'), ('head', 'head'),
                             ('hair', 'head'), ('body', 'body')):
        if folder in folders:
            return category
    return 'other'
