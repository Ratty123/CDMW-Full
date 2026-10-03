from dataclasses import replace

import pytest

from tools.placement_studio.motionblending import MotionSpace, Dimension, Example, Triangle, Plane, BlendError


def space():
    return MotionSpace('test', 'rig', ('a', 'b', 'c'),
                       (Dimension('x', 0, 1), Dimension('y', 0, 1)),
                       tuple(Example(p, (i,), (1,)) for i,p in enumerate(((0.,0.),(1.,0.),(0.,1.)))),
                       (Triangle((0,1,2), ((0.,0.),(1.,0.),(0.,1.))),),
                       ((0,15,60),(0,30,90),(0,15,60)), True, 1., (4.,8.))


def test_stored_triangle_weights_and_hull_projection():
    s = space()
    assert dict(s.contributions((.25,.25))) == {'a':.5,'b':.25,'c':.25}
    assert dict(s.contributions((1.,1.))) == {'b':.5,'c':.5}
    assert dict(s.contributions((-1.,-1.))) == {'a':1.}
