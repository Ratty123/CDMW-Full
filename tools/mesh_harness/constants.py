from __future__ import annotations

from pathlib import Path

_WM_COPYDATA = 0x004A

_WM_CLOSE = 0x0010

_WM_MOUSEMOVE = 0x0200

_WM_LBUTTONDOWN = 0x0201

_WM_LBUTTONUP = 0x0202

_WM_COPYDATA_COMMAND = 0x43444D57

_MK_LBUTTON = 0x0001

_HOST_CLASS = "CDMWNativeD3D11PreviewWindow"

_REAL_MESH_EDITOR_DOTNET_SCENARIO = "real-archive-mesh-editor-dotnet-edit-smoke"

_REAL_MESH_EDITOR_VISUAL_SCENARIO = _REAL_MESH_EDITOR_DOTNET_SCENARIO

_DOTNET_NATIVE_PARITY_SCENARIO = "mesh-dotnet-native-parity-report"

_SYNTHETIC_D3D11_SCENARIOS = frozenset(
    {
        "full-suite-smoke",
        "native-mesh-editor-d3d11-delta",
        "native-mesh-editor-d3d11-payloads",
    }
)

_SYNTHETIC_MESH_FORMATS = ("pac", "pam", "pamlod")

_DEFAULT_GAME_ROOT = Path(r"C:\games\Steam\steamapps\common\Crimson Desert")

_REAL_ARCHIVE_RIGGING_SAMPLES = (
    "character/model/1_pc/14_ptm/nude/cd_ptm_00_nude_00_0001.pac",
    "character/model/1_pc/10_pgw/nude/cd_pgw_00_nude_00_0001.pac",
)

_REAL_ARCHIVE_ANIMATION_SAMPLE_LIMIT = 8

_REAL_ARCHIVE_ANIMATION_PREFERRED_PAA = (
    "character/motion/1_pc/14_ptm/00_mon/cd_hardptm_baxe_01_01_att_move_f_jumpatt_00.paa",
    "character/motion/1_pc/14_ptm/00_mon/cd_hardptm_baxe_01_01_att_nor_coma_move_f_00.paa",
    "character/motion/1_pc/14_ptm/00_mon/cd_ptm_basic_01_01_nor_std_idle_00.paa",
    "character/motion/1_pc/14_ptm/00_mon/cd_ptm_basic_00_01_normal_stand_idle_000.paa",
    "character/motion/1_pc/cd_phm_basic_00_00_abn_dam_upper_l_end_05_00.paa",
)

_REAL_ARCHIVE_SEQUENCE_SAMPLE = "sequencer/binary__/stageseq/abyssone/cd_seq_abyss_miseenscene_0003.paseqc"

_REAL_ARCHIVE_SEQUENCE_PTM_PAA = "character/motion/1_pc/14_ptm/01_npc/cd_ptm_backpack_00_00_nor_std_idle_ing_03.paa"

_REAL_ARCHIVE_SEQUENCE_PTM_PAB = "character/model/1_pc/14_ptm/ptm_01.pab"

_REAL_ARCHIVE_SEQUENCE_PTM_DESCRIPTOR = "character/prefab/1_pc/14_ptm/nude/cd_ptm_00_nude_00_0001.prefabdata_xml"

_REAL_ARCHIVE_SEQUENCE_PTM_PAPR = "character/model/1_pc/14_ptm/ptm_01.papr"

_REAL_ARCHIVE_SEQUENCE_EXTENSIONS = (".paseq", ".paseqc", ".pastage", ".paschedule", ".paschedulepath")

_ADVANCED_AUTHORING_CORPUS_EXTENSIONS = (
    ".paa",
    ".paseq",
    ".paseqc",
    ".papr",
    ".pabc",
    ".pab",
    ".pac",
    ".pam",
    ".pamlod",
    ".hkx",
    ".xml",
    ".material",
    ".shader",
)

_ADVANCED_AUTHORING_CONFIDENCE_LABELS = ("proven", "inferred", "unknown", "blocked")

_ADVANCED_AUTHORING_STATE_LABELS = ("blocked", "preview-only", "exportable", "archive-mutable")

_LEGACY_SCREEN_CAMERA_FIELDS = frozenset({"camera_world", "yaw_degrees", "pitch_degrees", "distance", "vertical_fov_degrees", "pan"})
