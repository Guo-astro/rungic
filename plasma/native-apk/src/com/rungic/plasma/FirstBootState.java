package com.rungic.plasma;

import java.io.*;
import java.util.Properties;

/** Read-only installation status. The root controller independently checks completion. */
final class FirstBootState {
    final boolean ready, failed;
    final String message;
    FirstBootState(boolean ready, boolean failed, String message) {
        this.ready=ready; this.failed=failed; this.message=message;
    }
    private static Properties readProperties(File file) throws IOException {
        if(file.length()>4096)throw new IOException("oversized installation status");
        Properties values=new Properties();
        try(Reader reader=new InputStreamReader(new FileInputStream(file),"UTF-8")) { values.load(reader); }
        return values;
    }
    static FirstBootState read(File seed, File status) {
        if(!seed.exists())return new FirstBootState(true,false,""); // Existing standalone deployments.
        String message="正在准备首次安装，请保持手机开机…";
        try {
            String release=readProperties(seed).getProperty("RELEASE_ID","").replace("'", "").replace("\"", "");
            Properties state=readProperties(status);
            if(!release.isEmpty() && release.equals(state.getProperty("release"))) {
                if("ready".equals(state.getProperty("state")))return new FirstBootState(true,false,"");
                if("failed".equals(state.getProperty("state")))return new FirstBootState(false,true,
                    "首次安装尚未完成。请重启手机以继续安装；你的账户尚未开始创建。");
                switch(state.getProperty("phase","")) {
                    case "verify": message="正在检查系统安装文件…"; break;
                    case "runtime": message="正在准备系统运行环境…"; break;
                    case "rootfs": message="正在展开系统镜像，首次安装需要几分钟…"; break;
                    case "configure": message="正在配置系统…"; break;
                    case "storage": message="正在等待共享存储就绪，请先解锁手机…"; break;
                    case "finish": message="正在完成初始化…"; break;
                }
            }
        } catch(IOException | IllegalArgumentException ignored) { /* Not published yet: keep waiting. */ }
        return new FirstBootState(false,false,message);
    }
}
