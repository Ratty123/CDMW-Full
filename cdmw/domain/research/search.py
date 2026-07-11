"""Pure Research search presets and result clustering."""

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath
from typing import Dict, List, Sequence

from cdmw.domain.research.classification import system_area_from_path
from cdmw.domain.research.contracts import RegexPreset, SearchCluster


def get_regex_presets() -> List[RegexPreset]:
    return [
        RegexPreset("Materials", "Material names", r"(?i)material(name|id)?\s*=\s*\"([^\"]+)\"", "Find material-name assignments in XML or material-like files."),
        RegexPreset("Materials", "Texture references", r"(?i)(texture|albedo|normal|roughness|mask)[^\\n=]*=\s*\"([^\"]+)\"", "Find texture-path assignments and texture parameters."),
        RegexPreset("Actors", "Actor IDs", r"(?i)(actor|npc|pawn)[^\\n=]*id\s*=\s*\"?([A-Za-z0-9_./:-]+)\"?", "Find actor or NPC identifiers.", path_hint="character"),
        RegexPreset("Actors", "Gameplay tags", r"(?i)(gameplaytag|tag)[^\\n=]*=\s*\"([^\"]+)\"", "Find gameplay-tag style assignments."),
        RegexPreset("Paths", "File paths", r"(?i)([A-Za-z0-9_./-]+\.(dds|png|xml|material|json|lua))", "Find referenced asset paths."),
        RegexPreset("Paths", "Package-like IDs", r"(?i)\b\d{4}/[A-Za-z0-9_./-]+\b", "Find archive-style package/path references."),
        RegexPreset("Sound", "Event names", r"(?i)(Wwise|Sound(Event|Bank)|RTPC|SwitchGroup|State)", "Find sound-system references.", extensions=".xml;.json"),
        RegexPreset("UI", "UI widget refs", r"(?i)(widget|hud|icon|layout|panel|button)[A-Za-z0-9_./:-]*", "Find likely UI/layout terms.", extensions=".xml;.json;.cfg", path_hint="ui"),
        RegexPreset("Gameplay", "Quest or objective refs", r"(?i)(quest|objective|mission|scenario)[A-Za-z0-9_./:-]*", "Find quest/objective-style names."),
        RegexPreset("Scripts", "Class or function refs", r"(?i)\b(class|function|script|handler)\b", "Find script/class-like declarations.", extensions=".lua;.json;.xml"),
    ]


def cluster_text_search_results(results: Sequence[object], mode: str) -> List[SearchCluster]:
    bucket_counts: Dict[str, int] = defaultdict(int)
    bucket_matches: Dict[str, int] = defaultdict(int)
    bucket_samples: Dict[str, List[str]] = defaultdict(list)

    for result in results:
        relative_path = str(getattr(result, "relative_path", "") or "")
        if not relative_path:
            continue
        if mode == "package":
            label = str(getattr(result, "package_label", "") or "Loose file")
        elif mode == "system":
            label = system_area_from_path(relative_path)
        else:
            label = PurePosixPath(relative_path).parent.as_posix() or "(root)"
        bucket_counts[label] += 1
        bucket_matches[label] += int(getattr(result, "match_count", 0) or 0)
        samples = bucket_samples[label]
        if len(samples) < 3:
            samples.append(relative_path)

    clusters = [
        SearchCluster(
            mode=mode,
            label=label,
            file_count=file_count,
            total_matches=bucket_matches[label],
            sample_paths=bucket_samples[label],
        )
        for label, file_count in bucket_counts.items()
    ]
    clusters.sort(key=lambda cluster: (-cluster.file_count, -cluster.total_matches, cluster.label))
    return clusters


__all__ = ["cluster_text_search_results", "get_regex_presets"]
