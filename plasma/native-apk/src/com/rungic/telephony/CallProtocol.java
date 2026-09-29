// SPDX-License-Identifier: MIT
package com.rungic.telephony;

import android.net.LocalSocket;
import android.net.LocalSocketAddress;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;

/** Small control messages; audio uses a separate, explicitly negotiated PCM connection. */
public final class CallProtocol {
    public static final String CONTROL="com.rungic.calls.v1", INCALL="com.rungic.incall.v1";
    public static int appUid=-1;
    public static JSONObject read(InputStream in) throws Exception {
        ByteArrayOutputStream data=new ByteArrayOutputStream();
        for(int b;(b=in.read())!=-1;){
            if(b=='\n')return new JSONObject(data.toString("UTF-8"));
            if(data.size()>=16384)throw new IOException("request-too-large");
            data.write(b);
        }
        throw new EOFException();
    }
    public static void write(OutputStream out,JSONObject data) throws Exception {
        out.write((data.toString()+"\n").getBytes(StandardCharsets.UTF_8));out.flush();
    }
    public static JSONObject request(JSONObject request) throws Exception {
        try(LocalSocket socket=new LocalSocket()){
            socket.connect(new LocalSocketAddress(INCALL));socket.setSoTimeout(4000);
            if(socket.getPeerCredentials().getUid()!=appUid)throw new SecurityException("invalid-incall-peer");
            write(socket.getOutputStream(),request);return read(socket.getInputStream());
        }
    }
}
