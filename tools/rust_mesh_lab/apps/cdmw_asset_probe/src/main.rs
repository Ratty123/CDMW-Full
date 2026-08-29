#![forbid(unsafe_code)]

use anyhow::{Context, Result, bail};
use cdmw_archive::{ArchiveIndex, ArchiveLimits};
use cdmw_formats::{MeshFormat, decode_mesh};
use cdmw_mesh::WorkingMesh;
use cdmw_oracle::{compare_manifests, read_manifest, write_mesh_package};
use cdmw_replay::{ReplayEvent, run_replay};
use cdmw_texture::{TextureRole, inspect_dds};
use serde::Serialize;
use std::env;
use std::fs;
use std::path::PathBuf;
use std::time::Instant;

fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .with_target(false)
        .try_init()
        .ok();
    let mut arguments = env::args().skip(1);
    let command = arguments.next().unwrap_or_else(|| "help".to_owned());
    match command.as_str() {
        "inventory" => {
            let path = required_path(arguments.next(), "inventory requires a .pamt path")?;
            let index = ArchiveIndex::read(&path, ArchiveLimits::default())?;
            print_json(&index)?;
        }
        "decode-mesh" => {
            let input = required_path(arguments.next(), "decode-mesh requires an input mesh path")?;
            let output = required_path(
                arguments.next(),
                "decode-mesh requires an output package directory",
            )?;
            let format = MeshFormat::from_path(&input)?;
            let document = decode_mesh(
                &fs::read(&input).with_context(|| format!("failed to read {}", input.display()))?,
                format,
            )?;
            let manifest = write_mesh_package(&output, &document, None)?;
            print_json(&manifest)?;
        }
        "inspect-texture" => {
            let input = required_path(arguments.next(), "inspect-texture requires a DDS path")?;
            let metadata = inspect_dds(
                &fs::read(&input).with_context(|| format!("failed to read {}", input.display()))?,
                TextureRole::Unknown,
            )?;
            print_json(&metadata)?;
        }
        "compare" => {
            let expected = required_path(
                arguments.next(),
                "compare requires an expected manifest path",
            )?;
            let actual =
                required_path(arguments.next(), "compare requires an actual manifest path")?;
            let report = compare_manifests(&read_manifest(&expected)?, &read_manifest(&actual)?);
            print_json(&report)?;
            if !report.equal {
                std::process::exit(2);
            }
        }
        "create-synthetic" => {
            let output = required_path(
                arguments.next(),
                "create-synthetic requires a new output directory",
            )?;
            fs::create_dir(&output).with_context(|| {
                format!(
                    "synthetic output must be a new directory: {}",
                    output.display()
                )
            })?;
            fs::write(
                output.join("triangle.pam"),
                cdmw_formats::synthetic::triangle_pam("synthetic.dds"),
            )?;
            fs::write(
                output.join("synthetic.dds"),
                cdmw_texture::synthetic::rgba8_checker_dds(),
            )?;
            println!(
                "Created synthetic PAM and DDS fixtures in {}",
                output.display()
            );
        }
        "benchmark-synthetic" => print_json(&benchmark_synthetic()?)?,
        "help" | "--help" | "-h" => print_help(),
        other => bail!("unknown command {other:?}; use --help"),
    }
    Ok(())
}

fn required_path(value: Option<String>, message: &str) -> Result<PathBuf> {
    value.map(PathBuf::from).with_context(|| message.to_owned())
}

fn print_json(value: &impl Serialize) -> Result<()> {
    println!("{}", serde_json::to_string_pretty(value)?);
    Ok(())
}

fn print_help() {
    println!(
        "CDMW Rust Asset Probe\n\n  inventory <index.pamt>\n  decode-mesh <input.pac|pam|pamlod> <new-output-directory>\n  inspect-texture <input.dds>\n  compare <expected-manifest.json> <actual-manifest.json>\n  create-synthetic <new-output-directory>\n  benchmark-synthetic"
    );
}

#[derive(Serialize)]
struct SyntheticBenchmark {
    schema_version: u32,
    fixture: &'static str,
    pam_decode_iterations: u32,
    pam_decode_total_ms: f64,
    pam_decode_mean_ms: f64,
    dds_plan_iterations: u32,
    dds_plan_total_ms: f64,
    dds_plan_mean_ms: f64,
    mixed_replay_events: usize,
    mixed_replay_total_ms: f64,
    final_fingerprint: String,
    proof_class: &'static str,
}

fn benchmark_synthetic() -> Result<SyntheticBenchmark> {
    let pam = cdmw_formats::synthetic::triangle_pam("synthetic.dds");
    let dds = cdmw_texture::synthetic::rgba8_checker_dds();
    let decode_iterations = 1_000_u32;
    let decode_started = Instant::now();
    let mut document = None;
    for _ in 0..decode_iterations {
        document = Some(decode_mesh(&pam, MeshFormat::Pam)?);
    }
    let decode_elapsed = decode_started.elapsed();
    let dds_iterations = 10_000_u32;
    let dds_started = Instant::now();
    for _ in 0..dds_iterations {
        let _ = cdmw_texture::plan_2d_upload(&dds, TextureRole::BaseColor)?;
    }
    let dds_elapsed = dds_started.elapsed();
    let document = document.context("synthetic decode did not produce a document")?;
    let mut mesh = WorkingMesh::from_document(&document)?;
    let events = (0..1_000)
        .map(|index| {
            if index % 2 == 0 {
                ReplayEvent::Translate {
                    vertex_ordinals: vec![0, 1, 2],
                    delta: [0.0001, 0.0, 0.0],
                }
            } else {
                ReplayEvent::Sculpt {
                    tool: cdmw_replay::ReplaySculptTool::Smooth,
                    vertex_ordinals: vec![0, 1, 2],
                    center: [0.0, 0.0, 0.0],
                    delta: [0.0, 0.0, 0.0],
                    strength: 0.01,
                }
            }
        })
        .collect::<Vec<_>>();
    let replay_started = Instant::now();
    let replay = run_replay(&mut mesh, &events, 8 * 1024 * 1024)?;
    let replay_elapsed = replay_started.elapsed();
    Ok(SyntheticBenchmark {
        schema_version: 1,
        fixture: "3-vertex PAM + 2x2 RGBA8 DDS",
        pam_decode_iterations: decode_iterations,
        pam_decode_total_ms: decode_elapsed.as_secs_f64() * 1_000.0,
        pam_decode_mean_ms: decode_elapsed.as_secs_f64() * 1_000.0 / f64::from(decode_iterations),
        dds_plan_iterations: dds_iterations,
        dds_plan_total_ms: dds_elapsed.as_secs_f64() * 1_000.0,
        dds_plan_mean_ms: dds_elapsed.as_secs_f64() * 1_000.0 / f64::from(dds_iterations),
        mixed_replay_events: replay.events_executed,
        mixed_replay_total_ms: replay_elapsed.as_secs_f64() * 1_000.0,
        final_fingerprint: replay.final_fingerprint,
        proof_class: "synthetic CPU microbenchmark; not real-game or GPU frame proof",
    })
}
