//! Android Choreographer clock shared with the compositor. No queued per-frame JNI commands.
//!
//! On-demand vsync: while the desktop is static the compositor loop parks. It
//! stops asking Java for Choreographer callbacks (`wantsVsync`) and sleeps in
//! poll() on the Wayland sockets and a kick eventfd (JNI commands, SurfaceFlinger
//! release callbacks) instead of waking every vsync. Leaving the parked state
//! signals `vsyncWakeFd`, which the Java main looper watches, so the next frame
//! is paced by vsync again.
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd, RawFd};
use std::sync::{Condvar, Mutex, OnceLock, atomic::{AtomicBool, AtomicI32, AtomicU64, Ordering}};
use std::time::Duration;
use jni::{JNIEnv, objects::JClass, sys::{jboolean, jint}};
static TICK: Mutex<u64> = Mutex::new(0);
static WAKE: Condvar = Condvar::new();
static TIME_NS: AtomicU64 = AtomicU64::new(0);
static REFRESH: AtomicI32 = AtomicI32::new(60000);
static PRESENTS: AtomicU64 = AtomicU64::new(0);
static WANT_VSYNC: AtomicBool = AtomicBool::new(true);
static PARKS: AtomicU64 = AtomicU64::new(0);
pub fn refresh_mhz() -> i32 { REFRESH.load(Ordering::Relaxed) }
pub fn set_refresh(hz: f32) { if hz.is_finite() { REFRESH.store((hz.clamp(1.0,240.0)*1000.0).round() as i32, Ordering::Relaxed); } }
pub fn timestamp_ms() -> u32 { (TIME_NS.load(Ordering::Relaxed)/1_000_000) as u32 }
pub fn presented_count() -> u64 { PRESENTS.load(Ordering::Relaxed) }
pub fn note_present() { PRESENTS.fetch_add(1, Ordering::Relaxed); }
pub fn wait_next(last: &mut u64) {
    let tick = TICK.lock().unwrap_or_else(|e|e.into_inner());
    let (tick, _) = WAKE.wait_timeout_while(tick, Duration::from_millis(100), |v|*v==*last).unwrap_or_else(|e|e.into_inner());
    *last = *tick;
}

fn eventfd() -> OwnedFd {
    let fd = unsafe { libc::eventfd(0, libc::EFD_CLOEXEC | libc::EFD_NONBLOCK) };
    assert!(fd >= 0, "eventfd failed");
    unsafe { OwnedFd::from_raw_fd(fd) }
}
fn signal(fd: &OwnedFd) {
    let one = 1u64;
    unsafe { libc::write(fd.as_raw_fd(), &one as *const u64 as *const _, 8) };
}
fn drain(fd: &OwnedFd) {
    let mut value = 0u64;
    unsafe { libc::read(fd.as_raw_fd(), &mut value as *mut u64 as *mut _, 8) };
}
/// Wakes the parked compositor loop.
static KICK: OnceLock<OwnedFd> = OnceLock::new();
/// Signalled on every Choreographer tick, for the active loop's poll (wait_active).
static TICK_FD: OnceLock<OwnedFd> = OnceLock::new();
/// Tells the Java main looper to resume Choreographer callbacks.
static RESUME: OnceLock<OwnedFd> = OnceLock::new();

/// Wake the compositor loop if it is parked. Cheap; callable from any thread.
pub fn kick() { signal(KICK.get_or_init(eventfd)); }

/// Parked wait: until a Wayland fd is readable, `kick()` or the timeout.
pub fn wait_parked(fds: &[RawFd], timeout: Duration) {
    let kick = KICK.get_or_init(eventfd);
    let mut polls: Vec<libc::pollfd> = std::iter::once(kick.as_raw_fd()).chain(fds.iter().copied())
        .map(|fd| libc::pollfd { fd, events: libc::POLLIN, revents: 0 }).collect();
    unsafe { libc::poll(polls.as_mut_ptr(), polls.len() as libc::nfds_t, timeout.as_millis() as i32) };
    drain(kick);
    // Frame callbacks sent before the next Choreographer tick carry the current time.
    let mut now = libc::timespec { tv_sec: 0, tv_nsec: 0 };
    if unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut now) } == 0 {
        TIME_NS.store(now.tv_sec as u64 * 1_000_000_000 + now.tv_nsec as u64, Ordering::Relaxed);
    }
}

/// Active wait: until the next Choreographer tick, a Wayland fd is readable or `kick()`
/// (JNI commands, SurfaceFlinger callbacks), whichever comes first. A client commit is
/// handled when it arrives, not at the next tick: KWin's frames land anywhere in the
/// vsync period, and one landing just after a tick used to wait almost a full period
/// while the next one caught up with it, so the display skipped a vsync (docs/59).
/// `last` follows the tick count like `wait_next`.
pub fn wait_active(fds: &[RawFd], last: &mut u64) {
    let tick = TICK_FD.get_or_init(eventfd);
    let kick = KICK.get_or_init(eventfd);
    let mut polls: Vec<libc::pollfd> = [tick.as_raw_fd(), kick.as_raw_fd()].into_iter().chain(fds.iter().copied())
        .map(|fd| libc::pollfd { fd, events: libc::POLLIN, revents: 0 }).collect();
    unsafe { libc::poll(polls.as_mut_ptr(), polls.len() as libc::nfds_t, 100) };
    if polls[0].revents != 0 { drain(tick); }
    if polls[1].revents != 0 { drain(kick); }
    *last = *TICK.lock().unwrap_or_else(|e| e.into_inner());
}

/// Whether the loop is paced by vsync. Resuming signals the Java looper.
pub fn set_wants_vsync(want: bool) {
    if WANT_VSYNC.swap(want, Ordering::SeqCst) != want {
        if want { signal(RESUME.get_or_init(eventfd)); } else { PARKS.fetch_add(1, Ordering::Relaxed); }
    }
}
pub fn wants_vsync() -> bool { WANT_VSYNC.load(Ordering::SeqCst) }
pub fn stats() -> String {
    format!("vsync_wanted={} parks={}", wants_vsync(), PARKS.load(Ordering::Relaxed))
}

#[no_mangle]
pub extern "system" fn Java_com_winland_server_NativeBridge_frameTick(_env:JNIEnv, _class:JClass, time_ns:i64) {
    if time_ns <= 0 { return; }
    TIME_NS.store(time_ns as u64,Ordering::Relaxed);
    let mut tick=TICK.lock().unwrap_or_else(|e|e.into_inner());
    *tick=tick.wrapping_add(1);
    WAKE.notify_one();
    signal(TICK_FD.get_or_init(eventfd));
}
#[no_mangle]
pub extern "system" fn Java_com_winland_server_NativeBridge_getPresentedFrames(_env:JNIEnv, _class:JClass) -> i64 {
    PRESENTS.load(Ordering::Relaxed) as i64
}
#[no_mangle]
pub extern "system" fn Java_com_winland_server_NativeBridge_wantsVsync(_env:JNIEnv, _class:JClass) -> jboolean {
    wants_vsync() as jboolean
}
/// Readable when the compositor wants vsync again; the reader drains it.
#[no_mangle]
pub extern "system" fn Java_com_winland_server_NativeBridge_vsyncWakeFd(_env:JNIEnv, _class:JClass) -> jint {
    RESUME.get_or_init(eventfd).as_raw_fd()
}

// Startup proof is separate from PRESENTS (which counts submissions). Only the
// phone presenter may confirm it; cast, timeout and fabricated feedback cannot.
static PHONE_GATE: super::presentation_gate::PresentationGate = super::presentation_gate::PresentationGate::new();
pub fn arm_phone_proof(ticket: u64) { PHONE_GATE.arm(ticket); }
pub fn phone_proof() -> u64 { PHONE_GATE.pending() }
pub fn confirm_phone_proof(ticket: u64) { PHONE_GATE.confirm(ticket); }
#[no_mangle]
pub extern "system" fn Java_com_winland_server_NativeBridge_requestPhoneFrame(_env:JNIEnv, _class:JClass) -> i64 {
    let ticket = PHONE_GATE.request();
    if crate::android::command_channel::send_command(
        crate::android::command_channel::JniCommand::AwaitPhoneFrame { ticket }) { ticket as i64 }
    else { PHONE_GATE.cancel(ticket); 0 }
}
#[no_mangle]
pub extern "system" fn Java_com_winland_server_NativeBridge_isPhoneFrameReady(_env:JNIEnv, _class:JClass, ticket:i64) -> jboolean {
    (ticket > 0 && PHONE_GATE.ready(ticket as u64)) as jboolean
}
#[no_mangle]
pub extern "system" fn Java_com_winland_server_NativeBridge_cancelPhoneFrame(_env:JNIEnv, _class:JClass, ticket:i64) {
    PHONE_GATE.cancel(ticket as u64); kick();
}
