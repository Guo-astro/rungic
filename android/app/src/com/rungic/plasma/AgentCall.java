package com.rungic.plasma;

import android.content.ComponentName;
import android.content.Context;
import android.media.AudioDeviceInfo;
import android.media.AudioManager;
import android.net.Uri;
import android.os.Bundle;
import android.telecom.CallAudioState;
import android.telecom.Connection;
import android.telecom.ConnectionRequest;
import android.telecom.ConnectionService;
import android.telecom.DisconnectCause;
import android.telecom.PhoneAccount;
import android.telecom.PhoneAccountHandle;
import android.telecom.TelecomManager;
import android.util.Log;

/**
 * A call with the Agent as Android knows a call: a self-managed Telecom call (2026-10-05, the user:
 * "run as a phone call, as Android's best practice"), as chat apps' calls are. Android then keeps it
 * going with the screen locked, puts it on hold for a phone call and back, and can hang it up from
 * the call notification or a headset. CaptureBridge opens and closes it with the call's audio; a
 * hang-up from Android is reported in the call's position (hungUp), and the Linux session ends the
 * call as when hung up in the Agent app. Should Telecom refuse the call, it goes on without it.
 *
 * Telecom owns the call's audio mode and route. The call's playback starts only once Telecom has
 * the call and has set the mode (start): a track started before was routed again while Telecom
 * took over, and paused long enough for the Linux side to end the call (the G100 S, 2026-10-05).
 */
final class AgentCall {
    private static final String TAG="RungicAgentCall";
    /** Android hung the call up (notification, headset, Telecom): the Linux session is to end it. */
    static volatile boolean hungUp;
    /** Android holds the call for another one: the Agent neither hears nor is heard meanwhile. */
    static volatile boolean held;
    private static volatile AgentConnection connection;
    private static volatile boolean wanted;

    private AgentCall() {}

    private static PhoneAccountHandle account(Context context) {
        return new PhoneAccountHandle(new ComponentName(context,Service.class),"agent");
    }

    /**
     * The call's audio is about to open (not on the UI thread): the call is placed, and this waits
     * up to `wait` ms for Telecom to have it and to set the audio mode. -> whether Telecom has the
     * call (it then owns the mode and route); false: the call goes on without Telecom.
     */
    static boolean start(Context context,long wait) {
        hungUp=false;held=false;wanted=true;
        if(!place(context)) { wanted=false;return false; }
        AudioManager audio=context.getSystemService(AudioManager.class);
        long deadline=android.os.SystemClock.uptimeMillis()+wait;
        while(android.os.SystemClock.uptimeMillis()<deadline
                && (connection==null || audio.getMode()!=AudioManager.MODE_IN_COMMUNICATION)) {
            try { Thread.sleep(20); } catch(InterruptedException e) { Thread.currentThread().interrupt();break; }
        }
        AgentConnection c=connection;
        if(c==null) { wanted=false;Log.w(TAG,"Telecom did not take the call in time; it goes on without it");return false; }
        // A conversation with the phone in hand, not at the ear: the speaker, unless a headset or
        // Bluetooth is there. Asked once Telecom owns the mode: asked before, Telecom showed the
        // speaker while Android's communication device fell back to the earpiece.
        AudioDeviceInfo device=audio.getCommunicationDevice();
        Log.i(TAG,"call active; mode="+audio.getMode()+" device="+(device==null?"none":device.getType()));
        if(!headset(audio) && (device==null || device.getType()!=AudioDeviceInfo.TYPE_BUILTIN_SPEAKER)) {
            c.speaker();
            // Playback starts on the speaker, not on the earpiece and then moved.
            long until=android.os.SystemClock.uptimeMillis()+1000;
            while(android.os.SystemClock.uptimeMillis()<until && ((device=audio.getCommunicationDevice())==null
                    || device.getType()!=AudioDeviceInfo.TYPE_BUILTIN_SPEAKER)) {
                try { Thread.sleep(20); } catch(InterruptedException e) { Thread.currentThread().interrupt();break; }
            }
            Log.i(TAG,"routed; device="+(device==null?"none":device.getType()));
        }
        return true;
    }
    private static boolean headset(AudioManager audio) {
        for(AudioDeviceInfo d:audio.getAvailableCommunicationDevices()) switch(d.getType()) {
            case AudioDeviceInfo.TYPE_WIRED_HEADSET: case AudioDeviceInfo.TYPE_USB_HEADSET:
            case AudioDeviceInfo.TYPE_BLUETOOTH_SCO: case AudioDeviceInfo.TYPE_BLE_HEADSET: return true;
            default: break;
        }
        return false;
    }
    private static boolean place(Context context) {
        try {
            TelecomManager telecom=context.getSystemService(TelecomManager.class);
            PhoneAccountHandle handle=account(context);
            telecom.registerPhoneAccount(PhoneAccount.builder(handle,"Rungic Agent")
                .setCapabilities(PhoneAccount.CAPABILITY_SELF_MANAGED).addSupportedUriScheme(PhoneAccount.SCHEME_SIP).build());
            if(!telecom.isOutgoingCallPermitted(handle)) { Log.w(TAG,"Telecom does not permit the call now");return false; }
            Bundle extras=new Bundle();
            extras.putParcelable(TelecomManager.EXTRA_PHONE_ACCOUNT_HANDLE,handle);
            extras.putBoolean(TelecomManager.EXTRA_START_CALL_WITH_SPEAKERPHONE,true);
            telecom.placeCall(Uri.fromParts(PhoneAccount.SCHEME_SIP,"agent",null),extras);
            return true;
        } catch(RuntimeException e) { Log.w(TAG,"The call goes on without Telecom",e);return false; }
    }

    /** The call's audio closed: the Linux session ended the call. */
    static void end() {
        wanted=false;held=false;
        AgentConnection c=connection;connection=null;
        if(c!=null)c.close(new DisconnectCause(DisconnectCause.LOCAL));
    }

    /** Hang up from Android's side: the call notification. */
    static void hangUp() {
        hungUp=true;
        AgentConnection c=connection;connection=null;
        if(c!=null)c.close(new DisconnectCause(DisconnectCause.LOCAL));
    }

    private static final class AgentConnection extends Connection {
        AgentConnection() {
            setConnectionProperties(PROPERTY_SELF_MANAGED);
            setConnectionCapabilities(CAPABILITY_HOLD|CAPABILITY_SUPPORT_HOLD);
            setAudioModeIsVoip(true);
            setCallerDisplayName("Agent",TelecomManager.PRESENTATION_ALLOWED);
        }
        void close(DisconnectCause cause) { setDisconnected(cause);destroy(); }
        private void hungUpHere() {
            if(connection==this)connection=null;
            hungUp=true;close(new DisconnectCause(DisconnectCause.LOCAL));
        }
        @Override public void onDisconnect() { hungUpHere(); }
        @Override public void onAbort() { hungUpHere(); }
        @Override public void onReject() { hungUpHere(); }
        @Override public void onHold() { held=true;setOnHold(); }
        @Override public void onUnhold() { held=false;setActive(); }
        @SuppressWarnings("deprecation")
        void speaker() { setAudioRoute(CallAudioState.ROUTE_SPEAKER); }
    }

    /** Telecom's side: binds while the call lasts, which also keeps the app running as a call's. */
    public static final class Service extends ConnectionService {
        @Override public Connection onCreateOutgoingConnection(PhoneAccountHandle account,ConnectionRequest request) {
            if(!wanted)return Connection.createFailedConnection(new DisconnectCause(DisconnectCause.CANCELED));
            AgentConnection c=new AgentConnection();
            c.setAddress(request.getAddress(),TelecomManager.PRESENTATION_ALLOWED);
            c.setActive();
            connection=c;
            return c;
        }
        @Override public void onCreateOutgoingConnectionFailed(PhoneAccountHandle account,ConnectionRequest request) {
            Log.w(TAG,"Telecom refused the call; it goes on without it");
        }
    }
}
