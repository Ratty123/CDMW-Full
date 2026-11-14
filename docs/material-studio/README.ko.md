# 재질 편집 개조 기록 (material-studio 브랜치)

기준: upstream `Ratty123/cdmw-full` `faf38ee` (2026-11-11). 작업 지시서의 단계 번호를 그대로 쓴다.

## 진행 상태

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | XML 원본값을 패널에 표시 | 완료 (Mesh Editor, New Item) |
| 2 | 슬라이더 실시간 반영 | 완료 (Mesh Editor) |
| 3 | 프리셋 | 내장 프리셋 완료. 사용자 프리셋 저장은 미구현 |
| 4 | 텍스처 슬롯 교체·파일 감시·채널 보기 | 슬롯 교체 완료(Windows 미확인). 파일 감시·채널 보기는 미구현 |
| 5 | 셰이더 변경 재구성 방식 | 선택 옵션으로 완료 (망사·Glass) |
| 6 | 폴더 열기 | 기존 "Drafts & Mods > Add Mod Folder"를 확장해 재질·텍스처까지 불러옴. 추출 폴더처럼 모델이 많으면 검색·선택 창이 뜸. 셰이더 종류 필터와 썸네일은 미구현 |
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

### 바꾼 파일 (2차)
| 파일 | 내용 |
|---|---|
| `cdmw/core/material_shader_controls.py` | `material_source_details`: wrapper별 원문 행, 변형, 파일 내 위치 |
| `cdmw/services/mesh_shader_controls.py` | 패널 상태에 `source`, 변형 Index, 원문 행 추가. 뷰포트 변형을 맨 앞으로 |
| `tools/rust_mesh_lab/crates/cdmw_render_wgpu/src/lib.rs` | 카메라 uniform에 `preview_light`, `preview_settings` 추가(288 → 320바이트), `set_material_inspection`, `camera_basis` |
| `tools/rust_mesh_lab/apps/cdmw_mesh_lab/src/main.rs`, `cdmw_shader_controls.rs` | `MaterialInspection` 상태와 패널 UI |
| `cdmw/resources/localization/*` | 새 문자열 21개 |

## 남긴 결정 사항

1. `_screenSpaceDisplacementScale`은 슬라이더로 추가하지 않았다. 유일한 근거인 Angel Teddy 모드가 이 행에 작은 ItemID 3을 쓰는데, 작은 ID의 규칙이 밝혀지지 않았다. 다만 Glass를 "다시 쓰기"로 만들면 그 모드의 구성대로 이 행(ItemID 3)을 넣는다. 원본에 값이 있으면 그 값을, 없으면 0을 쓴다.
2. "시스루 천: 얇게" 프리셋의 Opacity는 0.34다. Angel Teddy의 0.40에 glassColor 알파 `d7`(0.843)을 곱한 값이다. 색 편집은 원본 알파를 유지하므로 알파를 직접 쓸 수 없다.
3. 실시간 미리보기는 호스트가 `preview_base`를 준 셰이더에서만 동작한다. 텍스처 bake가 필요한 변환이나 마스크를 칠한 재질은 놓은 뒤 호스트가 다시 만든 결과로 갱신된다.
