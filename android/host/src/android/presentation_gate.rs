//! Startup evidence belongs to one phone surface attempt, never a global frame count.
use std::sync::Mutex;

#[derive(Default)]
struct State { next: u64, requested: u64, armed: u64, confirmed: u64 }
pub struct PresentationGate(Mutex<State>);
impl PresentationGate {
    pub const fn new() -> Self {
        Self(Mutex::new(State { next: 0, requested: 0, armed: 0, confirmed: 0 }))
    }
    pub fn request(&self) -> u64 {
        let mut s = self.0.lock().unwrap_or_else(|e| e.into_inner());
        s.next += 1;
        s.requested = s.next; s.armed = 0; s.confirmed = 0;
        s.requested
    }
    pub fn arm(&self, ticket: u64) {
        let mut s = self.0.lock().unwrap_or_else(|e| e.into_inner());
        if ticket == s.requested { s.armed = ticket; }
    }
    pub fn pending(&self) -> u64 {
        let s = self.0.lock().unwrap_or_else(|e| e.into_inner());
        if s.armed == s.requested && s.confirmed != s.armed { s.armed } else { 0 }
    }
    pub fn confirm(&self, ticket: u64) {
        let mut s = self.0.lock().unwrap_or_else(|e| e.into_inner());
        if ticket != 0 && ticket == s.requested && ticket == s.armed { s.confirmed = ticket; }
    }
    pub fn ready(&self, ticket: u64) -> bool {
        let s = self.0.lock().unwrap_or_else(|e| e.into_inner());
        ticket != 0 && s.requested == ticket && s.confirmed == ticket
    }
    pub fn cancel(&self, ticket: u64) {
        let mut s = self.0.lock().unwrap_or_else(|e| e.into_inner());
        if s.requested == ticket { s.requested = 0; s.armed = 0; s.confirmed = 0; }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn old_frame_cannot_open_new_attempt() {
        let gate = PresentationGate::new();
        let old = gate.request(); gate.arm(old);
        let new = gate.request(); gate.arm(new);
        gate.confirm(old); assert!(!gate.ready(new));
        gate.confirm(new); assert!(gate.ready(new)); assert_eq!(gate.pending(), 0);
        gate.confirm(old); assert!(gate.ready(new));
    }
    #[test]
    fn cancelled_command_cannot_arm_later() {
        let gate = PresentationGate::new();
        let ticket = gate.request(); gate.cancel(ticket); gate.arm(ticket); gate.confirm(ticket);
        assert!(!gate.ready(ticket)); assert_eq!(gate.pending(), 0);
    }
    #[test]
    fn submission_before_barrier_is_not_evidence() {
        let gate = PresentationGate::new();
        let ticket = gate.request(); gate.confirm(ticket);
        assert!(!gate.ready(ticket)); assert_eq!(gate.pending(), 0);
        gate.arm(ticket); assert_eq!(gate.pending(), ticket); assert!(!gate.ready(ticket));
        gate.confirm(ticket); assert!(gate.ready(ticket));
        let new = gate.request(); gate.cancel(ticket); gate.arm(new); gate.confirm(new);
        assert!(gate.ready(new));
    }
}
