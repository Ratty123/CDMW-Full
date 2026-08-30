#![forbid(unsafe_code)]

use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap};
use std::path::Path;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RelationKind {
    MaterialSidecar,
    BaseColorTexture,
    NormalTexture,
    MaterialTexture,
    RoughnessTexture,
    MetalnessTexture,
    OcclusionTexture,
    SpecularTexture,
    GlossinessTexture,
    EmissiveTexture,
    OpacityTexture,
    HeightTexture,
    FlowTexture,
    Skeleton,
    SkeletonVariation,
    MorphTargetSet,
    AppearanceDescriptor,
    PrefabData,
    MeshInfo,
    PhysicsReference,
    Companion,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ResolutionMethod {
    ExplicitVirtualPath,
    NormalizedVirtualPath,
    SamePackageRelative,
    UnambiguousBasename,
    ProvenFamilyRule,
    Heuristic,
    Unresolved,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AssetRelation {
    pub source_virtual_path: String,
    pub requested_reference: String,
    pub target_virtual_path: Option<String>,
    pub kind: RelationKind,
    pub method: ResolutionMethod,
    pub confidence: f32,
    pub ambiguity_count: usize,
    pub evidence: String,
    pub target_exists: bool,
    pub target_format_supported: bool,
}

#[derive(Debug, Clone)]
pub struct AssetIndex {
    canonical: BTreeMap<String, String>,
    basenames: HashMap<String, Vec<String>>,
}

impl AssetIndex {
    #[must_use]
    pub fn new(paths: impl IntoIterator<Item = String>) -> Self {
        let mut canonical = BTreeMap::new();
        let mut basenames: HashMap<String, Vec<String>> = HashMap::new();
        for path in paths {
            let normalized = normalize(&path);
            canonical
                .entry(normalized.clone())
                .or_insert_with(|| path.clone());
            let basename = normalized
                .rsplit('/')
                .next()
                .unwrap_or(normalized.as_str())
                .to_owned();
            basenames.entry(basename).or_default().push(path);
        }
        for values in basenames.values_mut() {
            values.sort();
            values.dedup();
        }
        Self {
            canonical,
            basenames,
        }
    }

    #[must_use]
    pub fn resolve(
        &self,
        source: &str,
        reference: &str,
        kind: RelationKind,
        supported_extensions: &[&str],
    ) -> AssetRelation {
        let normalized_reference = normalize(reference);
        if let Some(target) = self.canonical.get(&normalized_reference) {
            return relation(
                source,
                reference,
                target,
                kind,
                ResolutionMethod::ExplicitVirtualPath,
                1.0,
                1,
                supported_extensions,
            );
        }
        let source_parent = Path::new(source.replace('\\', "/").as_str())
            .parent()
            .map(|path| path.to_string_lossy().replace('\\', "/"))
            .unwrap_or_default();
        let relative = normalize(format!("{source_parent}/{reference}").as_str());
        if let Some(target) = self.canonical.get(&relative) {
            return relation(
                source,
                reference,
                target,
                kind,
                ResolutionMethod::SamePackageRelative,
                0.98,
                1,
                supported_extensions,
            );
        }
        let basename = normalized_reference
            .rsplit('/')
            .next()
            .unwrap_or(normalized_reference.as_str());
        if let Some(candidates) = self.basenames.get(basename) {
            if let Some(target) = candidates.first().filter(|_| candidates.len() == 1) {
                return relation(
                    source,
                    reference,
                    target,
                    kind,
                    ResolutionMethod::UnambiguousBasename,
                    0.85,
                    1,
                    supported_extensions,
                );
            }
            return AssetRelation {
                source_virtual_path: source.to_owned(),
                requested_reference: reference.to_owned(),
                target_virtual_path: None,
                kind,
                method: ResolutionMethod::Unresolved,
                confidence: 0.0,
                ambiguity_count: candidates.len(),
                evidence: "basename is ambiguous; no candidate selected".to_owned(),
                target_exists: false,
                target_format_supported: false,
            };
        }
        AssetRelation {
            source_virtual_path: source.to_owned(),
            requested_reference: reference.to_owned(),
            target_virtual_path: None,
            kind,
            method: ResolutionMethod::Unresolved,
            confidence: 0.0,
            ambiguity_count: 0,
            evidence: "no exact, relative, or unambiguous basename match".to_owned(),
            target_exists: false,
            target_format_supported: false,
        }
    }
}

fn relation(
    source: &str,
    reference: &str,
    target: &str,
    kind: RelationKind,
    method: ResolutionMethod,
    confidence: f32,
    ambiguity_count: usize,
    supported_extensions: &[&str],
) -> AssetRelation {
    let extension = Path::new(target)
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("");
    AssetRelation {
        source_virtual_path: source.to_owned(),
        requested_reference: reference.to_owned(),
        target_virtual_path: Some(target.to_owned()),
        kind,
        method,
        confidence,
        ambiguity_count,
        evidence: format!("resolved through {method:?}"),
        target_exists: true,
        target_format_supported: supported_extensions
            .iter()
            .any(|candidate| extension.eq_ignore_ascii_case(candidate)),
    }
}

fn normalize(value: &str) -> String {
    let mut parts = Vec::new();
    for part in value.replace('\\', "/").split('/') {
        match part {
            "" | "." => {}
            ".." => {
                let _ = parts.pop();
            }
            other => parts.push(other.to_ascii_lowercase()),
        }
    }
    parts.join("/")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ambiguous_basename_never_selects_a_target() {
        let index = AssetIndex::new([
            "character/a/body.dds".to_owned(),
            "character/b/body.dds".to_owned(),
        ]);
        let relation = index.resolve(
            "character/model.pac",
            "body.dds",
            RelationKind::BaseColorTexture,
            &["dds"],
        );
        assert_eq!(relation.method, ResolutionMethod::Unresolved);
        assert_eq!(relation.ambiguity_count, 2);
        assert!(relation.target_virtual_path.is_none());
    }

    #[test]
    fn relative_reference_beats_basename_search() {
        let index = AssetIndex::new(["character/hero/body.dds".to_owned()]);
        let relation = index.resolve(
            "character/hero/model.pac",
            "body.dds",
            RelationKind::BaseColorTexture,
            &["dds"],
        );
        assert_eq!(relation.method, ResolutionMethod::SamePackageRelative);
        assert_eq!(
            relation.target_virtual_path.as_deref(),
            Some("character/hero/body.dds")
        );
    }
}
