from __future__ import annotations

import re
from pathlib import Path


DIRECTXTEX_COMMIT = "bf256afaed1c789ddd444fb45105ffbcab283efe"
VGMSTREAM_BUILD_COMMIT = "21bfb6f0a513271f2e18a51322128756bb59f365"
VGMSTREAM_SHA256 = "110f9087e60057c4af6cff84e26c214159c224792421affdddd3aaa2091f2641"


def test_directxtex_fetches_are_pinned_to_the_same_commit() -> None:
    for path in (
        Path("native/cdmw_d3d11_preview/CMakeLists.txt"),
        Path("native/cd_texture_dx/CMakeLists.txt"),
    ):
        source = path.read_text(encoding="utf-8")
        assert f'set(CDMW_DIRECTXTEX_COMMIT "{DIRECTXTEX_COMMIT}"' in source
        assert "GIT_TAG ${CDMW_DIRECTXTEX_COMMIT}" in source
        assert "GIT_TAG main" not in source


def test_vgmstream_packaging_uses_immutable_version_commit_and_sha256() -> None:
    source = Path("build_pyside6_app.ps1").read_text(encoding="utf-8")

    assert '$vgmstreamVersion = "r1980"' in source
    assert f'$vgmstreamBuildCommit = "{VGMSTREAM_BUILD_COMMIT}"' in source
    assert f'$vgmstreamArchiveSha256 = "{VGMSTREAM_SHA256}"' in source
    assert "raw/master" not in source
    assert "vgmstream-latest" not in source
    assert "Get-FileHash -LiteralPath $zipPath -Algorithm SHA256" in source
    assert re.search(r"if \(\$downloadHash -ne \$vgmstreamArchiveSha256\)", source)
    assert "function Test-VgmstreamRuntimePin" in source
    assert 'Join-Path $RuntimeDir ".cdmw-dependency.json"' in source
    assert "Get-FileHash -LiteralPath $runtimeFile -Algorithm SHA256" in source
