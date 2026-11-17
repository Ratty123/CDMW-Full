# CDMW 재질 편집 개조: 최종 정리와 남은 작업 (2026-11-18 갱신)

다음 작업을 이어받는 사람(또는 다른 모델)이 이 문서 하나로 상태를 파악하고 바로 이어갈 수 있게 정리했다. 자세한 경과는 같은 폴더의 `README.ko.md`에 있다.

## 1. 저장소와 빌드

- 포크: `blablahandsome1212/cdmw-full`, 브랜치 `material-studio`. 원작자 저장소 `Ratty123/cdmw-full`(MIT)은 `upstream`.
- 원작자 반영 시점: 0.12.0-alpha.5와 그 뒤의 도움말 커밋 `96bf50e`까지 병합.
- Windows 빌드: GitHub Actions의 "Windows Build" 워크플로를 `build_mode=onefile`로 실행한다. 산출물은 `CrimsonDesertModWorkbench-onefile-unsigned`.
  - 가끔 원작자 .NET 테스트(`archive_name_index`)가 빌드 서버에서 "접근 거부"로 멈춘다. 실패한 작업만 다시 실행(rerun failed)하면 통과한다.
- 작업 원칙(1·2차 지시서): 기존 기능 보존, 단계별 커밋과 테스트, 14개 언어 문자열, 추측 구현 금지, 결과는 확정 / 추정 / 추가 입력 필요로 보고.

## 2. 완료된 것

| 기능 | 위치 | 사용자 확인 |
|---|---|---|
| 셰이더 패널: XML 원본값 표시, 실시간 미리보기, 프리셋(사용자 저장·삭제), 변형(Index) 선택, 원본 재질 행 보기·복사 | Mesh Editor > Inspector > Shader experiments | 확인 |
| 텍스처 교체, 셰이더 고유 구성으로 다시 쓰기(rebuild) | 같은 패널 | 확인 |
| 모드 폴더·추출 폴더 열기, 새 모드 폴더로 저장·이어서 작업 | Drafts & Mods > Add Mod Folder | 확인 |
| 배경색, 조명 방향, 게임 해상도, 원본 보기 | 같은 패널 | 확인 |
| 11월 패치 웨딩 면사포(Ver2 망사) 렌더링: DXIL 식대로 실 굵기 = 주름 맵 + 레이스, 레이스 반복 UV, 알파 × 0.99 | 렌더러 kind 11, 15–22번 칸 | 확인 |
| Close 직후 다시 열어도 처음과 같은 재질 | 닫은 세션의 검증된 재질 정보 재사용 | 확인 |
| "Thread width scale", "Lace strength" 슬라이더 | 레이스 레이어가 있는 망사에서만 표시 | 확인 |
| 레이스 반복·오프셋·회전 편집(Byte4 바이트 쓰기) | 같은 패널 | 미확인 |
| `SkinnedMeshStandard_Ver2` 의상을 Sheer net veil / Layered glass로 변환(레이어를 먼저 구움) | 셰이더 드롭다운 | 미확인 |
| 선택 강조 숨기기: Shift+H, Viewport 설정 체크박스, 셰이더 패널 버튼 | | Shift+H 안 됨 보고 → 버튼·체크박스 추가, 미확인 |
| 강제 교체: Cloth·Cloth_Ver2 등 어떤 장비 재질이든 Sheer net veil / Layered glass로 통째로 교체, 유지할 원본 텍스처 선택 | 셰이더 패널 "Replace the material outright (force)" | 미확인 |

## 3. 인게임 확인이 필요한 것 (우선순위 순)

1. **Ver2 의상 → Sheer net veil 변환.** 미리보기에 색과 무늬가 남은 채 망사가 되는지 확인한다. 이어서 다시 쓰기(rebuild)를 켜고 모드를 빌드해 게임에서도 같게 보이는지 본다.
   - 변환된 의상에는 실 굵기 높이 맵이 없어 그물 굵기가 고르다. 텍스처 교체로 `_heightTexture`를 넣을 수 있다.
2. **레이스 반복·회전 편집.** 쓰기 규칙은 셰이더가 값을 읽는 식을 뒤집어 만든 **추정**이다. 반복 값을 바꾼 모드를 게임에 넣어, 레이스 밀도와 방향이 미리보기처럼 바뀌는지 확인한다.
   - scale 바이트 = round(255 / 반복)
   - offset 바이트 = round(오프셋 × 255)
   - 회전 바이트 = round((도 + 180) / 360 × 255)
3. **면사포 `_01` 부위.** `_detailScreenSpaceDisplacementScale` 행이 없어 레이스 가산이 0으로 계산된다. 인게임과 비교한다.
4. **강제 교체.** Cloth 또는 Cloth_Ver2 의상에서 force를 켜고 Sheer net veil을 골라 모드를 빌드한다. 게임에서 비쳐 보이는지, 옷이 깨지거나 사라지지 않는지 본다.
   - 염색·레이어 색은 사라진다(회색). 색이 필요하면 텍스처 교체로 base 텍스처를 넣는다.
5. **선택 강조 숨기기.** Viewport 설정의 "Hide selection highlight" 체크박스나 셰이더 패널 버튼으로 꺼지는지 본다. Shift+H는 한/영을 영문으로 놓고 뷰포트를 한 번 클릭한 뒤 눌러본다.

## 4. 남은 작업

| 작업 | 크기 | 필요한 것 | 메모 |
|---|---|---|---|
| 체커 배경 | 중 | Windows에서 화면 확인 | 배경이 단색 clear라 렌더 패스를 새로 추가해야 한다. GPU 없이 확인할 수 없어 보류했다. |
| 선택 외곽선 방식 | 중 | Windows에서 화면 확인 | 렌더러에 외곽선 그리기가 없다. 지금은 숨기기로 대신한다. |
| 모델 선택 창 썸네일 | 중~대 | 없음 | `cdmw/ui/mesh_editor/folder_model_picker.py` |
| 전용 "재질 편집" 화면 | 대 | 원하는 화면 구성 | 지금은 Inspector 패널이다. 부족한 점을 먼저 정한다. |
| 조명 전체 재현, 렌더 파라미터 offset 40 조건 | 대 | 게임 실행 중 GPU 캡처(RenderDoc/PIX) | DXIL만으로는 확정할 수 없다. |
| 네이티브 패키지 batch의 부위·재질 짝짓기 오류 | 중 | 원작자 C++ 수정 또는 보고 | Archive Browser에서 다른 모델로 넘어간 뒤 Mesh Editor에서 열면 이 경로를 탄다. `package_writer_json.cpp`가 batch의 `shader_family`를 첫 binding에서 가져오는 게 원인으로 보인다. |
| Python 결합기 세로 뒤집기 시 Transform 부호 | 소 | 원작자 코드 | Y 오프셋과 회전이 0이 아니면 DXIL과 반대가 된다. 면사포는 영향 없음. |
| 원작자에게 공유 | - | 사용자 결정 | 기능별 PR로 나누는 안: A 셰이더 패널, B 모드 폴더, C 면사포 DXIL, D 다시 열기 수정 |
| 리깅 저장소 PR #1 병합 | - | 사용자 결정 | |

## 5. 핵심 사실 (다시 조사하지 않도록)

- **11월 패치 면사포** `cd_phw_00_hel_00_0219`의 망사 wrapper 값: `_netPitch` 0.142, `_netThread` 0.275, `_glow` 0.516, `_sheen` 0.901, `_detailScreenSpaceDisplacementScale` 1.732051, `_dyeingTransformProperty0` 11565(약 5.67회 반복), `_dyeingPropertyBlend` R 바이트 0(−180°). 레이스는 `_detailHeightMaskR` = `0219_disp.dds`, 주름은 `_heightTexture` = `0219_02_disp.dds`에 있다.
- **DXIL 근거:** `blablahandsome1212/rigging`의 `docs/character-library/shader-research/veil-update-2026-11-16/`.
- **미리보기 칸(망사 kind 11):**
  - 4 pitch, 5 thread, 6 glow, 7 sheen, 8 uvScale
  - 9 실 굵기 배율, 10 레이스 강도
  - 11–13 색, 14 색 알파
  - 15 레이어 켜짐, 16 opacity × mask, 17–20 Transform, 21 회전, 22 overlay 알파
- **다시 열기:** Mesh Editor를 처음 열면 Archive Browser 렌더러가 멈춘다. 닫은 세션의 재질 정보는 `_stash_reusable_archive_material_context`가 보관한다.
- **Preview Core 패키지:** 부위별 재질 입력이 batch 최상위가 아니라 `dds_textures.material_inputs` 아래에 있다.
- **원작자 기준선에서도 실패하는 테스트**(Linux 작업 환경):
  - Rust `loader::tests::archive_reader_reconstructs_uploadable_partial_dds…`
  - bake를 쓰는 Python 테스트(네이티브 DDS 디코더 없음)
  - `test_localization_catalog_contracts`의 오프스크린 창 테스트
  - 새 실패 여부는 원작자 기준선 worktree와 파일별로 비교해서 판단한다.

## 6. 이어서 작업할 때

1. `git fetch upstream`으로 원작자 업데이트를 확인한다. 번역 파일 충돌은 양쪽 문자열을 모두 유지하고, `scripts/generate_ui_localization_manifest.py --write`로 manifest를 다시 만든다.
2. 새 UI 문자열을 넣은 뒤 할 일:
   - manifest를 다시 만든다.
   - 13개 언어 번역을 넣는다.
   - `scripts/validate_ui_localization_catalogs.py --write-source-identical`을 실행한 뒤 검증한다.
3. Rust 테스트는 `tools/rust_mesh_lab`에서 `cargo test -p cdmw_mesh_lab`(약 10–15분), 렌더러는 `-p cdmw_render_wgpu`로 돌린다.
4. 사용자가 "화면이 다르다"고 하면 짐작으로 고치지 않는다. 그 상태에서 `%TEMP%\cdmw-rust-mesh-editor`의 최신 `session-…` 폴더를 압축해 받아 `manifest.json`의 `textures`, `material_presentations`, `state.shader_controls`를 비교한다. 이 방법으로 다시 열기 문제를 찾았다.
