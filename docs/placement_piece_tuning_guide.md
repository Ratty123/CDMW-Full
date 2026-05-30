# Placement Piece Tuning Guide

Goal: make small placement variants without rediscovering the whole 1H/shield setup.

Work on an extracted package folder, not a zip. Make a test copy first, tune that copy, test in game, then copy the proven files back into the package you plan to publish and rebuild the zip.

## Mental model

Three files decide where a visible item sits:

1. Character socket file
   - Path: `character/descriptors/socketbonedata/1_pc/1_phm/phm_01.pab.sockets.xml`
   - This is the body-side attach point.
   - Examples: `Spine2_R_Socket`, `Spine2_L_Socket`, `Spine2_B_Shield_Socket`, `LForearm_Socket`.

2. Character descriptor
   - Paths:
     - `character/phm_description_player_kliff.xml`
     - `character/descriptors/characterdescription/phm_description_player_kliff.xml`
   - This routes each equipment part to body socket + weapon child socket.
   - Keep both files byte-identical when both exist.

3. Weapon socket file
   - Path pattern: `character/descriptors/socketbonedata/1_pc/1_phm/weapon/.../*.sockets.xml`
   - This is the item-side local offset once attached to the body socket.
   - Examples: `Spine2_R_ChildSocket`, `Spine2_L_ChildSocket`, `Spine2_B_Shield_ChildSocket`.

`InSocketBone` means stowed/carry. `OutSocketBone` means held/drawn. `WeaponCasePart` links sword to sheath/case.

## Safe edit size

Use small translation steps:

- Tiny nudge: `0.010000`
- Normal nudge: `0.020000`
- Big visible nudge: `0.050000`
- Risky jump: `0.100000`

Rotation is quaternion, not degrees. Translation-only tests are easiest. For rotation, copy a known good quaternion or use tooling to convert degrees; do not hand-randomize quaternion values.

## Backup

Use a dated backup before touching a package you plan to publish:

```powershell
$src = "<path to extracted package folder>"
$backupRoot = "<path to backup folder>"
$dst = Join-Path $backupRoot "<package name>_before-placement-tune"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
Copy-Item -LiteralPath $src -Destination $dst -Recurse
```

For tests, use a separate copy so the publish-ready package stays clean.

## Shield

### Stowed shield on back

Rows:

- Descriptor part: `CD_MainWeapon_Shield_L`
- Descriptor part: `CD_MainWeapon_TowerShield_L`
- Body socket: `Spine2_B_Shield_Socket`
- Child socket: `Spine2_B_Shield_ChildSocket`

Current routing:

```xml
PartName="CD_MainWeapon_Shield_L"
InSocketBone="Spine2_B_Shield_Socket"
OutSocketBone="LForearm_Socket"
InChildSocketBone="Spine2_B_Shield_ChildSocket"
OutChildSocketBone="Basic_ChildSocket"
```

Easiest tweak:

- Edit `Spine2_B_Shield_Socket` in `phm_01.pab.sockets.xml`.
- This moves/rotates stowed shield on back.
- It does not require editing descriptor rows if socket name stays same.

Medium tweak:

- Change `InSocketBone` to another body socket.
- Also change `InChildSocketBone` if needed.
- More risk: draw/stow animation may no longer line up.

Avoid first:

- Editing `BagSocketBone` or `VehicleBagSocketBone`.
- Adding shield weapon sidecar files unless you are testing a specific shield model family.

### Held shield on forearm

Rows:

- Body socket: `LForearm_Socket`
- Descriptor `OutSocketBone`: `LForearm_Socket`
- Descriptor `OutChildSocketBone`: `Basic_ChildSocket`

Easiest tweak:

- Edit `LForearm_Socket` in `phm_01.pab.sockets.xml`.
- This changes held shield placement.

Risk:

- This can affect combat/blocking visuals because shield animations expect forearm placement.
- Test idle, block, draw, stow, movement.

## Right 1H Sword

Rows:

- Main part: `CD_MainWeapon_Sword_R`
- Sheath/case part: `CD_MainWeapon_Sword_IN_R`
- Body socket: `Spine2_R_Socket`
- Child socket: `Spine2_R_ChildSocket`

Current back routing:

```xml
PartName="CD_MainWeapon_Sword_R"
InSocketBone="Spine2_R_Socket"
OutSocketBone="RHand_Socket"
InChildSocketBone="Spine2_R_ChildSocket"
OutChildSocketBone="Basic_ChildSocket"
WeaponCasePart="CD_MainWeapon_Sword_IN_R"

PartName="CD_MainWeapon_Sword_IN_R"
InSocketBone="Spine2_R_Socket"
OutSocketBone="Spine2_R_Socket"
InChildSocketBone="Spine2_R_ChildSocket"
OutChildSocketBone="Spine2_R_ChildSocket"
```

Easiest tweak:

- Edit `Spine2_R_Socket` in `phm_01.pab.sockets.xml`.
- This moves sword and sheath together because both descriptor rows use same body socket.

Medium tweak:

- Edit `Spine2_R_ChildSocket` in included onehand weapon `.sockets.xml` files.
- This changes local blade/sheath offset.
- Apply to both normal and `_in` socket sidecars when both exist.

Avoid first:

- Changing `OutSocketBone="RHand_Socket"` unless you are intentionally changing held position.
- Removing `WeaponCasePart`.

## Left 1H Sword

Rows:

- Main part: `CD_MainWeapon_Sword_L`
- Sheath/case part: `CD_MainWeapon_Sword_IN_L`
- Body socket: `Spine2_L_Socket`
- Child socket: `Spine2_L_ChildSocket`

Current back routing:

```xml
PartName="CD_MainWeapon_Sword_L"
InSocketBone="Spine2_L_Socket"
OutSocketBone="LHand_Socket"
InChildSocketBone="Spine2_L_ChildSocket"
OutChildSocketBone="Basic_ChildSocket"
WeaponCasePart="CD_MainWeapon_Sword_IN_L"

PartName="CD_MainWeapon_Sword_IN_L"
InSocketBone="Spine2_L_Socket"
OutSocketBone="Spine2_L_Socket"
InChildSocketBone="Spine2_L_ChildSocket"
OutChildSocketBone="Spine2_L_ChildSocket"
```

Easiest tweak:

- Edit `Spine2_L_Socket` in `phm_01.pab.sockets.xml`.
- This moves left sword and left sheath together.

Medium tweak:

- Edit `Spine2_L_ChildSocket` in included onehand weapon `.sockets.xml` files.
- Keep right/left child rotations mirrored unless you want asymmetric crossed swords.

Also check:

- Dual packages may use `CD_MainWeapon_Sword_R_Aux` and `CD_MainWeapon_Sword_IN_R_Aux`.
- Those currently route to `Spine2_L_Socket` / `Spine2_L_ChildSocket`.
- If left sword looks fixed but aux sword does not, update aux rows too.

## Both 1H Swords Together

Rows:

- Right: `Spine2_R_Socket`, `Spine2_R_ChildSocket`
- Left: `Spine2_L_Socket`, `Spine2_L_ChildSocket`
- Descriptor parts: `CD_MainWeapon_Sword_R`, `CD_MainWeapon_Sword_IN_R`, `CD_MainWeapon_Sword_L`, `CD_MainWeapon_Sword_IN_L`
- Dual aux parts: `CD_MainWeapon_Sword_R_Aux`, `CD_MainWeapon_Sword_IN_R_Aux`

Easiest linked body-socket edits:

- Move both higher/lower: add same amount to both `Translation` Y values.
- Move both closer/farther from body: add same amount to both `Translation` Z values.
- Move whole pair left/right: add same amount to both `Translation` X values.
- Increase spread: move right socket negative X, left socket positive X.
- Decrease spread: move right socket positive X, left socket negative X.

Current crossed baseline in combined dual package:

```xml
Spine2_R_Socket Translation="-0.080000 -0.050000 0.045000"
Spine2_L_Socket Translation="0.050000 -0.050000 0.035000"
Spine2_R_ChildSocket Translation="0.000000 0.000000 -0.360000"
Spine2_L_ChildSocket Translation="0.000000 0.000000 -0.360000"
```

Keep this invariant:

- If `CD_MainWeapon_Sword_R` changes, `CD_MainWeapon_Sword_IN_R` should usually change same way.
- If `CD_MainWeapon_Sword_L` changes, `CD_MainWeapon_Sword_IN_L` should usually change same way.
- If aux rows exist, keep them aligned with left-side rows unless intentionally testing another layout.

## Sheaths / Cases

Descriptor rows ending in `_IN_*` are sheath/case placement rows:

- `CD_MainWeapon_Sword_IN_R`
- `CD_MainWeapon_Sword_IN_L`
- `CD_MainWeapon_Sword_IN_R_Aux`

Main rows point to them with `WeaponCasePart`.

Easiest sheath-safe edit:

- Change body socket values only (`Spine2_R_Socket`, `Spine2_L_Socket`).
- Main sword and sheath follow same body socket.

When sheaths need independent fine tuning:

- Edit child sockets in `_in.sockets.xml` files.
- Example: `cd_phm_01_sword_0001_r_in.sockets.xml`.
- Search for `Spine2_R_ChildSocket` and `Spine2_L_ChildSocket`.

Do not leave this mismatch:

```xml
CD_MainWeapon_Sword_R     InSocketBone="Spine2_R_Socket"
CD_MainWeapon_Sword_IN_R  InSocketBone="Pelvis_R_Socket"
```

That means sword and sheath separate when stowed.

## Single 1H Sword Variant

Treat right side as primary:

- Tune `CD_MainWeapon_Sword_R`.
- Tune `CD_MainWeapon_Sword_IN_R`.
- Tune `Spine2_R_Socket`.
- Tune `Spine2_R_ChildSocket`.

Leave left/aux rows alone unless the package actually exposes dual swords in game. This keeps single-sword testing smaller.

## Changing Attach Location

Moving within existing back layout is easy. Moving to a new attach point is harder.

Easy:

- Keep `InSocketBone` names same.
- Tune `Translation` on existing body sockets.
- Tune child socket translation only if needed.

Medium:

- Change `InSocketBone` from one existing socket to another.
- Example: `Spine2_R_Socket` to `Spine2_B_SubWeapon_Socket`.
- Must also choose matching `InChildSocketBone`.

Hard:

- New draw/stow animations.
- New socket names used by PAA/PAAC/metabin.
- Per-item-only placement for one specific sword model across all managers.

## Finding Rows

Find descriptor rows:

```powershell
Select-String -LiteralPath "$pkg\character\phm_description_player_kliff.xml" -Pattern "CD_MainWeapon_Sword|CD_MainWeapon_Shield|CD_MainWeapon_TowerShield"
```

Find body sockets:

```powershell
Select-String -LiteralPath "$pkg\character\descriptors\socketbonedata\1_pc\1_phm\phm_01.pab.sockets.xml" -Pattern "Spine2_R_Socket|Spine2_L_Socket|Spine2_B_Shield_Socket|LForearm_Socket"
```

Find child sockets:

```powershell
Get-ChildItem -LiteralPath "$pkg\character\descriptors\socketbonedata\1_pc\1_phm\weapon" -Recurse -Filter "*.sockets.xml" |
  Select-String -Pattern "Spine2_R_ChildSocket|Spine2_L_ChildSocket|Spine2_B_Shield_ChildSocket"
```

Verify descriptor aliases match:

```powershell
Get-FileHash "$pkg\character\phm_description_player_kliff.xml"
Get-FileHash "$pkg\character\descriptors\characterdescription\phm_description_player_kliff.xml"
```

## JMM Reminder

If descriptor path changes are touched in JMM packages, `mod.json` should include both:

```json
"character/phm_description_player_kliff.xml",
"character/descriptors/characterdescription/phm_description_player_kliff.xml"
```

If either path is in `new_paths`, both should be in `new_paths`.

## Test Checklist

Minimum in-game checks:

- Load save.
- Stand idle with weapon stowed.
- Draw weapon.
- Stow weapon.
- Walk/run with weapon stowed.
- Walk/run with weapon drawn.
- Mount horse if package includes riding files.
- Equip shield and repeat draw/stow if shield placement changed.
- Check clipping from back, side, and front camera angles.

Pass means:

- Weapon and sheath stay together.
- Draw/stow hand reaches close enough.
- Shield does not snap, rotate wrong, or cover camera badly.
- No teleport/eject on horseback.

## Rebuild Zip

Only after the tested package folder is good:

```powershell
$pkg = "<path to tested package folder>"
$zip = "<path to output zip>"
Compress-Archive -Path "$pkg\*" -DestinationPath $zip -Force
```

Then verify the root JSON version fields match the release version you intend to publish.
