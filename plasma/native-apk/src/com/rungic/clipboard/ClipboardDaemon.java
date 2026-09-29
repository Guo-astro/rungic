// SPDX-License-Identifier: MIT
package com.rungic.clipboard;

import android.app.KeyguardManager;
import android.content.*;
import android.net.*;
import android.os.*;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.concurrent.*;

/** Container-lifetime Android clipboard backend, run by Magisk as Shell (not as an Activity).
 * Uses the device's framework ClipboardManager rather than vendor-specific Binder signatures.
 * See docs/research/clipboard-background.md. Never logs clipboard contents. */
public final class ClipboardDaemon {
    public static final String SOCKET="com.rungic.clipboard.v1";
    private final ClipboardManager clipboard;
    private final KeyguardManager keyguard;
    private final int appUid;
    private final Object changes=new Object();
    private final String epoch=UUID.randomUUID().toString();
    private long version;
    private final ExecutorService clients=new ThreadPoolExecutor(0,8,30,TimeUnit.SECONDS,
        new SynchronousQueue<Runnable>(),new ThreadPoolExecutor.AbortPolicy());

    private ClipboardDaemon(Context context,int appUid) throws Exception {
        this.appUid=appUid;
        if(context.getPackageManager().checkPermission("android.permission.READ_CLIPBOARD_IN_BACKGROUND",
            "com.android.shell")!=android.content.pm.PackageManager.PERMISSION_GRANTED)
            throw new SecurityException("Shell clipboard permission is missing");
        keyguard=context.getSystemService(KeyguardManager.class);
        clipboard=ClipboardManager.class.getConstructor(Context.class,Handler.class)
            .newInstance(context,new Handler(Looper.getMainLooper()));
        clipboard.addPrimaryClipChangedListener(this::changed);
        IntentFilter filter=new IntentFilter();
        filter.addAction(Intent.ACTION_USER_PRESENT);filter.addAction(Intent.ACTION_SCREEN_OFF);
        filter.addAction("android.intent.action.USER_SWITCHED");
        context.registerReceiver(new BroadcastReceiver(){
            @Override public void onReceive(Context c,Intent i){changed();}
        },filter);
        IBinder binder=(IBinder)Class.forName("android.os.ServiceManager").getMethod("getService",String.class).invoke(null,"clipboard");
        binder.linkToDeath(()->System.exit(1),0);
    }
    private void changed(){synchronized(changes){version++;changes.notifyAll();}}
    private boolean accessible() throws Exception {
        // This container belongs to Android user 0. Never silently follow a different user's clipboard.
        int user=(Integer)Class.forName("android.app.ActivityManager").getMethod("getCurrentUser").invoke(null);
        return user==0 && !keyguard.isDeviceLocked();
    }
    private synchronized JSONObject read() throws Exception {
        if(!accessible())return new JSONObject().put("available",false).put("reason","locked-or-other-user");
        ClipData clip=clipboard.getPrimaryClip();
        if(clip!=null && clip.getDescription().getExtras()!=null &&
            clip.getDescription().getExtras().getBoolean("android.content.extra.IS_SENSITIVE",false))
            return new JSONObject().put("available",false).put("reason","sensitive");
        CharSequence text=clip!=null && clip.getItemCount()>0?clip.getItemAt(0).getText():null;
        if(clip!=null && text==null)return new JSONObject().put("available",false).put("reason","non-text");
        if(text!=null && (text.length()>65536 || text.toString().getBytes(StandardCharsets.UTF_8).length>262144))
            return new JSONObject().put("available",false).put("reason","too-large");
        return new JSONObject().put("available",true).put("text",text==null?JSONObject.NULL:text.toString());
    }
    private synchronized JSONObject write(JSONObject request) throws Exception {
        if(!accessible())return new JSONObject().put("error","locked-or-other-user");
        if(!request.has("text"))throw new IllegalArgumentException();
        Object value=request.get("text");
        if(value!=JSONObject.NULL && !(value instanceof String))throw new IllegalArgumentException();
        String text=value==JSONObject.NULL?null:(String)value;
        if(text!=null && (text.length()>65536 || text.getBytes(StandardCharsets.UTF_8).length>262144))throw new IllegalArgumentException();
        ClipData old=clipboard.getPrimaryClip();
        CharSequence previous=old!=null && old.getItemCount()>0?old.getItemAt(0).getText():null;
        if(text==null){if(old!=null)clipboard.clearPrimaryClip();}
        else if(previous==null || !text.contentEquals(previous))clipboard.setPrimaryClip(ClipData.newPlainText("Linux",text));
        return new JSONObject().put("ok",true);
    }
    private JSONObject handle(JSONObject request) throws Exception {
        switch(request.optString("op")) {
            case "clipboard-get":return read();
            case "clipboard-set":return write(request);
            case "status":return new JSONObject().put("protocol",1).put("uid",android.os.Process.myUid()).put("epoch",epoch);
            case "watch":
                synchronized(changes){
                    JSONObject seen=request.optJSONObject("seen");
                    long before=seen==null?-1:seen.optLong("clipboard",-1);
                    long until=SystemClock.elapsedRealtime()+Math.max(1,Math.min(30000,request.optLong("timeout",30000)));
                    while(epoch.equals(request.optString("epoch")) && before==version){
                        long remaining=until-SystemClock.elapsedRealtime();if(remaining<=0)break;
                        changes.wait(remaining);
                    }
                    return new JSONObject().put("epoch",epoch).put("versions",new JSONObject().put("clipboard",version));
                }
            default:throw new IllegalArgumentException();
        }
    }
    private void answer(LocalSocket socket){
        try(LocalSocket c=socket){
            int uid=c.getPeerCredentials().getUid();
            if(uid!=0 && uid!=1000 && uid!=appUid)return;
            c.setSoTimeout(3000);
            ByteArrayOutputStream data=new ByteArrayOutputStream();int b;
            while((b=c.getInputStream().read())!=-1 && b!='\n'){
                if(data.size()>=524288)throw new IOException();data.write(b);
            }
            JSONObject result;
            try{result=handle(new JSONObject(data.toString("UTF-8")));}
            catch(Exception e){result=new JSONObject().put("error","clipboard-operation-failed");}
            c.getOutputStream().write((result.toString()+"\n").getBytes(StandardCharsets.UTF_8));
        }catch(Exception ignored){} // no content or raw framework exception in logs
    }
    public static void main(String[] args) {
        try {
            if(android.os.Process.myUid()!=2000 || args.length!=1)throw new IllegalArgumentException();
            try(FileWriter pid=new FileWriter("pid")){pid.write(Integer.toString(android.os.Process.myPid()));}
            Looper.prepareMainLooper();
            Class<?> at=Class.forName("android.app.ActivityThread");
            Context system=(Context)at.getMethod("getSystemContext").invoke(at.getMethod("systemMain").invoke(null));
            Context context=new ContextWrapper(system){
                @Override public String getPackageName(){return "com.android.shell";}
                @Override public String getOpPackageName(){return "com.android.shell";}
                @Override public AttributionSource getAttributionSource(){return new AttributionSource.Builder(2000).setPackageName("com.android.shell").build();}
            };
            ClipboardDaemon daemon=new ClipboardDaemon(context,Integer.parseInt(args[0]));
            LocalServerSocket server=new LocalServerSocket(SOCKET);
            new Thread(()->{
                for(;;)try{
                    LocalSocket client=server.accept();
                    try{daemon.clients.execute(()->daemon.answer(client));}
                    catch(RejectedExecutionException e){client.close();}
                }catch(IOException e){System.exit(1);}
            },"clipboard-socket").start();
            Looper.loop();
        }catch(Throwable e){System.err.println("clipboard backend unavailable: "+e.getClass().getSimpleName());System.exit(1);}
    }
}
