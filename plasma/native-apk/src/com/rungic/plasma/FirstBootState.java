package com.rungic.plasma;

import java.io.*;
import java.util.Properties;

/** Read-only, versioned install state. Root independently checks the completion marker.
 * Plain Java (tests/FirstBootStateTest runs without Android): it reports what to say as codes,
 * and StartupScreen turns them into text in the system language. */
final class FirstBootState {
    /** What the startup screen tells the user. */
    enum Message { NONE, VERIFY, RUNTIME, ROOTFS, CONFIGURE, STORAGE_WAIT, FINISH,
        FAILED_CHECKSUM, FAILED_SPACE, FAILED_STORAGE, FAILED, WAITING }
    /** Why the state is not known yet (the details); null when the details are the state's own fields. */
    enum Reason { STANDALONE, RELEASE_MISMATCH, SCHEMA_UNSUPPORTED, STATE_INCOMPLETE, PHASE_UNKNOWN, UNREADABLE }
    final boolean ready, failed, attention, stale;
    final Message message;
    final Reason reason;
    final String release, phase, state, code;
    private FirstBootState(boolean ready, boolean failed, boolean attention, boolean stale, Message message, Reason reason,
            String release, String phase, String state, String code) {
        this.ready=ready; this.failed=failed; this.attention=attention; this.stale=stale;
        this.message=message; this.reason=reason;
        this.release=release; this.phase=phase; this.state=state; this.code=code;
    }
    private static Properties readProperties(File file) throws IOException {
        if(file.length()>4096)throw new IOException("oversized installation status");
        Properties values=new Properties();
        try(Reader reader=new InputStreamReader(new FileInputStream(file),"UTF-8")) { values.load(reader); }
        return values;
    }
    static FirstBootState read(File seed, File status) {
        return read(seed,status,System.currentTimeMillis());
    }
    static FirstBootState read(File seed, File status,long now) {
        if(!seed.exists())return new FirstBootState(true,false,false,false,Message.NONE,Reason.STANDALONE,"","","","");
        try {
            String release=readProperties(seed).getProperty("RELEASE_ID","").replace("'", "").replace("\"", "");
            Properties state=readProperties(status);
            if(release.isEmpty() || !release.equals(state.getProperty("release")))return unknown(Reason.RELEASE_MISMATCH);
            String value=state.getProperty("state", ""), phase=state.getProperty("phase", "");
            String code=state.getProperty("error", "unknown");
            // v1 remains readable; unknown future versions cannot open the account gate.
            String schema=state.getProperty("schema", "1");
            if(!schema.equals("1") && !schema.equals("2"))return unknown(Reason.SCHEMA_UNSUPPORTED);
            if(value.equals("ready"))return new FirstBootState(true,false,false,false,Message.NONE,null,release,phase,value,code);
            if(value.equals("failed")) {
                Message message;
                switch(code) {
                    case "checksum": message=Message.FAILED_CHECKSUM; break;
                    case "space": message=Message.FAILED_SPACE; break;
                    case "storage": message=Message.FAILED_STORAGE; break;
                    default: message=Message.FAILED;
                }
                return new FirstBootState(false,true,true,false,message,null,release,phase,value,code);
            }
            if(!value.equals("installing") && !value.equals("waiting"))return unknown(Reason.STATE_INCOMPLETE);
            Message message;
            switch(phase) {
                case "verify": message=Message.VERIFY; break;
                case "runtime": message=Message.RUNTIME; break;
                case "rootfs": message=Message.ROOTFS; break;
                case "configure": message=Message.CONFIGURE; break;
                case "storage": message=Message.STORAGE_WAIT; break;
                case "finish": message=Message.FINISH; break;
                default: return unknown(Reason.PHASE_UNKNOWN);
            }
            long changed=status.lastModified();
            boolean stale=changed>0 && now-changed>180000;
            return new FirstBootState(false,false,stale || value.equals("waiting"),stale,message,null,release,phase,value,code);
        } catch(IOException | IllegalArgumentException ignored) { return unknown(Reason.UNREADABLE); }
    }
    private static FirstBootState unknown(Reason reason) {
        return new FirstBootState(false,false,true,false,Message.WAITING,reason,"","","","");
    }
}
