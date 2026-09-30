//! zwp_linux_explicit_synchronization_v1: sync_file acquire fences.
//!
//! KGSL is not a DRM device, so linux-drm-syncobj-v1 is unavailable; clients
//! (KWin's Wayland backend) send the GPU completion fence of each commit with
//! `set_acquire_fence` instead of waiting with glFinish. The fence is
//! double-buffered surface state. The zero-copy path hands it to SurfaceFlinger
//! as the buffer's acquire fence; the GLES path waits for it before sampling.
//!
//! Releases keep wl_buffer.release timing (after SurfaceFlinger's release fence,
//! see surface_control.rs). A `get_release` object is answered with
//! `immediate_release` when the last reference to its commit is dropped, which is
//! the moment the buffer is no longer read on the Android side.
use std::os::fd::OwnedFd;
use std::sync::{Arc, Mutex};

use smithay::reexports::wayland_server::protocol::wl_surface::WlSurface;
use smithay::reexports::wayland_server::{Client, DataInit, DisplayHandle, New, Resource, Weak};
use smithay::wayland::compositor::{with_states, Cacheable};
use wayland_protocols::wp::linux_explicit_synchronization::zv1::server::{
    zwp_linux_buffer_release_v1::{self, ZwpLinuxBufferReleaseV1},
    zwp_linux_explicit_synchronization_v1::{self, ZwpLinuxExplicitSynchronizationV1},
    zwp_linux_surface_synchronization_v1::{self, ZwpLinuxSurfaceSynchronizationV1},
};

use crate::android::backend::wayland::seat::AndroidSeatRuntime;

/// Sends `immediate_release` once nothing on the Android side uses the commit.
#[derive(Debug)]
pub(crate) struct ReleaseOnDrop(ZwpLinuxBufferReleaseV1);

impl Drop for ReleaseOnDrop {
    fn drop(&mut self) {
        if self.0.is_alive() {
            self.0.immediate_release();
        }
    }
}

/// Per-commit synchronization state of a surface.
#[derive(Debug, Default)]
pub(crate) struct SyncState {
    pub acquire: Option<Arc<OwnedFd>>,
    pub release: Option<Arc<ReleaseOnDrop>>,
}

impl Cacheable for SyncState {
    fn commit(&mut self, _dh: &DisplayHandle) -> Self {
        // Fences and release objects apply to exactly one commit.
        std::mem::take(self)
    }
    fn merge_into(self, into: &mut Self, _dh: &DisplayHandle) {
        *into = self;
    }
}

/// The acquire fence and release object of the surface's current commit.
pub(crate) fn current(surface: &WlSurface) -> (Option<Arc<OwnedFd>>, Option<Arc<ReleaseOnDrop>>) {
    with_states(surface, |states| {
        let mut cached = states.cached_state.get::<SyncState>();
        let current = cached.current();
        (current.acquire.clone(), current.release.clone())
    })
}

/// Marks a surface that already has a synchronization object.
#[derive(Default)]
struct HasSynchronization(Mutex<bool>);

fn set_has_sync(surface: &WlSurface, value: bool) -> bool {
    with_states(surface, |states| {
        states.data_map.insert_if_missing_threadsafe(HasSynchronization::default);
        let mut flag = states.data_map.get::<HasSynchronization>().unwrap().0.lock().unwrap();
        std::mem::replace(&mut *flag, value)
    })
}

pub(crate) struct ExplicitSyncGlobal;

pub(crate) fn create_global(display: &DisplayHandle) {
    display.create_global::<AndroidSeatRuntime, ZwpLinuxExplicitSynchronizationV1, _>(2, ExplicitSyncGlobal);
}

impl smithay::wayland::GlobalDispatch2<ZwpLinuxExplicitSynchronizationV1, AndroidSeatRuntime> for ExplicitSyncGlobal {
    fn bind(
        &self,
        _state: &mut AndroidSeatRuntime,
        _handle: &DisplayHandle,
        _client: &Client,
        resource: New<ZwpLinuxExplicitSynchronizationV1>,
        data_init: &mut DataInit<'_, AndroidSeatRuntime>,
    ) {
        data_init.init(resource, ManagerData);
    }
}

pub(crate) struct ManagerData;

impl smithay::wayland::Dispatch2<ZwpLinuxExplicitSynchronizationV1, AndroidSeatRuntime> for ManagerData {
    fn request(
        &self,
        _state: &mut AndroidSeatRuntime,
        _client: &Client,
        resource: &ZwpLinuxExplicitSynchronizationV1,
        request: zwp_linux_explicit_synchronization_v1::Request,
        _handle: &DisplayHandle,
        data_init: &mut DataInit<'_, AndroidSeatRuntime>,
    ) {
        match request {
            zwp_linux_explicit_synchronization_v1::Request::GetSynchronization { id, surface } => {
                if set_has_sync(&surface, true) {
                    resource.post_error(
                        zwp_linux_explicit_synchronization_v1::Error::SynchronizationExists,
                        "surface already has a synchronization object",
                    );
                    return;
                }
                data_init.init(id, SurfaceSyncData { surface: surface.downgrade() });
                log::info!("explicit-sync: surface synchronization created");
            }
            zwp_linux_explicit_synchronization_v1::Request::Destroy => {}
            _ => {}
        }
    }
}

pub(crate) struct SurfaceSyncData {
    surface: Weak<WlSurface>,
}

impl smithay::wayland::Dispatch2<ZwpLinuxSurfaceSynchronizationV1, AndroidSeatRuntime> for SurfaceSyncData {
    fn request(
        &self,
        _state: &mut AndroidSeatRuntime,
        _client: &Client,
        resource: &ZwpLinuxSurfaceSynchronizationV1,
        request: zwp_linux_surface_synchronization_v1::Request,
        _handle: &DisplayHandle,
        data_init: &mut DataInit<'_, AndroidSeatRuntime>,
    ) {
        use zwp_linux_surface_synchronization_v1::{Error, Request};
        let Ok(surface) = self.surface.upgrade() else {
            if let Request::GetRelease { release } = request {
                // Keep the protocol object valid; the error below terminates the client.
                data_init.init(release, ReleaseData);
            }
            resource.post_error(Error::NoSurface, "the surface was destroyed");
            return;
        };
        match request {
            Request::SetAcquireFence { fd } => {
                let duplicate = with_states(&surface, |states| {
                    let mut cached = states.cached_state.get::<SyncState>();
                    let pending = cached.pending();
                    let duplicate = pending.acquire.is_some();
                    if !duplicate {
                        pending.acquire = Some(Arc::new(fd));
                    }
                    duplicate
                });
                if duplicate {
                    resource.post_error(Error::DuplicateFence, "acquire fence already set for this commit");
                }
            }
            Request::GetRelease { release } => {
                let release = data_init.init(release, ReleaseData);
                let duplicate = with_states(&surface, |states| {
                    let mut cached = states.cached_state.get::<SyncState>();
                    let pending = cached.pending();
                    let duplicate = pending.release.is_some();
                    if !duplicate {
                        pending.release = Some(Arc::new(ReleaseOnDrop(release)));
                    }
                    duplicate
                });
                if duplicate {
                    resource.post_error(Error::DuplicateRelease, "release already requested for this commit");
                }
            }
            Request::Destroy => {
                set_has_sync(&surface, false);
            }
            _ => {}
        }
    }
}

pub(crate) struct ReleaseData;

impl smithay::wayland::Dispatch2<ZwpLinuxBufferReleaseV1, AndroidSeatRuntime> for ReleaseData {
    fn request(
        &self,
        _state: &mut AndroidSeatRuntime,
        _client: &Client,
        _resource: &ZwpLinuxBufferReleaseV1,
        _request: zwp_linux_buffer_release_v1::Request,
        _handle: &DisplayHandle,
        _data_init: &mut DataInit<'_, AndroidSeatRuntime>,
    ) {
        // zwp_linux_buffer_release_v1 has no requests.
    }
}

/// Wait on the CPU for an acquire fence (GLES fallback path), bounded so a hung
/// client GPU job cannot stall the compositor indefinitely.
pub(crate) fn wait(fence: &OwnedFd, timeout_ms: i32) -> bool {
    use std::os::fd::AsRawFd;
    let mut poll = libc::pollfd { fd: fence.as_raw_fd(), events: libc::POLLIN, revents: 0 };
    unsafe { libc::poll(&mut poll, 1, timeout_ms) > 0 }
}
