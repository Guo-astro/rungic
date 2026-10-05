package com.rungic.plasma;

import android.content.ComponentName;
import android.content.Context;
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
 */
final class AgentCall {
    private static final String TAG="RungicAgentCall";
    /** Android hung the call up (notification, headset, Telecom): the Linux session is to end it. */
    static volatile boolean hungUp;
    /** Android holds the call for another one: the Agent neither hears nor is heard meanwhile. */
    static volatile boolean held;
    private static AgentConnection connection;
    private static boolean wanted;

    private AgentCall() {}

    private static PhoneAccountHandle account(Context context) {
        return new PhoneAccountHandle(new ComponentName(context,Service.class),"agent");
    }

    /** The call's audio opened (on the UI thread). */
    static void start(Context context) {
        hungUp=false;held=false;wanted=true;
        try {
            TelecomManager telecom=context.getSystemService(TelecomManager.class);
            PhoneAccountHandle handle=account(context);
            telecom.registerPhoneAccount(PhoneAccount.builder(handle,"Rungic Agent")
                .setCapabilities(PhoneAccount.CAPABILITY_SELF_MANAGED).addSupportedUriScheme(PhoneAccount.SCHEME_SIP).build());
            if(!telecom.isOutgoingCallPermitted(handle)) { Log.w(TAG,"Telecom does not permit the call now");return; }
            Bundle extras=new Bundle();
            extras.putParcelable(TelecomManager.EXTRA_PHONE_ACCOUNT_HANDLE,handle);
            extras.putBoolean(TelecomManager.EXTRA_START_CALL_WITH_SPEAKERPHONE,true);
            telecom.placeCall(Uri.fromParts(PhoneAccount.SCHEME_SIP,"agent",null),extras);
        } catch(RuntimeException e) { Log.w(TAG,"The call goes on without Telecom",e); }
    }

    /** The call's audio closed (on the UI thread): the Linux session ended the call. */
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
        private boolean routed;
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
        @Override public void onCallAudioStateChanged(CallAudioState state) {
            // A conversation with the phone in hand, not at the ear: the earpiece Telecom may start on
            // becomes the speaker, once; a headset or Bluetooth it picks stays.
            if(routed || state==null)return;
            routed=true;
            if(state.getRoute()==CallAudioState.ROUTE_EARPIECE && (state.getSupportedRouteMask()&CallAudioState.ROUTE_SPEAKER)!=0)
                setAudioRoute(CallAudioState.ROUTE_SPEAKER);
        }
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
