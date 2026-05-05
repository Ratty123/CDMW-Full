use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use std::process;

fn print_usage() {
    eprintln!("Usage:");
    eprintln!("  cd-hkx summary-json <file.hkx>");
    eprintln!("  cd-hkx summary-json -");
    eprintln!("  cd-hkx roundtrip-noedit <input.hkx> <output.hkx>");
    eprintln!("  cd-hkx patch-fixed-f32 <input.hkx> <output.hkx> <record-index> <item-index> <offset> <value>");
    eprintln!("  cd-hkx corpus-json <folder-or-file> [max-files]");
    eprintln!("  cd-hkx corpus-stats-json <folder-or-file> [max-files]");
    eprintln!("  cd-hkx verify-noedit <folder-or-file> [max-files]");
}

fn read_input(path: &str) -> io::Result<Vec<u8>> {
    if path == "-" {
        let mut data = Vec::new();
        io::stdin().read_to_end(&mut data)?;
        Ok(data)
    } else {
        fs::read(path)
    }
}

fn json_escape(value: &str) -> String {
    let mut output = String::with_capacity(value.len() + 8);
    for character in value.chars() {
        match character {
            '"' => output.push_str("\\\""),
            '\\' => output.push_str("\\\\"),
            '\n' => output.push_str("\\n"),
            '\r' => output.push_str("\\r"),
            '\t' => output.push_str("\\t"),
            c if c.is_control() => output.push_str(&format!("\\u{:04x}", c as u32)),
            c => output.push(c),
        }
    }
    output
}

fn increment_count(map: &mut BTreeMap<String, usize>, key: &str, count: usize) {
    *map.entry(key.to_string()).or_insert(0) += count;
}

fn print_json_count_map(map: &BTreeMap<String, usize>) {
    print!("{{");
    for (index, (key, value)) in map.iter().enumerate() {
        if index > 0 {
            print!(",");
        }
        print!("\"{}\":{}", json_escape(key), value);
    }
    print!("}}");
}

fn parse_usize_arg(value: &str, name: &str) -> Result<usize, String> {
    if let Some(hex) = value
        .strip_prefix("0x")
        .or_else(|| value.strip_prefix("0X"))
    {
        usize::from_str_radix(hex, 16)
            .map_err(|error| format!("{name} must be an integer: {error}"))
    } else {
        value
            .parse::<usize>()
            .map_err(|error| format!("{name} must be an integer: {error}"))
    }
}

fn collect_hkx_files(path: &Path, files: &mut Vec<PathBuf>) -> io::Result<()> {
    if path.is_file() {
        if path
            .extension()
            .and_then(|extension| extension.to_str())
            .is_some_and(|extension| extension.eq_ignore_ascii_case("hkx"))
        {
            files.push(path.to_path_buf());
        }
        return Ok(());
    }
    if !path.is_dir() {
        return Ok(());
    }
    for entry in fs::read_dir(path)? {
        let entry = entry?;
        collect_hkx_files(&entry.path(), files)?;
    }
    Ok(())
}

fn command_summary_json(path: &str) -> Result<(), String> {
    let data = read_input(path).map_err(|error| format!("failed to read {path}: {error}"))?;
    let summary = cd_hkx::parse_summary(&data);
    let writer_report = cd_hkx::verify_no_edit_roundtrip(&data);
    println!(
        "{}",
        cd_hkx::summary_to_json_with_no_edit_report(&summary, &writer_report)
    );
    Ok(())
}

fn command_roundtrip_noedit(args: &[String]) -> Result<(), String> {
    if args.len() != 4 {
        return Err("roundtrip-noedit requires input and output paths".to_string());
    }
    let input_path = &args[2];
    let output_path = &args[3];
    let data =
        fs::read(input_path).map_err(|error| format!("failed to read {input_path}: {error}"))?;
    let (roundtrip, report) = cd_hkx::roundtrip_no_edit(&data);
    if !report.byte_identical_no_edit_rebuild_supported {
        let mut report_json = cd_hkx::no_edit_binary_writer_report_to_json(&report);
        if report_json.ends_with('}') {
            report_json.pop();
        }
        return Err(format!(
            "native no-edit roundtrip failed: {},\"input\":\"{}\",\"output\":\"{}\"}}",
            report_json,
            json_escape(input_path),
            json_escape(output_path)
        ));
    }
    fs::write(output_path, &roundtrip)
        .map_err(|error| format!("failed to write no-edit HKX {output_path}: {error}"))?;
    let mut report_json = cd_hkx::no_edit_binary_writer_report_to_json(&report);
    if report_json.ends_with('}') {
        report_json.pop();
    }
    println!(
        "{},\"input\":\"{}\",\"output\":\"{}\"}}",
        report_json,
        json_escape(input_path),
        json_escape(output_path)
    );
    Ok(())
}

fn command_patch_fixed_f32(args: &[String]) -> Result<(), String> {
    if args.len() != 8 {
        return Err("patch-fixed-f32 requires 6 arguments".to_string());
    }
    let input_path = &args[2];
    let output_path = &args[3];
    let record_index = parse_usize_arg(&args[4], "record-index")?;
    let item_index = parse_usize_arg(&args[5], "item-index")?;
    let offset = parse_usize_arg(&args[6], "offset")?;
    let value = args[7]
        .parse::<f32>()
        .map_err(|error| format!("value must be a finite float: {error}"))?;
    let data =
        fs::read(input_path).map_err(|error| format!("failed to read {input_path}: {error}"))?;
    let patched = cd_hkx::patch_fixed_float(&data, record_index, item_index, offset, value)?;
    fs::write(output_path, &patched)
        .map_err(|error| format!("failed to write patched HKX {output_path}: {error}"))?;
    println!(
        "{{\"status\":\"patched\",\"input\":\"{}\",\"output\":\"{}\",\"record_index\":{},\"item_index\":{},\"offset\":{},\"hex_offset\":\"0x{:X}\",\"value\":{},\"byte_length\":{}}}",
        json_escape(input_path),
        json_escape(output_path),
        record_index,
        item_index,
        offset,
        offset,
        value,
        patched.len()
    );
    Ok(())
}

fn command_corpus_json(
    root: &str,
    verify_only: bool,
    stats_only: bool,
    max_files: Option<usize>,
) -> Result<(), String> {
    let mut files = Vec::new();
    collect_hkx_files(Path::new(root), &mut files)
        .map_err(|error| format!("failed to scan {root}: {error}"))?;
    files.sort();
    let discovered_file_count = files.len();
    if let Some(max_files) = max_files {
        files.truncate(max_files);
    }
    let mut ok_count = 0usize;
    let mut error_count = 0usize;
    let mut total_items = 0usize;
    let mut total_objects = 0usize;
    let mut total_tuning_slots = 0usize;
    let mut total_reference_candidates = 0usize;
    let mut total_fixup_sections = 0usize;
    let mut total_fixup_words = 0usize;
    let mut total_fixup_resolved_references = 0usize;
    let mut total_fixup_unresolved_words = 0usize;
    let mut total_ptch_tables = 0usize;
    let mut total_ptch_patch_sites = 0usize;
    let mut total_ptch_resolved_patch_sites = 0usize;
    let mut total_ptch_null_patch_sites = 0usize;
    let mut total_ptch_unresolved_patch_sites = 0usize;
    let mut total_native_graph_nodes = 0usize;
    let mut total_native_graph_edges = 0usize;
    let mut total_native_graph_fixup_edges = 0usize;
    let mut total_native_graph_owner_arrays = 0usize;
    let mut total_hard_internal_observed_targets = 0usize;
    let mut total_bytes = 0usize;
    let mut no_edit_identical_count = 0usize;
    let mut no_edit_error_count = 0usize;
    let mut aggregate_reference_category_counts = BTreeMap::<String, usize>::new();
    let mut aggregate_fixup_match_kind_counts = BTreeMap::<String, usize>::new();
    let mut aggregate_fixup_reference_category_counts = BTreeMap::<String, usize>::new();
    let mut aggregate_ptch_tuple_shape_counts = BTreeMap::<String, usize>::new();
    let mut aggregate_ptch_payload_match_kind_counts = BTreeMap::<String, usize>::new();
    let mut aggregate_ptch_semantics_remaining_case_counts = BTreeMap::<String, usize>::new();
    let mut aggregate_hard_internal_target_counts = BTreeMap::<String, usize>::new();
    let mut aggregate_hard_internal_status_counts = BTreeMap::<String, usize>::new();

    print!(
        "{{\"format\":\"cd_hkx_{}_v1\",\"native_writer_status\":\"available\",\"no_edit_roundtrip_mode\":\"native_read_model_write_lossless_bytes\",\"read_model_write_pipeline\":\"raw_preserving_model\",\"root\":\"{}\",\"discovered_file_count\":{},\"scanned_file_limit\":{},\"files\":[",
        if stats_only {
            "corpus_stats"
        } else if verify_only {
            "verify_noedit"
        } else {
            "corpus_report"
        },
        json_escape(root),
        discovered_file_count,
        max_files
            .map(|value| value.to_string())
            .unwrap_or_else(|| "null".to_string())
    );
    for (index, path) in files.iter().enumerate() {
        if !stats_only && index > 0 {
            print!(",");
        }
        let path_text = path.to_string_lossy();
        match fs::read(path) {
            Ok(data) => {
                let summary = cd_hkx::parse_summary(&data);
                let no_edit_writer_report = cd_hkx::verify_no_edit_roundtrip(&data);
                let no_edit_roundtrip_identical = no_edit_writer_report.byte_identical;
                if no_edit_roundtrip_identical {
                    no_edit_identical_count += 1;
                } else {
                    no_edit_error_count += 1;
                }
                ok_count += 1;
                total_bytes += data.len();
                total_items += summary.item_records.len();
                total_objects += summary.object_records.len();
                let reference_candidate_count = summary
                    .object_records
                    .iter()
                    .map(|record| record.references.len())
                    .sum::<usize>();
                total_reference_candidates += reference_candidate_count;
                for record in &summary.object_records {
                    for reference in &record.references {
                        increment_count(
                            &mut aggregate_reference_category_counts,
                            &reference.reference_category,
                            1,
                        );
                    }
                }
                let fixups = &summary.tagfile_reference_fixups;
                total_fixup_sections += fixups.section_count;
                for (match_kind, count) in &fixups.match_kind_counts {
                    increment_count(&mut aggregate_fixup_match_kind_counts, match_kind, *count);
                }
                for (category, count) in &fixups.reference_category_counts {
                    increment_count(
                        &mut aggregate_fixup_reference_category_counts,
                        category,
                        *count,
                    );
                }
                let fixup_word_count = fixups
                    .sections
                    .iter()
                    .map(|section| section.word_count)
                    .sum::<usize>();
                let fixup_resolved_reference_count = fixups
                    .sections
                    .iter()
                    .map(|section| section.resolved_references.len())
                    .sum::<usize>();
                let fixup_unresolved_word_count = fixups
                    .match_kind_counts
                    .get("unresolved_word")
                    .copied()
                    .unwrap_or(0);
                total_fixup_words += fixup_word_count;
                total_fixup_resolved_references += fixup_resolved_reference_count;
                total_fixup_unresolved_words += fixup_unresolved_word_count;
                total_ptch_tables += fixups.ptch_table_count;
                total_ptch_patch_sites += fixups.ptch_patch_site_count;
                total_ptch_resolved_patch_sites += fixups.ptch_resolved_patch_site_count;
                total_ptch_null_patch_sites += fixups.ptch_null_patch_site_count;
                total_ptch_unresolved_patch_sites += fixups.ptch_unresolved_patch_site_count;
                let native_graph = &summary.native_model_graph;
                total_native_graph_nodes += native_graph.node_count;
                total_native_graph_edges += native_graph.edge_count;
                total_native_graph_fixup_edges += native_graph.fixup_backed_reference_edge_count;
                total_native_graph_owner_arrays += native_graph.owner_array_count;
                let hard_internal_evidence = &summary.hard_internal_evidence;
                total_hard_internal_observed_targets +=
                    hard_internal_evidence.observed_target_count;
                increment_count(
                    &mut aggregate_hard_internal_status_counts,
                    &hard_internal_evidence.status,
                    1,
                );
                for target in &hard_internal_evidence.targets {
                    increment_count(
                        &mut aggregate_hard_internal_status_counts,
                        &target.status,
                        1,
                    );
                    if target.present_in_file {
                        increment_count(&mut aggregate_hard_internal_target_counts, &target.key, 1);
                    }
                }
                let fixup_semantics = &summary.fixup_semantics_report;
                for (shape, count) in &fixup_semantics.ptch_tuple_shape_counts {
                    increment_count(&mut aggregate_ptch_tuple_shape_counts, shape, *count);
                }
                for (kind, count) in &fixup_semantics.ptch_payload_match_kind_counts {
                    increment_count(&mut aggregate_ptch_payload_match_kind_counts, kind, *count);
                }
                for case_row in &fixup_semantics.ptch_remaining_case_priorities {
                    increment_count(
                        &mut aggregate_ptch_semantics_remaining_case_counts,
                        &case_row.case_name,
                        case_row.count,
                    );
                }
                let tuning_slots = summary
                    .physics_tuning_groups
                    .iter()
                    .map(|group| group.slots.len())
                    .sum::<usize>();
                total_tuning_slots += tuning_slots;
                if !stats_only {
                    print!(
                        "{{\"path\":\"{}\",\"status\":\"ok\",\"size\":{},\"declared_size\":{},\"size_matches\":{},\"sdk_version\":\"{}\",\"item_record_count\":{},\"object_record_count\":{},\"reference_candidate_count\":{},\"tagfile_fixup_section_count\":{},\"tagfile_fixup_word_count\":{},\"tagfile_fixup_resolved_reference_count\":{},\"tagfile_fixup_unresolved_word_count\":{},\"tagfile_ptch_table_count\":{},\"tagfile_ptch_patch_site_count\":{},\"tagfile_ptch_resolved_patch_site_count\":{},\"tagfile_ptch_null_patch_site_count\":{},\"tagfile_ptch_unresolved_patch_site_count\":{},\"native_model_graph_status\":\"{}\",\"native_model_graph_node_count\":{},\"native_model_graph_edge_count\":{},\"native_model_graph_fixup_backed_reference_edge_count\":{},\"native_model_graph_owner_array_count\":{},\"hard_internal_evidence_status\":\"{}\",\"hard_internal_observed_target_count\":{},\"physics_tuning_group_count\":{},\"physics_tuning_slot_count\":{},\"warning_count\":{},\"native_writer_status\":\"{}\",\"no_edit_roundtrip_mode\":\"{}\",\"read_model_write_pipeline\":\"{}\",\"native_read_model_write_available\":{},\"no_edit_roundtrip_identical\":{},\"type_names\":[",
                        json_escape(&path_text),
                        data.len(),
                        summary
                            .declared_size
                            .map(|value| value.to_string())
                            .unwrap_or_else(|| "null".to_string()),
                        if summary.size_matches { "true" } else { "false" },
                        json_escape(&summary.sdk_version),
                        summary.item_records.len(),
                        summary.object_records.len(),
                        reference_candidate_count,
                        fixups.section_count,
                        fixup_word_count,
                        fixup_resolved_reference_count,
                        fixup_unresolved_word_count,
                        fixups.ptch_table_count,
                        fixups.ptch_patch_site_count,
                        fixups.ptch_resolved_patch_site_count,
                        fixups.ptch_null_patch_site_count,
                        fixups.ptch_unresolved_patch_site_count,
                        json_escape(&native_graph.status),
                        native_graph.node_count,
                        native_graph.edge_count,
                        native_graph.fixup_backed_reference_edge_count,
                        native_graph.owner_array_count,
                        json_escape(&hard_internal_evidence.status),
                        hard_internal_evidence.observed_target_count,
                        summary.physics_tuning_groups.len(),
                        tuning_slots,
                        summary.warnings.len(),
                        json_escape(&no_edit_writer_report.native_writer_status),
                        json_escape(&no_edit_writer_report.no_edit_roundtrip_mode),
                        json_escape(&no_edit_writer_report.read_model_write_pipeline),
                        if no_edit_writer_report.native_read_model_write_available { "true" } else { "false" },
                        if no_edit_roundtrip_identical { "true" } else { "false" }
                    );
                    for (type_index, type_name) in summary.type_names.iter().take(32).enumerate() {
                        if type_index > 0 {
                            print!(",");
                        }
                        print!("\"{}\"", json_escape(type_name));
                    }
                    print!(
                        "],\"fixup_semantics_summary\":{{\"status\":\"{}\",\"ptch_table_count\":{},\"ptch_patch_site_count\":{},\"ptch_object_patch_site_count\":{},\"ptch_null_patch_site_count\":{},\"ptch_unresolved_patch_site_count\":{},\"ptch_tuple_shape_counts\":",
                        json_escape(&fixup_semantics.status),
                        fixup_semantics.ptch_table_count,
                        fixup_semantics.ptch_patch_site_count,
                        fixup_semantics.ptch_object_patch_site_count,
                        fixup_semantics.ptch_null_patch_site_count,
                        fixup_semantics.ptch_unresolved_patch_site_count,
                    );
                    print_json_count_map(&fixup_semantics.ptch_tuple_shape_counts);
                    print!(",\"ptch_payload_match_kind_counts\":");
                    print_json_count_map(&fixup_semantics.ptch_payload_match_kind_counts);
                    print!(
                        ",\"ptch_remaining_case_count\":{}}}",
                        fixup_semantics.ptch_remaining_case_priorities.len()
                    );
                    print!(
                        ",\"no_edit_binary_writer\":{}",
                        cd_hkx::no_edit_binary_writer_report_to_json(&no_edit_writer_report)
                    );
                    print!(
                        ",\"hard_internal_evidence_summary\":{{\"status\":\"{}\",\"target_count\":{},\"observed_target_count\":{},\"unresolved_target_count\":{},\"total_observed_byte_count\":{},\"observed_targets\":[",
                        json_escape(&hard_internal_evidence.status),
                        hard_internal_evidence.target_count,
                        hard_internal_evidence.observed_target_count,
                        hard_internal_evidence.unresolved_target_count,
                        hard_internal_evidence.total_observed_byte_count
                    );
                    let mut emitted_target = false;
                    for target in &hard_internal_evidence.targets {
                        if !target.present_in_file {
                            continue;
                        }
                        if emitted_target {
                            print!(",");
                        }
                        emitted_target = true;
                        print!(
                            "{{\"key\":\"{}\",\"status\":\"{}\",\"proof_status\":\"{}\",\"observed_record_count\":{},\"observed_byte_count\":{}}}",
                            json_escape(&target.key),
                            json_escape(&target.status),
                            json_escape(&target.proof_status),
                            target.observed_record_count,
                            target.observed_byte_count
                        );
                    }
                    print!("]}}");
                    print!("}}");
                }
            }
            Err(error) => {
                error_count += 1;
                if !stats_only {
                    print!(
                        "{{\"path\":\"{}\",\"status\":\"error\",\"error\":\"{}\"}}",
                        json_escape(&path_text),
                        json_escape(&error.to_string())
                    );
                }
            }
        }
    }
    print!(
        "],\"file_count\":{},\"ok_count\":{},\"error_count\":{},\"total_bytes\":{},\"total_item_records\":{},\"total_object_records\":{},\"total_reference_candidates\":{},\"total_tagfile_fixup_sections\":{},\"total_tagfile_fixup_words\":{},\"total_tagfile_fixup_resolved_references\":{},\"total_tagfile_fixup_unresolved_words\":{},\"total_tagfile_ptch_tables\":{},\"total_tagfile_ptch_patch_sites\":{},\"total_tagfile_ptch_resolved_patch_sites\":{},\"total_tagfile_ptch_null_patch_sites\":{},\"total_tagfile_ptch_unresolved_patch_sites\":{},\"total_native_model_graph_nodes\":{},\"total_native_model_graph_edges\":{},\"total_native_model_graph_fixup_backed_reference_edges\":{},\"total_native_model_graph_owner_arrays\":{},\"total_hard_internal_observed_targets\":{},\"total_physics_tuning_slots\":{},\"no_edit_roundtrip_identical_count\":{},\"no_edit_roundtrip_error_count\":{},\"aggregate_reference_category_counts\":",
        files.len(),
        ok_count,
        error_count,
        total_bytes,
        total_items,
        total_objects,
        total_reference_candidates,
        total_fixup_sections,
        total_fixup_words,
        total_fixup_resolved_references,
        total_fixup_unresolved_words,
        total_ptch_tables,
        total_ptch_patch_sites,
        total_ptch_resolved_patch_sites,
        total_ptch_null_patch_sites,
        total_ptch_unresolved_patch_sites,
        total_native_graph_nodes,
        total_native_graph_edges,
        total_native_graph_fixup_edges,
        total_native_graph_owner_arrays,
        total_hard_internal_observed_targets,
        total_tuning_slots,
        no_edit_identical_count,
        no_edit_error_count,
    );
    print_json_count_map(&aggregate_reference_category_counts);
    print!(",\"aggregate_tagfile_fixup_match_kind_counts\":");
    print_json_count_map(&aggregate_fixup_match_kind_counts);
    print!(",\"aggregate_tagfile_fixup_reference_category_counts\":");
    print_json_count_map(&aggregate_fixup_reference_category_counts);
    print!(",\"aggregate_ptch_tuple_shape_counts\":");
    print_json_count_map(&aggregate_ptch_tuple_shape_counts);
    print!(",\"aggregate_ptch_payload_match_kind_counts\":");
    print_json_count_map(&aggregate_ptch_payload_match_kind_counts);
    print!(",\"aggregate_ptch_semantics_remaining_case_counts\":");
    print_json_count_map(&aggregate_ptch_semantics_remaining_case_counts);
    print!(",\"aggregate_hard_internal_target_counts\":");
    print_json_count_map(&aggregate_hard_internal_target_counts);
    print!(",\"aggregate_hard_internal_status_counts\":");
    print_json_count_map(&aggregate_hard_internal_status_counts);
    println!(
        ",\"native_writer_status\":\"available\",\"no_edit_roundtrip_mode\":\"native_read_model_write_lossless_bytes\",\"read_model_write_pipeline\":\"raw_preserving_model\",\"all_no_edit_roundtrips_identical\":{}}}",
        if error_count == 0 && no_edit_error_count == 0 { "true" } else { "false" }
    );
    Ok(())
}

fn run(args: &[String]) -> Result<(), String> {
    match args.get(1).map(String::as_str) {
        Some("summary-json") if args.len() == 3 => command_summary_json(&args[2]),
        Some("roundtrip-noedit") => command_roundtrip_noedit(args),
        Some("patch-fixed-f32") => command_patch_fixed_f32(args),
        Some("corpus-json") if args.len() == 3 || args.len() == 4 => command_corpus_json(
            &args[2],
            false,
            false,
            args.get(3)
                .map(|value| parse_usize_arg(value, "max-files"))
                .transpose()?,
        ),
        Some("corpus-stats-json") if args.len() == 3 || args.len() == 4 => command_corpus_json(
            &args[2],
            false,
            true,
            args.get(3)
                .map(|value| parse_usize_arg(value, "max-files"))
                .transpose()?,
        ),
        Some("verify-noedit") if args.len() == 3 || args.len() == 4 => command_corpus_json(
            &args[2],
            true,
            false,
            args.get(3)
                .map(|value| parse_usize_arg(value, "max-files"))
                .transpose()?,
        ),
        _ => {
            print_usage();
            Err("invalid arguments".to_string())
        }
    }
}

fn main() {
    let args = env::args().collect::<Vec<_>>();
    if let Err(error) = run(&args) {
        eprintln!("cd-hkx: {error}");
        process::exit(2);
    }
}
