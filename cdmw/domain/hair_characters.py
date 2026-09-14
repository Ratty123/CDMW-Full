"""Playable-character ownership of hair, fitting references and barber slots."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HairCharacter:
    name: str
    appearance_path: str
    mesh_param_path: str
    hair_family: str
    reference_family: str
    prefix: str

    @property
    def hair_root(self):
        return f"character/model/1_pc/{self.hair_family}/head/hair/"

    def accepts_hair(self, path):
        path = str(path).replace("\\", "/").casefold()
        return path.startswith(self.hair_root) and path.endswith("_player.pac")

    def accepts_reference(self, path, role):
        path = str(path).replace("\\", "/").casefold()
        root = f"character/model/1_pc/{self.reference_family}/"
        if not path.startswith(root) or not path.endswith(".pac"):
            return False
        return ("/head/head/" in path if role == "head" else
                "/nude/" in path and path.rsplit("/", 1)[-1].startswith(f"cd_{self.prefix}_00_nude_"))


HAIR_CHARACTERS = (
    HairCharacter("Kliff", "character/appearance/1_pc/1_phm/cd_phm_macduff/cd_phm_macduff_00000.app_xml",
                  "character/descriptors/customizationmeta/meshparam_example_kliff.xml", "1_phm", "1_phm", "phm"),
    HairCharacter("Damiane", "character/appearance/1_pc/2_phw/cd_phw_damian/cd_phw_damian_00000.app_xml",
                  "character/descriptors/customizationmeta/meshparam_example_damian.xml", "2_phw", "2_phw", "phw"),
    HairCharacter("Oongka", "character/appearance/1_pc/1_phm/cd_phm_oongka/cd_phm_oongka_00000.app_xml",
                  "character/descriptors/customizationmeta/meshparam_example_oongka.xml", "1_phm", "5_pom", "pom"),
)


def hair_character(name="Damiane"):
    for profile in HAIR_CHARACTERS:
        if profile.name == name:
            return profile
    raise ValueError("Choose Kliff, Damiane or Oongka for Hair authoring.")


def character_for_appearance(path):
    path = str(path).replace("\\", "/").casefold()
    return next((p for p in HAIR_CHARACTERS if p.appearance_path == path), None)


def unique_hair_character(path):
    matches = [p for p in HAIR_CHARACTERS if p.accepts_hair(path)]
    return matches[0] if len(matches) == 1 else None
