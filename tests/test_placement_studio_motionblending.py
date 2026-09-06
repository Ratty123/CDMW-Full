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


def test_degenerate_attachment_axis_interpolates_all_examples():
    s = replace(space(), examples=(Example((0.,0.),(0,),(1,)), Example((0.,1.),(1,),(1,))),triangles=())
    assert dict(s.contributions((0.,.25))) == {'a':.75,'b':.25}


def test_phase_clock_uses_declared_clip_duration_and_boundaries():
    s = space()
    assert s.phase_seconds(0,.5,2.) == .5
    assert s.phase_seconds(1,.5,3.) == 1.
    assert s.phase_seconds(0,1.,2.) == 2.
    with pytest.raises(BlendError, match='Unverified'): s.phase_seconds(0,.5,5.)


def test_unknown_triangulation_does_not_invent_a_blend():
    with pytest.raises(BlendError, match='triangulation'):
        replace(space(),triangles=()).contributions((.25,.25))
    with pytest.raises(BlendError): space().contributions((float('nan'),0))


def test_blended_duration_seeking_and_looping_share_the_weighted_seconds_clock():
    from tools.paa_motion.format import MotionClip
    from tools.placement_studio.preview_pose import space_duration, samples_for_space
    clips = {p:MotionClip((2,3),0,'',1,'',duration,0,0,0,()) for p,duration in zip(('a','b','c'),(2.,3.,2.))}
    s=space(); parameters=(.5,0.)
    assert space_duration(s,clips,parameters) == 2.5
    assert space_duration(s,clips,parameters,scale=2) == 1.25
    samples,_,notes=samples_for_space(s,clips,parameters,1.25,looping=False)
    assert [seconds for _,seconds,_ in samples] == [.5,1.]
    assert not notes
    samples,_,_=samples_for_space(s,clips,parameters,2.5,looping=False)
    assert [seconds for _,seconds,_ in samples] == [2.,3.]
    samples,_,_=samples_for_space(s,clips,parameters,2.5,looping=True)
    assert [seconds for _,seconds,_ in samples] == [0.,0.]


def test_three_dimensions_use_plane_membership_and_interpolate_the_stored_knots():
    s = space()
    points = ((0.,0.,-1.), (1.,0.,-1.), (0.,1.,-1.),
              (0.,0.,1.), (2.,0.,1.), (0.,2.,1.))
    examples = tuple(Example(p, (i,), (1,)) for i,p in enumerate(points))
    planes = (Plane(-1., (0,1,2), (Triangle((0,1,2), tuple(p[:2] for p in points[:3])),)),
              Plane(1., (3,4,5), (Triangle((3,4,5), tuple(p[:2] for p in points[3:])),)))
    s = replace(s, clips=tuple('abcdef'), dimensions=s.dimensions+(Dimension('z',-1,1),),
                examples=examples, planes=planes)
    assert dict(s.contributions((.5,.5,0.))) == {'b':.25,'c':.25,'d':.25,'e':.125,'f':.125}
    assert dict(s.contributions((.5,.5,-2.))) == {'b':.5,'c':.5}
    assert dict(s.contributions((0.,0.,2.))) == {'d':1.}


def test_plane_mapping_resolves_local_indices_and_rejects_missing_or_conflicting_members():
    from types import SimpleNamespace as N
    import struct
    from tools.placement_studio.motionblending import decode_planes
    def number(name, code, values):
        return N(name=name, raw=struct.pack('<'+code*len(values), *values))
    # Plane-local index zero is global example 1 in the first plane, 0 in the second.
    examples = tuple(Example(p, (i,), (1,), i%2 ^ 1) for i,p in enumerate(
        ((0,0,1),(0,0,-1),(1,0,1),(1,0,-1),(0,1,1),(0,1,-1))))
    mapping = (1,3,5,0,0,0, 0,2,4,0,0,0)
    doc = N(root_numbers=(number('_thirdDimensionSplitInfo','f',(-1,1)), number('_delaunayPointIndexMap','H',mapping)),
            collections=(N(owner_type='ParameterizedMotionSpace', member_name='_delaunayTriangles', count=2, elements=((100,200),(200,300))),),
            objects=(N(component_type='DelaunayTriangle',offset=110),N(component_type='DelaunayTriangle',offset=210)))
    tris = (Triangle((0,1,2), ((0,0),(1,0),(0,1))),)*2
    result = decode_planes(doc, examples, tris, [])
    assert result[0].triangles[0].indices == (1,3,5)
    assert result[1].triangles[0].indices == (0,2,4)
    with pytest.raises(BlendError, match='Explicit example plane'):
        decode_planes(doc, (replace(examples[0],plane=0),)+examples[1:], tris, [])
    with pytest.raises(BlendError, match='outside plane'):
        decode_planes(doc, examples, (replace(tris[0],indices=(0,1,5)),tris[1]), [])
    doc.root_numbers = (doc.root_numbers[0], number('_delaunayPointIndexMap','H',(1,3,0,0,0,0,0,2,4,0,0,0)))
    with pytest.raises(BlendError):
        decode_planes(doc, examples, (), [])


def test_small_scale_triangle_is_valid_and_degenerate_triangle_is_individually_reported():
    from tools.placement_studio.motionblending import barycentric, validated_triangles
    tiny = ((0.,0.),(1e-8,0.),(0.,1e-8))
    assert barycentric((2.5e-9,2.5e-9), tiny) == pytest.approx((.5,.25,.25))
    examples = tuple(Example(p,(i,),(1,)) for i,p in enumerate(((0.,0.),(1.,0.),(0.,1.),(2.,0.))))
    valid = Triangle((0,1,2), tuple(e.parameters for e in examples[:3]))
    degenerate = Triangle((0,1,3), tuple(examples[i].parameters for i in (0,1,3)))
    notes = []
    assert validated_triangles((degenerate,valid), examples, notes) == (valid,)
    assert notes == ['Degenerate stored triangles: excluded from interpolation']


def test_typed_decoder_uses_validated_constructor_defaults_and_retains_inherited_weight_limit(monkeypatch):
    from types import SimpleNamespace as N
    import struct
    from tools.placement_studio import motionblending as module
    def number(name, code, values):
        return N(name=name, raw=struct.pack('<'+code*len(values), *values))
    dimension = N(component_type='ParameterDimension', type_source='stated', numbers=(),
                  values=(('_dimensionType',N(text='LeftStickX')),))
    example = N(component_type='ParameterizedMotionExample', type_source='stated', values=(),
                numbers=(number('_animationDataIndex','I',(0,)), number('_animationDataProbability','H',(1,)),
                         number('_parameters','f',(0.,))))
    doc = N(root_type='ParameterizedMotionSpace',walk_complete=True,root_values=(('_animationFileNames',N(text='1_pc/1_phm/clip.paa')),),
            root_numbers=(number('_parameterMinMax','f',(-1.,1.)),),objects=(dimension,example))
    monkeypatch.setattr(module,'decode_prefab_binary',lambda _:doc)
    result = module.decode(b'')
    assert result.dimensions[0].scale == 1.
    assert result.dimensions[0].smoothing == 0.
    assert result.smoothing == (1.75,3.5) and result.scale == 1. and result.keep_weights == 0
    doc.root_numbers += (number('_keepInitialBlendWeights','i',(2,)),)
    inherited = module.decode(b'')
    assert inherited.keep_weights == 2
    assert any('Previous-motion weights: Unverified' in note for note in inherited.limitations)
