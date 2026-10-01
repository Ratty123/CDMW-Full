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

// Child HWNDs do not receive the top-level WM_NCACTIVATE sequence that winit
// combines with WM_SETFOCUS. Query keyboard focus on the owning event thread.
#[cfg(target_os = "windows")]
mod keyboard_focus {
    #[link(name = "user32")]
    unsafe extern "system" {
        fn GetFocus() -> isize;
        fn SetFocus(window: isize) -> isize;
        fn GetForegroundWindow() -> isize;
        fn GetAncestor(window: isize, flags: u32) -> isize;
        fn IsWindowVisible(window: isize) -> i32;
    }

    pub fn current() -> isize {
        // SAFETY: GetFocus has no parameters and only reads this thread's queue.
        unsafe { GetFocus() }
    }

    pub fn set(window: isize) {
        // SAFETY: callers obtain this live HWND from their retained winit Window.
        // No foreground-window activation or cross-thread input attachment occurs.
        unsafe {
            // A queued host request can arrive after the user changed tabs or
            // switched applications. It must never activate a hidden child or
            // take keyboard focus back from another foreground window.
            if IsWindowVisible(window) != 0
                && GetForegroundWindow() == GetAncestor(window, 2)
            {
                SetFocus(window);
            }
        }
    }
}

pub fn has_keyboard_focus(window: &Window) -> Result<bool, EmbeddedWindowError> {
    #[cfg(target_os = "windows")]
    {
        Ok(keyboard_focus::current() == window_hwnd(window)? as isize)
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = window;
        Err(EmbeddedWindowError::UnsupportedPlatform)
    }
}

pub fn focus_child_window(window: &Window) -> Result<bool, EmbeddedWindowError> {
    #[cfg(target_os = "windows")]
    {
        keyboard_focus::set(window_hwnd(window)? as isize);
        has_keyboard_focus(window)
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = window;
        Err(EmbeddedWindowError::UnsupportedPlatform)
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

    #[cfg(target_os = "windows")]
    #[test]
    fn hidden_window_focus_request_keeps_keyboard_focus_unchanged() {
        use winit::application::ApplicationHandler;
        use winit::event_loop::{ActiveEventLoop, EventLoop};
        use winit::platform::windows::EventLoopBuilderExtWindows;

        struct Probe(bool);
        impl ApplicationHandler for Probe {
            fn resumed(&mut self, event_loop: &ActiveEventLoop) {
                let window = event_loop
                    .create_window(Window::default_attributes().with_visible(false))
                    .unwrap();
                let before = keyboard_focus::current();
                assert!(!focus_child_window(&window).unwrap());
                assert_eq!(keyboard_focus::current(), before);
                self.0 = true;
                event_loop.exit();
            }

            fn window_event(
                &mut self,
                _event_loop: &ActiveEventLoop,
                _window_id: winit::window::WindowId,
                _event: winit::event::WindowEvent,
            ) {
            }
        }

        let event_loop = EventLoop::builder().with_any_thread(true).build().unwrap();
        let mut probe = Probe(false);
        event_loop.run_app(&mut probe).unwrap();
        assert!(probe.0);
    }
}
