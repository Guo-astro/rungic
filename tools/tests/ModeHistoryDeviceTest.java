// SPDX-License-Identifier: MIT
package com.rungic.cast;
import android.os.Looper;
import java.io.File;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import org.json.JSONObject;

/** Run alongside the deployed root jar. Uses a unique result file; never changes a display. */
public final class ModeHistoryDeviceTest {
    static void check(boolean condition,String message){if(!condition)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception {
        Looper.prepareMainLooper();
        Constructor<ModeHistory> ctor=ModeHistory.class.getDeclaredConstructor(String.class,String.class);ctor.setAccessible(true);
        String identity="test-"+android.os.Process.myPid();ModeHistory history=ctor.newInstance("00:00:00:00:00:01",identity);
        Field fileField=ModeHistory.class.getDeclaredField("file");fileField.setAccessible(true);File file=(File)fileField.get(history);
        check(!file.exists(),"Test file must be new");
        try {
            history.record("1920x1080@30","passed","test only");
            check(history.results().getJSONObject("1920x1080@30").getString("state").equals("passed"),"Persisted positive");
            history.record("1920x1080@30","rejected","test only");
            check(history.results().getJSONObject("1920x1080@30").getString("state").equals("rejected"),"Failure supersedes success");
            JSONObject data=new JSONObject(new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8));
            data.getJSONObject("modes").getJSONObject("1920x1080@30").put("checked_at",System.currentTimeMillis()-8L*86400000);
            Files.write(file.toPath(),data.toString().getBytes(StandardCharsets.UTF_8));
            check(history.results().length()==0,"Expired individual result is not renewed by other modes");
            data.put("identity","different-backend");Files.write(file.toPath(),data.toString().getBytes(StandardCharsets.UTF_8));
            check(history.results().length()==0,"Identity mismatch is not trusted");
            Files.write(file.toPath(),"broken json".getBytes(StandardCharsets.UTF_8));
            check(history.results().length()==0,"Corrupt history fails closed");
            JSONObject peer=new JSONObject().put("r2",true).put("offered","fixture-a");
            ModeHistory a=ModeHistory.open("00:00:00:00:00:01",peer),b=ModeHistory.open("00:00:00:00:00:02",peer);
            ModeHistory c=ModeHistory.open("00:00:00:00:00:01",new JSONObject().put("r2",true).put("offered","fixture-b"));
            check(a!=null&&b!=null&&c!=null,"Current backend identity available");
            check(!fileField.get(a).equals(fileField.get(b)),"Receiver isolation");
            check(!fileField.get(a).equals(fileField.get(c)),"Changed advertised capabilities invalidate history");
            System.out.println("Mode history isolation, expiry, failure and corruption checks passed");
        }finally {file.delete();}
        System.exit(0);
    }
}
