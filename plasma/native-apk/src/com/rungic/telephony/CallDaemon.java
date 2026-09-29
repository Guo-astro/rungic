// SPDX-License-Identifier: MIT
package com.rungic.telephony;

import android.content.*;
import android.media.*;
import android.net.*;
import android.os.*;
import android.telecom.*;
import android.telephony.TelephonyManager;
import org.json.*;
import java.io.*;
import java.util.*;
import java.util.concurrent.*;

/** Privileged, container-lifetime cellular backend. No vendor mixer/Binder transaction numbers.
 * UI and Telecom Call objects live in InCallBridge; only audio and placeCall need this process.
 * A lost PCM client releases both tracks and restores the physical microphone, never redials. */
public final class CallDaemon {
    private final Context context;
    private final AudioManager audio;
    private final TelecomManager telecom;
    private final String epoch=UUID.randomUUID().toString();
    private final ExecutorService clients=new ThreadPoolExecutor(0,8,30,TimeUnit.SECONDS,
        new SynchronousQueue<Runnable>(),new ThreadPoolExecutor.AbortPolicy());
    private volatile AudioSession session;
    private long pendingAt=-15000;
    private final Set<String> dialTokens=new HashSet<>();
    private CallDaemon(Context c){context=c;audio=c.getSystemService(AudioManager.class);telecom=c.getSystemService(TelecomManager.class);
        try(BufferedReader reader=new BufferedReader(new FileReader("dial-tokens"))){
            for(String line;(line=reader.readLine())!=null;)dialTokens.add(line);
        }catch(FileNotFoundException ignored){}catch(IOException e){throw new IllegalStateException("request-cache-unreadable",e);}
    }
    private boolean supported() throws Exception {
        return (Boolean)AudioManager.class.getMethod("isPstnCallAudioInterceptable").invoke(audio);
    }
    private int phoneState() throws Exception {return (Integer)TelecomManager.class.getMethod("getCallState").invoke(telecom);}
    private JSONObject incall() throws Exception {
        try{return CallProtocol.request(new JSONObject().put("op","status"));}
        catch(IOException e){return new JSONObject().put("calls",new JSONArray()).put("available",false);}
    }
    private JSONObject call(String id) throws Exception {
        JSONArray calls=incall().getJSONArray("calls");
        for(int i=0;i<calls.length();i++)if(id.equals(calls.getJSONObject(i).getString("id")))return calls.getJSONObject(i);
        throw new IllegalStateException("stale-call");
    }
    private JSONObject status() throws Exception {
        JSONObject s=incall();JSONArray accounts=new JSONArray();
        List<PhoneAccountHandle> handles=telecom.getCallCapablePhoneAccounts();
        for(int i=0;i<handles.size();i++){
            PhoneAccount account=telecom.getPhoneAccount(handles.get(i));
            accounts.put(new JSONObject().put("id",handles.get(i).getId()).put("label",String.valueOf(account.getLabel())));
        }
        return s.put("protocol",1).put("epoch",epoch).put("phoneState",phoneState()).put("audioMode",audio.getMode())
            .put("audioCapable",supported()).put("accounts",accounts).put("audioActive",session!=null)
            .put("privateVoiceInstructions",false).put("independentMonitor",false);
    }
    private synchronized JSONObject dial(JSONObject r) throws Exception {
        String token=r.getString("requestId"),number=r.getString("number");
        if(!token.matches("[A-Za-z0-9_-]{8,80}") || !number.matches("\\+?[0-9]{3,15}"))throw new IllegalArgumentException("invalid-dial-request");
        if(context.getSystemService(TelephonyManager.class).isEmergencyNumber(number))throw new IllegalArgumentException("use-system-emergency-dialer");
        if(dialTokens.contains(token))return new JSONObject().put("accepted",false).put("duplicate",true);
        if(phoneState()!=TelephonyManager.CALL_STATE_IDLE || SystemClock.elapsedRealtime()-pendingAt<15000)
            throw new IllegalStateException("call-already-pending-or-active");
        List<PhoneAccountHandle> accounts=telecom.getCallCapablePhoneAccounts();PhoneAccountHandle selected=null;
        String account=r.optString("account");
        if(!account.isEmpty())for(PhoneAccountHandle a:accounts){if(account.equals(a.getId()))selected=a;}
        if(account.isEmpty()){
            selected=telecom.getDefaultOutgoingPhoneAccount("tel");
            if(selected==null && accounts.size()==1)selected=accounts.get(0);
        }
        if(selected==null)throw new IllegalStateException("select-voice-sim");
        // Remember before invoking Binder: a timeout must not cause a duplicate outbound call.
        if(dialTokens.size()>=4096)throw new IllegalStateException("dial-request-cache-full");
        try(FileOutputStream out=new FileOutputStream("dial-tokens",true)){
            out.write((token+"\n").getBytes(java.nio.charset.StandardCharsets.UTF_8));out.getFD().sync();
        }
        dialTokens.add(token);pendingAt=SystemClock.elapsedRealtime();
        Bundle extras=new Bundle();extras.putParcelable(TelecomManager.EXTRA_PHONE_ACCOUNT_HANDLE,selected);
        telecom.placeCall(Uri.fromParts("tel",number,null),extras);
        return new JSONObject().put("accepted",true).put("requestId",token);
    }
    private JSONObject handle(JSONObject r) throws Exception {
        String op=r.getString("op");
        if(op.equals("status"))return status();
        if(op.equals("dial"))return dial(r);
        if(op.equals("show-linux")){
            call(r.getString("id"));
            // app_process's system Context cannot attribute an activity launch to
            // this APK. Use the same root shell entry point as the host controller.
            java.lang.Process launch=new ProcessBuilder("/system/bin/am","start","--user","0","-n",
                "com.rungic.plasma/.MainActivity").redirectErrorStream(true).start();
            try(InputStream output=launch.getInputStream()){byte[] b=new byte[1024];while(output.read(b)!=-1){}}
            if(launch.waitFor()!=0)throw new IOException("linux-ui-unavailable");
            return new JSONObject().put("accepted",true);
        }
        if(op.equals("release-audio")){
            if(session!=null && session.id.equals(r.getString("id")))session.close();
            return new JSONObject().put("ok",true);
        }
        if(op.equals("hangup") || op.equals("answer") || op.equals("dtmf")){
            call(r.getString("id"));
            if(op.equals("hangup") && session!=null && session.id.equals(r.getString("id")))session.close();
            return CallProtocol.request(r);
        }
        throw new IllegalArgumentException("unknown-operation");
    }
    private synchronized AudioSession begin(JSONObject r,LocalSocket socket) throws Exception {
        if(session!=null)throw new IllegalStateException("audio-already-owned");
        String id=r.getString("id");JSONObject state=incall();JSONArray calls=state.getJSONArray("calls");
        if(calls.length()!=1 || !calls.getJSONObject(0).getString("id").equals(id)
            || calls.getJSONObject(0).getInt("state")!=Call.STATE_ACTIVE
            || calls.getJSONObject(0).optBoolean("emergency"))throw new IllegalStateException("requires-single-active-call");
        AudioSession candidate=new AudioSession(id,socket,state.optBoolean("muted"));
        try{candidate.open();session=candidate;return candidate;}catch(Exception e){candidate.close();throw e;}
    }
    private final class AudioSession {
        final String id;final String lease=UUID.randomUUID().toString();final LocalSocket socket;final boolean wasMuted;
        volatile boolean closed;AudioRecord record;AudioTrack track;long received,sent;
        AudioSession(String id,LocalSocket s,boolean mute){this.id=id;socket=s;wasMuted=mute;}
        void open() throws Exception {
            AudioFormat rx=new AudioFormat.Builder().setSampleRate(24000).setEncoding(AudioFormat.ENCODING_PCM_16BIT).setChannelMask(AudioFormat.CHANNEL_IN_MONO).build();
            AudioFormat tx=new AudioFormat.Builder().setSampleRate(24000).setEncoding(AudioFormat.ENCODING_PCM_16BIT).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build();
            record=(AudioRecord)AudioManager.class.getMethod("getCallDownlinkExtractionAudioRecord",AudioFormat.class).invoke(audio,rx);
            track=(AudioTrack)AudioManager.class.getMethod("getCallUplinkInjectionAudioTrack",AudioFormat.class).invoke(audio,tx);
            // Telecom owns microphone mute across route changes. Restored when the lease ends.
            JSONObject muted=CallProtocol.request(new JSONObject().put("op","lease-acquire").put("id",id).put("lease",lease));
            if(muted.has("error"))throw new IOException("microphone-isolation-unavailable");
            record.startRecording();track.play();
        }
        void stream() throws Exception {
            socket.setSoTimeout(5000);
            CallProtocol.write(socket.getOutputStream(),new JSONObject().put("ok",true).put("rate",24000).put("channels",1).put("format","s16le"));
            Thread reader=new Thread(()->{
                byte[] buffer=new byte[960];
                try{
                    while(!closed){int n=record.read(buffer,0,buffer.length);if(n<=0)throw new IOException("downlink-ended");socket.getOutputStream().write(buffer,0,n);sent+=n;}
                }catch(Exception e){}finally{close();}
            },"call-downlink");reader.start();
            Thread guard=new Thread(()->{
                try{
                    while(!closed){Thread.sleep(1000);
                        JSONObject heartbeat=CallProtocol.request(new JSONObject().put("op","lease-renew").put("id",id).put("lease",lease));
                        if(heartbeat.has("error"))break;
                        JSONObject s=incall();JSONArray cs=s.getJSONArray("calls");
                        if(cs.length()!=1 || !cs.getJSONObject(0).getString("id").equals(id)
                            || cs.getJSONObject(0).getInt("state")!=Call.STATE_ACTIVE)break;}
                }catch(Exception e){}finally{close();}
            },"call-lifetime");guard.start();
            byte[] buffer=new byte[960];InputStream in=socket.getInputStream();
            try{
                while(!closed){
                    int count=0;while(count<buffer.length){int n=in.read(buffer,count,buffer.length-count);if(n<0)throw new EOFException();count+=n;}
                    int offset=0;while(offset<count){int n=track.write(buffer,offset,count-offset);if(n<=0)throw new IOException("uplink-ended");offset+=n;received+=n;}
                }
            }finally{close();}
        }
        synchronized void close(){
            if(closed)return;closed=true;
            try{socket.close();}catch(Exception ignored){}
            try{if(record!=null){record.stop();record.release();}}catch(Exception ignored){}
            try{if(track!=null){track.pause();track.flush();track.release();}}catch(Exception ignored){}
            try{CallProtocol.request(new JSONObject().put("op","lease-release").put("id",id).put("lease",lease));}catch(Exception ignored){}
            synchronized(CallDaemon.this){if(session==this)session=null;}
        }
    }
    private void answer(LocalSocket socket){
        boolean streaming=false;
        try(LocalSocket c=socket){
            int uid=c.getPeerCredentials().getUid();if(uid!=0 && uid!=1000 && uid!=CallProtocol.appUid)return;
            c.setSoTimeout(3000);JSONObject r=CallProtocol.read(c.getInputStream());
            try{
                if(r.getString("op").equals("audio")){AudioSession a=begin(r,c);streaming=true;try{a.stream();}finally{a.close();}}
                else CallProtocol.write(c.getOutputStream(),handle(r));
            }catch(Exception e){
                if(streaming)return; // Binary PCM has started; EOF is the only valid error indication.
                Throwable cause=e instanceof java.lang.reflect.InvocationTargetException?e.getCause():e;
                CallProtocol.write(c.getOutputStream(),new JSONObject().put("error",cause.getClass().getSimpleName())
                    .put("reason",String.valueOf(cause.getMessage())));
            }
        }catch(Exception ignored){}
    }
    public static void main(String[] args){
        try{
            if(android.os.Process.myUid()!=0 || args.length!=1)throw new IllegalArgumentException();
            CallProtocol.appUid=Integer.parseInt(args[0]);
            Looper.prepareMainLooper();Class<?> at=Class.forName("android.app.ActivityThread");
            // app_process does not run ZygoteInit's telephony module initialization.
            Class<?> init=Class.forName("android.telephony.TelephonyFrameworkInitializer");
            Class<?> manager=Class.forName("android.os.TelephonyServiceManager");
            if(init.getMethod("getTelephonyServiceManager").invoke(null)==null)
                init.getMethod("setTelephonyServiceManager",manager).invoke(null,manager.getConstructor().newInstance());
            Context context=(Context)at.getMethod("getSystemContext").invoke(at.getMethod("systemMain").invoke(null));
            android.app.AppOpsManager.class.getMethod("setMode",String.class,int.class,String.class,int.class)
                .invoke(context.getSystemService(android.app.AppOpsManager.class),"android:manage_ongoing_calls",
                    CallProtocol.appUid,"com.rungic.plasma",android.app.AppOpsManager.MODE_ALLOWED);
            CallDaemon daemon=new CallDaemon(context);LocalServerSocket server=new LocalServerSocket(CallProtocol.CONTROL);
            try(FileWriter p=new FileWriter("pid")){p.write(Integer.toString(android.os.Process.myPid()));}
            Runtime.getRuntime().addShutdownHook(new Thread(()->{if(daemon.session!=null)daemon.session.close();}));
            new Thread(()->{
                for(;;)try{LocalSocket client=server.accept();try{daemon.clients.execute(()->daemon.answer(client));}
                    catch(RejectedExecutionException e){client.close();}}
                catch(IOException e){System.exit(1);}
            },"call-control").start();
            Looper.loop();
        }catch(Throwable e){System.err.println("call backend unavailable: "+e.getClass().getSimpleName());System.exit(1);}
    }
}
