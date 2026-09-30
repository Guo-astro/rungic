//! Idle inhibition from Wayland clients (zwp_idle_inhibit_manager_v1) keeps the phone screen on
//! (docs/72). KWin creates an inhibitor on its output surface while a window inhibits idle
//! (video, presentation); the Java main looper watches `idleInhibitFd` and sets
//! FLAG_KEEP_SCREEN_ON from `idleInhibited` (MainActivity.setKeepAwake, source AWAKE_WAYLAND).

use jni::{objects::JClass, sys::{jboolean, jint}, JNIEnv};
use std::collections::HashSet;
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd};
use std::sync::{Mutex, OnceLock, atomic::{AtomicBool, Ordering}};

/// The surfaces that currently have an inhibitor, by protocol object id. Inhibition holds while
/// any does; a surface counts once however many inhibitors it has.
#[derive(Default)]
pub struct Inhibitors {
    surfaces: HashSet<u32>,
    inhibitors: std::collections::HashMap<u32, u32>,
}

impl Inhibitors {
    /// An inhibitor was created on `surface`; true when inhibition started.
    pub fn add(&mut self, surface: u32) -> bool {
        let count = self.inhibitors.entry(surface).or_insert(0);
        *count += 1;
        let was = !self.surfaces.is_empty();
        self.surfaces.insert(surface);
        !was
    }

    /// An inhibitor of `surface` was destroyed (or its surface went away); true when inhibition ended.
    pub fn remove(&mut self, surface: u32) -> bool {
        let Some(count) = self.inhibitors.get_mut(&surface) else { return false };
        *count -= 1;
        if *count == 0 {
            self.inhibitors.remove(&surface);
            self.surfaces.remove(&surface);
            return self.surfaces.is_empty();
        }
        false
    }

    pub fn inhibited(&self) -> bool {
        !self.surfaces.is_empty()
    }
}

static STATE: Mutex<Option<Inhibitors>> = Mutex::new(None);
static INHIBITED: AtomicBool = AtomicBool::new(false);
static CHANGED: OnceLock<OwnedFd> = OnceLock::new();

fn changed_fd() -> &'static OwnedFd {
    CHANGED.get_or_init(|| {
        let fd = unsafe { libc::eventfd(0, libc::EFD_CLOEXEC | libc::EFD_NONBLOCK) };
        assert!(fd >= 0, "eventfd failed");
        unsafe { OwnedFd::from_raw_fd(fd) }
    })
}

fn publish(inhibited: bool) {
    if INHIBITED.swap(inhibited, Ordering::SeqCst) != inhibited {
        let one = 1u64;
        unsafe { libc::write(changed_fd().as_raw_fd(), &one as *const u64 as *const _, 8) };
    }
}

/// Called by the compositor's IdleInhibitHandler.
pub fn inhibit(surface: u32) {
    let mut state = STATE.lock().unwrap_or_else(|e| e.into_inner());
    let state = state.get_or_insert_with(Inhibitors::default);
    state.add(surface);
    publish(state.inhibited());
}

pub fn uninhibit(surface: u32) {
    let mut state = STATE.lock().unwrap_or_else(|e| e.into_inner());
    let state = state.get_or_insert_with(Inhibitors::default);
    state.remove(surface);
    publish(state.inhibited());
}

pub fn inhibited() -> bool {
    INHIBITED.load(Ordering::SeqCst)
}

#[no_mangle]
pub extern "system" fn Java_com_winland_server_NativeBridge_idleInhibited(_env: JNIEnv, _class: JClass) -> jboolean {
    inhibited() as jboolean
}

/// Readable when `idleInhibited` changed; the reader drains it and reads the state.
#[no_mangle]
pub extern "system" fn Java_com_winland_server_NativeBridge_idleInhibitFd(_env: JNIEnv, _class: JClass) -> jint {
    changed_fd().as_raw_fd()
}

#[cfg(test)]
mod tests {
    use super::Inhibitors;

    #[test]
    fn inhibition_follows_surfaces_not_inhibitor_count() {
        let mut state = Inhibitors::default();
        assert!(state.add(7));            // first inhibitor starts inhibition
        assert!(!state.add(7));           // a second one on the same surface changes nothing
        assert!(!state.add(9));
        assert!(!state.remove(7));        // surface 7 still has one, 9 has one
        assert!(!state.remove(7));        // 7 gone, 9 remains
        assert!(state.inhibited());
        assert!(state.remove(9));         // the last one ends inhibition
        assert!(!state.inhibited());
    }

    #[test]
    fn removing_unknown_inhibitors_is_harmless() {
        let mut state = Inhibitors::default();
        assert!(!state.remove(3));
        assert!(state.add(3));
        assert!(state.remove(3));
        assert!(!state.remove(3));
        assert!(!state.inhibited());
    }
}
