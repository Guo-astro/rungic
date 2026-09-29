// SPDX-License-Identifier: MIT
package com.rungic.cast;
import android.os.*;
import android.content.*;
import java.lang.reflect.*;
import java.util.*;

/** Capability-probed Qualcomm session adapter. Uses the installed AIDL implementation;
 * never creates/replaces a WFD session, never guesses Binder transaction numbers.
 */
final class WfdSession {
    private final ClassLoader loader;
    private final Class<?> managerApi, sessionApi;
    private final Object manager, session;
    static String packagePath()throws Exception {
        Class<?> thread=Class.forName("android.app.ActivityThread");
        Object activity=thread.getMethod("currentActivityThread").invoke(null);
        if(activity==null)activity=thread.getMethod("systemMain").invoke(null);
        Context context=(Context)thread.getMethod("getSystemContext").invoke(activity);
        return context.getPackageManager().getApplicationInfo("com.qualcomm.wfd.service",0).sourceDir;
    }
    WfdSession() throws Exception {
        String pkg="com.qualcomm.wfd.service";
        loader=new dalvik.system.PathClassLoader(packagePath(),WfdSession.class.getClassLoader());
        managerApi=loader.loadClass(pkg+".ISessionManagerService");sessionApi=loader.loadClass(pkg+".IWfdSession");
        Object am=Class.forName("android.app.ActivityManager").getMethod("getService").invoke(null);
        IBinder binder=(IBinder)Class.forName("android.app.IActivityManager").getMethod("peekService",Intent.class,String.class,String.class)
                .invoke(am,new Intent().setComponent(new ComponentName(pkg,pkg+".WfdService")),null,"android");
        if(binder==null)throw new IllegalStateException("No live WFD service");
        manager=loader.loadClass(pkg+".ISessionManagerService$Stub").getMethod("asInterface",IBinder.class).invoke(null,binder);
        IBinder managed=(IBinder)managerApi.getMethod("getManagedSession").invoke(manager);
        if(managed==null)throw new IllegalStateException("No managed WFD session");
        session=loader.loadClass(pkg+".IWfdSession$Stub").getMethod("asInterface",IBinder.class).invoke(null,managed);
        sessionApi.getMethod("setCodecResolution",int.class,int.class,int.class,int.class,int.class);
    }
    WfdFormats.Mode current() throws Exception {
        Bundle value=new Bundle();
        if((int)managerApi.getMethod("getNegotiatedResolution",Bundle.class).invoke(manager,value)!=0)return null;
        long[] bits=value.getLongArray("negRes");
        if(bits==null||bits.length!=4||Long.bitCount(bits[1])+Long.bitCount(bits[2])+Long.bitCount(bits[3])!=1)return null;
        for(WfdFormats.Mode m:WfdFormats.TABLE)if((bits[m.family+1]&(1L<<m.bit))!=0)return m;
        return null;
    }
    boolean canSet(WfdFormats.Mode mode) {
        if(mode==null||mode.bit>=32||mode.interlaced)return false;
        try {
            Class<?> enums=loader.loadClass("com.qualcomm.wfd.WfdEnums");
            return (boolean)enums.getMethod("is"+new String[]{"Cea","Vesa","Hh"}[mode.family]+"Resolution",int.class).invoke(null,1<<mode.bit);
        }catch(Exception e){return false;}
    }
    boolean compatible(WfdFormats.Mode mode,List<WfdFormats.Codec> peer) {
        try {return parameters(mode,peer)!=null;}catch(Exception unavailable){return false;}
    }
    void set(WfdFormats.Mode mode, List<WfdFormats.Codec> peer) throws Exception {
        int[] p=parameters(mode,peer);
        if(p==null)throw new IllegalArgumentException("No compatible codec profile for runtime mode switching");
        int result=(int)sessionApi.getMethod("setCodecResolution",int.class,int.class,int.class,int.class,int.class)
                .invoke(session,p[0],p[1],p[2],p[3],p[4]);
        if(result!=0)throw new IllegalStateException("WFD mode request failed: "+result);
        // A successful Binder call does not prove the receiver accepted it: verify in the controller.
    }
    private int[] parameters(WfdFormats.Mode mode,List<WfdFormats.Codec> peer)throws Exception {
        if(!canSet(mode))return null;
        int format=ordinal("CapabilityType",new String[]{"WFD_CEA_RESOLUTIONS_BITMAP","WFD_VESA_RESOLUTIONS_BITMAP","WFD_HH_RESOLUTIONS_BITMAP"}[mode.family]);
        for(String[] choice:new String[][]{{"H264Profile","WFD_VIDEO_H264_RESTRICTED_HIGH2","WFD_VIDEO_H264"},
                {"H264Profile","WFD_VIDEO_H264_RESTRICTED_HIGH","WFD_VIDEO_H264"},
                {"H264Profile","WFD_VIDEO_H264_CONSTRAINED_BASELINE","WFD_VIDEO_H264"},
                {"H265Profile","WFD_VIDEO_H265_MAIN","WFD_VIDEO_H265"}}) {
            int codec=choice[0].equals("H264Profile")?1:2, profile;
            try {profile=ordinal(choice[0],choice[1]);}catch(ReflectiveOperationException missing){continue;}
            for(WfdFormats.Codec remote:peer) if(remote.codec==codec && (remote.profile&(1<<profile))!=0 && remote.contains(mode)) {
                int level=WfdConfig.levelForMode(codec,profile,mode,remote.level);
                if(level>=0)return new int[]{ordinal("VideoFormat",choice[2]),profile,level,format,1<<mode.bit};
            }
        }
        return null;
    }
    private int ordinal(String type,String name)throws Exception {
        Class<?> c=loader.loadClass("com.qualcomm.wfd.WfdEnums$"+type);
        return ((Enum<?>)c.getField(name).get(null)).ordinal();
    }
}
