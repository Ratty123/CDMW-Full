# 재질 편집 개조 기록 (material-studio 브랜치)

기준: upstream `Ratty123/cdmw-full` `faf38ee` (2026-11-11). 작업 지시서의 단계 번호를 그대로 쓴다.

## 진행 상태

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | XML 원본값을 패널에 표시 | 완료 (Mesh Editor, New Item) |
| 2 | 슬라이더 실시간 반영 | 완료 (Mesh Editor) |
| 3 | 프리셋 | 내장 프리셋 완료. 사용자 프리셋 저장은 미구현 |
| 4 | 텍스처 슬롯 교체·파일 감시·채널 보기 | 미착수 (원본 텍스처 경로 표시만 추가) |
| 5 | 셰이더 변경 재구성 방식 | 미착수 |
| 6 | 폴더 열기 | 미착수 |
| 7 | 새 모드 폴더 저장·이어서 작업 | 미착수 |
| 8 | 원본 비교·배경 전환 | 배경 빠른 전환만 완료. 원본 비교는 기존 Compare 기능 사용, 체크무늬 배경은 미구현 |
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

## 구현 위치

| 파일 | 변경 |
|---|---|
| `cdmw/domain/mesh/shader_controls.py` | `authored_field_numbers`(패널과 렌더러가 함께 쓰는 단일 파서), `authored_values_payload`, `SHADER_PRESETS`, 카탈로그의 `presets` |
| `cdmw/services/mesh_shader_controls.py` | 부위별 `authored`(변형별 셰이더·값·텍스처)와 `preview_base`(호환 셰이더별 계수 32개) |
| `cdmw/core/material_shader_controls.py` | `equipment_authored_values` |
| `cdmw/ui/new_item/*`, `cdmw/services/new_item_template_model.py` | New Item 편집기로 원본값 전달 |
| `tools/rust_mesh_lab/apps/cdmw_mesh_lab/src/cdmw_shader_controls.rs` | 패널 전면 개편, `shader_live_factors` |
| `tools/rust_mesh_lab/apps/cdmw_mesh_lab/src/main.rs` | `UiAction::CdmwShaderPreview`, `UiAction::SetViewportBackground`, `cdmw_shader_live_preview`, `cdmw_live_material_factors`, 호스트 응답·LOD 전환·재질 재설치 시 미리보기 해제 |
| `cdmw/resources/localization/*` | 새 문자열 18개, 14개 언어 |

계수 레이아웃 규칙: 앞 4칸은 헤더, 그 뒤로 카탈로그의 필드 순서대로 `default` 길이만큼 차지한다. Python `preview_factors`와 Rust `shader_live_factors`가 같은 규칙을 쓰며, `tests/test_material_studio_panel_state.py`와 Rust 테스트가 이를 고정한다.

## 검증

- Python: `pytest tests/test_material_studio_panel_state.py`
- Rust: `cargo test -p cdmw_mesh_lab shader`
- 지역화: `python scripts/generate_ui_localization_manifest.py --check`, `python scripts/validate_ui_localization_catalogs.py`
- Linux 컨테이너에서 실행했다. Windows 전용 테스트 2개는 `#[cfg(windows)]`로 묶었다.
- 결과(2026-11-12): Rust `cdmw_mesh_lab` 전체 715 통과 / 1 실패. 실패한 `archive_reader_reconstructs_uploadable_partial_dds…`는 수정 전 기준선에서도 이 Linux 환경에서 실패한다. 관련 Python 테스트 묶음은 기준선 대비 새 실패 없음(기준선 실패 104개는 Linux 환경 문제로 그대로).
- **Windows 통합 실행(Python 호스트 + Rust 뷰포트)과 인게임 결과는 확인하지 못했다.**

## 남긴 결정 사항

1. `_screenSpaceDisplacementScale`은 추가하지 않았다. 유일한 근거인 Angel Teddy 모드가 이 행에 작은 ItemID 3을 쓰는데, 작은 ID의 규칙이 밝혀지지 않았다. 원본 게임에서 이 파라미터를 쓰는 pac_xml이 확인되면 추가한다.
2. "시스루 천: 얇게" 프리셋의 Opacity는 0.34다. Angel Teddy의 0.40에 glassColor 알파 `d7`(0.843)을 곱한 값이다. 색 편집은 원본 알파를 유지하므로 알파를 직접 쓸 수 없다.
3. 실시간 미리보기는 호스트가 `preview_base`를 준 셰이더에서만 동작한다. 텍스처 bake가 필요한 변환이나 마스크를 칠한 재질은 놓은 뒤 호스트가 다시 만든 결과로 갱신된다.
