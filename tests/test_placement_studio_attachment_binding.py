import struct
from types import SimpleNamespace

import numpy as np
import pytest

from tools.placement_studio.attachment_binding import embedded_skeleton, exact_skin, BindingError


def records(*, bad_parent=False, bad_inverse=False):
    matrix = tuple(float(x) for x in np.eye(4).flat)
    inverse = tuple(2*x for x in matrix) if bad_inverse else matrix
    data = bytearray(struct.pack('<I',2))
    for i in range(2):
        name = f'bone{i}'.encode()
        data += struct.pack('<IB',0x12340000+i,len(name)) + name + struct.pack('<i', -1 if i==0 else (2 if bad_parent else 0))
        data += struct.pack('<64f', *matrix,*inverse,*matrix,*inverse)
        data += struct.pack('<10f',1,1,1,0,0,0,1,0,0,0)
    data += b'\x01\x01' + struct.pack('<HII',2,0x12340000,0x12340001)
    return bytes(data)


def test_embedded_binding_requires_reconstruction_and_exact_palette():
    data=records()
    skeleton,palette,_,_,error=embedded_skeleton(data,0,len(data))
    assert skeleton.bone_count==2 and palette==(0,1) and error==0
    with pytest.raises(BindingError): embedded_skeleton(records(bad_parent=True),0,len(data))
    with pytest.raises(BindingError): embedded_skeleton(records(bad_inverse=True),0,len(data))
    with pytest.raises(BindingError): embedded_skeleton(data+data,0,2*len(data))


def test_all_weighted_influences_including_zero_slot_are_preserved():
    data=records(); skeleton,palette,*_=embedded_skeleton(data,0,len(data))
    sub=SimpleNamespace(vertices=[(0,0,0),(1,0,0),(0,1,0)],faces=[(0,1,2)],
                        bone_indices=[(0,1,0)]*3,bone_weights=[(.2,.5,.3)]*3)
    mesh=exact_skin(SimpleNamespace(submeshes=[sub]),skeleton,palette)
    assert mesh.binding_exact and mesh.influences_exact
    assert tuple(mesh.weights[0,:3])==(.2,.5,.3)
    sub.bone_indices=[(0,8,0)]*3
    with pytest.raises(BindingError, match=r'slots \[8\].*2-bone palette'):
        exact_skin(SimpleNamespace(submeshes=[sub]),skeleton,palette)


def test_optional_leaf_evidence_never_remaps_or_drops_an_ancestor():
    from dataclasses import replace
    from tools.placement_studio.attachment_binding import AttachmentBinding, optional_leaf_tracks
    from tools.paa_motion.format import BoneTrack, MotionClip
    data=records(); skeleton,palette,off,pal,error=embedded_skeleton(data,0,len(data))
    binding=AttachmentBinding(skeleton,palette,None,off,pal,error)
    from copy import deepcopy
    witness=deepcopy(binding)
    leaf=deepcopy(witness.skeleton.bones[-1]); leaf.name='optional';leaf.name_hash=19;leaf.index=2;leaf.parent_index=1
    witness.skeleton.bones.append(leaf);witness.skeleton.bone_count=3
    clip=MotionClip((2,3),0,'',1,'',1,0,1,0,(BoneTrack(19,translation=((0,(9.,0.,0.)),)),))
    assert binding.unmatched(clip)==(19,)
    evidence=optional_leaf_tracks(binding,witness,{19},'same-set.pac',b'proof')
    resolved=replace(binding,unused_tracks=evidence)
    assert not resolved.unmatched(clip)
    assert resolved.unused(clip)[0].name=='optional'
    assert len(resolved.unused(clip)[0].sha256)==64
    assert resolved.skeleton is skeleton  # Witness transforms never replace target binds.
    witness.skeleton.bones[1].parent_index=2
    assert not optional_leaf_tracks(binding,witness,{19},'wrong-tree.pac',b'proof')


def test_optional_evidence_requires_one_shared_installed_animation_set(monkeypatch):
    from tools.placement_studio import attachment_binding as ab
    from copy import deepcopy
    data=records(); skeleton,palette,off,pal,error=embedded_skeleton(data,0,len(data))
    binding=ab.AttachmentBinding(skeleton,palette,None,off,pal,error)
    witness=deepcopy(binding)
    leaf=deepcopy(witness.skeleton.bones[-1]);leaf.name='optional';leaf.name_hash=19;leaf.index=2;leaf.parent_index=1
    witness.skeleton.bones.append(leaf)
    clip=SimpleNamespace(tracks=(SimpleNamespace(name_hash=19),))
    relationships=SimpleNamespace(matches=(('target.pac','bow-set'),('wrong.pac','other-set'),('proof.pac','bow-set')),
                                  spaces={},entries={'target.pac':None,'wrong.pac':None,'proof.pac':None})
    scene=SimpleNamespace(equipment=(binding,'target.pac',{'character.paa':('bow.paa','explicit')}),
                          relationships=relationships,clips={'bow.paa':clip})
    monkeypatch.setattr(ab,'decode_binding',lambda *_:witness)
    reads=[]
    ab.complete_scene_binding(scene,lambda p: reads.append(p) or b'proof')
    assert reads==['proof.pac']
    assert not scene.equipment[0].unmatched(clip)
    scene.equipment=(binding,'target.pac',{'character.paa':('bow.paa','explicit')})
    with pytest.raises(RuntimeError,match='cancelled'):
        ab.complete_scene_binding(scene,lambda _:b'',cancelled=lambda:True)
    cancelled = False
    def cancelling_read(_):
        nonlocal cancelled
        cancelled = True
        return b'proof'
    with pytest.raises(RuntimeError, match='cancelled'):
        ab.complete_scene_binding(scene, cancelling_read, cancelled=lambda:cancelled)
    assert scene.equipment[0] is binding  # Cancellation cannot publish witness evidence.
