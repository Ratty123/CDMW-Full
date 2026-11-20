"""The prefab speed values Speed Tuning offers (experimental).

Keyed by (the component type of the object the value sits in, member name), as the
prefab walk reports them. Built from a scan of the installed game's 51,178 prefabs,
then cut down by ``scripts/prefab_speed_census.py`` to the members the walk actually
reaches (census run 2026-11-20 on the Home PC, CDMW at b14d1ce):

=============================================  ========  ===========  ===========
member                                          declared  files with   values
                                                in files  a value      reached
=============================================  ========  ===========  ===========
CameraComponent._speed (camera processors)          301            4            6
VelocityComponent._angularVelocity (float3)          86           70          141
WindComponent._windSpeedAccelerationScale            86            7            7
CloudDensityVolumeComponent._detailNoiseFlowSpeed     4            2            2
CloudDensityVolumeComponent._macroNoiseFlowSpeed      4            3            3
CloudDensityVolumeComponent._vortexAngularSpeed       4            3            3
=============================================  ========  ===========  ===========

Left out because the walk reaches no value in any shipped prefab: the emitter
speeds (EmitterSimulationData._simulationSpeed, EmitterRenderData._sequencePlaySpeed,
EmitterMoveTrackData._moveTrackPlaySpeed and _moveTrackConstantSpeed, the
EmitterDynamicData velocities; 61 of 68 walks stop early and the other 7 never reach
an emitter), VelocityComponent._linearVelocity, NPCScheduleSplineDataAttribute._speedLimit,
WeatherConstant._windSpeed and ScenePostProcessing's _speedDarkToBright and
_speedBrightToDark. The camera processors (CameraFollowProcessor, CameraLookAtProcessor,
CameraSpringArmProcessor, CameraTargetsAlwaysOnScreen) all name their member ``_speed``
and are stored inline in a CameraComponent, so the walk reports them under it.

None of these has been tested in game.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

#: Category key -> label, in the order Speed Tuning lists them.
CATEGORIES = MappingProxyType({
    "cameras": "Scene cameras",
    "moving": "Moving and wind-driven objects",
    "weather": "Weather and clouds",
})


@dataclass(frozen=True, slots=True)
class SpeedMember:
    type_name: str
    member: str
    category: str
    label: str
    #: The editable kinds (prefab_values.editable_kind) a value may have to be offered.
    kinds: tuple[str, ...] = ("float",)


SPEED_MEMBERS = MappingProxyType({
    (item.type_name, item.member): item for item in (
        SpeedMember("CameraComponent", "_speed", "cameras", "Camera speed"),
        SpeedMember("VelocityComponent", "_angularVelocity", "moving", "Spin speed (x, y, z)", ("float3",)),
        SpeedMember("WindComponent", "_windSpeedAccelerationScale", "moving", "Wind speed-up"),
        SpeedMember("CloudDensityVolumeComponent", "_detailNoiseFlowSpeed", "weather", "Cloud detail drift"),
        SpeedMember("CloudDensityVolumeComponent", "_macroNoiseFlowSpeed", "weather", "Cloud drift"),
        SpeedMember("CloudDensityVolumeComponent", "_vortexAngularSpeed", "weather", "Cloud swirl speed"),
    )
})

#: Every catalogue type, for a search that reads only a prefab's type table.
SPEED_TYPES = frozenset(type_name for type_name, _member in SPEED_MEMBERS)
#: Every catalogue member name, for a byte search that rejects most prefabs before decoding.
SPEED_MEMBER_NAMES = frozenset(member for _type, member in SPEED_MEMBERS)


def speed_member(type_name: str, member: str) -> SpeedMember | None:
    return SPEED_MEMBERS.get((str(type_name or ""), str(member or "")))


def category_label(category: str) -> str:
    return CATEGORIES.get(category, category)


__all__ = ["CATEGORIES", "SPEED_MEMBERS", "SPEED_MEMBER_NAMES", "SPEED_TYPES", "SpeedMember", "category_label",
           "speed_member"]
