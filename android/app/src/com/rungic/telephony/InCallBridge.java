// SPDX-License-Identifier: MIT
package com.rungic.telephony;

import android.net.*;
import android.os.*;
import android.telecom.*;
import org.json.*;
import java.io.*;
import java.util.*;
import java.util.concurrent.*;

/** Non-UI Telecom client. The stock dialer remains responsible for the phone UI.
 * Only the root call backend may use this socket. All Call operations run on the main looper. */
public final class InCallBridge extends InCallService {
    private final Handler main=new Handler(Looper.getMainLooper());
    private final Map<String,Call> calls=new LinkedHashMap<>();
    private LocalServerSocket server;
    // The app owns a short mute lease independently of app_process. Even SIGKILL of
    // the audio daemon cannot leave the user's ordinary phone microphone muted.
    private String leaseId,leaseCall;
    private boolean beforeMute;
    private long leaseUntil;
    private final Runnable watchdog=new Runnable(){public void run(){
        if(leaseId!=null && SystemClock.elapsedRealtime()>leaseUntil)releaseLease();
        main.postDelayed(this,500);
    }};
    private void releaseLease(){
        if(leaseId==null)return;
        if(calls.containsKey(leaseCall) && calls.size()==1){
            CallAudioState state=getCallAudioState();
            if(state!=null && state.isMuted())setMuted(beforeMute);
        }
        leaseId=null;leaseCall=null;
    }
    private final ExecutorService clients=new ThreadPoolExecutor(0,4,20,TimeUnit.SECONDS,
        new SynchronousQueue<Runnable>(),new ThreadPoolExecutor.AbortPolicy());
    @Override public void onCreate(){
        super.onCreate();main.post(watchdog);
        try{
            server=new LocalServerSocket(CallProtocol.INCALL);
            new Thread(()->{
                while(!clients.isShutdown())try{
                    LocalSocket socket=server.accept();
                    try{clients.execute(()->answer(socket));}catch(RejectedExecutionException e){socket.close();}
                }catch(IOException e){break;}
            },"incall-control").start();
        }catch(IOException e){throw new IllegalStateException("incall socket unavailable",e);}
    }
    @Override public void onCallAdded(Call call){super.onCallAdded(call);calls.put(UUID.randomUUID().toString(),call);}
    @Override public void onCallRemoved(Call call){if(call==calls.get(leaseCall))releaseLease();calls.values().remove(call);super.onCallRemoved(call);}
    @Override public void onDestroy(){
        try{if(server!=null)server.close();}catch(IOException ignored){}
        main.removeCallbacks(watchdog);releaseLease();clients.shutdownNow();super.onDestroy();
    }
    private JSONObject snapshot() throws Exception {
        JSONArray list=new JSONArray();
        for(Map.Entry<String,Call> entry:calls.entrySet()){
            Call call=entry.getValue();Call.Details details=call.getDetails();
            String number=details.getHandle()==null?"":details.getHandle().getSchemeSpecificPart();
            list.put(new JSONObject().put("id",entry.getKey()).put("state",call.getState())
                .put("number",number).put("emergency",emergency(call)));
        }
        CallAudioState audio=getCallAudioState();
        return new JSONObject().put("calls",list).put("muted",audio!=null && audio.isMuted())
            .put("route",audio==null?0:audio.getRoute());
    }
    private boolean emergency(Call call){
        if(call.getDetails().getHandle()==null)return false;
        return getSystemService(android.telephony.TelephonyManager.class)
            .isEmergencyNumber(call.getDetails().getHandle().getSchemeSpecificPart());
    }
    private JSONObject handle(JSONObject r) throws Exception {
        if(r.getString("op").equals("status"))return snapshot();
        Call call=calls.get(r.getString("id"));
        if(call==null || call.getState()==Call.STATE_DISCONNECTED)throw new IllegalStateException("stale-call");
        if(emergency(call))throw new IllegalStateException("use-system-emergency-dialer");
        // Never let a stale/reconnected Agent act on a different call.
        switch(r.getString("op")){
            case "hangup":call.disconnect();break;
            case "answer":
                if(call.getState()!=Call.STATE_RINGING)throw new IllegalStateException("not-ringing");
                call.answer(0);break;
            case "lease-acquire":
                if(calls.size()!=1 || call.getState()!=Call.STATE_ACTIVE || leaseId!=null)
                    throw new IllegalStateException("audio-lease-unavailable");
                CallAudioState state=getCallAudioState();
                if(state==null)throw new IllegalStateException("audio-state-unavailable");
                beforeMute=state.isMuted();leaseId=r.getString("lease");leaseCall=r.getString("id");
                leaseUntil=SystemClock.elapsedRealtime()+4000;setMuted(true);break;
            case "lease-renew":
                if(!r.getString("lease").equals(leaseId) || !r.getString("id").equals(leaseCall))
                    throw new IllegalStateException("audio-lease-expired");
                leaseUntil=SystemClock.elapsedRealtime()+4000;break;
            case "lease-release":
                if(r.getString("lease").equals(leaseId) && r.getString("id").equals(leaseCall))releaseLease();break;
            case "mute":
                if(calls.size()!=1)throw new IllegalStateException("multiple-calls");
                setMuted(r.getBoolean("muted"));break;
            case "dtmf":
                String digit=r.getString("digit");
                if(call.getState()!=Call.STATE_ACTIVE || !digit.matches("[0-9*#]"))throw new IllegalArgumentException("invalid-dtmf");
                call.playDtmfTone(digit.charAt(0));main.postDelayed(call::stopDtmfTone,180);break;
            default:throw new IllegalArgumentException("unknown-operation");
        }
        return new JSONObject().put("accepted",true);
    }
    private void answer(LocalSocket socket){
        try(LocalSocket c=socket){
            if(c.getPeerCredentials().getUid()!=0)return;
            c.setSoTimeout(4000);JSONObject r=CallProtocol.read(c.getInputStream());
            FutureTask<JSONObject> task=new FutureTask<>(()->handle(r));main.post(task);
            JSONObject result;
            try{result=task.get(3,TimeUnit.SECONDS);}catch(Exception e){task.cancel(false);result=new JSONObject().put("error","call-operation-failed");}
            CallProtocol.write(c.getOutputStream(),result);
        }catch(Exception ignored){}
    }
}
