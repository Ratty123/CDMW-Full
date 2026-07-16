from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from cdmw.core import pipeline
from cdmw.domain.textures import output, plan, policy, profiles, rules, semantics


class TextureDomainProfileTests(unittest.TestCase):
    def test_pipeline_exports_domain_default_builders(self) -> None:
        self.assertIs(
            pipeline.build_default_texture_workflow_profiles,
            profiles.build_default_texture_workflow_profiles,
        )
        self.assertIs(
            pipeline.build_default_texture_workflow_rules,
            profiles.build_default_texture_workflow_rules,
        )
        self.assertIs(
            pipeline.upgrade_default_texture_workflow_state,
            profiles.upgrade_default_texture_workflow_state,
        )
        self.assertIs(
            pipeline.should_seed_default_texture_workflow_state,
            profiles.should_seed_default_texture_workflow_state,
        )
        self.assertIs(
            pipeline.describe_processing_path_kind,
            plan.describe_processing_path_kind,
        )
        self.assertIs(
            pipeline._build_backend_capability_matrix,
            plan._build_backend_capability_matrix,
        )
        self.assertIs(
            pipeline._build_texture_processing_plan_entry,
            plan._build_texture_processing_plan_entry,
        )
        self.assertIs(
            pipeline._semantic_override_components,
            plan._semantic_override_components,
        )
        self.assertIs(
            pipeline.parse_texture_rules,
            rules.parse_texture_rules,
        )
        self.assertIs(
            pipeline.find_matching_texture_rule,
            rules.find_matching_texture_rule,
        )
        self.assertIs(
            pipeline.coerce_texture_workflow_profiles,
            rules.coerce_texture_workflow_profiles,
        )
        self.assertIs(
            pipeline.coerce_texture_workflow_rules,
            rules.coerce_texture_workflow_rules,
        )
        self.assertIs(
            pipeline.migrate_legacy_texture_rules_to_structured,
            rules.migrate_legacy_texture_rules_to_structured,
        )
        self.assertIs(
            pipeline.max_mips_for_size,
            output.max_mips_for_size,
        )
        self.assertIs(
            pipeline.apply_texture_workflow_output_override,
            output.apply_texture_workflow_output_override,
        )
        self.assertIs(
            pipeline.resolve_dds_output_settings,
            output.resolve_dds_output_settings,
        )
        self.assertIs(
            pipeline.summarize_texture_workflow_rule,
            output.summarize_texture_workflow_rule,
        )

    def test_default_profiles_and_rules_have_expected_starter_ids(self) -> None:
        profile_ids = {profile.profile_id for profile in profiles.build_default_texture_workflow_profiles()}
        rule_patterns = {rule.pattern for rule in profiles.build_default_texture_workflow_rules()}

        self.assertIn("starter_color_albedo", profile_ids)
        self.assertIn("starter_normal_map", profile_ids)
        self.assertIn("*_n.dds", rule_patterns)
        self.assertIn("normal_bc5", profiles.get_texture_processing_profile_keys())

    def test_default_workflow_state_seed_and_upgrade_live_in_domain(self) -> None:
        from cdmw.models import TextureRule, TextureWorkflowProfile

        placeholder_profile = TextureWorkflowProfile(profile_id="", label="Profile")
        placeholder_rule = TextureRule(pattern="*.dds")

        self.assertTrue(
            profiles.should_seed_default_texture_workflow_state(
                (placeholder_profile,),
                (placeholder_rule,),
            )
        )

        legacy_profiles = profiles._build_legacy_default_texture_workflow_profiles()
        legacy_rules = profiles._build_legacy_default_texture_workflow_rules()
        upgraded_profiles, upgraded_rules = profiles.upgrade_default_texture_workflow_state(
            legacy_profiles,
            legacy_rules,
        )

        self.assertEqual(
            profiles.build_default_texture_workflow_profiles(),
            upgraded_profiles,
        )
        self.assertIn("*_disp.dds", {rule.pattern for rule in upgraded_rules})

    def test_texture_planner_rules_live_in_domain(self) -> None:
        self.assertEqual(
            "Visible-color PNG path: generic 8-bit image staging for color-like textures.",
            plan.describe_processing_path_kind("visible_color_png_path"),
        )
        self.assertEqual(("normal", "normal"), plan._semantic_override_components("normal"))
        self.assertEqual("normal_bc5", plan._profile_for_key("normal_bc5").key)

    def test_texture_rule_parsing_and_coercion_live_in_domain(self) -> None:
        from cdmw.models import TextureRule, TextureWorkflowProfile

        parsed_rules = rules.parse_texture_rules(
            "*_n.dds; semantic=normal:normal; profile=normal_bc5; colorspace=linear; alpha=none; path=technical_preserve_path"
        )
        self.assertEqual(1, len(parsed_rules))
        self.assertEqual("normal:normal", parsed_rules[0].semantic_value)
        self.assertIs(
            parsed_rules[0],
            rules.find_matching_texture_rule(Path("character/body_n.dds"), parsed_rules),
        )

        coerced_profiles = rules.coerce_texture_workflow_profiles(
            ({"profile_id": "normal", "label": "Normal", "action_mode": "inherit", "ncnn_scale": 2},)
        )
        self.assertEqual("", coerced_profiles[0].action_mode)

        coerced_rules = rules.coerce_texture_workflow_rules(
            (TextureRule(pattern="textures/body_n.dds", match_mode="exact", profile_value="normal_bc5"),)
        )
        self.assertEqual("exact", coerced_rules[0].match_mode)
        self.assertIs(
            coerced_rules[0],
            rules.find_matching_texture_rule(Path("textures/body_n.dds"), coerced_rules),
        )

        migrated_profiles, migrated_rules = rules.migrate_legacy_texture_rules_to_structured(
            "*.dds; format=match_original; size=png; mips=full_chain"
        )
        self.assertEqual(1, len(migrated_profiles))
        self.assertEqual(migrated_profiles[0].profile_id, migrated_rules[0].workflow_profile_id)

        with self.assertRaises(ValueError):
            rules.coerce_texture_workflow_profiles(
                (TextureWorkflowProfile(profile_id="bad", label="Bad", ncnn_scale=5),)
            )

    def test_texture_output_rules_live_in_domain(self) -> None:
        from cdmw.models import DdsInfo, DdsOutputSettings, TextureWorkflowDdsOverride

        settings = DdsOutputSettings(
            dds_format="BC1_UNORM",
            mip_count=1,
            width=64,
            height=32,
            resize_to_dimensions=False,
        )
        dds_info = DdsInfo(
            width=128,
            height=64,
            mip_count=7,
            dds_format="BC7_UNORM",
            source_path=Path("source.dds"),
        )

        self.assertEqual(8, output.max_mips_for_size(128, 64))
        overridden = output.apply_texture_workflow_output_override(
            settings,
            TextureWorkflowDdsOverride(format_value="match_original", size_value="original", mip_value="match_original"),
            dds_info=dds_info,
            note_label="profile matched",
        )

        self.assertEqual("BC7_UNORM", overridden.dds_format)
        self.assertEqual((128, 64), (overridden.width, overridden.height))
        self.assertEqual(7, overridden.mip_count)
        self.assertIn("profile matched", overridden.notes)

    def test_texture_output_accepts_injected_semantic_decision_factory(self) -> None:
        from cdmw.models import DdsInfo, DdsOutputSettings

        decision = semantics.TextureUpscaleDecision(
            path="body_n.dds",
            texture_type="normal",
            semantic_subtype="normal",
            semantic_confidence=100,
            should_upscale=False,
            recommended_colorspace="linear",
            format_strategy="bc5_linear",
            recommended_dds_format="BC5_UNORM",
            preserve_alpha=False,
            alpha_mode="none",
        )
        adjusted = output.apply_automatic_texture_rule_adjustments(
            DdsOutputSettings(
                dds_format="BC7_UNORM_SRGB",
                mip_count=1,
                width=64,
                height=64,
                resize_to_dimensions=False,
            ),
            Path("body_n.dds"),
            DdsInfo(
                width=64,
                height=64,
                mip_count=1,
                dds_format="BC7_UNORM_SRGB",
                source_path=Path("body_n.dds"),
            ),
            has_alpha=False,
            preset="balanced",
            decision_factory=lambda *_args, **_kwargs: decision,
        )

        self.assertEqual("BC5_UNORM", adjusted.dds_format)

    def test_texture_profile_ui_uses_domain_profile_keys_directly(self) -> None:
        source = Path("cdmw/ui/texture_workflow/workflow_profiles_ui.py").read_text(encoding="utf-8")

        self.assertIn(
            "from cdmw.domain.textures.profiles import get_texture_processing_profile_keys",
            source,
        )
        self.assertNotIn(
            "from cdmw.core.pipeline import get_texture_processing_profile_keys",
            source,
        )

    def test_material_authority_policy_helpers_normalize_runtime_options(self) -> None:
        from cdmw.modding.material_replacer import (
            complete_swap_material_authority_contract as legacy_contract,
            serialize_complete_swap_manual_material_profile,
        )

        runtime_options = SimpleNamespace(complete_swap_material_profile="material_authority_runtime_xml")
        true_source_options = SimpleNamespace(
            complete_swap_material_profile="true_source",
            edge_relief_strength=0.35,
            edge_relief_source="hybrid",
        )

        self.assertTrue(policy.complete_swap_allows_inherited_layer_color_bindings(runtime_options))
        self.assertTrue(policy.complete_swap_requires_true_source_authority(true_source_options))
        self.assertEqual(
            "true_source_authority_relief_support",
            policy.complete_swap_authority_contract(true_source_options),
        )
        manual_token = serialize_complete_swap_manual_material_profile({"authority_contract": "true_source_authority_detail_mask"})
        for profile_name in (
            "material_authority_runtime_xml",
            "true_source",
            "material_authority_detail_mask",
            "material_authority_placeholder_safe_test",
            "material_authority_clean_source",
            manual_token,
        ):
            self.assertEqual(
                legacy_contract(profile_name),
                policy.complete_swap_authority_contract(profile_name),
            )

    def test_material_authority_policy_formats_blockers_and_review_lines(self) -> None:
        missing_report_result = policy.check_final_preview_material_authority(SimpleNamespace())
        self.assertEqual("failed", missing_report_result["status"])
        self.assertIn("missing_material_authority_report", missing_report_result["blocking_risk_flags"])

        check_result = {
            "status": "failed",
            "errors": [],
            "warnings": ["manual review"],
            "blocking_risk_flags": ["invalid_dds_payload"],
            "review_risk_flags": ["source_role_warning"],
        }

        self.assertEqual(
            ("Blocking material authority risk flag(s): invalid_dds_payload",),
            policy.material_authority_check_blockers(check_result),
        )
        self.assertEqual(
            ("Review material authority risk flag(s): source_role_warning", "manual review"),
            policy.material_authority_check_review_lines(check_result),
        )

    def test_material_authority_policy_uses_injected_checker(self) -> None:
        report = {"schema": "example"}
        final_preview = SimpleNamespace(material_authority_report=report)

        result = policy.check_final_preview_material_authority(
            final_preview,
            report_checker=lambda value: {"status": "passed", "same_report": value == report},
        )

        self.assertEqual({"status": "passed", "same_report": True}, result)

    def test_material_authority_policy_fails_closed_without_checker(self) -> None:
        result = policy.check_final_preview_material_authority(
            SimpleNamespace(material_authority_report={"schema": "example"})
        )

        self.assertEqual("failed", result["status"])
        self.assertIn("material_authority_checker_unavailable", result["blocking_risk_flags"])


if __name__ == "__main__":
    unittest.main()
