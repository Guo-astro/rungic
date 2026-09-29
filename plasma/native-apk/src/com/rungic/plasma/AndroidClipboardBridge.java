// SPDX-License-Identifier: MIT
package com.rungic.plasma;

import android.net.LocalSocket;
import android.net.LocalSocketAddress;
import com.rungic.clipboard.ClipboardDaemon;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/** Compatibility forwarding only. Clipboard access and notifications belong to the host daemon. */
final class AndroidClipboardBridge implements java.io.Closeable {
    private volatile boolean running;
    private volatile LocalSocket watcher;
    void start(){
        if(running)return;
        running=true;
        Thread thread=new Thread(()->{
            String epoch="";JSONObject seen=null;
            while(running){
                try(LocalSocket c=new LocalSocket()){
                    watcher=c;
                    if(!running)break;
                    JSONObject query=new JSONObject().put("op","watch").put("epoch",epoch)
                        .put("seen",seen==null?JSONObject.NULL:seen).put("timeout",30000);
                    JSONObject reply=exchange(c,query,35000);
                    String next=reply.getString("epoch");JSONObject versions=reply.getJSONObject("versions");
                    if(!epoch.equals(next) || seen==null || seen.optLong("clipboard")!=versions.optLong("clipboard"))
                        HostEvents.bump(HostEvents.CLIPBOARD);
                    epoch=next;seen=versions;
                }catch(Exception e){
                    try{Thread.sleep(2000);}catch(InterruptedException ignored){}
                }finally{watcher=null;}
            }
        },"clipboard-events");thread.setDaemon(true);thread.start();
    }
    @Override public void close(){
        running=false;LocalSocket c=watcher;
        if(c!=null)try{c.close();}catch(Exception ignored){}
    }
    static JSONObject request(JSONObject request,int timeout) throws Exception {
        try(LocalSocket c=new LocalSocket()){
            return exchange(c,request,timeout);
        }catch(Exception e){return new JSONObject().put("error","clipboard-backend-unavailable");}
    }
    private static JSONObject exchange(LocalSocket c,JSONObject request,int timeout) throws Exception {
            c.connect(new LocalSocketAddress(ClipboardDaemon.SOCKET,LocalSocketAddress.Namespace.ABSTRACT));
            if(c.getPeerCredentials().getUid()!=2000)throw new SecurityException("Unexpected clipboard backend");
            c.setSoTimeout(timeout);
            c.getOutputStream().write((request.toString()+"\n").getBytes(StandardCharsets.UTF_8));
            ByteArrayOutputStream data=new ByteArrayOutputStream();int b;
            while((b=c.getInputStream().read())!=-1 && b!='\n'){
                if(data.size()>=524288)throw new IllegalArgumentException("Response too large");data.write(b);
            }
            return new JSONObject(data.toString("UTF-8"));
    }
}
