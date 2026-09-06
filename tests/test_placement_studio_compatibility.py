from types import SimpleNamespace
import pytest

from tools.placement_studio.compatibility import proportion_difference, measure_fit
from tools.placement_studio.model import Vec3, Quat
from tools.placement_studio.skeleton import matrix_from
from tools.paa_motion.format import MotionClip


def test_shared_hashes_do_not_hide_proportion_differences():
    a = SimpleNamespace(bones=[SimpleNamespace(name_hash=1,position=(.1,0,0))])
    b = SimpleNamespace(bones=[SimpleNamespace(name_hash=1,position=(.4,0,0))])
    count, maximum, mean = proportion_difference(a,b)
    assert count == 1 and abs(maximum-.3)<1e-6 and mean == maximum


def test_destination_changes_fit_but_does_not_verify_contact():
    class Session:
        has_skeleton=True
        _weapon=SimpleNamespace(sockets={'grip':SimpleNamespace(rotation=Quat(),translation=Vec3())})
        destination=.2
        def descriptor_part(self,_):
            return SimpleNamespace(in_socket='destination',in_child_socket='stowed',out_socket='hand',out_child_socket='grip')
        def apply_pose(self, *_): pass
        def clear_pose(self): pass
        def attachment_matrix(self,*_): return matrix_from(Quat(),Vec3(self.destination,0,0))
        def placed(self,*_): return SimpleNamespace(world_matrix=matrix_from(Quat(),Vec3()))
    clip=MotionClip((2,3),0,'',1,'',1,0,0,0,())
    session=Session(); unit=SimpleNamespace(primary_part='weapon')
    before=measure_fit(session,clip,unit)
    session.destination=.8
    after=measure_fit(session,clip,unit)
    assert before.nearest_grip == .2 and after.nearest_grip == .8
    assert before.contact_state == after.contact_state == 'Unverified'


def test_shrink_socket_overrides_are_settings_not_a_clearance_guarantee():
    from tools.placement_studio.equipment_rules import shrink_rules,alignment_bones
    rules=shrink_rules(b'<GlobalSetting><ShrinkDepthBias><Weapon Value="0.04" UseCustomVolume="True"/></ShrinkDepthBias>'
        b'<SocketToShrinkTag><LForearm_Socket toTag="Zero"/></SocketToShrinkTag></GlobalSetting>'
        b'<Shrink><ShrinkTag Name="Weapon"><Shrink>Nude</Shrink></ShrinkTag></Shrink>')
    assert rules.setting('Weapon','Spine2') == ('Weapon',.04,True,('Nude',))
    assert rules.setting('Weapon','LForearm_Socket') == ('Zero',0.,False,())
    assert alignment_bones(b'<Root><BoneMapping Name="InterimToGame"><Mapping InterimBone="Hand" MappedBone="Bip01 L Hand"/></BoneMapping>'
        b'<BoneNameList Name="BonesForAlignment"><Bone Name="Hand"/></BoneNameList></Root>') == ('Bip01 L Hand',)


def test_invalid_optional_descriptors_have_explicit_analysis_errors():
    from tools.placement_studio.equipment_rules import shrink_rules, alignment_bones
    for parse in (shrink_rules, alignment_bones):
        with pytest.raises(ValueError, match='Invalid'):
            parse(b'<broken>')


def test_candidate_order_changes_with_destination_and_donors_are_read_once():
    from tools.placement_studio.candidate_analysis import analyse_candidates
    from tools.placement_studio.clips import ClipEntry
    from tools.placement_studio.carry import AnimationReplacement
    from tools.paa_motion.format import BoneTrack
    from tools.paa_motion.pose import sample_delta_seconds
    from tools.paa_motion.encode import encode_paa
    class Session:
        has_skeleton = True
        hierarchy = SimpleNamespace(parsed=SimpleNamespace(bones=[SimpleNamespace(name_hash=1)]))
        _weapon = SimpleNamespace(sockets={'grip':SimpleNamespace(rotation=Quat(),translation=Vec3())})
        destination = .15
        hand = 0.
        def descriptor_part(self, _):
            return SimpleNamespace(in_socket='destination',in_child_socket='stowed',out_socket='hand',out_child_socket='grip')
        def apply_pose(self, clip, frame):
            self.hand = sample_delta_seconds(clip,1,frame/30).translation[0]
        def clear_pose(self): self.hand = 0.
        def attachment_matrix(self, *_): return matrix_from(Quat(),Vec3(self.destination,0,0))
        def placed(self, *_): return SimpleNamespace(world_matrix=matrix_from(Quat(),Vec3(self.hand,0,0)))
    root = 'character/motion/1_pc/1_phm/'
    entries = [ClipEntry(root+f'cd_phm_longsword_00_00_normal_stand_weapon_out_{i:03d}.paa','1_pc/1_phm','',False) for i in range(2)]
    payloads = {e.path:encode_paa(MotionClip((2,3),0,'',1,'',1,0,1,0,
               (BoneTrack(1,translation=((0,(x,0.,0.)),)),))) for e,x in zip(entries,(.1,.9))}
    row = AnimationReplacement(entries[0],entries[0],options=tuple(entries))
    plan = SimpleNamespace(request=SimpleNamespace(replacements=(row,row)),
                           unit=SimpleNamespace(primary_part='weapon',donor_animation_families=('longsword',)))
    scene = SimpleNamespace(after=Session(),prepared=SimpleNamespace(plan=plan))
    reads = []
    def read(entry):
        reads.append(entry.path)
        return payloads[entry.path]
    left = analyse_candidates(scene,read=read)
    assert len(reads) == 2 and min(left,key=lambda c:c.rank).donor == entries[0].path
    reads.clear();scene.after.destination = .85
    right = analyse_candidates(scene,read=read)
    assert len(reads) == 2 and min(right,key=lambda c:c.rank).donor == entries[1].path
    assert row.donor == entries[0] and all('Unverified' in c.detail for c in right)
