"""Generate owned synthetic sample vectors; run with the repo's venv Python.

No game payloads are read. Chained rows feed each implementation's own packed
sample into the next frame, exercising float-bit random feedback.
"""

from pathlib import Path
import hashlib
import math
import struct
import sys

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT))
from cdmw.modding.pac_jiggle_samples import step_jiggle_sample
from tests.test_pac_jiggle_samples import globals_record, sample

lines = ['# Owned synthetic records. Regenerate with adjacent generate_vectors.py.',
         '# name|index|previous (^ native feedback)|globals|sample|matrix_f64']
for name in ('pac_jiggle_samples.py', 'pac_jiggle_bones.py'):
    lines.append('# ' + name + ' SHA256 ' + hashlib.sha256((ROOT / 'cdmw/modding' / name).read_bytes()).hexdigest())
last = None


def add(name, index, previous, data):
    global last
    chained = previous == '^'
    result = step_jiggle_sample(last if chained else previous, global_data=data, sample_index=index)
    lines.append('|'.join((name, str(index), '^' if chained else previous.hex(), data.hex(),
                           result['sample'].hex(), struct.pack('<16d', *[v for row in result['matrix'] for v in row]).hex())))
    last = result['sample']


for index in (0, 255, 256, 511):
    add('double-integration', index, sample(v=(4, 0, 0), rv=(.5, 0, 0)), globals_record())
add('cpu-bypass', 511, sample(p=(2, 3, 4), v=(8, 9, 10), r=(0, 0, math.pi / 2)),
    globals_record(dt=math.nan, cpu_mode=1))
for elapsed in (0., .5, .75):
    data = globals_record()
    struct.pack_into('<3f', data, 16, 1, .25, .5)
    struct.pack_into('<3f', data, 32, .3, .2, .1)
    struct.pack_into('<2f', data, 48, 2, .5)
    struct.pack_into('<3f', data, 64, 1, .5, 4)
    add('wind-phase', 3, sample(elapsed=elapsed, duration=1), data)
data = globals_record()
struct.pack_into('<2f', data, 104, .5, 4)
struct.pack_into('<4f', data, 112, 1, .3, .2, .4)
struct.pack_into('<f', data, 132, 2)
add('water-rollover', 256, sample(elapsed=1, duration=1, angular=(1, 2, 3, 8)), data)
for index in (7, 300):
    for frame in range(16):
        data = globals_record(dt=1 / 60)
        struct.pack_into('<3f', data, 16, 1, .25, .5)
        struct.pack_into('<3f', data, 32, .3, .2, .1)
        struct.pack_into('<2f', data, 48, 2, .5)
        struct.pack_into('<4f', data, 64, 1, .5, 4, .07)
        struct.pack_into('<2f', data, 104, .07, 2)
        struct.pack_into('<4f', data, 112, .2, .3, .4, .5)
        struct.pack_into('<2f', data, 128, .5, .2)
        struct.pack_into('<I', data, 136, 42 + frame)
        struct.pack_into('<16f', data, 160, 680, .82, 3, .055, 400, .7, 200, .7,
                         680, .082, 3, .11, 400, .07, 200, 1.4)
        previous = '^' if frame else sample(p=(.01, -.02, .03), v=(.1, .2, .3), r=(.04, -.08, .12))
        add(f'feedback-{index}-{frame}', index, previous, data)

Path(__file__).with_name('vectors.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
print(f'Generated {len(lines) - 4} synthetic sample vectors.')
