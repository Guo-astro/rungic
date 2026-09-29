// SPDX-License-Identifier: MIT
package com.rungic.cast;

import android.os.Build;
import android.util.AtomicFile;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import org.json.*;

/** Observed outcomes, never a hardware allowlist. A backend/firmware/offer change
 * invalidates previous results. A passed check does not certify TV picture quality.
 */
final class ModeHistory {
    private static final File DIR=new File("/data/adb/rungic-wfd/mode-results");
    private final File file;
    private final String address, identity;

    private ModeHistory(String address,String identity) {
        this.address=address;this.identity=identity;file=new File(DIR,identity+".json");
    }
    static ModeHistory open(String address,JSONObject peer) {
        try {return create(address,peer);}catch(Exception unavailable){return null;}
    }
    private static ModeHistory create(String address,JSONObject peer)throws Exception {
        if(peer==null||address==null)return null;
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        // Length-delimited fields avoid ambiguous identities; package bytes include its ABI.
        for(String value:new String[]{"mode-check-v1",address.toLowerCase(java.util.Locale.ROOT),Build.FINGERPRINT,
                peer.getString("offered"),String.valueOf(peer.getBoolean("r2"))}) {
            byte[] bytes=value.getBytes(StandardCharsets.UTF_8);
            digest.update(java.nio.ByteBuffer.allocate(4).putInt(bytes.length).array());digest.update(bytes);
        }
        for(File source:new File[]{new File("/data/adb/rungic-wfd/rungic-cast.jar"),
                new File("/data/adb/rungic-wfd/wfdconfig-stock.xml"),new File(WfdSession.packagePath())}) {
            byte[] bytes=Files.readAllBytes(source.toPath());
            digest.update(java.nio.ByteBuffer.allocate(4).putInt(bytes.length).array());digest.update(bytes);
        }
        StringBuilder key=new StringBuilder();for(byte b:digest.digest())key.append(String.format("%02x",b&255));
        return new ModeHistory(address,key.toString());
    }
    JSONObject results() {
        try {
            if(!file.exists()||file.length()>131072)return new JSONObject();
            JSONObject data=new JSONObject(new String(new AtomicFile(file).readFully(),StandardCharsets.UTF_8));
            long age=System.currentTimeMillis()-data.getLong("updated_at");
            if(!identity.equals(data.getString("identity"))||age<0||age>7L*86400000)return new JSONObject();
            JSONObject modes=data.getJSONObject("modes"),recent=new JSONObject();
            java.util.Iterator<String> keys=modes.keys();
            while(keys.hasNext()) {
                String key=keys.next();JSONObject value=modes.getJSONObject(key);
                long entryAge=System.currentTimeMillis()-value.getLong("checked_at");
                if(entryAge>=0&&entryAge<=7L*86400000)recent.put(key,value);
            }
            return recent;
        }catch(Exception invalid){return new JSONObject();}
    }
    void record(String mode,String state,String detail) {
        if("auto".equals(mode))return;
        try {
            DIR.mkdirs();
            try(RandomAccessFile lock=new RandomAccessFile(new File(DIR,"lock"),"rw");
                    java.nio.channels.FileLock held=lock.getChannel().lock()) {
                JSONObject modes=results();
                modes.put(mode,new JSONObject().put("state",state).put("detail",detail).put("checked_at",System.currentTimeMillis()));
                JSONObject data=new JSONObject().put("identity",identity).put("address",address)
                        .put("updated_at",System.currentTimeMillis()).put("modes",modes);
                AtomicFile target=new AtomicFile(file);FileOutputStream out=target.startWrite();
                try {out.write(data.toString().getBytes(StandardCharsets.UTF_8));target.finishWrite(out);}
                catch(Exception e){target.failWrite(out);throw e;}
            }
        }catch(Exception e){System.err.println("WFD mode history: "+e.getMessage());}
    }
}
