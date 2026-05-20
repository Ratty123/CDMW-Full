use std::env;
use std::path::PathBuf;
use std::process;

fn print_usage() {
    eprintln!("Usage:");
    eprintln!("  cd-texture inspect-json <texture.dds>");
    eprintln!("  cd-texture preview-png <texture.dds> <out.png> --max-dim N --slot base|normal|material|height --srgb auto|on|off --normal-space auto|directx|green_up");
}

fn value_after(args: &[String], name: &str, default: &str) -> String {
    args.windows(2)
        .find_map(|window| {
            if window[0] == name {
                Some(window[1].clone())
            } else {
                None
            }
        })
        .unwrap_or_else(|| default.to_string())
}

fn run(args: Vec<String>) -> Result<(), String> {
    if args.len() < 3 {
        print_usage();
        return Err("missing command".to_string());
    }
    match args[1].as_str() {
        "inspect-json" => {
            let path = PathBuf::from(&args[2]);
            let report = cd_texture::inspect_dds(&path);
            println!(
                "{}",
                serde_json::to_string_pretty(&report)
                    .map_err(|error| format!("failed to serialize report: {error}"))?
            );
            Ok(())
        }
        "preview-png" => {
            if args.len() < 4 {
                return Err("preview-png requires input and output paths".to_string());
            }
            let input = PathBuf::from(&args[2]);
            let output = PathBuf::from(&args[3]);
            let max_dim = value_after(&args, "--max-dim", "4096")
                .parse::<u32>()
                .map_err(|error| format!("--max-dim must be an integer: {error}"))?;
            let slot = cd_texture::TextureSlot::parse(&value_after(&args, "--slot", "base"));
            let srgb = cd_texture::SrgbMode::parse(&value_after(&args, "--srgb", "auto"));
            let normal_space =
                cd_texture::NormalSpace::parse(&value_after(&args, "--normal-space", "auto"));
            let report =
                cd_texture::preview_png(&input, &output, max_dim, slot, srgb, normal_space);
            println!(
                "{}",
                serde_json::to_string_pretty(&report)
                    .map_err(|error| format!("failed to serialize report: {error}"))?
            );
            if report.status == "decoded" {
                Ok(())
            } else {
                Err(report.error)
            }
        }
        _ => {
            print_usage();
            Err(format!("unknown command: {}", args[1]))
        }
    }
}

fn main() {
    if let Err(error) = run(env::args().collect()) {
        eprintln!("{error}");
        process::exit(1);
    }
}
