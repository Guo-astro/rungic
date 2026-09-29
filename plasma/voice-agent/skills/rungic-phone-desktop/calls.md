# Shared call interface

These commands run inside the current Linux desktop, as its user. Use the transport the user requested. Examples describe parameter shapes; replace recipient/goal with the user's actual request. They do not authorize calls to any example recipient.

## Phone / SIM

`rungic-voice-agent --start-call '{"backend":"cellular","number":"<verified telephone number>","contact":"<display name>","goal":"<authorized purpose>"}'`

Telecom supplies the voice SIM accounts. Omit `account` to use the configured outgoing voice default or sole account; if the backend reports `select-voice-sim`, use the accounts returned by `--call-capabilities` and ask which one. Do not infer voice SIM from mobile data, a slot number, handset model or a previous session.

## Application voice call

`rungic-voice-agent --start-call '{"backend":"app","app":"<actual process binary>","contact":"<verified contact>","goal":"<authorized purpose>","dial":"<voice call control>"}'`

Open the correct contact's chat on the assistant's screen first and verify its header. `app=wechat` and `dial=Voice Call` are the existing WeChat path, not defaults for all calls. Another app needs its actual binary, visible voice-call control and working shared audio routing; merely finding the app or router does not verify compatibility. For an already-running application call omit `dial`; `incoming=true` identifies a call the other party placed. The current cellular entry places outgoing calls; do not infer incoming-answer support from the application API.

## During either call

- Both transports produce the same card. The requested channel and recipient are visible; elapsed call time starts on connection. Transcript, errors, questions and result stay with that card and conversation when the user switches chats.
- `rungic-voice-agent --call-text '<instruction>'` sends private text to the active call agent. The card also offers this directly. Whether private voice instructions or independent monitoring is available comes from the active backend; do not promise those based on another transport.
- `rungic-voice-agent --call-command take-over` releases agent audio for the user; `--call-command hang-up` requests hanging up. The interface must wait for the backend's confirmation before saying the call ended.
- For cellular menus, `rungic-voice-agent --call-dtmf '<one digit or * or #>'` sends a keypad digit. Follow the user's goal and what the remote prompt actually says; do not invent a fixed menu sequence.
- The shared Realtime conversation and call controller have separate capabilities. A configured OpenAI key does not by itself prove remote audio, private microphone isolation or autonomous call-supervision functions work. Use current capability/verification information and actual results.
