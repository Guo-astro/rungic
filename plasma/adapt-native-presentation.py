#!/usr/bin/env python3
"""Apply the Moto presentation patch to a prepared Winland source tree."""
from pathlib import Path
import sys
r = Path(sys.argv[1])
p = r/'src/android/frame_clock.rs'
s = p.read_text().replace('pub fn note_present()', 'pub fn presented_count() -> u64 { PRESENTS.load(Ordering::Relaxed) }\npub fn note_present()')
p.write_text(s)
p = r/'src/android/backend/wayland/seat.rs'
s = p.read_text()
anchor = '    fn send_frame_callback(wl_surface: &WlSurface) {'
assert s.count(anchor) == 1
s = s.replace(anchor, '''    /// Complete the feedback for the surfaces just submitted to Android.
    /// This is a software estimate after eglSwapBuffers, not a hardware
    /// scanout timestamp: advertise no HW_CLOCK/HW_COMPLETION/VSYNC flags.
    /// The runtime and GL submission execute on the same compositor thread;
    /// no client commits are dispatched between render_all and this call.
    pub(crate) fn finish_presentation(&self) {
        use smithay::wayland::compositor::with_states;
        use smithay::wayland::presentation::{PresentationFeedbackCachedState, Refresh};
        use wayland_protocols::wp::presentation_time::server::wp_presentation_feedback;
        let mut now = libc::timespec { tv_sec: 0, tv_nsec: 0 };
        if unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut now) } != 0 { return; }
        let time = std::time::Duration::new(now.tv_sec as u64, now.tv_nsec as u32);
        let refresh = Refresh::fixed(std::time::Duration::from_secs_f64(
            1000.0 / crate::android::frame_clock::refresh_mhz() as f64));
        let finish = |surface: &WlSurface| {
            let callbacks = with_states(surface, |states| {
                std::mem::take(&mut states.cached_state
                    .get::<PresentationFeedbackCachedState>().current().callbacks)
            });
            for feedback in callbacks {
                feedback.presented(&self.output, time, refresh, 0,
                    wp_presentation_feedback::Kind::empty());
            }
        };
        for elem in self.space.elements() {
            if let Some(surface) = elem.0.wl_surface() {
                finish(surface.as_ref());
                for (popup, _) in PopupManager::popups_for_surface(surface.as_ref()) {
                    finish(popup.wl_surface());
                }
            }
        }
        for surface in &self.unmanaged_surfaces { finish(surface); }
    }

''' + anchor)
p.write_text(s)
p = r/'src/compositor.rs'
s = p.read_text()
anchor = '            flush_deferred_composite(&mut backend_state, &render_rx);'
assert s.count(anchor) == 1
s = s.replace(anchor, '''            let presents_before = crate::android::frame_clock::presented_count();
''' + anchor + '''
            if crate::android::frame_clock::presented_count() != presents_before {
                if let Some(server) = wayland_server.as_mut() {
                    server.runtime.finish_presentation();
                }
            }''')
p.write_text(s)

# A repeated Android display notification need not announce a new Wayland mode.
p = r/'src/compositor.rs'
s = p.read_text()
old = """                                mode.refresh = crate::android::frame_clock::refresh_mhz();
                                server.runtime.output.change_current_state(Some(mode), None, None, None);
                                server.runtime.output.set_preferred(mode);"""
new = """                                let refresh = crate::android::frame_clock::refresh_mhz();
                                if mode.refresh != refresh {
                                    mode.refresh = refresh;
                                    server.runtime.output.change_current_state(Some(mode), None, None, None);
                                    server.runtime.output.set_preferred(mode);
                                }"""
assert s.count(old) == 1
p.write_text(s.replace(old, new))
