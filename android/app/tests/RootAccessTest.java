package com.rungic.plasma;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;

/** A refused or hidden su is told apart from other start failures, and names its provider. */
public final class RootAccessTest {
    // covers: install.desktop-entry/E7
    public static void main(String[] args) throws Exception {
        // KernelSU before the grant: su is not there for the app.
        if(!RootAccess.denied(new IOException("Cannot run program \"/system/bin/su\": error=2, No such file or directory")))
            throw new AssertionError("hidden su");
        if(!RootAccess.denied(new IOException("Cannot run program \"/system/bin/su\": error=13, Permission denied")))
            throw new AssertionError("unexecutable su");
        // Magisk's denied request.
        if(!RootAccess.denied(new ControlException("account-status",13,"Permission denied\n")))
            throw new AssertionError("denied su");
        if(!RootAccess.denied(new ControlException("account-status",1,"Permission denied")))
            throw new AssertionError("denied su, older client");
        // Controller failures after su ran are not a missing grant.
        if(RootAccess.denied(new ControlException("start",1,"Android 共享存储尚未就绪，请解锁手机后重试。")))
            throw new AssertionError("controller failure");
        if(RootAccess.denied(new ControlException("start",1,"cp: /x: Permission denied")))
            throw new AssertionError("controller's own permission error");
        if(RootAccess.denied(new ControlException("start",2,"Permission denied")))
            throw new AssertionError("other exit code");
        if(RootAccess.denied(new IOException("Wayland 初始化失败")))throw new AssertionError("native failure");
        if(RootAccess.denied(new IOException("Cannot run program \"/system/bin/su\": error=7, Argument list too long")))
            throw new AssertionError("other exec error");
        if(RootAccess.denied(new RuntimeException("Cannot run program \"/system/bin/su\": error=2,")))
            throw new AssertionError("not an IOException");
        if(RootAccess.provider("kernelsu")!=RootAccess.Provider.KERNELSU)throw new AssertionError();
        if(RootAccess.provider("magisk")!=RootAccess.Provider.MAGISK)throw new AssertionError();
        if(RootAccess.provider(null)!=RootAccess.Provider.UNKNOWN || RootAccess.provider("")!=RootAccess.Provider.UNKNOWN)
            throw new AssertionError();
        // The provider comes from the app-private install status that first boot publishes.
        Path status=Files.createTempFile(Paths.get(args[0]),"install-status-",".properties");
        Files.write(status,"schema=2\nrelease=r\nstate=ready\nphase=complete\nerror=none\nroot=kernelsu\n".getBytes(StandardCharsets.UTF_8));
        if(RootAccess.provider(FirstBootState.rootProvider(status.toFile()))!=RootAccess.Provider.KERNELSU)throw new AssertionError();
        Files.write(status,"schema=2\nrelease=r\nstate=ready\n".getBytes(StandardCharsets.UTF_8));
        if(!FirstBootState.rootProvider(status.toFile()).isEmpty())throw new AssertionError("older status");
        Files.delete(status);
        if(!FirstBootState.rootProvider(status.toFile()).isEmpty())throw new AssertionError("missing status");
        System.out.println("PASS hidden, denied and unrelated su failures; recorded provider");
    }
}
