//! Zero-copy presentation of a client's leased AHardwareBuffer.
//!
//! When a frame consists of one full-surface buffer from the GPU allocator
//! (KWin's output), the buffer is handed to SurfaceFlinger on a child
//! ASurfaceControl of the SurfaceView window instead of being drawn with GLES.
//! The Wayland buffer stays referenced, so `wl_buffer.release` is not sent to
//! the client, until SurfaceFlinger releases the AHardwareBuffer
//! (ASurfaceTransaction_setBufferWithRelease, API 36) and the release fence
//! has signalled. Anything else falls back to the GLES compositor, which keeps
//! running underneath; the child layer is hidden while falling back.
//!
//! `setprop debug.rungic.zerocopy 0` disables the path at run time.
use std::collections::HashMap;
use std::ffi::{c_char, c_int, c_void, CStr};
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

use crate::android::gpu_allocator::Buffer as AhbBuffer;

type WaylandBuffer = smithay::backend::renderer::utils::Buffer;

#[link(name = "android")]
extern "C" {
    fn ASurfaceControl_createFromWindow(parent: *mut ndk_sys::ANativeWindow, name: *const c_char) -> *mut c_void;
    fn ASurfaceControl_release(control: *mut c_void);
    fn ASurfaceTransaction_create() -> *mut c_void;
    fn ASurfaceTransaction_delete(txn: *mut c_void);
    fn ASurfaceTransaction_apply(txn: *mut c_void);
    fn ASurfaceTransaction_setVisibility(txn: *mut c_void, control: *mut c_void, visibility: i8);
    fn ASurfaceTransaction_setZOrder(txn: *mut c_void, control: *mut c_void, z: i32);
    fn ASurfaceTransaction_setBufferTransparency(txn: *mut c_void, control: *mut c_void, transparency: i8);
    fn ASurfaceTransaction_setScale(txn: *mut c_void, control: *mut c_void, x: f32, y: f32);
    fn ASurfaceTransaction_setGeometry(txn: *mut c_void, control: *mut c_void, source: *const ARect, destination: *const ARect, transform: i32);
    fn ASurfaceTransaction_setDamageRegion(txn: *mut c_void, control: *mut c_void, rects: *const ARect, count: u32);
    fn ASurfaceTransaction_setBufferDataSpace(txn: *mut c_void, control: *mut c_void, data_space: i32);
    fn ASurfaceTransaction_setOnComplete(txn: *mut c_void, context: *mut c_void, func: OnComplete);
    fn ASurfaceTransactionStats_getLatchTime(stats: *mut c_void) -> i64;
    fn ASurfaceTransactionStats_getPresentFenceFd(stats: *mut c_void) -> c_int;
}
type OnComplete = unsafe extern "C" fn(context: *mut c_void, stats: *mut c_void);
type Feedback = smithay::wayland::presentation::PresentationFeedbackCallback;

/// Kernel sync_file API (include/uapi/linux/sync_file.h): read when a fence signalled.
#[repr(C)]
struct SyncFenceInfo { obj_name: [u8; 32], driver_name: [u8; 32], status: i32, flags: u32, timestamp_ns: u64 }
#[repr(C)]
struct SyncFileInfo { name: [u8; 32], status: i32, flags: u32, num_fences: u32, pad: u32, sync_fence_info: u64 }
const SYNC_IOC_FILE_INFO: libc::c_ulong = 0xC038_3E04; // _IOWR('>', 4, struct sync_file_info)

/// CLOCK_MONOTONIC time at which a signalled sync_file's last fence signalled.
fn fence_signal_time(fd: &OwnedFd) -> Option<u64> {
    let mut info: SyncFileInfo = unsafe { std::mem::zeroed() };
    if unsafe { libc::ioctl(fd.as_raw_fd(), SYNC_IOC_FILE_INFO as _, &mut info) } != 0 || info.status != 1 || info.num_fences == 0 {
        return None;
    }
    let mut fences: Vec<SyncFenceInfo> = (0..info.num_fences).map(|_| unsafe { std::mem::zeroed() }).collect();
    info.sync_fence_info = fences.as_mut_ptr() as u64;
    if unsafe { libc::ioctl(fd.as_raw_fd(), SYNC_IOC_FILE_INFO as _, &mut info) } != 0 {
        return None;
    }
    fences.iter().map(|f| f.timestamp_ns).max().filter(|t| *t > 0)
}

struct CompleteContext {
    id: u64,
    tx: Sender<(u64, i64, c_int)>,
}

unsafe extern "C" fn on_complete(context: *mut c_void, stats: *mut c_void) {
    let context = Box::from_raw(context as *mut CompleteContext);
    let latch = ASurfaceTransactionStats_getLatchTime(stats);
    let present = ASurfaceTransactionStats_getPresentFenceFd(stats);
    if context.tx.send((context.id, latch, present)).is_err() && present >= 0 {
        libc::close(present);
    }
    crate::android::frame_clock::kick();
}

static FEEDBACK_IMPLAUSIBLE: AtomicU64 = AtomicU64::new(0);

/// Presentation times must lie in the recent past on CLOCK_MONOTONIC; anything
/// else is replaced by "now" and no longer reported as a hardware timestamp.
fn plausible(time_ns: u64, hardware: bool) -> (u64, bool) {
    let now = monotonic_ns();
    if time_ns > now + 5_000_000 || time_ns + 1_000_000_000 < now {
        FEEDBACK_IMPLAUSIBLE.fetch_add(1, Ordering::Relaxed);
        (now, false)
    } else {
        (time_ns, hardware)
    }
}

fn monotonic_ns() -> u64 {
    let mut now = libc::timespec { tv_sec: 0, tv_nsec: 0 };
    unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut now) };
    now.tv_sec as u64 * 1_000_000_000 + now.tv_nsec as u64
}

/// A frame's presentation: when it reached the screen, and whether the time is
/// the display's own (present fence) or SurfaceFlinger's latch estimate.
pub(crate) struct Presented {
    pub callbacks: Vec<Feedback>,
    pub time_ns: u64,
    pub hardware: bool,
}

#[repr(C)]
struct ARect { left: i32, top: i32, right: i32, bottom: i32 }
const ADATASPACE_SRGB: i32 = 142671872;

const TRANSPARENCY_OPAQUE: i8 = 2;
type OnBufferRelease = unsafe extern "C" fn(context: *mut c_void, release_fence_fd: c_int);
type SetBufferWithRelease = unsafe extern "C" fn(
    txn: *mut c_void, control: *mut c_void, buffer: *mut c_void, acquire_fence_fd: c_int,
    context: *mut c_void, func: OnBufferRelease);

fn set_buffer_with_release() -> Option<SetBufferWithRelease> {
    static SYMBOL: OnceLock<Option<SetBufferWithRelease>> = OnceLock::new();
    *SYMBOL.get_or_init(|| unsafe {
        let lib = libc::dlopen(c"libandroid.so".as_ptr(), libc::RTLD_NOW | libc::RTLD_NOLOAD);
        let lib = if lib.is_null() { libc::dlopen(c"libandroid.so".as_ptr(), libc::RTLD_NOW) } else { lib };
        if lib.is_null() {
            return None;
        }
        let sym = libc::dlsym(lib, c"ASurfaceTransaction_setBufferWithRelease".as_ptr());
        (!sym.is_null()).then(|| std::mem::transmute::<*mut c_void, SetBufferWithRelease>(sym))
    })
}

// ── Counters for native-stats (tools/rungic_agent.py host_request native-stats) ──
static FRAMES: AtomicU64 = AtomicU64::new(0);
static FALLBACKS: AtomicU64 = AtomicU64::new(0);
static RELEASED: AtomicU64 = AtomicU64::new(0);
static IN_FLIGHT: AtomicU64 = AtomicU64::new(0);
static AVAILABLE: AtomicBool = AtomicBool::new(false);
static ACQUIRE_FENCES: AtomicU64 = AtomicU64::new(0);
static FEEDBACK_HW: AtomicU64 = AtomicU64::new(0);
static FEEDBACK_LATCH: AtomicU64 = AtomicU64::new(0);
static FEEDBACK_TIMEOUT: AtomicU64 = AtomicU64::new(0);
static FEEDBACK_PENDING: AtomicU64 = AtomicU64::new(0);
/// A client's frame must always complete: KWin's render loop waits for presented/
/// discarded, so a lost SurfaceFlinger completion would freeze the desktop.
const FEEDBACK_DEADLINE: Duration = Duration::from_millis(60);
fn reason() -> &'static Mutex<&'static str> {
    static R: OnceLock<Mutex<&'static str>> = OnceLock::new();
    R.get_or_init(|| Mutex::new("none"))
}

pub fn note_fallback(why: &'static str) {
    FALLBACKS.fetch_add(1, Ordering::Relaxed);
    if let Ok(mut r) = reason().lock() {
        *r = why;
    }
}

pub fn stats() -> String {
    format!(
        "zero_copy(enabled={} available={} frames={} acquire_fences={} feedback_hw={} feedback_latch={} feedback_timeout={} feedback_pending={} feedback_implausible={} fallback={} last_fallback={} in_flight={} released={})",
        enabled(),
        AVAILABLE.load(Ordering::Relaxed),
        FRAMES.load(Ordering::Relaxed),
        ACQUIRE_FENCES.load(Ordering::Relaxed),
        FEEDBACK_HW.load(Ordering::Relaxed),
        FEEDBACK_LATCH.load(Ordering::Relaxed),
        FEEDBACK_TIMEOUT.load(Ordering::Relaxed),
        FEEDBACK_PENDING.load(Ordering::Relaxed),
        FEEDBACK_IMPLAUSIBLE.load(Ordering::Relaxed),
        FALLBACKS.load(Ordering::Relaxed),
        reason().lock().map(|r| *r).unwrap_or("?"),
        IN_FLIGHT.load(Ordering::Relaxed),
        RELEASED.load(Ordering::Relaxed),
    )
}

fn property(name: &CStr) -> Vec<u8> {
    let mut value = [0 as c_char; 92];
    let len = unsafe { libc::__system_property_get(name.as_ptr(), value.as_mut_ptr()) };
    if len <= 0 { Vec::new() } else { unsafe { CStr::from_ptr(value.as_ptr()) }.to_bytes().to_vec() }
}

fn cached(cache: &Mutex<Option<(Instant, bool)>>, read: impl FnOnce() -> bool) -> bool {
    let mut cache = cache.lock().unwrap_or_else(|e| e.into_inner());
    if let Some((at, value)) = *cache {
        if at.elapsed() < Duration::from_millis(500) {
            return value;
        }
    }
    let value = read();
    *cache = Some((Instant::now(), value));
    value
}

/// `debug.rungic.zerocopy` (default on), re-read at most every 500 ms.
pub fn enabled() -> bool {
    static CACHE: Mutex<Option<(Instant, bool)>> = Mutex::new(None);
    cached(&CACHE, || property(c"debug.rungic.zerocopy") != b"0")
}

/// `debug.rungic.ondemand_vsync=0`: follow every vsync even on a static desktop
/// (frame_clock.rs), for A/B measurements.
pub fn on_demand_vsync() -> bool {
    static CACHE: Mutex<Option<(Instant, bool)>> = Mutex::new(None);
    cached(&CACHE, || property(c"debug.rungic.ondemand_vsync") != b"0")
}

/// `debug.rungic.present_feedback=hw`: report zero-copy frames with SurfaceFlinger's
/// real present time. Off by default: KWin turns (present - frame callback) into
/// its render safety margin, and the real 1-2 vsync pipeline delay cut its frame
/// rate about 3.5x (docs/57). The default reports the frame when it is submitted.
pub fn hardware_feedback() -> bool {
    static CACHE: Mutex<Option<(Instant, bool)>> = Mutex::new(None);
    cached(&CACHE, || property(c"debug.rungic.present_feedback") == b"hw")
}

/// What must stay alive until SurfaceFlinger no longer reads the buffer.
struct Held {
    _wayland: WaylandBuffer, // dropping it sends wl_buffer.release
    _ahb: Arc<AhbBuffer>,
    _release: Option<Arc<crate::android::backend::wayland::explicit_sync::ReleaseOnDrop>>,
}

struct ReleaseContext {
    id: u64,
    tx: Sender<(u64, c_int)>,
}

unsafe extern "C" fn on_buffer_release(context: *mut c_void, release_fence_fd: c_int) {
    // Invoked exactly once per buffer set with a callback, on any thread.
    let context = Box::from_raw(context as *mut ReleaseContext);
    if context.tx.send((context.id, release_fence_fd)).is_err() && release_fence_fd >= 0 {
        libc::close(release_fence_fd);
    }
    crate::android::frame_clock::kick();
}

pub(crate) struct Presenter {
    control: *mut c_void,
    visible: bool,
    next_id: u64,
    unclaimed: Option<u64>,
    startup_proofs: HashMap<u64, u64>,
    feedback: HashMap<u64, (Instant, Vec<Feedback>)>,
    completions: HashMap<u64, (i64, Option<OwnedFd>)>,
    ready: Vec<Presented>,
    complete_tx: Sender<(u64, i64, c_int)>,
    complete_rx: Receiver<(u64, i64, c_int)>,
    in_flight: HashMap<u64, Held>,
    releasing: Vec<(Held, OwnedFd)>,
    tx: Sender<(u64, c_int)>,
    rx: Receiver<(u64, c_int)>,
}

impl std::fmt::Debug for Presenter {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Presenter(visible={}, in_flight={}, releasing={})", self.visible, self.in_flight.len(), self.releasing.len())
    }
}

impl Presenter {
    pub fn new(window: *mut ndk_sys::ANativeWindow) -> Option<Self> {
        if window.is_null() || set_buffer_with_release().is_none() {
            AVAILABLE.store(false, Ordering::Relaxed);
            return None;
        }
        let control = unsafe { ASurfaceControl_createFromWindow(window, c"rungic-zero-copy".as_ptr()) };
        if control.is_null() {
            AVAILABLE.store(false, Ordering::Relaxed);
            return None;
        }
        AVAILABLE.store(true, Ordering::Relaxed);
        let (tx, rx) = channel();
        let (complete_tx, complete_rx) = channel();
        log::info!("zero-copy: child SurfaceControl ready");
        Some(Self {
            control, visible: false, next_id: 0, unclaimed: None, feedback: HashMap::new(),
            startup_proofs: HashMap::new(),
            completions: HashMap::new(), ready: Vec::new(), complete_tx, complete_rx,
            in_flight: HashMap::new(), releasing: Vec::new(), tx, rx,
        })
    }

    /// Release Wayland buffers whose SurfaceFlinger release fence has signalled.
    /// Call from the compositor thread (it owns the Wayland display).
    pub fn collect(&mut self) {
        while let Ok((id, fence)) = self.rx.try_recv() {
            let Some(held) = self.in_flight.remove(&id) else {
                if fence >= 0 {
                    unsafe { libc::close(fence) };
                }
                continue;
            };
            if fence < 0 {
                drop(held);
                RELEASED.fetch_add(1, Ordering::Relaxed);
            } else {
                self.releasing.push((held, unsafe { OwnedFd::from_raw_fd(fence) }));
            }
        }
        self.releasing.retain(|(_, fence)| {
            let mut poll = libc::pollfd { fd: fence.as_raw_fd(), events: libc::POLLIN, revents: 0 };
            let signalled = unsafe { libc::poll(&mut poll, 1, 0) } > 0;
            if signalled {
                RELEASED.fetch_add(1, Ordering::Relaxed);
            }
            !signalled
        });
        IN_FLIGHT.store((self.in_flight.len() + self.releasing.len()) as u64, Ordering::Relaxed);
        while let Ok((id, latch, present)) = self.complete_rx.try_recv() {
            let fence = (present >= 0).then(|| unsafe { OwnedFd::from_raw_fd(present) });
            self.completions.insert(id, (latch, fence));
        }
        self.resolve_feedback();
    }

    /// The zero-copy frame presented since the last call, if any: its presentation
    /// feedback must wait for SurfaceFlinger instead of being sent now.
    pub fn take_unclaimed_frame(&mut self) -> Option<u64> {
        self.unclaimed.take()
    }

    /// Called only by the phone backend immediately after submitting a frame.
    pub fn track_startup_frame(&mut self, ticket: u64) {
        if ticket != 0 { if let Some(id) = self.unclaimed { self.startup_proofs.insert(id, ticket); } }
    }

    pub fn attach_feedback(&mut self, id: u64, callbacks: Vec<Feedback>) {
        if !callbacks.is_empty() {
            self.feedback.insert(id, (Instant::now(), callbacks));
            self.resolve_feedback();
        }
    }

    /// Frames whose presentation time is known, to be reported by the caller.
    pub fn drain_presented(&mut self) -> Vec<Presented> {
        std::mem::take(&mut self.ready)
    }

    fn resolve_feedback(&mut self) {
        let active = crate::android::frame_clock::phone_proof();
        self.startup_proofs.retain(|_, ticket| active != 0 && *ticket == active);
        let ids: Vec<u64> = self.completions.keys().copied().collect();
        for id in ids {
            let (latch, fence) = &self.completions[&id];
            let latch_ns = u64::try_from(*latch).ok().filter(|t| *t > 0);
            let (time, hardware) = match fence {
                Some(fence) => {
                    let mut poll = libc::pollfd { fd: fence.as_raw_fd(), events: libc::POLLIN, revents: 0 };
                    if unsafe { libc::poll(&mut poll, 1, 0) } <= 0 {
                        continue; // not on screen yet
                    }
                    match fence_signal_time(fence) {
                        Some(t) => (t, true),
                        None => (latch_ns.unwrap_or_else(monotonic_ns), false),
                    }
                }
                None => (latch_ns.unwrap_or_else(monotonic_ns), false),
            };
            // A real completed transaction/fence, not the feedback timeout below.
            if (hardware || latch_ns.is_some()) && self.visible {
                if let Some(ticket) = self.startup_proofs.remove(&id) {
                    crate::android::frame_clock::confirm_phone_proof(ticket);
                }
            }
            let callbacks = self.feedback.remove(&id).map(|(_, c)| c).unwrap_or_default();
            // Completions of frames without feedback are only kept briefly.
            if callbacks.is_empty() && id + 8 > self.next_id {
                continue;
            }
            self.completions.remove(&id);
            if !callbacks.is_empty() {
                // KWin derives its render safety margin from this time; a bogus value
                // (e.g. getLatchTime() == -1 read as unsigned) froze the desktop.
                let (time, hardware) = plausible(time, hardware);
                if hardware { &FEEDBACK_HW } else { &FEEDBACK_LATCH }.fetch_add(1, Ordering::Relaxed);
                self.ready.push(Presented { callbacks, time_ns: time, hardware });
            }
        }
        // Liveness: never let a frame wait for SurfaceFlinger longer than the deadline.
        let expired: Vec<u64> = self.feedback.iter()
            .filter(|(_, (since, _))| since.elapsed() > FEEDBACK_DEADLINE).map(|(id, _)| *id).collect();
        for id in expired {
            self.startup_proofs.remove(&id);
            let (_, callbacks) = self.feedback.remove(&id).expect("listed above");
            let latch = self.completions.remove(&id).and_then(|(latch, _)| u64::try_from(latch).ok()).filter(|t| *t > 0);
            FEEDBACK_TIMEOUT.fetch_add(1, Ordering::Relaxed);
            let (time_ns, _) = plausible(latch.unwrap_or_else(monotonic_ns), false);
            self.ready.push(Presented { callbacks, time_ns, hardware: false });
        }
        FEEDBACK_PENDING.store(self.feedback.len() as u64, Ordering::Relaxed);
    }

    /// Report every pending frame now (zero-copy switched off, layer hidden).
    pub fn flush_feedback(&mut self) {
        self.startup_proofs.clear();
        let now = monotonic_ns();
        for (_, (_, callbacks)) in self.feedback.drain() {
            self.ready.push(Presented { callbacks, time_ns: now, hardware: false });
        }
        FEEDBACK_PENDING.store(0, Ordering::Relaxed);
    }

    /// Show `ahb` full-surface, scaled to the surface size. `acquire` is the client's
    /// GPU completion fence (explicit sync), or None when the client already waited.
    /// `rotation` 90 turns the picture a quarter clockwise and fits it into the surface,
    /// centred with black bars (the assistant's screen fullscreen on the portrait phone,
    /// docs/65); SurfaceFlinger does the turn, so the frame stays zero-copy.
    pub fn present(
        &mut self,
        ahb: Arc<AhbBuffer>,
        wayland: WaylandBuffer,
        release: Option<Arc<crate::android::backend::wayland::explicit_sync::ReleaseOnDrop>>,
        acquire: Option<OwnedFd>,
        buffer_size: (i32, i32),
        surface_size: (i32, i32),
        rotation: i32,
    ) {
        let Some(set_buffer) = set_buffer_with_release() else { return };
        let id = self.next_id;
        self.next_id += 1;
        let context = Box::into_raw(Box::new(ReleaseContext { id, tx: self.tx.clone() })) as *mut c_void;
        unsafe {
            let txn = ASurfaceTransaction_create();
            let acquire_fd = acquire.map(|fd| std::os::fd::IntoRawFd::into_raw_fd(fd)).unwrap_or(-1);
            set_buffer(txn, self.control, ahb.ptr, acquire_fd, context, on_buffer_release);
            if acquire_fd >= 0 {
                ACQUIRE_FENCES.fetch_add(1, Ordering::Relaxed);
            }
            ASurfaceTransaction_setBufferTransparency(txn, self.control, TRANSPARENCY_OPAQUE);
            ASurfaceTransaction_setBufferDataSpace(txn, self.control, ADATASPACE_SRGB);
            // Explicit full damage: some Android builds treat unset damage as none (crbug.com/993977).
            let full = ARect { left: 0, top: 0, right: buffer_size.0, bottom: buffer_size.1 };
            ASurfaceTransaction_setDamageRegion(txn, self.control, &full, 1);
            if hardware_feedback() || crate::android::frame_clock::phone_proof() != 0 {
                // Completion callbacks cost a binder round trip per frame; only for real present times.
                let complete = Box::into_raw(Box::new(CompleteContext { id, tx: self.complete_tx.clone() })) as *mut c_void;
                ASurfaceTransaction_setOnComplete(txn, complete, on_complete);
            }
            if rotation == 90 && buffer_size.0 > 0 && buffer_size.1 > 0 {
                let (content_w, content_h) = (buffer_size.1 as f32, buffer_size.0 as f32);
                let scale = (surface_size.0 as f32 / content_w).min(surface_size.1 as f32 / content_h);
                let (w, h) = ((content_w * scale).round() as i32, (content_h * scale).round() as i32);
                let (x, y) = ((surface_size.0 - w) / 2, (surface_size.1 - h) / 2);
                let destination = ARect { left: x, top: y, right: x + w, bottom: y + h };
                const ANATIVEWINDOW_TRANSFORM_ROTATE_90: i32 = 4;
                ASurfaceTransaction_setGeometry(txn, self.control, &full, &destination, ANATIVEWINDOW_TRANSFORM_ROTATE_90);
            } else if buffer_size != surface_size && buffer_size.0 > 0 && buffer_size.1 > 0 {
                ASurfaceTransaction_setScale(txn, self.control,
                    surface_size.0 as f32 / buffer_size.0 as f32, surface_size.1 as f32 / buffer_size.1 as f32);
            } else {
                ASurfaceTransaction_setScale(txn, self.control, 1.0, 1.0);
            }
            if !self.visible {
                ASurfaceTransaction_setZOrder(txn, self.control, 1);
                ASurfaceTransaction_setVisibility(txn, self.control, 1);
            }
            ASurfaceTransaction_apply(txn);
            ASurfaceTransaction_delete(txn);
        }
        self.visible = true;
        self.in_flight.insert(id, Held { _wayland: wayland, _ahb: ahb, _release: release });
        self.unclaimed = Some(id);
        FRAMES.fetch_add(1, Ordering::Relaxed);
        IN_FLIGHT.store((self.in_flight.len() + self.releasing.len()) as u64, Ordering::Relaxed);
    }

    /// Hide the layer so the GLES compositor output underneath is visible.
    /// No release fence or presentation feedback is waiting to be resolved, so
    /// the loop may park until the next SurfaceFlinger callback kicks it.
    pub fn settled(&self) -> bool {
        self.releasing.is_empty() && self.feedback.is_empty() && self.ready.is_empty() && self.startup_proofs.is_empty()
    }

    pub fn hide(&mut self) {
        self.flush_feedback();
        if !self.visible {
            return;
        }
        unsafe {
            let txn = ASurfaceTransaction_create();
            ASurfaceTransaction_setVisibility(txn, self.control, 0);
            ASurfaceTransaction_apply(txn);
            ASurfaceTransaction_delete(txn);
        }
        self.visible = false;
    }
}

impl Drop for Presenter {
    fn drop(&mut self) {
        // Frames that will never be reported: tell the clients (presentation-time spec).
        for callbacks in self.feedback.drain().map(|(_, (_, c))| c).chain(self.ready.drain(..).map(|p| p.callbacks)) {
            for callback in callbacks {
                callback.discarded();
            }
        }
        // Releasing the control removes the layer; SurfaceFlinger then releases its
        // buffers. Held Wayland buffers are released with it: the window is gone.
        unsafe { ASurfaceControl_release(self.control) };
        // AVAILABLE is left alone: a replacement presenter may already exist.
        IN_FLIGHT.store(0, Ordering::Relaxed);
    }
}
