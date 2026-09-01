//! Narrow safe interface around winit's Windows child-window contract.

use raw_window_handle::{HasWindowHandle, RawWindowHandle, Win32WindowHandle};
use std::num::NonZeroIsize;
use winit::window::{Window, WindowAttributes};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EmbeddedWindowError {
    UnsupportedPlatform,
    InvalidParentHandle,
    WindowHandleUnavailable,
    UnexpectedWindowHandle,
}

impl std::fmt::Display for EmbeddedWindowError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let message = match self {
            Self::UnsupportedPlatform => "embedded child windows are supported on Windows only",
            Self::InvalidParentHandle => "embedded parent HWND is invalid",
            Self::WindowHandleUnavailable => "the created window has no native HWND",
            Self::UnexpectedWindowHandle => "the created window is not a Win32 window",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for EmbeddedWindowError {}

#[cfg(target_os = "windows")]
pub fn with_parent_window(
    attributes: WindowAttributes,
    parent_hwnd: u64,
) -> Result<WindowAttributes, EmbeddedWindowError> {
    let parent = isize::try_from(parent_hwnd)
        .ok()
        .and_then(NonZeroIsize::new)
        .ok_or(EmbeddedWindowError::InvalidParentHandle)?;
    let handle = RawWindowHandle::Win32(Win32WindowHandle::new(parent));
    // SAFETY: CDMW supplies a live native Qt HWND and retains it for the child
    // lifetime. The host verifies and reparents again if Qt recreates it.
    Ok(unsafe { attributes.with_parent_window(Some(handle)) })
}

#[cfg(not(target_os = "windows"))]
pub fn with_parent_window(
    _attributes: WindowAttributes,
    _parent_hwnd: u64,
) -> Result<WindowAttributes, EmbeddedWindowError> {
    Err(EmbeddedWindowError::UnsupportedPlatform)
}

pub fn window_hwnd(window: &Window) -> Result<u64, EmbeddedWindowError> {
    let handle = window
        .window_handle()
        .map_err(|_| EmbeddedWindowError::WindowHandleUnavailable)?;
    match handle.as_raw() {
        RawWindowHandle::Win32(handle) => Ok(handle.hwnd.get() as u64),
        _ => Err(EmbeddedWindowError::UnexpectedWindowHandle),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zero_parent_handle_is_rejected() {
        let result = with_parent_window(WindowAttributes::default(), 0);
        assert_eq!(
            result.unwrap_err(),
            EmbeddedWindowError::InvalidParentHandle
        );
    }
}
