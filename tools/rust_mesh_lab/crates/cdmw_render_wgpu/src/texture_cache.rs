//! Textures kept after the scene that used them is gone (P4 V3).
//!
//! The renderer finds textures by the SHA-256 of their DDS bytes. A scene's
//! bindings hold them; this list holds them too, so a texture outlives its
//! scene. That is what lets the viewport switch between Browse's preview and
//! the edit, or reselect a recent model, without uploading again.
//!
//! A texture some scene still binds is *pinned* (another strong reference
//! exists) and is never dropped here. Unpinned textures are kept in
//! least-recently-used order up to a byte limit; above it the oldest go first.

use std::collections::VecDeque;
use std::sync::Arc;

/// Unpinned textures kept for reuse. One constant, measured in V3 against the
/// memory target (see the parity report).
pub const RETAINED_TEXTURE_LIMIT_BYTES: u64 = 512 * 1024 * 1024;

/// What the cache holds, for reports and tests.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct RetainedTextureReport {
    pub entries: usize,
    pub pinned_entries: usize,
    pub pinned_bytes: u64,
    pub unpinned_bytes: u64,
}

#[derive(Debug)]
pub struct RetainedTextures<T> {
    // Oldest first.
    entries: VecDeque<(String, Arc<T>, u64)>,
    limit_bytes: u64,
}

impl<T> Default for RetainedTextures<T> {
    fn default() -> Self {
        Self::with_limit(RETAINED_TEXTURE_LIMIT_BYTES)
    }
}

impl<T> RetainedTextures<T> {
    #[must_use]
    pub fn with_limit(limit_bytes: u64) -> Self {
        Self {
            entries: VecDeque::new(),
            limit_bytes,
        }
    }

    /// Keep `texture` as the most recently used, then drop unpinned textures
    /// beyond the limit.
    pub fn keep(&mut self, digest: &str, texture: &Arc<T>, bytes: u64) {
        if let Some(position) = self.entries.iter().position(|(key, ..)| key == digest) {
            let entry = self.entries.remove(position).expect("position is in range");
            self.entries.push_back(entry);
        } else {
            self.entries
                .push_back((digest.to_owned(), Arc::clone(texture), bytes));
        }
        self.trim();
    }

    /// A strong reference to a kept texture, marked as just used.
    pub fn get(&mut self, digest: &str) -> Option<Arc<T>> {
        let position = self.entries.iter().position(|(key, ..)| key == digest)?;
        let entry = self.entries.remove(position).expect("position is in range");
        let texture = Arc::clone(&entry.1);
        self.entries.push_back(entry);
        Some(texture)
    }

    /// Drop the oldest unpinned textures until the unpinned bytes fit the limit.
    pub fn trim(&mut self) {
        let mut unpinned = self.report().unpinned_bytes;
        let mut index = 0;
        while unpinned > self.limit_bytes && index < self.entries.len() {
            if Arc::strong_count(&self.entries[index].1) == 1 {
                let (_, _, bytes) = self.entries.remove(index).expect("index is in range");
                unpinned = unpinned.saturating_sub(bytes);
            } else {
                index += 1;
            }
        }
    }

    /// Drop every texture no scene binds (device loss, or memory pressure).
    pub fn release_unpinned(&mut self) {
        self.entries
            .retain(|(_, texture, _)| Arc::strong_count(texture) > 1);
    }

    pub fn clear(&mut self) {
        self.entries.clear();
    }

    #[must_use]
    pub fn report(&self) -> RetainedTextureReport {
        let mut report = RetainedTextureReport {
            entries: self.entries.len(),
            ..RetainedTextureReport::default()
        };
        for (_, texture, bytes) in &self.entries {
            if Arc::strong_count(texture) > 1 {
                report.pinned_entries += 1;
                report.pinned_bytes = report.pinned_bytes.saturating_add(*bytes);
            } else {
                report.unpinned_bytes = report.unpinned_bytes.saturating_add(*bytes);
            }
        }
        report
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_texture_outlives_the_scene_that_bound_it() {
        let mut cache = RetainedTextures::with_limit(100);
        let scene = vec![Arc::new(1_u32), Arc::new(2_u32)];
        cache.keep("a", &scene[0], 40);
        cache.keep("b", &scene[1], 40);
        assert_eq!(cache.report().pinned_entries, 2);
        drop(scene);
        assert_eq!(cache.report().unpinned_bytes, 80);
        assert_eq!(cache.get("a").as_deref(), Some(&1));
    }

    #[test]
    fn the_oldest_unpinned_texture_goes_first_and_pinned_ones_stay() {
        let mut cache = RetainedTextures::with_limit(100);
        let pinned = Arc::new(0_u32);
        cache.keep("pinned", &pinned, 500);
        for (index, digest) in ["a", "b", "c"].into_iter().enumerate() {
            cache.keep(digest, &Arc::new(index as u32), 40);
        }
        // 120 unpinned bytes over a 100-byte limit: "a", the oldest, is dropped.
        assert!(cache.get("a").is_none());
        assert!(cache.get("b").is_some() && cache.get("c").is_some());
        assert!(cache.get("pinned").is_some());
        let report = cache.report();
        assert_eq!((report.pinned_bytes, report.unpinned_bytes), (500, 80));
        // A reused texture becomes the newest: "b" now outlives "c".
        let _ = cache.get("b");
        cache.keep("d", &Arc::new(9_u32), 40);
        assert!(cache.get("c").is_none() && cache.get("b").is_some());
    }

    #[test]
    fn releasing_unpinned_keeps_what_a_scene_still_shows() {
        let mut cache = RetainedTextures::with_limit(1_000);
        let shown = Arc::new(1_u32);
        cache.keep("shown", &shown, 10);
        cache.keep("old", &Arc::new(2_u32), 10);
        cache.release_unpinned();
        assert_eq!(cache.report().entries, 1);
        assert!(cache.get("shown").is_some());
    }
}
