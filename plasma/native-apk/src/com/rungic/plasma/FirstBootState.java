package com.rungic.plasma;

import java.io.*;
import java.util.Properties;

/** Read-only, versioned install state. Root independently checks the completion marker. */
final class FirstBootState {
    final boolean ready, failed, attention;
    final String message, details;
    private FirstBootState(boolean ready, boolean failed, boolean attention, String message, String details) {
        this.ready=ready; this.failed=failed; this.attention=attention;
        this.message=message; this.details=details;
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
        if(!seed.exists())return new FirstBootState(true,false,false,"", "独立安装");
        try {
            String release=readProperties(seed).getProperty("RELEASE_ID","").replace("'", "").replace("\"", "");
            Properties state=readProperties(status);
            if(release.isEmpty() || !release.equals(state.getProperty("release")))return unknown("安装版本尚未匹配");
            String value=state.getProperty("state", ""), phase=state.getProperty("phase", "");
            String code=state.getProperty("error", "unknown");
            String details="版本："+release+"\n阶段："+phase+"\n状态："+value+"\n原因："+code;
            // v1 remains readable; unknown future versions cannot open the account gate.
            String schema=state.getProperty("schema", "1");
            if(!schema.equals("1") && !schema.equals("2"))return unknown("安装状态版本不受支持");
            if(value.equals("ready"))return new FirstBootState(true,false,false,"",details);
            if(value.equals("failed")) {
                String message;
                switch(code) {
                    case "checksum": message="安装文件校验未通过。请重新获取与本机匹配的安装包；重启不会修复文件。"; break;
                    case "space": message="手机存储空间不足。请返回 Android 释放空间，再重启手机继续准备。"; break;
                    case "storage": message="共享存储尚未可用。请先解锁手机；若安装已停止，重启后会重新检查。"; break;
                    default: message="系统准备未完成。请查看安装详情，保留错误信息后再处理；此时无需重新填写账户。";
                }
                return new FirstBootState(false,true,true,message,details);
            }
            if(!value.equals("installing") && !value.equals("waiting"))return unknown("尚未收到完整的安装状态");
            String message;
            switch(phase) {
                case "verify": message="正在检查安装文件…"; break;
                case "runtime": message="正在准备运行环境…"; break;
                case "rootfs": message="正在展开桌面系统，首次安装需要几分钟…"; break;
                case "configure": message="正在配置系统…"; break;
                case "storage": message="等待共享存储可用，请先解锁手机。解锁后会自动继续。"; break;
                case "finish": message="正在完成初始化…"; break;
                default: return unknown("安装阶段尚未识别");
            }
            long changed=status.lastModified();
            boolean stale=changed>0 && now-changed>180000;
            if(stale)message+="\n较长时间未收到新的阶段状态，准备可能仍在进行。可以重新检查或查看详情。";
            return new FirstBootState(false,false,stale || value.equals("waiting"),message,details);
        } catch(IOException | IllegalArgumentException ignored) { return unknown("安装服务尚未发布可读取的状态"); }
    }
    private static FirstBootState unknown(String reason) {
        return new FirstBootState(false,false,true,"正在等待安装状态。首次开机可能还在准备，请保持手机开机并完成 Android 引导。\n若长时间没有变化，可查看详情并重新检查。",reason);
    }
}
