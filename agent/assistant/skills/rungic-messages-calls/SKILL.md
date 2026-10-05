---
name: rungic-messages-calls
description: >-
  Send and read SMS on the phone's SIM. Call phone numbers with a call agent.
  Send WeChat text and voice messages and make WeChat calls for the user.
  Use when the user says 发短信, 短信, 验证码, 打电话, 打微信电话, 发微信 or 发语音, or asks to text, call or message a person or a business.
  Also use to wait for an SMS reply or a verification code.
---

# Messages and calls for the user

Run all commands as the desktop user inside the Linux container.
Commands return JSON unless stated otherwise.

## When to use this skill

- SMS: "发短信给…", "text Anna that…", "有没有新短信", "验证码是多少". A login that sends a code by SMS.
- A phone call on the SIM: "打电话给…", "帮我问一下餐厅还有没有位", "call the shop".
- WeChat: "发微信给…", "发语音告诉…", "打微信电话".

Sending a message and making a call have an effect outside the phone.
Do them only on the user's explicit request or "yes".
Never send or call on your own initiative.
Reading SMS needs no go-ahead.

## SMS: `rungic-sms`

Use only the authorized recipient and text.
Ask when either is missing or ambiguous.
Do not ask again when the user already specified both.
Do not add recipients, promotions, or subscription commands.
An explicitly requested test can use a simple inquiry, never a purchase or subscription.

- `rungic-sms send NUMBER "TEXT"` uses the active default SMS SIM.
  `--subscription ID` selects an explicitly requested active SIM.
  Without a default, use the sole active SIM.
  Multiple active SIMs require a choice.
- `status: sent` means the radio sent every part, not that the recipient received them.
  Only `delivery: delivered` and `delivered: true` establish all delivery receipts.
  `unconfirmed` can mean the carrier supplies no receipts.
- `failed` can still include `sentParts > 0`.
  `pending`, socket timeouts, and lost responses leave the result uncertain.
  Inspect existing sent messages and report the uncertainty.
  Never resend automatically.
- `rungic-sms list --from NUMBER --box inbox --after TIMESTAMP_MS --wait 60` waits for replies at or after `submittedAt`.
  This includes replies received before the send call returned.
  `--since 120` covers the preceding 120 seconds.
  No reply produces exit 1 and `timedOut: true`, not successful receipt.
- Query only the relevant number/time range.
  Reading preserves unread flags and the Android messaging app.
  Do not mark/remove messages or change the default SMS app.
  `truncated: true` means the bounded scan did not cover everything.
  Narrow the time range before concluding there are no messages.
- Require Android SMS permissions and a live platform bridge, APK 2.31+.
  Report explicit errors.
  Do not silently select another SIM or app.

## Calls for the user

Use the requested transport.
“打电话” means SIM/telephone, and “打微信电话” means a WeChat voice call.
Retain another explicitly named app.
Check whether the requested transport works.
Do not substitute a transport because it is available or worked previously.
Resolve an ambiguous contact/number without asking for a transport choice again.

1. Run `rungic-voice-agent --call-capabilities` in the current desktop session.
   It checks backend/SIM/key prerequisites without dialing.
   An unreachable backend does not establish unsupported hardware.
   An available interface does not establish that the remote party hears the agent.
   Read capability/verification fields and report limits affecting the call.
   Do not hard-code handset, host, SIM, test number, or permanent feature absence.
2. Use `--start-call` with the authorized recipient, purpose, and transport.
   It prepares Realtime before dialing.
   Read [calls.md](calls.md) for parameters and controls.
   Do not click a dial button first or invent a telephone number.
3. Keep SIM and app calls in a card in the originating voice-assistant conversation.
   The card owns status, transcript, questions, private text, takeover/hang-up controls, and the final result.
   Leaving the assistant can retain a compact call bar.
   Returning restores the card.
   Do not replace it with a fullscreen workflow.
4. `dialed: true` acknowledges the request only.
   Live call state and remote responses establish connection and conversation success.
   Briefly report the recipient and transport after the call request.
   Then let the call agent speak.
   After timeout or lost connection, inspect the existing call.
   Never automatically redial or select another transport.

## WeChat

Use the app's English control names instead of guessing.
A narrow window hides the chat list and search field.
The TV uses desktop-sized WeChat.
If `list 'Chats'` is absent, use `desktop_window ... maximize` first.

To open a chat:

1. Type into `Search` above the chat list.
2. Select the person under `Contacts` in the results popup.
   Alternatively, select the matching `list 'Chats'` item, whose name has the chat name as its prefix, such as `File Transfer`.
3. Check the visible chat header.

The navigation-bar `Search` button is web search, “搜一搜”, rather than contact search.
Speech recognition can substitute same-sounding characters, such as 周凯文 for 周楷雯.
Search spoken names by pinyin, for example `zhoukaiwen`, instead of recognized characters.
Select the contact whose name sounds the same.

In API mode, `desktop_goal` does this when the goal identifies a spoken name.
Its `answer` identifies the actual opened contact.
If two people match or none matches, ask the user with the found names.

The message field is editable text named after the open chat, for example `周楷雯`.
ENTER sends the message.
Check the header before typing.
Type only when authorized to send that text to that chat.

Chat controls are `Voice Call`, `Send Voice`, `Send File`, `Send`, and `Chat Info`.
`Voice Call` is in the header.
`Voice Input (Hold Ctrl+Super)` is dictation, not a voice message.
Test only with `File Transfer`, “文件传输助手”, which sends to the user's devices.
Do not test with a real contact.

## Voice messages for the user

Use this flow for requests such as “发语音” or “用语音告诉…”.

1. Resolve the spoken contact name with screenshots/actions and pinyin search.
   Check the visible chat header before sending.
   Report the contact's actual name.
2. Use only the authorized content and requested language.
   By default, use the language of the request.
   Use a short opening statement that the assistant sends the message for the user.
   Examples: `This is Kevin's AI assistant with a voice message from him: …` or `我是凯文的 AI 助理，替他发一条语音：……`.
   Do not add other content.
3. In Codex mode, follow the recording procedure below.
   In API mode, use listed `desktop_voice_message` with authorized text and the verified open chat.
   That tool uses the existing Luna/OCR workflow.
4. Report the recipient and successful sending.
   The tool returns the length.

### Codex recording procedure

1. Call `desktop_voice_recording` with `phase: "prepare"` and authorized `text` before selecting the app's recording control.
2. Inspect and select that control, such as WeChat's round Send Voice icon rather than dictation.
3. Call `phase: "status"`.
   Require audio-backend confirmation of `recording: true`.
4. Call `phase: "play"` exactly once.
   Require `played: true`.
5. Inspect the screen before selecting the recording's Send control.
   Check that the message appears.
6. Call `phase: "close"` to release routing.

On failure or uncertain playback, cancel the recording without sending and close routing.
Never retry uncertain playback.
The helper performs speech synthesis, not UI decisions.
This mode does not support hold-to-record gestures.
Stop and explain if the app requires one.

