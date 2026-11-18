# 재질 편집 개조 기록 (material-studio 브랜치)

기준: upstream `Ratty123/cdmw-full` `faf38ee` (2026-11-11)에서 시작했고, 2026-11-15에 `97931c6`(0.12.0-alpha.5, 게임 최신 패치 대응)을 합쳤다. 작업 지시서의 단계 번호를 그대로 쓴다.

## 진행 상태

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | XML 원본값을 패널에 표시 | 완료 (Mesh Editor, New Item) |
| 2 | 슬라이더 실시간 반영 | 완료 (Mesh Editor) |
| 3 | 프리셋 | 내장 프리셋과 사용자 프리셋 저장·삭제 완료 |
| 4 | 텍스처 슬롯 교체·파일 감시·채널 보기 | 슬롯 교체와 파일 감시 완료(파일 감시는 Windows 미확인). 채널 보기는 미구현 |
| 5 | 셰이더 변경 재구성 방식 | 선택 옵션으로 완료 (망사·Glass) |
| 6 | 폴더 열기 | 기존 "Drafts & Mods > Add Mod Folder"를 확장해 재질·텍스처까지 불러옴. 추출 폴더처럼 모델이 많으면 검색·선택 창이 뜨고, 셰이더 종류로 걸러 볼 수 있음. 썸네일은 미구현 |
| 7 | 새 모드 폴더 저장·이어서 작업 | 저장은 기존 Build Mod 사용. 모드 폴더 다시 열기는 6단계 기능으로 해결 |
| 8 | 원본 비교·배경 전환 | 배경 빠른 전환, 패널의 "원본 재질 보기" 토글 완료. 체크무늬 배경은 미구현 |
| UI | 전용 "재질 편집" 화면 | 미착수 (기존 Shader experiments 패널만 개편) |

## 1~3단계에서 바뀐 동작

### Mesh Editor > Inspector > Shader experiments
- 체크박스와 "Apply shader controls" 버튼이 없어졌다.
- 각 슬라이더는 **원본 재질(pac_xml)에 적힌 값**에서 시작한다. 아래에 `원본: 0.727`이 표시된다. 재질이 그 파라미터를 선언하지 않았으면 `.material` 기본값과 함께 "이 재질에 지정되지 않은 값"이라고 표시한다.
- 값을 바꾸면 이름 뒤에 `*`가 붙고 강조색이 된다. 옆의 "원본" 버튼이 그 값만 원본으로 되돌린다.
- 슬라이더를 움직이는 동안 뷰포트가 즉시 바뀐다. 메시와 텍스처는 다시 올리지 않고 재질 계수만 교체한다.
- 컨트롤을 놓고 0.12초가 지나면 편집이 호스트(Python)에 전달되어 실행 취소 기록 한 단계로 저장된다.
- 이미 Glass / Transparency 등을 쓰는 재질은 그 셰이더가 선택된 상태로 열린다. 그 밖의 재질은 "원본 셰이더 유지"로 열리고, 드롭다운에서 셰이더를 고르면 바로 적용된다.
- "프리셋 선택": 웨딩 면사포 A / B, 레이스 베일(커뮤니티 모드), 시스루 천 얇게 / 중간 / 진하게.
- 모델 변형(ModelProperty Index)마다 원본 값이 다르면 "모델 변형 N" 선택기가 나타난다. 표시만 바뀌고, 수정은 모든 변형에 적용된다.
- "원본 텍스처" 접기 영역에 파라미터별 텍스처 파일 이름이 나온다(읽기 전용).
- 패널 아래 "배경" 줄에서 뷰포트 배경을 기본 / 블랙 / 회색 / 흰색 / 피부색으로 바로 바꾼다. 재질과 저장 결과에는 영향이 없다.

### New Item > Shader experiments
- 체크하지 않은 필드가 기본값 대신 원본 재질의 값을 보여준다. 체크박스 방식은 그대로다.

## 4~7단계에서 바뀐 동작

### 텍스처 교체 (Shader experiments 패널)

- 셰이더가 읽는 텍스처마다 줄이 생긴다. 망사는 베이스 컬러와 실 굵기(height의 R 채널), Glass와 장비 유리는 베이스 컬러와 노멀이다.
- "교체..."로 DDS, PNG, TGA, JPG, BMP를 고른다. DDS는 그대로 쓰고, 이미지는 BC7 DDS(밉맵 포함)로 인코딩한다. 이미지 변의 길이는 4~8192 사이의 2의 거듭제곱이어야 한다.
- 고른 텍스처는 `%LOCALAPPDATA%/CrimsonDesertModWorkbench/shader_textures/<sha256>.dds`에 보관한다. 편집 상태에는 해시만 저장하므로 초안과 실행 취소가 가볍다. 이 PC에서 파일이 사라지면 "텍스처를 다시 고르라"는 오류가 난다.
- Build Mod 결과에는 `character/texture/<모델 경로>_cdmw_tex_<해시 10자>_<역할>.dds`로 들어가고, pac_xml의 해당 텍스처 경로가 이 이름을 가리킨다. 게임 원본 텍스처 경로는 덮어쓰지 않는다. 모든 ModelProperty 변형에 똑같이 적용하고, 기존 행의 ItemID와 Index는 유지한다.
- "원본"을 누르면 그 텍스처만 원래대로 돌아간다. 바꾼 숫자는 남는다.
- 뷰포트는 교체한 텍스처로 다시 만든 재질을 보여준다. bake한 유리 재질을 다시 올리는 기존 경로(`_stage_baked_glass_materials`)를 그대로 쓴다.

### 셰이더 고유 구성으로 다시 쓰기

- 망사와 Glass를 고르면 "이 셰이더의 파라미터 구성으로 다시 쓰기" 체크박스가 나온다. 기본은 꺼짐이며, 꺼져 있으면 기존 CDMW 방식(원본 행 유지 + 바꾼 행 추가)이다.
- 켜면 그 셰이더를 쓰는 재질의 행 구성 그대로 `_parameters`를 다시 쓴다. 구성에 없는 행(`_renderSettingFlag`, displacement scale 등)은 지우고, 텍스처 행은 구성의 ItemID(7/6/5/4/2)와 새 Index를 받는다. 바꾸지 않은 필드는 셰이더 정의 기본값으로 쓴다. `_permutations`는 `AlphaTest` 하나로 맞춘다.
- 근거:
  - 망사: 원본 웨딩 면사포 `cd_phw_00_hel_00_0219`(wrapper 508)의 구성. 배포된 Lace Veil 모드가 일반 마스크 재질을 이 구성으로 바꿨고, 같은 원본(Black 변형)에 이 기능을 적용하면 그 모드의 Blue 변형과 행 이름·ItemID·순서가 일치한다.
  - Glass: Angel Teddy 모드의 구성. 원본 게임의 Glass 재질(헬멧 바이저)은 읽어보지 못했다.
- 원본에 없는 텍스처 행은 만들지 않는다. 예외는 망사의 `_maskTexture`로, 원본과 모드가 모두 쓰는 `character/texture/Temp_r.dds`를 넣는다.
- 어느 방식이 인게임에서 더 안정적인지는 확인하지 못했다. 둘 다 만들어 비교해야 한다.

### 모드 폴더·추출 폴더 열기 (Drafts & Mods > Add Mod Folder)

- 메시가 없고 pac_xml만 있는 폴더도 받는다. `…/modelproperty/…/x.pac_xml`에서 `…/model/…/x.pac`를 찾아 게임의 메시 위에서 이어 작업한다.
- 폴더 구조는 자동으로 읽는다: 루트에 바로 `character/`, `0009/character/`, `files/0009/character/`, 이름 붙은 상위 폴더 한 겹.
- 모델이 64개 이하인 폴더는 모델마다 한 줄씩 등록된다.
- 모델이 64개를 넘는 폴더(게임 추출 폴더)는 "추가할 모델 선택" 창이 뜬다. 이름이나 경로의 일부를 띄어쓰기로 여러 개 입력해 좁히고, 최대 64개까지 골라 등록한다. 필터를 바꿔도 이미 고른 모델은 유지된다. 이런 폴더는 모드 한 개의 결과물이 아니므로 CDMW 빌드 기록 조회(모든 파일 해시 계산)를 건너뛴다.
- Continue Editing 한 번에 폴더를 파일 종류별로 한 번만 훑는다. 이전에는 파일 하나를 찾을 때마다 폴더 전체를 훑었다.
- 같은 게임 파일의 사본이 둘 이상 있는 폴더(여러 색상 변형의 상위 폴더)는 거절한다. 변형 하나의 폴더를 골라야 한다.
- Continue Editing을 누르면 그 모델의 pac_xml과, 그 pac_xml이 가리키는 텍스처 중 폴더에 있는 것을 게임 파일 대신 쓴다.
  - 게임 파일과 내용이 같은 파일은 건너뛴다. 그래서 수정하지 않은 추출 폴더는 게임 원본을 연 것과 같다.
  - 게임에 있는 경로를 바꾸는 파일은 "수정된 결과", 게임에 없는 경로의 파일(모드 전용 텍스처)은 "추가된 결과"로 표시한다. 기존 규칙에 따라 다음 Build Mod 결과에 함께 들어간다.
  - 폴더의 파일은 작업 영역으로 복사해서 쓴다. 작업 중에 폴더를 고쳐도 세션이 깨지지 않는다. 고친 내용을 반영하려면 다시 Continue Editing을 누른다.
- 폴더에 없는 파일(메시, 스켈레톤, 나머지 텍스처)은 게임 아카이브에서 읽는다. 따라서 Archive Browser에 게임 파일이 로드돼 있어야 하고, 게임에 없는 새 메시 경로(예: Angel Teddy의 `_9934`)는 열 수 없다.
- CDMW는 편집 기록을 모드 폴더가 아니라 이 PC의 기록 폴더에 둔다(원작 설계). 그 기록이 없어도 위 방식으로 폴더의 파일만으로 이어 작업할 수 있다. 이 경우 슬라이더의 "원본" 값은 모드의 현재 값이다.

## 구현 위치

| 파일 | 변경 |
|---|---|
| `cdmw/domain/mesh/shader_controls.py` | `authored_field_numbers`(패널과 렌더러가 함께 쓰는 단일 파서), `authored_values_payload`, `SHADER_PRESETS`, 카탈로그의 `presets` |
| `cdmw/services/mesh_shader_controls.py` | 부위별 `authored`(변형별 셰이더·값·텍스처)와 `preview_base`(호환 셰이더별 계수 32개) |
| `cdmw/core/material_shader_controls.py` | `equipment_authored_values` |
| `cdmw/ui/new_item/*`, `cdmw/services/new_item_template_model.py` | New Item 편집기로 원본값 전달 |
| `tools/rust_mesh_lab/apps/cdmw_mesh_lab/src/cdmw_shader_controls.rs` | 패널 전면 개편, `shader_live_factors` |
| `tools/rust_mesh_lab/apps/cdmw_mesh_lab/src/main.rs` | `UiAction::CdmwShaderPreview`, `UiAction::SetViewportBackground`, `cdmw_shader_live_preview`, `cdmw_live_material_factors`, 호스트 응답·LOD 전환·재질 재설치 시 미리보기 해제 |
| `cdmw/resources/localization/*` | 새 문자열 47개, 14개 언어 |
| `cdmw/core/shader_texture_store.py` | 교체 텍스처 보관소(해시 이름, 변조 검사) |
| `cdmw/domain/mesh/shader_controls.py` | `TEXTURE_SLOTS`, `SHADER_LAYOUTS`, `ShaderControls.textures` / `.rebuild` |
| `cdmw/core/material_shader_controls.py` | `rewrite_texture_paths`, `rebuild_material_layout` |
| `cdmw/services/mesh_shader_controls.py` | `import_shader_texture`, `owned_texture_files`, 교체 텍스처를 출력 파일과 미리보기 의존 파일에 추가 |
| `cdmw/services/mesh_shader_controls_preview.py` | 텍스처를 교체한 재질을 다시 스테이징 |
| `cdmw/services/mesh_saved_work_service.py`, `cdmw/ui/mesh_editor/saved_work_bridge.py` | `folder_model_paths`, `folder_model_choices`, `built_mod_companion_entries`, `_FolderFiles`, 재질 전용 모드의 Continue Editing |
| `cdmw/ui/mesh_editor/folder_model_picker.py`, `saved_work_page.py` | 추출 폴더의 모델 선택 창 |

계수 레이아웃 규칙: 앞 4칸은 헤더, 그 뒤로 카탈로그의 필드 순서대로 `default` 길이만큼 차지한다. Python `preview_factors`와 Rust `shader_live_factors`가 같은 규칙을 쓰며, `tests/test_material_studio_panel_state.py`와 Rust 테스트가 이를 고정한다.

## 검증

- Python: `pytest tests/test_material_studio_panel_state.py`
- Rust: `cargo test -p cdmw_mesh_lab shader`
- 지역화: `python scripts/generate_ui_localization_manifest.py --check`, `python scripts/validate_ui_localization_catalogs.py`
- Linux 컨테이너에서 실행했다. Windows 전용 테스트 2개는 `#[cfg(windows)]`로 묶었다.
- 결과(2026-11-12): Rust `cdmw_mesh_lab` 전체 715 통과 / 1 실패. 실패한 `archive_reader_reconstructs_uploadable_partial_dds…`는 수정 전 기준선에서도 이 Linux 환경에서 실패한다. 관련 Python 테스트 묶음은 기준선 대비 새 실패 없음(기준선 실패 104개는 Linux 환경 문제로 그대로).
- 결과(2026-11-13, 4~7단계 포함): Rust `cdmw_mesh_lab` 716 통과 / 2 실패. 하나는 위의 기준선 실패이고, 다른 하나(`hair_rapid_draw_preserves_every_stroke…`)는 60초 제한이 있는 테스트로 다른 테스트와 함께 돌릴 때만 시간 초과했다. 단독으로는 3회 모두 통과한다. 관련 Python 테스트는 기준선 대비 새 실패 없음.
- 아이템 패키지(v1) 코덱에는 `ShaderControls.textures`와 `.rebuild`를 '패키지에 담지 않는 필드'로 등록했다. 이 값을 쓴 설정을 아이템 패키지로 내보내면 거부된다. New Item 화면은 두 기능을 노출하지 않는다.
- 4~7단계 테스트: `pytest tests/test_material_studio_textures.py tests/test_material_studio_mod_folder.py`, `cargo test -p cdmw_mesh_lab shader_`.
- **Windows 통합 실행(Python 호스트 + Rust 뷰포트)과 인게임 결과는 확인하지 못했다.** 특히 다음은 Windows에서만 동작을 볼 수 있다.
  - 이미지(PNG 등)를 DDS로 인코딩하는 부분(DirectXTex 도우미 사용)
  - 텍스처 교체 후 뷰포트가 새 텍스처로 다시 그려지는 부분
  - Add Mod Folder → Continue Editing으로 Mesh Editor가 실제로 열리는 흐름

## 2차 수정 (2026-11-15)

사용자가 Windows 빌드로 웨딩 면사포를 열어 본 뒤 요청한 내용이다. 지시서는 프로젝트 문서 `CDMW_재질편집_2차수정_프롬프트_2026-11-14.md`에 있다.

### 원본 값 검증
- 패널 위에 재질 파일 이름(마우스를 올리면 전체 경로), 부위 이름, 그 파일에서 몇 번째 재질 wrapper인지 표시한다.
- "원본 재질 행" 접기 영역이 그 wrapper의 행을 파일에 적힌 그대로 보여준다(이름, 값 또는 텍스처 경로. 마우스를 올리면 종류·ItemID·Index). "행 복사"는 탭으로 구분한 텍스트를 클립보드에 넣는다.
- 첫 편집 전에는 뷰포트가 실제로 그린 wrapper의 값만 알 수 있어, 그 값과 텍스처 경로만 보여준다(ItemID 없음). 한 번 편집하면 pac_xml 전체가 세션에 들어와 모든 변형의 행을 원문으로 보여준다.
- **고친 불일치:** 변형이 여러 개인 pac_xml에서, 첫 편집 뒤에는 패널이 파일의 첫 변형(Index 0) 값을 "원본"으로 보여줬다. 뷰포트가 다른 변형을 그리고 있어도 그랬다. 이제 뷰포트가 그리는 변형(preview의 owner wrapper)이 항상 맨 앞에 오고, 실시간 미리보기의 기준 값도 그 변형에서 가져온다. 변형 선택기는 "모델 변형 Index n (뷰포트에 표시 중)"처럼 실제 Index를 표시한다.
- **미해결:** 사용자가 본 0.142 / 0.275가 어느 wrapper의 값인지는 실제 `cd_phw_00_hel_00_0219.pac_xml`이 있어야 확정할 수 있다. `_02_disp.dds`를 쓰는 다른 변형이거나 다른 부위일 가능성이 높다. 새 "원본 재질 행"으로 사용자가 직접 대조할 수 있다.

### 선택 강조
- Shader experiments 패널이 열려 있는 동안 선택한 부위의 주황색 채우기를 그리지 않는다(기본 켜짐, 패널의 체크박스로 끌 수 있다). 선택 상태는 그대로다.
- 외곽선만 그리는 방식과 단축키는 넣지 않았다. 렌더러에 외곽선 방식이 없고, 단축키는 재지정 가능한 키맵 체계에 등록해야 한다.

### 조명
- 패널의 "조명" 줄: 카메라 따라가기(기존) / 정면 / 측면 / 뒤(역광) / 위. 누른 순간의 시점을 기준으로 조명을 놓고, 그 뒤에는 장면에 고정된다. 카메라를 돌려 역광 상태를 볼 수 있다.
- 조명을 놓으면 세기 슬라이더(0~2)가 나온다.
- 조명을 놓았을 때만 면사포에 역광 항을 더한다: `albedo × _glow × (빛이 카메라 반대편에 있는 정도)² × 세기 × 0.9`. 근사값이며 게임 셰이더의 식이 아니다.
- "카메라 따라가기"에서는 셰이더 경로가 이전과 같다(uniform 기본값이 기존 계산을 그대로 탄다).

### 게임 화면 크기 (면사포 전용)
- 게임의 망사 간격 식 `pitch × 0.0015 × 2√(3840×2160 / 픽셀 수)`의 계수를 고를 수 있다: 1920 x 1080(4), 2560 x 1440(3, 기본), 3840 x 2160(2).
- 실 굵기 맵은 `height.R(uv / _uvScale)`로 읽는다(상류 연구 문서의 DXIL 분석과 일치). 따라서 꽃무늬 밀도는 `_uvScale`이 정하고, 화면 크기와는 무관하다.

### 원본 재질 보기
- 저장된 셰이더 변경이 있을 때 패널에 "원본 재질 보기" 토글이 나온다. 기존 비교 명령(`replacement_compare`)을 그대로 쓴다. 모델 전체가 변경 전 상태로 표시되고, 다시 누르면 편집 상태로 돌아온다.

### 텍스처 파일 감시
- "교체..."로 고른 파일을 이번 실행 동안 감시한다. 파일이 다시 저장되면(수정 시각이나 크기가 바뀌고 0.6초 동안 더 바뀌지 않으면) 같은 부위·같은 슬롯에 다시 넣는다. 포토샵 등에서 저장하면 뷰포트가 따라온다.
- 그 슬롯을 "원본"으로 되돌리거나 실행 취소하면 감시가 끝난다. 앱을 다시 켜면 감시는 이어지지 않는다(파일 경로를 초안에 저장하지 않는다).
- 슬롯 아래에 "… 파일을 다시 저장하면 자동으로 다시 불러옵니다"가 표시된다.

### 바꾼 파일 (2차)
| 파일 | 내용 |
|---|---|
| `cdmw/core/material_shader_controls.py` | `material_source_details`: wrapper별 원문 행, 변형, 파일 내 위치 |
| `cdmw/services/mesh_shader_controls.py` | 패널 상태에 `source`, 변형 Index, 원문 행 추가. 뷰포트 변형을 맨 앞으로 |
| `tools/rust_mesh_lab/crates/cdmw_render_wgpu/src/lib.rs` | 카메라 uniform에 `preview_light`, `preview_settings` 추가(288 → 320바이트), `set_material_inspection`, `camera_basis` |
| `tools/rust_mesh_lab/apps/cdmw_mesh_lab/src/main.rs`, `cdmw_shader_controls.rs` | `MaterialInspection` 상태와 패널 UI |
| `cdmw/resources/localization/*` | 새 문자열 22개 |

## 3차 추가 (2026-11-15)

### 사용자 프리셋
- 프리셋 목록 아래에 이름 입력칸과 "프리셋 저장" 버튼이 있다. 지금 슬라이더에 보이는 모든 값(바꾼 값, 원본 값, 정의 기본값)을 그 이름으로 저장한다. 같은 이름(대소문자 무시)은 교체한다.
- 저장한 프리셋은 내장 프리셋 뒤에 준 이름 그대로 나온다. "저장한 프리셋 삭제" 목록에서 지운다.
- 저장 위치는 `%LOCALAPPDATA%/CrimsonDesertModWorkbench/shader_presets.json`이다. 셰이더당 48개까지. 초안이나 모드는 이 파일을 참조하지 않으므로 지워도 작업이 깨지지 않는다.
- 호스트 명령은 기존 `replacement_shader_controls`에 `preset` 인자를 실어 보낸다. 모델 편집이 아니므로 실행 취소 기록을 만들지 않는다.

### 모델 선택 창의 셰이더 필터
- 추출 폴더를 Add Mod Folder로 열면, 각 모델의 pac_xml이 쓰는 셰이더 이름을 읽어 "모든 셰이더 / SkinnedMeshStandard (n) / SkinnedMeshTransparency (n) …" 목록을 만든다. 많이 쓰인 순서다.
- `SkinnedMeshTransparency`를 고르면 게임이 망사 셰이더를 준 모델만 남는다. 이름 필터와 함께 쓸 수 있다. 원본 게임에서 망사·Glass가 어디에 쓰였는지 찾는 용도다.
- 메시만 있고 pac_xml이 없는 모델은 셰이더 정보가 없어 "모든 셰이더"에서만 보인다.

### 바꾼 파일 (3차)
| 파일 | 내용 |
|---|---|
| `cdmw/core/shader_preset_store.py` | 사용자 프리셋 저장소 |
| `cdmw/services/mesh_shader_controls.py` | `catalogue_with_user_presets`, `preset` 요청 처리 |
| `cdmw/services/mesh_saved_work_service.py` | `folder_model_shaders` |
| `cdmw/ui/mesh_editor/folder_model_picker.py`, `saved_work_page.py` | 셰이더 필터 |
| `tools/rust_mesh_lab/apps/cdmw_mesh_lab/src/cdmw_shader_controls.rs` | 프리셋 저장·삭제 UI |
| `tests/test_material_studio_presets.py` 외 | 테스트 |

## 4차: 11월 패치 웨딩 면사포 대응 (2026-11-15)

### 확인한 사실
- 게임 업데이트로 `cd_phw_00_hel_00_0219.pac_xml`이 바뀌었다(메시 .pac은 동일). 면사포 천(wrapper 3)은 0.142 / 0.275 / 0.516 / 0.901이고, `_baseColorTexture`, `_uvScale`, `_dyeingColor`가 빠졌다.
- `SkinnedMeshTransparency.material`도 바뀌었다. `SkinnedMeshStandardParameterSet_Ver2`와 `PartColorBlendingParameterSet`을 쓰고(`USE_COMMON_PIXEL_VER2`), `_dyeingTransformProperty0/1/3`(Mask R/G/B Scale X, Scale Y, Offset X, Offset Y)이 추가됐다.
- 레이스 무늬는 디테일 레이어로 옮겨졌다. `_detailDiffuseMaskR` = 잔잔한 반복 레이스(`0219.dds`, 1024²), `_detailHeightMaskR` = 큰 꽃무늬(`0219_disp.dds`). `_colorBlendingFlag 13` = R 채널의 Diffuse, Material, Height 디테일 사용. `_colorBlendingMaskTexture`는 `temp_r.dds`(전체 R).
- `_heightTexture`는 새 `0219_02_disp.dds`로, 반복 무늬가 아니라 메시 UV에 맞춰 구운 주름 맵이다.
- `_dyeingTransformProperty0 = 11565` → 바이트 [45, 45, 0, 0] → Scale 0.176 × 0.176, Offset 0. CDMW 결합기 규칙(`(uv - 0.5 - offset) / scale`)으로는 약 5.7회 반복이다. `_dyeingPropertyBlend`의 R 회전 바이트는 0이다.
- CDMW 미리보기의 망사(family 11)는 패치 전 셰이더(베이스 + 높이 맵)만 구현한다. 그래서 새 면사포는 주름 맵이 실 굵기로 쓰이고 레이스는 그려지지 않는다.

### 고친 것
- 편집 세션 전 미리보기 메타데이터로 만든 원본 행에, 같은 파일의 다른 wrapper(화관 고리)의 행이 섞이던 문제. 부위가 그려진 wrapper(owner slot)의 입력만 쓴다. 텍스처 행은 빈칸 대신 해석된 경로를 보인다.
- 내장 프리셋: "웨딩 면사포: 천 / _01 부위"(패치 후 값), "웨딩 면사포 (패치 전): 천 / _01 부위".
- 디테일 레이어를 쓰는 망사 재질이면 패널에 "레이스 무늬와 밀도가 미리보기에 정확히 표시되지 않음" 경고.

### 남은 것
- 새 면사포를 제대로 그리려면, 망사 커버리지와 디테일 레이어(레이스)가 어떻게 합쳐지는지 알아야 한다. 정의 파일만으로는 합성 순서와 수식을 알 수 없다(셰이더 DXIL 필요).
- 처음 열 때와 다시 열 때 화면이 다른 문제: 다시 연 화면의 큰 꽃무늬 구멍은 `_detailHeightMaskR`(큰 꽃무늬)가 반복 없이 메시 UV 그대로 깔린 모습이다. Mesh Editor의 합성 미리보기(Preview Core 그래프 → Rust 합성기)가 디테일 레이어의 Mask 변환(`_dyeingTransformProperty0/1/3`, `_dyeingPropertyBlend`)을 무시했기 때문이다. Python 재질 결합기는 이미 적용하고 있었다.
  - 수정(2026-11-15): 패키지 빌더가 각 wrapper의 파라미터에서 레이어별 `uv_transform`을 계산해 넣고, Rust 합성기가 레이어 자신의 diffuse·material·normal·height 텍스처를 그 변환으로 반복 샘플링한다(마스크는 제외). 면사포는 레이스가 약 5.7회 반복된다.
  - 처음 열 때의 화면(주름 맵만 보이는 매끈한 베일)은 Archive Browser가 준비한 재질을 그대로 쓰는 다른 경로로 보인다. 두 경로가 같아지는지는 실제 앱에서 확인해야 한다.
  - 회전 부호: 결합기는 세로로 뒤집은 이미지에서 계산한다. 합성기는 DDS 원래 방향이라 Y 오프셋과 회전 부호를 바꿨다. 중심 기준·180°·무회전 변환에서는 두 식이 같다.

## 5차: 새 면사포를 게임 셰이더 식으로 그리기 (2026-11-16)

근거는 `blablahandsome1212/rigging`의 `docs/character-library/shader-research/veil-update-2026-11-16/`에 있는 DXIL 디스어셈블이다(기준 변형 `..._fd5b7acb_2_bd122a23_151cd770`).

### 확정 (DXIL 명령 근거)
- 실 굵기: `_netThread × 0.0003 × (Hbase + Hdetail) × _screenSpaceDisplacementScale`, 뒷면 ×4, 그 뒤 `min(굵기, 칸 간격)`.
- `Hdetail = opacity × mask × 디테일 높이(디테일 UV).r × _detailScreenSpaceDisplacementScale`. opacity는 `_dyeingGlobalOpacity`의 채널 바이트 / 255다.
- 디테일 UV(`%236–%249`, 원문 재확인): `qx = (u − 0.5 − Ox) / Sx`, `qy = (v − 0.5 + Oy) / Sy`, `u' = qx·cos − qy·sin + 0.5`, `v' = qx·sin + qy·cos + 0.5`, `θ = 회전 바이트 × 2π/255 − π`.
- 알파: `C = 망사 coverage × _overlayColorTexture 알파`, 색은 C로 premultiply, 블렌드 알파는 `C × 0.99`. 패치 전의 앞면 0.3 / 뒷면 0.7과 base 알파 × 염색 알파는 쓰지 않는다.
- 행이 없을 때의 기본값(정의 파일): `_screenSpaceDisplacementScale` 1.0(면사포 `.material`), `_detailScreenSpaceDisplacementScale` 0, `_dyeingGlobalOpacity` 0, 회전 0.5(바이트 128), Transform (1, 1, 0, 0), `_overlayColorTexture` = `nonetexture0xff888888`(알파 1).

### 구현
- **Rust 합성기의 디테일 UV**(`repeat_by_layer_transform`)를 위 식 그대로 고쳤다. 이전에는 Oy 부호와 회전 방향이 반대였다(면사포는 오프셋 0, 180°라 결과가 같았다).
- **렌더러**(`cdmw_render_wgpu`, kind 11): 13번 칸이 1이면 새 식을 쓴다. 14 = `_screenSpaceDisplacementScale`, 15 = `_detailScreenSpaceDisplacementScale`, 16 = opacity × mask, 17–20 = Scale X, Scale Y, Offset X, Offset Y, 21 = 회전(라디안), 22 = overlay 알파. 디테일 높이 텍스처는 shader mask 슬롯으로 받아 디테일 UV로 직접 샘플링한다(원본 DDS의 밉맵을 그대로 쓴다). 13번 칸이 0이면 패치 전 식 그대로다.
- **Python**(`cdmw/domain/mesh/shader_controls.py`): `veil_layer_inputs`가 원본 셰이더가 망사이고 `_detailHeightMask*`가 있거나 `_colorBlendingFlag`의 하위 12비트가 켜져 있을 때만 새 칸을 채운다. 패치 전 면사포, Lace Veil 모드, Glass는 벡터가 이전과 같다(테스트로 고정).
- **두 열기 경로를 같게**: 새 망사 부위는 편집기로 보낼 때 항상 자기 `_heightTexture`(주름 맵)를 height로, 선택된 채널의 `_detailHeightMask*`를 shader mask로 넘긴다(`_mesh_texture_payloads`). 합성 그래프에서는 망사 wrapper의 디테일 height를 빼서, Rust 합성기가 레이스를 주름 맵 위에 덮어쓴 height를 만들지 않게 했다.
- **패널**: 새 망사에서는 `_uvScale`, `_dyeingColor`를 숨기고(원본에 행이 있으면 보인다), "디테일 레이어 값 (읽기 전용)"에 변위 배율 두 개와 채널, 반복 횟수, 오프셋, 회전을 보인다. "다시 쓰기"를 켜면 패치 전 구성이 되므로 실시간 미리보기도 디테일 레이어를 끈다.
- **재질 쓰기**: 새 망사에는 `_uvScale`, `_dyeingColor` 행을 새로 추가하지 않는다(이미 있는 행은 고친다).

### 추정
- 채널 선택: `_colorBlendingMaskTexture`의 최대 채널을 텍스처를 디코드하지 않고 파일 이름(`temp_r/g/b.dds`)으로 정한다. 그 외의 마스크면 디테일 높이 텍스처가 있는 첫 채널을 쓰고 마스크 값은 1로 본다.
- overlay 알파: `nonetexture0xAARRGGBB` 이름이면 그 알파, 다른 텍스처면 1로 본다.
- 렌더 파라미터 offset 40의 진입 조건 `(v & 254) < 2`는 의미가 확인되지 않아 "켜짐"으로 뒀다.
- 조명(`lightingRGB`)은 기존 근사 그대로다. 새 프로필은 base 색에 `linear_to_srgb`와 염색 색을 적용하지 않는다(새 정의에서 `_baseColorTexture`가 sRGB=True).

### 확인한 것 / 못 한 것
- 실제 파일(패치 후·패치 전 `cd_phw_00_hel_00_0219.pac_xml`)로 벡터를 확인했다. 천: 13–22번 칸 = 1, 1, 1.732, 1, 0.176, 0.176, 0, 0, −π, 1. `_01` 부위는 `_detailScreenSpaceDisplacementScale` 행이 없어 디테일 가산이 0이다. 패치 전 파일은 13번 이후가 모두 0이다.
- Python 결합기(`_apply_pac_layer_sampling_transform`)는 DXIL과 같은 식을 쓰지만, 세로로 뒤집은 이미지에 적용하는 호출이 있다. 그 경우 Oy와 회전 방향이 반대가 된다(오프셋 0, 0°/180°에서는 같다). 원작자 코드라 고치지 않았다.
- 이 환경에는 GPU가 없어 화면 캡처는 만들지 못했다. WGSL은 naga 검증과 문자열 테스트로, 식은 Python 참조 구현으로 확인했다. 처음 열 때와 다시 열 때가 같아졌는지는 Windows 빌드에서 봐야 한다. 두 경로의 base 색(다시 열 때는 `_detailDiffuseMaskR` 합성)이 다를 수 있다.
- 변위 배율 두 개의 슬라이더와 Byte4 Transform 편집은 넣지 않았다(행 쓰기 규칙 미확정).

### 다시 열 때 레이스 패턴 문제 (2026-11-16 저녁)
- 증상: Archive Browser에서 처음 열면 정상, Close 직후 "Open Selected Mesh"로 다시 열면 큰 얼룩 구멍. "Show target in archive" 후 다시 열면 정상.
- 원인: 다시 열 때는 Archive Browser가 준비한 재질 대신 Preview Core 패키지(manifest의 batch)로 재질을 다시 만든다. 이 패키지는 부위별 입력과 wrapper 파라미터를 `dds_textures.material_inputs` 아래에 쓰는데(`native/cdmw_preview_core/src/owners/package_writer_json.cpp`), 레이어 복사 코드는 batch 최상위 `material_inputs`만 읽었다. 그래서 이 경로에서는 디테일 레이어의 UV 변환(약 5.67회 반복)과 "망사는 디테일 높이를 합성하지 않음"이 둘 다 빠져, 레이스가 반복 없이 주름 맵 위에 덮어씌워진 높이가 실 굵기로 쓰였다.
- 수정: `_preview_core_batch_material_inputs`가 두 위치를 모두 읽는다. 테스트는 두 형태의 batch를 모두 확인한다.

### 다시 열 때 문제의 실제 원인 (2026-11-17, 세션 폴더 비교)
- 앞의 `dds_textures` 수정은 맞는 수정이었지만 원인은 아니었다. 사용자가 보낸 두 세션 폴더(정상 / 깨짐)의 `manifest.json`을 비교해서 찾았다.
- 깨진 세션에서는 부위와 재질의 짝이 어긋나 있었다.
  - 화관(`Hel_Ring_00_0169`, `Hel_00_0169`)에 면사포 셰이더(SkinnedMeshTransparency)가 붙어, 망사로 그려져 사라졌다.
  - 면사포 천(`0219`)에는 `_01` 부위의 높이 맵(`0219_01_disp`)이 붙었다.
  - `_01` 부위는 셰이더를 잃었다.
  - `texture_status`에는 `compiler_owner_conservation_failed`(부위 0, 2, 3)가 기록돼 있었다.
- 경로: 첫 번째 열기가 Archive Browser 렌더러를 멈춘다(`_strip_archive_preview_heavy_payloads_for_mesh_editor`). 그래서 다시 열 때는 활성 패키지가 없어 `material_context_verified_for_rust`가 False가 된다. 그러면 `MeshArchiveMaterialContextWorker`가 원작자 설계대로 네이티브 패키지 batch로 재질 모델을 다시 만드는데, 이 메시에서는 그 짝짓기가 틀린다. "Show target in archive"를 거치면 Archive Browser가 미리보기를 다시 만들어 첫 번째 열기와 같은 경로를 탄다.
- 수정(`shell_bridge.py`의 `_mesh_editor_retained_textured_package_for_entry`): Archive Browser가 같은 모델의 미리보기 결과(해석된 재질 모델과 패키지)를 아직 들고 있고 그 패키지가 디스크에 있으면, 그것으로 첫 번째 열기와 똑같이 연다. 현재 미리보기 결과가 참조하는 패키지는 정리 대상에서 빠지므로 남아 있다.
- 남은 것: 미리보기 결과가 없을 때(다른 모델을 보다가 Mesh Editor에서 여는 경우 등)는 여전히 네이티브 batch 경로를 탄다. 그 경로의 짝짓기 오류는 원작자 네이티브 코어(`package_writer_json.cpp`의 batch `shader_family` = 첫 binding의 family) 쪽 문제라 고치지 않았다.

### 다시 열 때 문제, 세 번째 수정 (2026-11-17 새벽)
- `e3516e8` 빌드에서도 그대로였다. 두 세션 폴더를 다시 읽어 보니, 정상 세션의 텍스처 패키지는 Archive Browser의 "현재 미리보기 결과"가 아니라 렌더러가 쓰던 활성 패키지(텍스처 단계 결과)에서 왔다. 현재 미리보기 결과에는 텍스처 없는 패키지가 남을 수 있어서, `e3516e8`의 재사용 조건이 맞지 않았던 것으로 본다.
- Archive Browser 상태에 기대지 않도록 바꿨다. Mesh Editor 세션이 닫힐 때, 검증된 재질 정보(해석된 재질 모델, 패키지 경로, 패키지 lease)를 버리지 않고 한 벌 보관한다(`_stash_reusable_archive_material_context`). 같은 모델(identity와 prepared_sha256이 같음)을 검증되지 않은 정보로 다시 열면 보관해 둔 것을 쓴다(`_take_reusable_archive_material_context`). lease를 쥐고 있으므로 패키지는 디스크에 남는다. 다른 세션이 닫히며 새로 보관하거나 프로그램이 종료될 때 이전 lease를 놓는다.
- 참고: 두 세션 모두 디테일 높이(레이스) 텍스처가 shader mask로 전달되지 않았다. 정상 세션의 꽃무늬는 합성된 base 색에서 온 것이고, 실 굵기는 주름 맵만 반영했다. 이 부분은 다시 열기 문제가 해결된 뒤 따로 본다.

### 남은 작업 일괄 진행 (2026-11-17 새벽)
- **레이스 높이 텍스처 전달**: 정상 세션에서도 레이스 텍스처가 shader mask로 넘어가지 않았다. Archive Browser 모델의 텍스처 입력에는 원본 경로(`source_texture_path`)가 비어 있고 추출된 파일 경로만 있었는데, 코드는 원본 경로만 봤다. `source_inputs`가 추출 경로도 쓰도록 하고, 마스크 채널 판정은 해시가 앞에 붙은 이름(`a5793a…_temp_r.dds`)도 인식하게 했다.
- **변위 배율 슬라이더**: 망사 재질의 필드에 `_screenSpaceDisplacementScale`("실 굵기 배율", ItemID 3)과 `_detailScreenSpaceDisplacementScale`("레이스 강도", ItemID 3900249546424318)를 추가했다. 칸 배치가 바뀌었다: 4 pitch, 5 thread, 6 glow, 7 sheen, 8 uvScale, 9 실 굵기 배율, 10 레이스 강도, 11–13 색, 14 색 알파, 15 레이어 켜짐, 16 opacity × mask, 17–20 Transform, 21 회전, 22 overlay 알파. 디테일 레이어가 있는 망사에서만 두 슬라이더가 보이고 그때만 행을 쓴다. 프리셋 저장도 보이지 않는 필드는 넣지 않는다.
- **선택 강조 단축키**: Shift+H(키보드 단축키 창에서 변경 가능)로 선택 강조를 언제든 숨기거나 표시한다. 선택 상태는 그대로다.
- **하지 않은 것과 이유**
  - Transform(반복·오프셋·회전) 편집: `_dyeingTransformProperty*`와 `_dyeingPropertyBlend`는 채널 세 개가 한 행에 묶인 Byte4라, 기존 필드 구조(32칸, 필드 하나 = 행 하나의 숫자)로는 넣을 수 없다. 별도 편집 구조가 필요하다.
  - 체커 배경: 뷰포트 배경은 단색 clear라서 렌더 패스를 새로 만들어야 한다.
  - 선택 외곽선: 렌더러에 외곽선 그리기가 없다. 숨기기와 단축키로 대신한다.
  - 텍스처 채널 보기: 편집기의 보기 모드(Base Color, Base Alpha, Normal Map, Layer Mask)가 이미 있어 새로 만들지 않았다.
  - 모델 선택 창 썸네일, 전용 "재질 편집" 화면: 범위가 커서 하지 않았다.
  - Create New Item 화면의 망사 필드 목록에도 새 슬라이더 두 개가 보인다. 그 화면의 재질에는 디테일 레이어가 없어 저장할 때 쓰이지 않는다.

### 레이스 Transform 편집 (2026-11-17 오후)
- 사용자 확인: 다시 열기 문제 해결, 레이스 강도·실 굵기 배율 슬라이더 동작. Shift+H는 동작하지 않음(원인 미확인, 보류).
- 망사 재질에 "추가 컨트롤"(`ShaderFamily.extras`) 세 개를 넣었다: `veilDetailRepeat`(레이스 반복 X/Y, 1–64), `veilDetailOffset`(오프셋 X/Y, 0–1), `veilDetailRotation`(회전, −180–180도). 행 하나에 대응하지 않고 미리보기 칸도 따로 차지하지 않는다.
- 저장 규칙(DXIL의 디코드 식을 뒤집은 것): scale 바이트 = round(255 / 반복)(최소 1), offset 바이트 = round(오프셋 × 255), 회전 바이트 = round((도 + 180) / 360 × 255). 사용 중인 채널(R/G/B)의 `_dyeingTransformProperty0/1/3`과 `_dyeingPropertyBlend`의 해당 바이트만 바꾸고 나머지 바이트는 그대로 둔다. 행이 없으면 게임 파일의 ItemID(2380709743296510 / 2427310400602110 / 3193012944371710 / 3323518988058622)로 추가하고, 정의 기본값(scale 1, offset 0, 회전 128)에서 시작한다.
- 미리보기(Rust `shader_live_factors`, Python `veil_layer_factors`)는 저장될 바이트로 양자화한 값을 17–21번 칸에 넣는다. 편집 미리보기와 저장 후 다시 읽은 값이 같음을 테스트로 고정했다.
- 디테일 레이어가 없는 망사에는 보이지 않고, 저장해도 행을 쓰지 않는다.
- 인게임 확인 필요: 이 쓰기 규칙은 셰이더의 읽기 식에서 유도한 것이라, 값을 바꾼 모드를 게임에 넣어 실제로 반복·회전이 바뀌는지 확인해야 한다.
- 체커 배경과 선택 외곽선은 렌더 파이프라인을 새로 만들어야 하고 이 환경에는 GPU가 없어 실행 확인을 할 수 없으므로, 편집기 전체가 깨질 위험을 피하려고 넣지 않았다.

### StandardMesh_Ver2 의상을 망사·레이어 유리로 바꾸기 (2026-11-17 오후)
- 사용자 보고: Ver2 재질 의상에서 Sheer net veil이 비활성.
- 원인: 원작자 규칙상 Sheer net veil과 Layered glass는 plain 재질(`SkinnedMeshStandard`/`SkinnedMeshEmissive`)에서만 바꿀 수 있다. `SkinnedMeshStandard_Ver2`는 염색 색과 디테일 레이어를 셰이더 안에서 섞는 재질이라, 그대로 바꾸면 base 레이어만 남는다. Equipment glass만 "레이어를 먼저 한 장의 텍스처로 굽는(bake)" 경로가 있었다.
- 수정: 같은 bake 경로를 두 셰이더에도 쓴다(`BAKED_CONVERSION_SHADERS`). bake 결과는 plain `SkinnedMeshStandard`(base, normal, material 맵)이고, 그 위에 망사/유리 행을 쓴다. 미리보기도 Equipment glass처럼 구운 맵으로 다시 그린다.
- 망사로 바꾼 의상에는 `_heightTexture`가 없어서 실 굵기가 고르다. 텍스처 교체(Thread width texture)로 높이 맵을 넣을 수 있다.
- 염색 색은 구운 텍스처에 고정된다(Equipment glass와 같음).
- 이 환경에는 bake에 쓰는 네이티브 DDS 디코더가 없어서 bake 테스트는 Windows CI에서 돈다(원작자 기존 bake 테스트도 같다). 디코드 단계를 바꿔 넣은 확인에서는 세 셰이더 모두 레이어 행이 빠지고 대상 셰이더로 쓰였다.

### 마무리 보강 (2026-11-17 저녁)
- Shift+H: 헤드리스 테스트에서는 누르고 떼기를 두 번 하면 정상적으로 꺼지고 켜진다. 사용자 환경에서 안 되는 이유는 확인하지 못했다(한/영 입력 상태나 포커스로 추정). 키보드와 무관하게 쓸 수 있도록 Viewport 설정에 "Hide selection highlight" 체크박스, 셰이더 패널에 "Hide / Show selection highlight" 버튼을 넣었다.
- Ver2 → 망사·레이어 유리 변환을 Mesh Editor, Create New Item 템플릿, 가져온 모델 세 경로에서 확인했다(디코드 단계만 대체).
- 최종 정리와 남은 작업은 `HANDOFF.ko.md`에 있다.

### 강제 교체 (2026-11-18)
- 사용자 요청: 재질 자체를 바꿔서라도 의상을 투명하게 만들기. 게임에서 비쳐 보이는 재질은 망사(`SkinnedMeshTransparency`)와 유리(`SkinnedMeshGlass`) 계열이라, Cloth·Cloth_Ver2처럼 원본 검사에서 막히는 재질도 이 둘로 바꿀 수 있어야 한다.
- 셰이더 패널에 "Replace the material outright (force)" 체크박스를 넣었다. 켜면:
  - 다시 쓰기(rebuild)가 강제로 켜진다. 재질의 모든 행을 지우고 선택한 셰이더의 고유 행만 새로 쓴다.
  - 원본 셰이더 검사와 레이어 굽기(bake)를 건너뛴다. 장비가 아닌 정적 메시, 원본 재질 정보가 없는 부위, Glow·Translucency를 적용한 부위에는 체크박스가 나오지 않는다(호스트가 부위별 `forceable`로 알려준다).
  - 강제로 고른 셰이더도 슬라이더를 움직이는 동안 실시간 미리보기가 된다(`preview_base`에 포함).
  - "원본 재질에서 유지할 텍스처" 체크박스가 나온다. `_baseColorTexture`는 항상 유지하고, normal / material / height 텍스처는 끌 수 있다. 끈 텍스처는 셰이더 기본값(비어 있음)으로 쓴다.
- base 텍스처가 없는 재질(색을 전부 디테일 레이어에서 가져오는 Ver2 의상, 예: `cd_phw_00_uw_00_0001`)은 게임의 단색 텍스처 `texture/nonetexture0xffRRGGBB.dds`를 base로 쓴다. 색은 `_dyeingDetailLayerColorMaskR` → `_tintColorR` → `_dyeingColor` 순으로 찾고, 없으면 회색(888888)이다. 게임 정의 파일이 기본값으로 같은 형식(`nonetexture0xff888888`)을 쓰지만, base 자리에서 동작하는지는 인게임 확인이 필요하다.
- 대가: 원본이 셰이더 안에서 섞던 염색 색과 디테일 레이어는 사라진다. base 텍스처가 회색인 의상은 회색이 된다. 미리보기로 판단한다.
- 데이터: `ShaderControls.force`, `ShaderControls.dropped_textures`. force는 rebuild 없이 쓸 수 없고, dropped_textures에는 그 셰이더 구성의 텍스처 이름(base 제외)만 들어간다.
- 테스트: `tests/test_material_studio_force_replace.py`(Cloth_Ver2 + Cloth 픽스처, 거부·교체·텍스처 제외·직렬화·Ver2 직접 교체), Rust 헤드리스 `force_replace_opens_a_refused_shader_and_sends_the_rewrite_with_the_kept_textures`.
- 결과: Rust `cdmw_mesh_lab` 724 통과 / 2 실패(기준선에서도 실패하는 `loader` 테스트, 단독 실행 시 통과하는 60초 제한 hair 테스트). 관련 Python 테스트 83개 파일은 원작자 기준선과 파일별 결과가 같다. 새로 실패한 것은 bake를 쓰는 Ver2 변환 테스트 4개뿐이며, 네이티브 DDS 디코더가 없어서다(Windows CI에서 확인).
- 인게임 확인 필요: Cloth 계열을 망사로 바꾼 모드가 게임에서 깨지지 않고 비쳐 보이는지. Cloth 셰이더 고유의 물리·바람 설정은 재질 행이 아니라 메시 쪽에 있다고 보고 있지만 확인하지 않았다.

## 남긴 결정 사항

1. `_screenSpaceDisplacementScale`은 슬라이더로 추가하지 않았다. 유일한 근거인 Angel Teddy 모드가 이 행에 작은 ItemID 3을 쓰는데, 작은 ID의 규칙이 밝혀지지 않았다. 다만 Glass를 "다시 쓰기"로 만들면 그 모드의 구성대로 이 행(ItemID 3)을 넣는다. 원본에 값이 있으면 그 값을, 없으면 0을 쓴다.
2. "시스루 천: 얇게" 프리셋의 Opacity는 0.34다. Angel Teddy의 0.40에 glassColor 알파 `d7`(0.843)을 곱한 값이다. 색 편집은 원본 알파를 유지하므로 알파를 직접 쓸 수 없다.
3. 실시간 미리보기는 호스트가 `preview_base`를 준 셰이더에서만 동작한다. 텍스처 bake가 필요한 변환이나 마스크를 칠한 재질은 놓은 뒤 호스트가 다시 만든 결과로 갱신된다.
