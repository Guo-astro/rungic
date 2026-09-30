//! Cast display (Miracast TV) as a second host output (docs/58).
//!
//! The TV is offered to KWin as an extra wl_output made by "Moto" (kept until phase D of the
//! Rungic rename, docs/70: container releases from before it match that name) with model
//! "Cast". KWin (moto11) creates an output for it whose xdg_toplevel asks to be
//! fullscreen on that wl_output; that toplevel becomes the cast window. It is
//! kept apart from the phone: placed far away in the space, never focused by
//! touch routing, configured to the TV size, and its buffers go to the cast
//! presenter instead of the phone surface.
//!
//! While the phone acts as the TV's touchpad (`cast_pointer`), the host's
//! wl_pointer lives on the cast window: relative motion from the phone moves it
//! within the TV, and KWin draws the cursor into the cast output itself.
//!
//! Agent workspaces (docs/research/91): a KWin per workspace connects to ws-<n>
//! (server.rs) and gets an output of its own, seen by no one else; its fullscreen
//! window is claimed like the cast window. The TV or fullscreen presenter shows one
//! source at a time: `presented` 0 is the user's cast output above, n a workspace.
//! A workspace not presented still gets its frame callbacks as it commits, so it
//! keeps working (screenshots, its floating window) while nobody presents it.
use smithay::backend::input::{Axis, AxisSource, ButtonState};
use smithay::desktop::Window;
use smithay::input::pointer::{AxisFrame, ButtonEvent, MotionEvent, RelativeMotionEvent};
use smithay::output::{Mode as OutputMode, Output, PhysicalProperties, Scale, Subpixel};
use smithay::reexports::wayland_protocols::xdg::shell::server::xdg_toplevel;
use smithay::reexports::wayland_server::backend::{ClientId, GlobalId};
use smithay::reexports::wayland_server::protocol::wl_output::WlOutput;
use smithay::reexports::wayland_server::protocol::wl_surface::WlSurface;
use smithay::reexports::wayland_server::Resource;
use smithay::utils::{Point, Transform, SERIAL_COUNTER};
use smithay::wayland::seat::WaylandFocus;
use smithay::wayland::shell::xdg::ToplevelSurface;

use crate::android::backend::wayland::engine_timing;
use crate::android::backend::wayland::seat::AndroidSeatRuntime;
use crate::android::backend::wayland::shell::WindowElement;

/// Space position of the cast window: outside anything the phone maps or hit-tests.
const CAST_ORIGIN: (i32, i32) = (100_000, 0);
/// A workspace's size (the assistant's screen, docs/65) and refresh.
pub(crate) const WORKSPACE_SIZE: (i32, i32) = (1920, 1080);
const WORKSPACE_REFRESH_MHZ: i32 = 60_000;

#[derive(Debug)]
pub(crate) struct CastOutput {
    pub output: Output,
    pub global: GlobalId,
    pub size: (i32, i32),
    pub surface: Option<WlSurface>,
    /// Pointer position within the TV, in its pixels.
    pub pointer: (f64, f64),
    /// The buffer last handed to the TV; the same buffer is not presented twice.
    pub last_buffer: Option<smithay::reexports::wayland_server::protocol::wl_buffer::WlBuffer>,
    /// New cast frames taken (diagnostics).
    pub new_frames: u64,
    /// A workspace's own KWin (None: the user's cast output).
    pub client: Option<ClientId>,
    /// A workspace's pacing: its commits, those seen, its last turn, a change held back.
    pub commits: u64,
    pub commits_seen: u64,
    pub last_frame: Option<std::time::Instant>,
    pub deferred: bool,
}

/// Whether `buffer` is a new cast frame (and record it). Rendering the phone must
/// not re-present an unchanged TV frame; a new presenter or window resets this.
pub(crate) fn take_new_buffer(
    cast: Option<&mut CastOutput>,
    buffer: &smithay::reexports::wayland_server::protocol::wl_buffer::WlBuffer,
) -> bool {
    let Some(cast) = cast else { return false };
    if cast.last_buffer.as_ref() == Some(buffer) {
        return false;
    }
    cast.last_buffer = Some(buffer.clone());
    cast.new_frames += 1;
    true
}

impl AndroidSeatRuntime {
    /// Offer (or resize) the cast output; `size` in pixels, refresh in mHz.
    pub(crate) fn add_cast_output(&mut self, size: (i32, i32), refresh_mhz: i32) {
        if self.cast.as_ref().is_some_and(|c| c.size == size) {
            return;
        }
        self.remove_cast_output();
        let output = Output::new(
            "cast-0".to_string(),
            PhysicalProperties {
                // The Wi-Fi Display reports no physical size; a 45" 16:9 panel keeps
                // DPI-based heuristics sane. KWin sets the scale explicitly.
                size: (1000, 563).into(),
                subpixel: Subpixel::Unknown,
                make: "Moto".into(),
                model: "Cast".into(),
                serial_number: String::new(),
            },
        );
        let mode = OutputMode { size: size.into(), refresh: refresh_mhz.max(1000) };
        output.change_current_state(Some(mode), Some(Transform::Normal), Some(Scale::Integer(1)), Some(CAST_ORIGIN.into()));
        output.set_preferred(mode);
        // The user's KWin only: a workspace's KWin has its own output.
        let global = output.create_global_for::<Self>(&self.display_handle, |client| {
            crate::android::backend::wayland::server::client_workspace(client) == 0
        });
        log::info!("cast: offered host output {}x{}@{}", size.0, size.1, mode.refresh);
        self.cast = Some(CastOutput::new(output, global, size, None));
    }

    /// An agent workspace's KWin connected on ws-<slot>: its own output, seen by it alone.
    pub(crate) fn workspace_client_connected(&mut self, slot: usize, client: ClientId) {
        let Some(entry) = self.workspaces.get_mut(slot - 1) else { return };
        if let Some(old) = entry.take() {
            self.display_handle.remove_global::<Self>(old.global);
        }
        let size = WORKSPACE_SIZE;
        let output = Output::new(
            format!("workspace-{slot}"),
            PhysicalProperties {
                size: (1000, 563).into(),
                subpixel: Subpixel::Unknown,
                make: "Rungic".into(),
                model: "Cast".into(),
                serial_number: format!("workspace-{slot}"),
            },
        );
        let mode = OutputMode { size: size.into(), refresh: WORKSPACE_REFRESH_MHZ };
        let origin = (CAST_ORIGIN.0 + slot as i32 * 10_000, CAST_ORIGIN.1);
        output.change_current_state(Some(mode), Some(Transform::Normal), Some(Scale::Integer(1)), Some(origin.into()));
        output.set_preferred(mode);
        let global = output.create_global_for::<Self>(&self.display_handle, move |client| {
            crate::android::backend::wayland::server::client_workspace(client) == slot
        });
        log::info!("workspace {slot}: offered its output {}x{}", size.0, size.1);
        self.workspaces[slot - 1] = Some(CastOutput::new(output, global, size, Some(client)));
        if self.wanted_source == slot {
            self.present(slot);
        }
    }

    /// The platform bridge's choice: show `slot` (0: the user's cast output) on the TV,
    /// fullscreen or floating window. A workspace takes the user's cast output's place.
    pub(crate) fn present_source(&mut self, slot: usize) {
        self.wanted_source = slot;
        let presented = self.present(slot);
        if presented != slot {
            log::info!("cast: workspace {slot} is not connected yet; presenting it when it is");
        }
        self.sync_user_cast();
    }

    /// The user's cast output (the desktop mode's screen, docs/research/91) exists while desktop
    /// mode is on (`agent_screen`, its size), or while a TV or fullscreen window shows the user's
    /// desktop (the window's size). A presenter showing a workspace gives the user's KWin no
    /// empty second screen for its windows to land on.
    pub(crate) fn sync_user_cast(&mut self) {
        let wanted = self.agent_screen.or(if self.wanted_source == 0 { self.cast_window } else { None });
        match wanted {
            Some((size, refresh)) => self.add_cast_output(size, refresh),
            None => self.remove_cast_output(),
        }
    }

    /// Workspaces whose KWin is gone lose their output (`alive`: whether a client still is).
    pub(crate) fn drop_gone_workspaces(&mut self, alive: impl Fn(&ClientId) -> bool) {
        for slot in 1..=self.workspaces.len() {
            let gone = self.workspaces[slot - 1].as_ref().is_some_and(|w| w.client.as_ref().is_some_and(|c| !alive(c)));
            if gone {
                let workspace = self.workspaces[slot - 1].take().expect("checked");
                self.display_handle.remove_global::<Self>(workspace.global);
                if self.presented == slot {
                    self.present(0);
                }
                log::info!("workspace {slot}: its KWin left; output withdrawn");
            }
        }
    }

    /// The source (0: the user's cast output, n: workspace n).
    pub(crate) fn source(&self, slot: usize) -> Option<&CastOutput> {
        if slot == 0 { self.cast.as_ref() } else { self.workspaces.get(slot - 1)?.as_ref() }
    }

    pub(crate) fn source_mut(&mut self, slot: usize) -> Option<&mut CastOutput> {
        if slot == 0 { self.cast.as_mut() } else { self.workspaces.get_mut(slot - 1)?.as_mut() }
    }

    /// Show `slot` on the TV or fullscreen presenter (0: the user's cast output). A slot
    /// without a source falls back to 0. Returns the slot presented.
    pub(crate) fn present(&mut self, slot: usize) -> usize {
        let slot = if slot == 0 || self.source(slot).is_some() { slot } else { 0 };
        if slot != self.presented {
            self.presented = slot;
            self.pending_cast_frame = None;
            if let Some(source) = self.source_mut(slot) {
                source.last_buffer = None;       // its current frame goes out at once
                source.deferred = true;
            }
            self.pacing.cast_deferred = true;
            log::info!("cast: presenting source {slot}");
        }
        slot
    }

    /// The workspace whose window `surface` is (a root surface), if any.
    pub(crate) fn workspace_of_surface(&self, surface: &WlSurface) -> Option<usize> {
        self.workspaces.iter().position(|w| w.as_ref().and_then(|w| w.surface.as_ref()) == Some(surface)).map(|i| i + 1)
    }

    /// A commit of a workspace's window (handlers: commit) counts toward its own pacing.
    pub(crate) fn note_workspace_commit(&mut self, surface: &WlSurface) {
        if let Some(slot) = self.workspace_of_surface(surface) {
            if let Some(workspace) = self.workspaces[slot - 1].as_mut() {
                workspace.commits += 1;
            }
        }
    }

    /// Withdraw the cast output; KWin then removes its output and window.
    pub(crate) fn remove_cast_output(&mut self) {
        if let Some(cast) = self.cast.take() {
            self.display_handle.remove_global::<Self>(cast.global);
            self.pending_cast_frame = None;
            log::info!("cast: withdrew host output");
        }
    }

    /// Whether `surface` is not the phone's: the cast window or a workspace's window.
    pub(crate) fn is_cast_surface(&self, surface: &WlSurface) -> bool {
        self.cast.as_ref().and_then(|c| c.surface.as_ref()) == Some(surface) || self.workspace_of_surface(surface).is_some()
    }

    /// The window the TV or fullscreen presenter shows now.
    pub(crate) fn presented_surface(&self) -> Option<&WlSurface> {
        self.source(self.presented).and_then(|s| s.surface.as_ref())
    }

    /// xdg_toplevel.set_fullscreen on the cast output: adopt it as the cast window.
    /// Returns false when `output` is not the cast output.
    pub(crate) fn claim_cast_window(&mut self, toplevel: &ToplevelSurface, output: Option<&WlOutput>) -> bool {
        let Some(output) = output else { return false };
        let Some(slot) = (0..=self.workspaces.len()).find(|&slot| self.source(slot).is_some_and(|s| s.output.owns(output))) else {
            return false;
        };
        let cast = self.source_mut(slot).expect("found");
        let wl_surface = toplevel.wl_surface().clone();
        cast.surface = Some(wl_surface.clone());
        cast.last_buffer = None;
        let size = cast.size;
        let origin = cast.output.current_location();
        toplevel.with_pending_state(|state| {
            state.states.set(xdg_toplevel::State::Fullscreen);
            state.states.set(xdg_toplevel::State::Activated);
            state.size = Some(size.into());
            state.bounds = Some(size.into());
        });
        toplevel.send_configure();
        if let Some(window) = self.wl_to_window.get(&wl_surface).cloned() {
            self.space.map_element(WindowElement(window), origin, false);
        }
        // new_toplevel focused it; input focus belongs to the phone's window.
        if self.focused_surface.as_ref() == Some(&wl_surface) {
            let phone = self.phone_window_surface();
            self.focused_surface = phone.clone();
            if let (Some(keyboard), Some(phone)) = (self.keyboard.clone(), phone) {
                keyboard.set_focus(self, Some(phone), SERIAL_COUNTER.next_serial());
            }
        }
        log::info!("cast: window {:?} is fullscreen on source {slot}", wl_surface.id());
        true
    }

    /// The most recent live window that is not the cast window.
    pub(crate) fn phone_window_surface(&self) -> Option<WlSurface> {
        self.space
            .elements()
            .rev()
            .filter_map(|e| e.0.wl_surface().map(|s| s.as_ref().clone()))
            .find(|s| s.is_alive() && !self.is_cast_surface(s))
    }

    pub(crate) fn is_cast_window(&self, window: &Window) -> bool {
        window.wl_surface().is_some_and(|s| self.is_cast_surface(s.as_ref()))
    }

    /// Phone as the TV's touchpad on/off. The seat keeps a wl_pointer while on.
    pub(crate) fn set_cast_pointer(&mut self, enabled: bool) {
        if self.cast_pointer == enabled {
            return;
        }
        self.cast_pointer = enabled;
        // No motion here: KWin binds its wl_pointer only after seeing the new
        // capability, and smithay sends wl_pointer.enter once per focus change, so an
        // enter sent now would never reach it. The first finger motion enters.
        self.sync_pointer_capability();
        log::info!("cast: touchpad {}", if enabled { "on" } else { "off" });
    }

    /// Cast window and its space origin, when the pointer should go there.
    fn cast_pointer_target(&self) -> Option<(WlSurface, Point<f64, smithay::utils::Logical>)> {
        if !self.cast_pointer {
            return None;
        }
        let surface = self.source(self.presented)?.surface.clone().filter(|s| s.is_alive())?;
        let origin = self
            .wl_to_window
            .get(&surface)
            .and_then(|w| self.space.element_location(&WindowElement(w.clone())))
            .unwrap_or(Point::from(CAST_ORIGIN));
        Some((surface, (origin.x as f64, origin.y as f64).into()))
    }

    /// Relative motion in TV pixels (the cast output has scale 1).
    pub(crate) fn cast_pointer_motion(&mut self, dx: f64, dy: f64) {
        let presented = self.presented;
        let Some(cast) = self.source_mut(presented) else { return };
        let (w, h) = (cast.size.0 as f64, cast.size.1 as f64);
        cast.pointer = ((cast.pointer.0 + dx).clamp(0.0, w - 1.0), (cast.pointer.1 + dy).clamp(0.0, h - 1.0));
        let pos = cast.pointer;
        let Some((surface, origin)) = self.cast_pointer_target() else { return };
        let time = engine_timing::now_ms_u32();
        let pointer = self.pointer.clone();
        pointer.motion(
            self,
            Some((surface.clone(), origin)),
            &MotionEvent { location: (origin.x + pos.0, origin.y + pos.1).into(), serial: SERIAL_COUNTER.next_serial(), time },
        );
        if dx != 0.0 || dy != 0.0 {
            // KWin binds relative pointers only while a client holds a pointer lock.
            pointer.relative_motion(
                self,
                Some((surface, origin)),
                &RelativeMotionEvent { delta: (dx, dy).into(), delta_unaccel: (dx, dy).into(), utime: time as u64 * 1000 },
            );
        }
        pointer.frame(self);
        self.last_seat_dispatch = format!("cast_motion x={:.0} y={:.0}", pos.0, pos.1);
    }

    /// The pointer to a place of the output, in its pixels (fullscreen touch, docs/65).
    pub(crate) fn cast_pointer_to(&mut self, x: f64, y: f64) {
        let presented = self.presented;
        let Some(cast) = self.source_mut(presented) else { return };
        let (w, h) = (cast.size.0 as f64, cast.size.1 as f64);
        cast.pointer = (x.clamp(0.0, w - 1.0), y.clamp(0.0, h - 1.0));
        self.cast_pointer_motion(0.0, 0.0);
    }

    /// Linux button code (BTN_LEFT 0x110, BTN_RIGHT 0x111, BTN_MIDDLE 0x112).
    pub(crate) fn cast_pointer_button(&mut self, button: u32, pressed: bool) {
        if self.cast_pointer_target().is_none() {
            return;
        }
        let pointer = self.pointer.clone();
        let state = if pressed { ButtonState::Pressed } else { ButtonState::Released };
        pointer.button(
            self,
            &ButtonEvent { serial: SERIAL_COUNTER.next_serial(), time: engine_timing::now_ms_u32(), button, state },
        );
        pointer.frame(self);
        self.last_seat_dispatch = format!("cast_button 0x{:x} {}", button, pressed);
    }

    /// Two-finger scroll in TV pixels; `stop` ends the finger scroll (kinetic scrolling).
    pub(crate) fn cast_pointer_scroll(&mut self, dx: f64, dy: f64, stop: bool) {
        if self.cast_pointer_target().is_none() {
            return;
        }
        let pointer = self.pointer.clone();
        let mut frame = AxisFrame::new(engine_timing::now_ms_u32()).source(AxisSource::Finger);
        if stop {
            frame = frame.stop(Axis::Horizontal).stop(Axis::Vertical);
        } else {
            if dx != 0.0 {
                frame = frame.value(Axis::Horizontal, dx);
            }
            if dy != 0.0 {
                frame = frame.value(Axis::Vertical, dy);
            }
        }
        pointer.axis(self, frame);
        pointer.frame(self);
    }
}

impl CastOutput {
    fn new(output: Output, global: GlobalId, size: (i32, i32), client: Option<ClientId>) -> Self {
        let pointer = (size.0 as f64 / 2.0, size.1 as f64 / 2.0);
        Self {
            output, global, size, surface: None, pointer, last_buffer: None, new_frames: 0, client,
            commits: 0, commits_seen: 0, last_frame: None, deferred: false,
        }
    }
}
