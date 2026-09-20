"""Regenerate owned synthetic Rust vectors from the decoded Python reference.

Run from the repository root with .venv/Scripts/python.exe. No game data is
read or embedded. Chained cases feed each implementation's own packed result
into its next frame, so the check includes float-bit RNG feedback over time.
"""

from pathlib import Path
import hashlib
import math
import struct
import sys

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT))

from cdmw.modding.pac_jiggle_bones import step_jiggle_bone
from tests.test_pac_jiggle_bones import character, matrix, rotated, shader, state
from tests.test_pac_jiggle_effects import continuing, trigger


source = ROOT / 'cdmw/modding/pac_jiggle_bones.py'
lines = [
    '# Synthetic records only. Regenerate with the adjacent generate_vectors.py.',
    '# Python reference SHA256: ' + hashlib.sha256(source.read_bytes()).hexdigest(),
    '# name|previous (- missing, ^ preceding result)|command|shader|animation|character|params|bone|matrix|reset',
    '# params: little-endian 8xf64 (view, old_view, scale, dt), 2xu32 (bone, frame), u8 reset',
]
last = None


def add(name, previous, **changes):
    global last
    args = dict(command_bone=bytes(116), shader_data=shader(), animation_matrix=matrix(),
                character_transform=character(), view_position=(0., 0., 0.),
                previous_view_position=(0., 0., 0.), bone_scale=1., original_bone_index=0,
                update_frame_index=1, delta_time=.25, reset_requested=False)
    args.update(changes)
    chained = isinstance(previous, str) and previous == '^'
    previous_record = last if chained else previous
    result = step_jiggle_bone(previous_record, **args)
    params = struct.pack('<8d2IB', *args['view_position'], *args['previous_view_position'],
                         args['bone_scale'], args['delta_time'], args['original_bone_index'],
                         args['update_frame_index'], args['reset_requested'])
    fields = [name, '^' if chained else '-' if previous is None else previous.hex()]
    fields.extend(args[key].hex() for key in ('command_bone', 'shader_data', 'animation_matrix', 'character_transform'))
    fields.extend((params.hex(), result['bone'].hex(),
                   struct.pack('<16d', *(v for row in result['matrix'] for v in row)).hex(),
                   str(int(result['reset']))))
    lines.append('|'.join(fields))
    last = result['bone']


# Nonzero state products, moving origins/platform, nonuniform animation scale,
# and nonidentity world/inverse bases exercise the ordinary matrix/RNG path.
world = ((0., 2., 0., 0.), (-3., 0., 0., 0.), (0., 0., 4., 0.), (0., 0., 0., 1.))
inverse = ((0., -1/3, 0., 0.), (.5, 0., 0., 0.), (0., 0., .25, 0.), (0., 0., 0., 1.))
initial = state(p=(.031, -.127, .09), v=(.1, -.07, .02), r=(.04, -.08, .01), rv=(.1, .2, -.3))
for frame in range(1, 9):
    animated = rotated(.07 * frame, -.03 * frame, .05 * frame)
    animated = tuple(tuple(v * (i + 1) if j < 3 else v for j, v in enumerate(row))
                     if i < 3 else (.01 * frame, .02 * frame, -.015 * frame, 1.)
                     for i, row in enumerate(animated))
    add(f'ordinary-{frame}', initial if frame == 1 else '^', update_frame_index=frame,
        original_bone_index=157, delta_time=1/60, bone_scale=1.3,
        animation_matrix=matrix(animated), shader_data=shader(
            settings=(680, .82, 3, .055, 400, .7, 200, .7), platform=(.001, -.002, .003)),
        character_transform=character(world=world, inverse=inverse,
            origin=(.01 * frame, .02, -.03), old_origin=(.01 * (frame - 1), .02, -.03),
            bound_a=(-.1, -.2, -.3), bound_b=(.4, 1.8, .6)),
        view_position=(100., .03, -10.), previous_view_position=(100., .02, -10.))

# Each mode progresses from a pending impulse through fade and expiration to
# the ordinary path. Runtime tails and upper flag bits survive the transition.
for mode in (0, 4, 8, 10, 12, 14):
    command = bytearray(trigger(mode=mode, velocity=(.4, -.3, .2), angular_velocity=(.2, -.4, .3),
                                weight=1.25, duration=.875, fade_range=.5))
    struct.pack_into('<I', command, 108, 0x23)
    for frame in range(1, 6):
        add(f'instance-{mode}-{frame}', initial if frame == 1 else '^', update_frame_index=frame,
            command_bone=command if frame == 1 else bytes(116), original_bone_index=22,
            animation_matrix=matrix(rotated(.1, -.2, .3)),
            shader_data=shader(settings=(5, .5, 2, .4, 7, .6, 1.2, .3), flags=1),
            character_transform=character(bound_b=(0, 2, 0)))

add('reset-missing-buffer', None, animation_matrix=matrix(rotated(.1, .2, .3)),
    shader_data=shader(settings=(math.nan,) * 8), character_transform=character(origin=(100, 200, 300)))
add('reset-explicit-with-new-instance', initial, reset_requested=True,
    command_bone=trigger(mode=14, velocity=(.3, 0, 0), angular_velocity=(.1, .2, .3)),
    shader_data=shader(settings=(2, .6, 2, .2, 4, .8, 2, .4), flags=1))
add('reset-frame-gap-continuing', '^', update_frame_index=3,
    shader_data=shader(settings=(2, .6, 2, .2, 4, .8, 2, .4), flags=1))
add('reset-origin-speed', initial, character_transform=character(origin=(0, 18, 0)), delta_time=.25)
add('inverse-dt-guard', initial, character_transform=character(origin=(0, 18, 0)), delta_time=1e-6)
add('frame-wrap-ignore-nonpending-command', state(frame=0xffffffff, flags=0x20, v=(.1, .2, .3)),
    command_bone=state(flags=2), update_frame_index=0)
add('size-upper-limit-and-gimbal', initial, animation_matrix=matrix(rotated(math.pi/2, .2, -.4)),
    character_transform=character(bound_b=(0, 100, 0)), bone_scale=3)
add('zero-delta-still-damps', initial, delta_time=0,
    shader_data=shader(settings=(2, .5, 100, 100, 2, .5, 100, 100)))
add('negative-unclamped-mask-last-wins', initial, original_bone_index=65535,
    shader_data=shader(flags=2, masks=((65535, 2.), (3, .5), (65535, -.5))))
add('full-u32-bone-does-not-alias-mask', initial, original_bone_index=0xffffffff,
    shader_data=shader(flags=2, masks=((65535, 2.),)))
add('effect-passthrough-before-mask', initial,
    command_bone=trigger(mode=12, velocity=(10, 20, 30), weight=0),
    shader_data=shader(flags=2, masks=((0, 1.5),)))
add('duration-without-fade', initial,
    command_bone=trigger(mode=4, velocity=(1, 2, 3), duration=.25, fade_range=-1),
    shader_data=shader(flags=1))
add('continuing-axis-large-dt', continuing(mode=10, axis=(.1, .9, .2), angle=.2, duration=10),
    delta_time=1., shader_data=shader(settings=(0, 1, 100, 100, 2, .5, 10, 2), flags=1))

output = Path(__file__).with_name('vectors.txt')
output.write_text('\n'.join(lines) + '\n', encoding='ascii')
print(f'{len(lines) - 4} synthetic frames written to {output}')
