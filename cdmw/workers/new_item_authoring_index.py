"""Optional authoring indexes run in the Studio's existing bounded task lane."""
from cdmw.domain.cancellation import raise_if_cancelled


def authoring_index_task(kind, snapshot):
    def run(log, stop_event):
        raise_if_cancelled(stop_event, "Authoring index cancelled.")
        if kind == "bonuses":
            from cdmw.services.new_item_equipment_bonuses import load_equipment_bonuses
            result = load_equipment_bonuses(snapshot, stop_event=stop_event)
        elif kind == "acquisition":
            from cdmw.services.new_item_acquisition_index import load_acquisition_index
            result = load_acquisition_index(snapshot, stop_event=stop_event)
        elif kind == "dyes":
            from cdmw.services.new_item_dyes import load_dye_index
            result = load_dye_index(snapshot, stop_event=stop_event)
        else:
            raise ValueError(f"Unsupported authoring index: {kind}")
        raise_if_cancelled(stop_event, "Authoring index cancelled.")
        return result
    return run
