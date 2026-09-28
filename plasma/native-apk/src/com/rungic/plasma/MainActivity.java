package com.rungic.plasma;

import android.app.*;
import android.content.*;
import android.os.Bundle;
import android.view.*;
import android.view.inputmethod.*;
import android.widget.*;
import android.util.Log;
import android.util.AtomicFile;
import android.graphics.Rect;
import com.winland.server.NativeBridge;
import java.io.*;
import java.util.concurrent.*;

public final class MainActivity extends Activity implements SurfaceHolder.Callback {
    private static final ExecutorService worker = Executors.newSingleThreadExecutor();
    private static volatile boolean initialized;
    private DisplayView display;
    private DisplayPacer pacer;
    private PlatformBridge platform;
    private CaptureBridge capture;
    private CodecBridge codecs;
    private CastTest castTest;
    private CastDesktop castDesktop;
    /** The assistant's screen: a 1920x1080 desktop output, on the TV or in a Linux floating window. */
    static final int[] AGENT_SCREEN_SIZE = {1920, 1080};
    private boolean agentScreen;
    /** The floating window's last report of showing the assistant's screen (docs/65). */
    private boolean agentScreenWatched = true;
    private AgentFullscreen agentFullscreen;
    private String presenterOwner;
    private CastControls castControls;
    private StartupScreen loading;
    private final java.util.concurrent.atomic.AtomicBoolean startupBusy=new java.util.concurrent.atomic.AtomicBoolean();
    private volatile int surfaceGeneration;
    private boolean awaitingFrame;
    private long frameTicket, frameDeadline;
    private int frameGeneration;
    private String notificationState="";
    private final Runnable installPoll=() -> {
        if(!isDestroyed() && this.started && display.getHolder().getSurface().isValid())
            surfaceCreated(display.getHolder());
    };
    private final Runnable framePoll=new Runnable() {
        @Override public void run() {
            if(isDestroyed() || !started || frameGeneration!=surfaceGeneration) { awaitingFrame=false; return; }
            if(NativeBridge.isPhoneFrameReady(frameTicket)) {
                awaitingFrame=false; loading.setVisibility(View.GONE); notifyState("Rungic 正在运行");
            } else if(android.os.SystemClock.uptimeMillis()>frameDeadline) {
                awaitingFrame=false; NativeBridge.cancelPhoneFrame(frameTicket);
                showProblem("桌面正在运行，但尚未确认显示画面。请重新检查显示状态。", "显示确认超时；未使用旧帧或投屏帧放行。", true);
            } else display.postDelayed(this,100);
        }
    };
    private volatile int bufferWidth = 720, bufferHeight = 1600;
    private FrameLayout frame;
    private boolean androidKeyboard;
    private volatile String displayMetrics;
    private String writtenDisplayMetrics;
    private volatile boolean accountReady;
    private volatile boolean accountPromptShowing;
    private android.window.OnBackInvokedCallback edgeBackCallback;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        if (getDisplay() != null && getDisplay().getDisplayId() != android.view.Display.DEFAULT_DISPLAY) {
            // Launched on a cast display (input focus had moved there): the desktop's
            // host window belongs on the phone; the TV gets its own window (docs/58).
            android.app.ActivityOptions options = android.app.ActivityOptions.makeBasic()
                .setLaunchDisplayId(android.view.Display.DEFAULT_DISPLAY);
            startActivity(new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), options.toBundle());
            finish();
            return;
        }
        // A change of Android's clipboard: the Linux side reads it now (HostEvents), not every second.
        getSystemService(android.content.ClipboardManager.class)
            .addPrimaryClipChangedListener(() -> HostEvents.bump(HostEvents.CLIPBOARD));
        getWindow().setDecorFitsSystemWindows(false);
        getWindow().setNavigationBarColor(android.graphics.Color.TRANSPARENT);
        getWindow().setStatusBarColor(android.graphics.Color.TRANSPARENT);
        getWindow().setNavigationBarContrastEnforced(false);
        WindowManager.LayoutParams attrs=getWindow().getAttributes();
        attrs.layoutInDisplayCutoutMode=WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS;
        getWindow().setAttributes(attrs);
        immersive();
        frame = new FrameLayout(this);
        PlatformBridge.applyOrientation(this,getPreferences(MODE_PRIVATE).getString("orientation","portrait"));
        display = new DisplayView();
        pacer = new DisplayPacer(display, () -> initialized,
                this::publishDisplayInfo, worker);
        capture = new CaptureBridge(this);
        codecs = new CodecBridge(this);
        platform = new PlatformBridge(this,capture);
        display.getHolder().addCallback(this);
        frame.addView(display, new FrameLayout.LayoutParams(-1, -1));
        loading=new StartupScreen(this,() -> {
            display.removeCallbacks(installPoll);
            if(display.getHolder().getSurface().isValid())surfaceCreated(display.getHolder());
        },() -> moveTaskToBack(true));
        loading.show("正在准备 Rungic","请稍候…",true,false,"");
        frame.addView(loading,new FrameLayout.LayoutParams(-1,-1));
        setContentView(frame);
        castTest = new CastTest(this, frame);
        castControls = new CastControls(this, frame, this::setAndroidKeyboard);
        agentScreen = getPreferences(MODE_PRIVATE).getBoolean("agent_screen", false);
        agentFullscreen = new AgentFullscreen(this, frame, AGENT_SCREEN_SIZE[0], AGENT_SCREEN_SIZE[1], new AgentFullscreen.Host() {
            @Override public void bindPresenter(String owner, android.view.Surface surface, int width, int height, int rotation) {
                MainActivity.this.bindPresenter(owner, surface, width, height, 60000, rotation);
            }
            @Override public void releasePresenter(String owner) { MainActivity.this.releasePresenter(owner); }
            @Override public void leaveFullscreen() { agentFullscreen.hide(); }
            @Override public void castToTv() {
                agentFullscreen.hide();
                // As the Plasma cast tile does (rungic-cast, docs/58): the last TV; seconds to a minute.
                new Thread(() -> {
                    try { new ProcessBuilder("su", "-c", "/data/adb/rungic-wfd/rungic-cast connect").redirectErrorStream(true).start().waitFor(); }
                    catch (Exception e) { Log.w("RungicCast", "connect failed: " + e); }
                }, "rungic-cast").start();
            }
            @Override public void closeAgentScreen() {
                try { agentScreen(new org.json.JSONObject().put("enabled", false)); }
                catch (Exception e) { Log.w("RungicWayland", "agent screen off failed: " + e); }
            }
        });
        castDesktop = new CastDesktop(this, () -> initialized, () -> agentScreen ? AGENT_SCREEN_SIZE : null, bound -> {
            castControls.setAvailable(bound);
            // The TV takes the assistant's screen from fullscreen (it bound the presenter first).
            if (bound) agentFullscreen.hide();
            castBoundAt = bound ? android.os.SystemClock.uptimeMillis() : 0;
            // The secondary home may have taken the focus before the TV got the desktop.
            if (bound) display.postDelayed(this::reclaimFocus, 400);
        });
        registerEdgeBack();
        display.setOnApplyWindowInsetsListener((v, insets) -> {
            captureDisplayInsets(insets);
            castControls.imeVisible(insets.isVisible(WindowInsets.Type.ime()));
            return insets;
        });
        display.addOnLayoutChangeListener((v,l,t,r,b,ol,ot,or_,ob) ->
            { resizeDisplay(l,t,r,b); captureDisplayInsets(display.getRootWindowInsets()); });
        display.requestApplyInsets();
        display.requestFocus();
        notifyState("正在准备 Rungic");
    }

    @Override public void onDestroy() {
        if (pacer == null) { super.onDestroy(); return; } // finished before setup (onCreate)
        if(android.os.Build.VERSION.SDK_INT>=34 && edgeBackCallback!=null)
            getOnBackInvokedDispatcher().unregisterOnBackInvokedCallback(edgeBackCallback);
        pacer.stop();
        display.removeCallbacks(installPoll);
        display.removeCallbacks(framePoll);
        if(frameTicket!=0)NativeBridge.cancelPhoneFrame(frameTicket);
        surfaceGeneration++;
        if (idleInhibitFd != null) {
            android.os.Looper.getMainLooper().getQueue().removeOnFileDescriptorEventListener(idleInhibitFd.getFileDescriptor());
            try { idleInhibitFd.close(); } catch (IOException ignored) {}
        }
        castTest.release();
        castDesktop.release();
        try { capture.close(); } catch(IOException ignored) {}
        try { codecs.close(); } catch(IOException ignored) {}
        try { platform.close(); } catch(IOException ignored) {}
        super.onDestroy();
    }

    // FLAG_KEEP_SCREEN_ON has three owners: the Linux session (keep-awake op, e.g.
    // video playback through PowerDevil), a running cast, and Wayland idle inhibition
    // (KWin inhibits on its output surface while a window does, docs/72); the flag is the union.
    static final int AWAKE_LINUX = 1, AWAKE_CAST = 2, AWAKE_WAYLAND = 4;
    private int keepAwake;
    private android.os.ParcelFileDescriptor idleInhibitFd;
    private final android.os.MessageQueue.OnFileDescriptorEventListener idleInhibitChanged = (fd, events) -> {
        try { android.system.Os.read(fd, new byte[8], 0, 8); } catch (Exception e) { }
        setKeepAwake(AWAKE_WAYLAND, NativeBridge.idleInhibited());
        return android.os.MessageQueue.OnFileDescriptorEventListener.EVENT_INPUT;
    };

    /** Follow the host's idle inhibition from now on (main thread, once the host exists). */
    private void watchIdleInhibit() {
        if (idleInhibitFd != null) return;
        try { idleInhibitFd = android.os.ParcelFileDescriptor.fromFd(NativeBridge.idleInhibitFd()); }
        catch (IOException e) { Log.e("RungicWayland", "idle inhibition not followed", e); return; }
        android.os.Looper.getMainLooper().getQueue().addOnFileDescriptorEventListener(idleInhibitFd.getFileDescriptor(),
            android.os.MessageQueue.OnFileDescriptorEventListener.EVENT_INPUT, idleInhibitChanged);
        setKeepAwake(AWAKE_WAYLAND, NativeBridge.idleInhibited());
    }

    void setKeepAwake(int source, boolean on) {
        keepAwake = on ? keepAwake | source : keepAwake & ~source;
        if (keepAwake != 0) getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }

    private boolean started, topResumed;
    private long focusReclaimWindowStart, castBoundAt;
    private int focusReclaims;
    // The vendor home takes the focus only while the cast display comes up.
    private static final long FOCUS_RECLAIM_AFTER_CAST_MS = 15000;

    // When a cast display connects, Android starts the vendor's secondary-display
    // home there and moves input focus to that display; the desktop host (still
    // visible on the phone) then loses focus, the platform bridge refuses requests
    // and phone input may go astray. Take the focus back on the phone (docs/58 step 4),
    // a few times at most so two parties never fight over it. Only right after the
    // cast display is bound: later the focus moves because the user left (home
    // gesture, recents, notifications), and pulling the app back broke going home.
    @Override public void onTopResumedActivityChanged(boolean top) {
        super.onTopResumedActivityChanged(top);
        topResumed = top;
        if (!top && castControls != null && castControls.available()) display.postDelayed(this::reclaimFocus, 400);
    }

    private void reclaimFocus() {
        if (!started || topResumed || !castControls.available()) return;
        long now = android.os.SystemClock.uptimeMillis();
        if (now - castBoundAt > FOCUS_RECLAIM_AFTER_CAST_MS) return;
        if (now - focusReclaimWindowStart > 30000) { focusReclaimWindowStart = now; focusReclaims = 0; }
        if (++focusReclaims > 3) return;
        Log.i("RungicCast", "taking input focus back from the cast display");
        startActivity(new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT),
            android.app.ActivityOptions.makeBasic().setLaunchDisplayId(android.view.Display.DEFAULT_DISPLAY).toBundle());
    }

    @Override public void onStart() {
        super.onStart();
        started = true;
        if(capture!=null)capture.setVisible(true);
        if(platform!=null)platform.desktopBoost(true);
        if(pacer!=null && display.getHolder().getSurface().isValid())pacer.start();
        if(display!=null) {
            if(awaitingFrame)display.post(framePoll);
            else if(!accountReady)display.post(installPoll);
        }
    }
    @Override public void onStop() {
        started = false;
        if(display!=null) { display.removeCallbacks(installPoll); display.removeCallbacks(framePoll); }
        if(pacer!=null)pacer.stop();
        if(capture!=null)capture.setVisible(false);
        if(platform!=null)platform.desktopBoost(false);
        super.onStop();
    }
    @Override public void onRequestPermissionsResult(int code,String[] permissions,int[] grants) {
        super.onRequestPermissionsResult(code,permissions,grants);
        if(code==CaptureBridge.PERMISSION_REQUEST && capture!=null)capture.permissionResult();
    }

    private void immersive() {
        WindowInsetsController controller=getWindow().getDecorView().getWindowInsetsController();
        if(controller!=null) {
            controller.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            controller.hide(WindowInsets.Type.systemBars());
        }
    }
    @Override public void onWindowFocusChanged(boolean focus) {
        super.onWindowFocusChanged(focus);
        if(focus) { immersive(); if(display!=null)display.requestApplyInsets(); }
        // Android lets only the focused app read the clipboard: the Linux side reads it again now.
        HostEvents.bump(HostEvents.CLIPBOARD);
    }

    // Use SurfaceView coordinates, then convert to the actual Wayland buffer.
    // System bars are transient overlays; only permanent cutouts reserve space.
    private void captureDisplayInsets(WindowInsets insets) {
        if(insets==null || display.getWidth()==0 || display.getHeight()==0)return;
        float sx=(float)bufferWidth/display.getWidth(), sy=(float)bufferHeight/display.getHeight();
        int[] location=new int[2]; display.getLocationOnScreen(location);
        Rect topCutout=new Rect();
        int safeTop=0, safeLeft=0, safeRight=0, radius=0;
        DisplayCutout cutout=insets.getDisplayCutout();
        // In landscape the camera hole can cover application content halfway
        // down an edge. Reserve that edge in the host window, keeping portrait
        // edge-to-edge and its Phosh status-bar cutout handling.
        boolean landscape=getResources().getConfiguration().orientation==android.content.res.Configuration.ORIENTATION_LANDSCAPE;
        int padLeft=landscape && cutout!=null?cutout.getSafeInsetLeft():0;
        int padRight=landscape && cutout!=null?cutout.getSafeInsetRight():0;
        if(frame.getPaddingLeft()!=padLeft || frame.getPaddingRight()!=padRight)frame.setPadding(padLeft,0,padRight,0);
        if(cutout!=null) {
            safeTop=Math.max(0,cutout.getSafeInsetTop()-location[1]);
            safeLeft=Math.max(0,cutout.getSafeInsetLeft()-location[0]);
            safeRight=Math.max(0,cutout.getSafeInsetRight()-frame.getPaddingRight());
            for(Rect bounds:cutout.getBoundingRects()) {
                Rect local=new Rect(bounds); local.offset(-location[0],-location[1]);
                if(local.intersect(0,0,display.getWidth(),display.getHeight()) && local.top<safeTop)
                    topCutout.union(local);
            }
        }
        if(android.os.Build.VERSION.SDK_INT>=31) {
            for(int position:new int[]{RoundedCorner.POSITION_TOP_LEFT,RoundedCorner.POSITION_TOP_RIGHT}) {
                RoundedCorner corner=insets.getRoundedCorner(position);
                if(corner!=null)radius=Math.max(radius,corner.getRadius());
            }
        }
        displayMetrics="[display]\nversion=1\nwidth="+bufferWidth+"\nheight="+bufferHeight+
            "\nsafe-top="+(int)Math.ceil(safeTop*sy)+
            "\nsafe-left="+(int)Math.ceil(safeLeft*sx)+
            "\nsafe-right="+(int)Math.ceil(safeRight*sx)+
            "\ncutout-left="+(int)Math.floor(topCutout.left*sx)+
            "\ncutout-right="+(int)Math.ceil(topCutout.right*sx)+
            "\ncutout-top="+(int)Math.floor(topCutout.top*sy)+
            "\ncutout-bottom="+(int)Math.ceil(topCutout.bottom*sy)+
            "\ncorner-radius="+(int)Math.ceil(radius*Math.max(sx,sy))+"\n";
        worker.execute(this::writeDisplayInsets);
    }

    private void writeDisplayInsets() {
        String metrics=displayMetrics;
        if(metrics==null || metrics.equals(writtenDisplayMetrics))return;
        File dir=new File(getFilesDir(),"tmp"); dir.mkdirs();
        AtomicFile file=new AtomicFile(new File(dir,"android-display.ini"));
        FileOutputStream stream=null;
        try {
            stream=file.startWrite();
            stream.write(metrics.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            file.finishWrite(stream); stream=null;
            android.system.Os.chmod(file.getBaseFile().getAbsolutePath(),0644);
            writtenDisplayMetrics=metrics;
            Log.i("RungicSafeArea",metrics.replace('\n',' '));
        } catch(Exception e) {
            if(stream!=null)file.failWrite(stream);
            Log.e("RungicSafeArea","Cannot publish display insets",e);
        }
    }

    @Override public void surfaceCreated(SurfaceHolder holder) {
        pacer.start();
        if(awaitingFrame || !startupBusy.compareAndSet(false,true))return;
        final int generation=surfaceGeneration;
        worker.execute(() -> {
            try {
                if (isDestroyed() || generation!=surfaceGeneration || !holder.getSurface().isValid()) return;
                FirstBootState install=FirstBootState.read(new File("/product/etc/rungic/seed.env"),
                    new File(getFilesDir(),"rungic-install.properties"));
                if(!install.ready) {
                    runOnUiThread(() -> {
                        if(isDestroyed() || generation!=surfaceGeneration)return;
                        loading.show(install.failed?"系统准备需要处理":"正在准备 Rungic",install.message,
                            !install.failed && !install.attention,true,install.details);
                        notifyState(install.failed?"Rungic 准备需要处理":"正在准备 Rungic");
                        display.removeCallbacks(installPoll);
                        if(started)display.postDelayed(installPoll,2000);
                    });
                    return;
                }
                new File(getFilesDir(), "tmp").mkdirs();
                if (!accountReady) {
                    if (accountPromptShowing) return;
                    org.json.JSONObject account=new org.json.JSONObject(control("account-status"));
                    if(account.optBoolean("pending",false)) {
                        runOnUiThread(()->{
                            if(isDestroyed() || generation!=surfaceGeneration)return;
                            showLoading("账户仍在设置中，请稍候，无需重复提交。");
                            display.removeCallbacks(installPoll);
                            if(started)display.postDelayed(installPoll,2000);
                        }); return;
                    }
                    accountReady=account.optBoolean("configured",false);
                    if (!accountReady) {
                        runOnUiThread(() -> showLoading("正在准备账户环境，请稍候…"));
                        control("account-prepare");
                        accountPromptShowing=true;
                        runOnUiThread(() -> {
                            if(isDestroyed() || generation!=surfaceGeneration) { accountPromptShowing=false; return; }
                            notifyState("Rungic 等待设置账户");
                            AccountSetup.show(this,worker,payload -> {
                                try { control("account-setup",payload); }
                                catch(Exception failure) {
                                    // A timeout may have happened after the transaction committed.
                                    // A serialized status read must finish before another form is offered.
                                    if(!new org.json.JSONObject(control("account-status")).optBoolean("configured",false))throw failure;
                                }
                            },() -> {
                                accountReady=true; accountPromptShowing=false;
                                display.post(installPoll);
                            },failure -> {
                                accountPromptShowing=false;
                                showProblem("账户设置尚未完成。请先重新检查环境与账户状态，再继续设置。", "账户操作未完成；不会自动重复提交密码。", true);
                            });
                        });
                        return;
                    }
                }
                runOnUiThread(() -> showLoading("正在启动桌面…"));
                KeyboardAssets.ensure(getApplicationContext());
                new File(getFilesDir(), "tmp").mkdirs();
                platform.start();
                capture.start();
                codecs.start();
                boolean newServer = !initialized;
                if (!initialized) {
                    boolean ok = NativeBridge.initWaylandConnection(holder.getSurface(), getApplicationContext(), "ubuntu");
                    String error = NativeBridge.getLastNativeError();
                    if (!ok || error != null) throw new IOException(error == null ? "Wayland 初始化失败" : error);
                    initialized = true;
                    NativeBridge.setInputMode(1);
                    NativeBridge.setScale(1);
                    NativeBridge.setRefreshRate(display.getDisplay().getRefreshRate());
                    runOnUiThread(this::watchIdleInhibit);
                } else NativeBridge.rebindSurface(holder.getSurface());
                NativeBridge.resumeRendering();
                // The assistant's screen first, so a TV connected before the desktop (re)started
                // presents it rather than making an output of its own.
                if (agentScreen) NativeBridge.setAgentScreen(true, AGENT_SCREEN_SIZE[0], AGENT_SCREEN_SIZE[1], 60000);
                // A TV that was connected before the desktop (re)started gets it now.
                runOnUiThread(castDesktop::refresh);
                android.system.Os.chmod(new File(getFilesDir(), "tmp").getAbsolutePath(), 0755);
                if (!NativeBridge.startGpuAllocator(new File(getFilesDir(), "tmp/rungic-gpu-alloc").getAbsolutePath())) throw new IOException("GPU 缓冲服务启动失败");
                // Container releases from before the Rungic rename connect to the old name (docs/70, until phase D).
                try { android.system.Os.symlink("rungic-gpu-alloc", new File(getFilesDir(), "tmp/moto-gpu-alloc").getAbsolutePath()); }
                catch (android.system.ErrnoException e) { if (e.errno != android.system.OsConstants.EEXIST) throw new IOException(e); }
                updateSize();
                writeDisplayInsets();
                control(newServer ? "restart-session" : "start");
                Log.i("RungicWayland", NativeBridge.getWaylandRuntimeStats());
                long ticket=NativeBridge.requestPhoneFrame();
                if(ticket==0)throw new IOException("无法请求显示状态");
                runOnUiThread(() -> {
                    if(isDestroyed() || generation!=surfaceGeneration) {
                        NativeBridge.cancelPhoneFrame(ticket); return;
                    }
                    showLoading("正在等待桌面画面…");
                    frameTicket=ticket; frameGeneration=generation;
                    frameDeadline=android.os.SystemClock.uptimeMillis()+60000;
                    awaitingFrame=true;
                    if(started)display.post(framePoll);
                });
            } catch (Throwable e) {
                Log.e("RungicWayland", "Start failed", e);
                runOnUiThread(() -> {
                    if(!isDestroyed() && generation==surfaceGeneration)
                        showProblem("暂时无法进入 Rungic。请重新检查系统准备状态。", "启动或挂载检查未完成。诊断日志包含具体原因。", true);
                });
            } finally {
                startupBusy.set(false);
                if(generation!=surfaceGeneration && !isDestroyed())runOnUiThread(()->{ if(started)display.post(installPoll); });
            }
        });
    }

    private void notifyState(String message) {
        if(!message.equals(notificationState)) { notificationState=message; DesktopService.update(this,message); }
    }
    private void showLoading(String message) {
        if(isDestroyed())return;
        loading.show("正在准备 Rungic",message,true,false,""); notifyState("正在准备 Rungic");
    }
    private void showProblem(String message,String details,boolean retry) {
        if(isDestroyed())return;
        loading.show("需要处理",message,false,retry,details); notifyState("Rungic 需要处理");
    }

    private void resizeDisplay(int l,int t,int r,int b) {
        int width=r-l,height=b-t;
        if(width<=0 || height<=0)return;
        Display.Mode physical=display.getDisplay().getMode();
        int shortEdge=getPreferences(MODE_PRIVATE).getInt("render_short_edge",Math.min(physical.getPhysicalWidth(),physical.getPhysicalHeight()));
        int w=width>height?Math.max(shortEdge,(int)Math.round(shortEdge*0.5*width/height)*2):shortEdge;
        int h=height>=width?Math.max(shortEdge,(int)Math.round(shortEdge*0.5*height/width)*2):shortEdge;
        if(w==bufferWidth && h==bufferHeight)return;
        bufferWidth=w;bufferHeight=h;
        display.getHolder().setFixedSize(w,h);
        worker.execute(this::updateSize);
        captureDisplayInsets(display.getRootWindowInsets());
        publishDisplayInfo();
    }

    org.json.JSONObject castTest(org.json.JSONObject request) throws Exception { return castTest.request(request); }
    org.json.JSONObject castDesktop(org.json.JSONObject request) throws Exception {
        if (request.optBoolean("enabled")) castTest.request(new org.json.JSONObject().put("enabled", false));
        return castDesktop.request(request);
    }
    /**
     * The assistant's screen (docs/65): {"enabled": bool} turns it on or off, {"fullscreen": bool} shows
     * it over the whole phone, {"watched": bool} is the floating window's report of showing its picture
     * (false: tucked into the edge; the screen then gets frames at a low rate). The reply says whether
     * it is on, its size, whether a TV ("tv") or the phone ("fullscreen") presents it, else the Linux
     * floating window shows it, and the watched state last reported.
     */
    org.json.JSONObject agentScreen(org.json.JSONObject request) throws Exception {
        if (request.has("enabled")) {
            agentScreen = request.getBoolean("enabled");
            // A floating window starts showing its picture; a new one reports otherwise.
            setAgentScreenWatched(true);
            if (!agentScreen) agentFullscreen.hide();
            getPreferences(MODE_PRIVATE).edit().putBoolean("agent_screen", agentScreen).apply();
            if (initialized) NativeBridge.setAgentScreen(agentScreen, AGENT_SCREEN_SIZE[0], AGENT_SCREEN_SIZE[1], 60000);
        }
        if (request.has("fullscreen")) {
            if (!request.getBoolean("fullscreen")) agentFullscreen.hide();
            else if (!agentScreen) throw new IllegalStateException("the assistant's screen is off");
            else if (castControls.available()) throw new IllegalStateException("a TV shows the assistant's screen");
            else agentFullscreen.show();
        }
        if (request.has("watched")) setAgentScreenWatched(request.getBoolean("watched"));
        return new org.json.JSONObject().put("enabled", agentScreen)
            .put("width", AGENT_SCREEN_SIZE[0]).put("height", AGENT_SCREEN_SIZE[1])
            .put("tv", castControls.available()).put("fullscreen", agentFullscreen.shown())
            .put("watched", agentScreenWatched);
    }
    private void setAgentScreenWatched(boolean watched) {
        agentScreenWatched = watched;
        NativeBridge.setAgentScreenWatched(watched);
    }

    /**
     * The host's second presenter goes to one window at a time: the TV ("tv", CastDesktop) or the
     * assistant's screen fullscreen on the phone ("fullscreen", AgentFullscreen). A window releases
     * it only while it is the one bound, so the other is never cut off.
     */
    void bindPresenter(String owner, android.view.Surface surface, int width, int height, int refreshMhz, int rotation) {
        NativeBridge.bindCastSurface(surface, width, height, refreshMhz, rotation);
        presenterOwner = owner;
        // Fullscreen covers the phone's own picture: the host paces it down (docs/65).
        NativeBridge.setPhoneCovered("fullscreen".equals(owner));
    }
    void releasePresenter(String owner) {
        if (!owner.equals(presenterOwner)) return;
        NativeBridge.releaseCastSurface();
        presenterOwner = null;
        NativeBridge.setPhoneCovered(false);
    }
    org.json.JSONObject castControls(org.json.JSONObject request) throws Exception {
        if (request.has("mode")) castControls.setMode(CastControls.Mode.valueOf(request.getString("mode").toUpperCase()));
        return castControls.status();
    }

    /** Android keyboard on the phone; its keys and text go to the focused Linux window. */
    private void setAndroidKeyboard(boolean show) {
        InputMethodManager im=(InputMethodManager)getSystemService(INPUT_METHOD_SERVICE);
        if (show) {
            androidKeyboard=true;
            display.requestFocus();
            im.restartInput(display);
            im.showSoftInput(display, InputMethodManager.SHOW_IMPLICIT);
        } else {
            getWindow().getInsetsController().hide(WindowInsets.Type.ime());
            androidKeyboard=false;
        }
    }

    org.json.JSONObject displayInfo() throws org.json.JSONException {
        Display d=display.getDisplay();
        if(d==null)throw new IllegalStateException("Display unavailable");
        Display.Mode physical=d.getMode();
        android.util.DisplayMetrics metrics=new android.util.DisplayMetrics();
        d.getRealMetrics(metrics);
        int densityDpi=metrics.densityDpi,densityWidth=metrics.widthPixels,densityHeight=metrics.heightPixels;
        if(android.os.Build.VERSION.SDK_INT>=34) {
            // Maximum bounds describe the display reference, not the current Surface or a
            // split-screen window. Get density from that same immutable metrics snapshot.
            android.view.WindowMetrics reference=getWindowManager().getMaximumWindowMetrics();
            densityDpi=Math.round(reference.getDensity()*160);
            densityWidth=reference.getBounds().width();densityHeight=reference.getBounds().height();
        }
        int width=Math.max(1,display.getWidth()),height=Math.max(1,display.getHeight());
        int nativeEdge=Math.min(physical.getPhysicalWidth(),physical.getPhysicalHeight());
        org.json.JSONArray sizes=new org.json.JSONArray();
        for(int edge:new int[]{720,nativeEdge}) {
            if(edge==720 && edge>=nativeEdge)continue;
            int w=width>height?(int)Math.round(edge*0.5*width/height)*2:edge;
            int h=height>=width?(int)Math.round(edge*0.5*height/width)*2:edge;
            sizes.put(new org.json.JSONObject().put("width",w).put("height",h));
        }
        return new org.json.JSONObject().put("version",1).put("model",android.os.Build.MODEL)
            // Keep density and its pixel reference from one Android display snapshot. The
            // Surface buffer can be 720p while Android still uses the full display density.
            .put("densityDpi",densityDpi)
            .put("densityWidthPixels",densityWidth).put("densityHeightPixels",densityHeight)
            .put("physicalWidth",physical.getPhysicalWidth()).put("physicalHeight",physical.getPhysicalHeight())
            .put("physicalWidthMM",Math.round(physical.getPhysicalWidth()*25.4f/metrics.xdpi))
            .put("physicalHeightMM",Math.round(physical.getPhysicalHeight()*25.4f/metrics.ydpi))
            .put("renderWidth",bufferWidth).put("renderHeight",bufferHeight).put("renderModes",sizes)
            .put("refreshRates",pacer.supportedRates()).put("refreshPolicy",pacer.policy())
            .put("currentRefresh",d.getRefreshRate());
    }

    org.json.JSONObject setDisplayInfo(org.json.JSONObject request) throws org.json.JSONException {
        // Validate the entire request before changing preferences or buffers.
        org.json.JSONArray sizes=displayInfo().getJSONArray("renderModes");
        int shortEdge=-1;
        if(request.has("width") || request.has("height")) {
            int width=request.getInt("width"),height=request.getInt("height");
            for(int i=0;i<sizes.length();i++) {
                org.json.JSONObject size=sizes.getJSONObject(i);
                if(size.getInt("width")==width && size.getInt("height")==height)shortEdge=Math.min(width,height);
            }
            if(shortEdge<0)throw new IllegalArgumentException("Unsupported rendering resolution");
        }
        if(request.has("refreshPolicy"))pacer.setPolicy(request.getInt("refreshPolicy"));
        if(shortEdge>0) {
            getPreferences(MODE_PRIVATE).edit().putInt("render_short_edge",shortEdge).apply();
            resizeDisplay(0,0,display.getWidth(),display.getHeight());
        }
        publishDisplayInfo();
        return displayInfo().put("ok",true);
    }

    private String writtenDisplayInfo;
    private void publishDisplayInfo() {
        if(pacer==null || display==null || display.getWidth()==0)return;
        final String value;
        try { value=displayInfo().toString(); } catch(Exception e) { return; }
        worker.execute(() -> {
            if(value.equals(writtenDisplayInfo))return;
            File dir=new File(getFilesDir(),"tmp");dir.mkdirs();
            AtomicFile file=new AtomicFile(new File(dir,"android-display.json"));
            FileOutputStream stream=null;
            try {
                stream=file.startWrite();stream.write(value.getBytes(java.nio.charset.StandardCharsets.UTF_8));
                file.finishWrite(stream);stream=null;
                android.system.Os.chmod(file.getBaseFile().getAbsolutePath(),0644);
                writtenDisplayInfo=value;
            } catch(Exception e) { if(stream!=null)file.failWrite(stream);Log.w("RungicDisplay","Cannot publish modes",e); }
        });
    }
    private void updateSize() {
        if (initialized) {
            int w=bufferWidth,h=bufferHeight;
            NativeBridge.setResolution(w,h);
            NativeBridge.onSurfaceChanged(w,h,w>h?151:68,w>h?68:151);
        }
    }
    @Override public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) { worker.execute(this::updateSize); }
    @Override public void surfaceDestroyed(SurfaceHolder holder) {
        surfaceGeneration++; awaitingFrame=false; display.removeCallbacks(framePoll);
        if(frameTicket!=0)NativeBridge.cancelPhoneFrame(frameTicket);
        pacer.stop(); worker.execute(() -> { if(initialized)NativeBridge.suspendRendering(); });
    }

    private static String control(String action) throws Exception {
        return control(action,null);
    }

    private static String control(String action, String payload) throws Exception {
        ProcessBuilder b = new ProcessBuilder("/product/bin/su", "--mount-master", "-c", "/data/adb/rungic-plasma/rungic-plasma " + action);
        b.environment().put("PATH", "/product/bin:/system/bin:/system/xbin:/vendor/bin");
        b.environment().remove("LD_PRELOAD"); b.environment().remove("LD_LIBRARY_PATH");
        Process p = b.redirectErrorStream(true).start();
        try (OutputStream input=p.getOutputStream()) {
            if(payload!=null) input.write(payload.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        }
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        Thread reader = new Thread(() -> { try (InputStream in = p.getInputStream()) {
            byte[] data = new byte[4096]; int n; while ((n = in.read(data)) != -1) if (out.size() < 16384) out.write(data,0,n);
        } catch (IOException ignored) {} }); reader.start();
        if (!p.waitFor(action.equals("account-prepare")?240:90, TimeUnit.SECONDS)) {
            p.destroy(); throw new IOException("系统准备超时，请稍后重试并检查安装状态"); }
        reader.join(2000);
        if (p.exitValue() != 0) throw new IOException(out.toString("UTF-8"));
        return out.toString("UTF-8");
    }

    @Override public void onBackPressed() {
        WindowInsets insets=display.getRootWindowInsets();
        if(insets!=null && insets.isVisible(WindowInsets.Type.ime())) {
            getWindow().getInsetsController().hide(WindowInsets.Type.ime());
            androidKeyboard=false;
            return;
        }
        worker.execute(() -> {
            boolean hidden=false;
            try { hidden=control("hide-keyboard").contains("hidden"); }
            catch(Exception e) { Log.w("RungicWayland","Keyboard state unavailable",e); }
            if(!hidden)runOnUiThread(this::showDesktopMenu);
        });
    }

    private void registerEdgeBack() {
        if(android.os.Build.VERSION.SDK_INT<34) return;
        edgeBackCallback=new android.window.OnBackAnimationCallback() {
            private int edge=android.window.BackEvent.EDGE_LEFT;
            @Override public void onBackStarted(android.window.BackEvent event) {edge=event.getSwipeEdge();}
            @Override public void onBackProgressed(android.window.BackEvent event) {}
            @Override public void onBackCancelled() {edge=android.window.BackEvent.EDGE_LEFT;}
            @Override public void onBackInvoked() {
                boolean right=edge==android.window.BackEvent.EDGE_RIGHT;
                edge=android.window.BackEvent.EDGE_LEFT;
                if(accountPromptShowing) return;
                if(right) backInLinux(); else showDesktopMenu();
            }
        };
        getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
            android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT,edgeBackCallback);
    }

    private void backInLinux() {
        WindowInsets insets=display.getRootWindowInsets();
        if(insets!=null && insets.isVisible(WindowInsets.Type.ime())) {
            getWindow().getInsetsController().hide(WindowInsets.Type.ime());
            androidKeyboard=false;
            return;
        }
        worker.execute(() -> {
            try {
                if(control("hide-keyboard").contains("hidden")) return;
                if(!initialized) return;
                // KDE StandardKey.Back and GTK/browser history both use Alt+Left.
                // The focused application decides whether it can navigate back.
                NativeBridge.sendKeyEvent(KeyEvent.KEYCODE_ALT_LEFT,true);
                try {
                    NativeBridge.sendKeyEvent(KeyEvent.KEYCODE_DPAD_LEFT,true);
                    NativeBridge.sendKeyEvent(KeyEvent.KEYCODE_DPAD_LEFT,false);
                } finally { NativeBridge.sendKeyEvent(KeyEvent.KEYCODE_ALT_LEFT,false); }
            } catch(Exception e) {
                runOnUiThread(() -> Toast.makeText(this,"暂时无法向桌面发送返回操作",Toast.LENGTH_SHORT).show());
            }
        });
    }

    private void showDesktopMenu() {
        new AlertDialog.Builder(this).setTitle("Rungic").setItems(new String[]{"继续使用", "回到 Rungic 桌面", "Android 键盘", "切换到 Android（会话继续运行）", "麦克风与相机权限", "关闭 Rungic 会话", "显示流畅度"}, (d, i) -> {
            if (i == 1 && initialized) worker.execute(() -> {
                try { control("home"); }
                catch (Exception e) { runOnUiThread(() -> Toast.makeText(this, e.getMessage(), Toast.LENGTH_LONG).show()); }
            });
            if (i == 2) setAndroidKeyboard(true);
            if (i == 3) moveTaskToBack(true);
            if (i == 4) capture.requestPermissionsFromUser();
            if (i == 5) new AlertDialog.Builder(this).setTitle("关闭 Rungic 会话？")
                .setMessage("这会结束正在运行的 Linux 应用，请先保存文件。切换到 Android 可以让会话继续运行。")
                .setNegativeButton("取消",null).setPositiveButton("关闭会话",(dialog,which)->worker.execute(() -> { try { control("stop"); NativeBridge.releaseWaylandConnection(); initialized=false;
                runOnUiThread(() -> { stopService(new Intent(this, DesktopService.class)); finish(); });
            } catch(Exception e) { runOnUiThread(() -> Toast.makeText(this, "暂时无法关闭会话，请稍后重试", Toast.LENGTH_LONG).show()); } })).show();
            if(i==6) {
                org.json.JSONArray rates=pacer.supportedRates();
                String[] labels=new String[rates.length()+1];labels[0]="自动";
                int checked=0;
                for(int n=0;n<rates.length();n++) {
                    labels[n+1]=rates.optInt(n)+" Hz";
                    if(rates.optInt(n)==pacer.policy())checked=n+1;
                }
                new AlertDialog.Builder(this).setTitle("刷新率")
                    .setSingleChoiceItems(labels,checked,(choice,which)->{
                        pacer.setPolicy(which==0?0:rates.optInt(which-1));choice.dismiss();
                    }).setNegativeButton("取消",null).show();
            }
        }).show();
    }

    private final class DisplayView extends SurfaceView {
        DisplayView() { super(MainActivity.this); setFocusable(true); setFocusableInTouchMode(true); getHolder().setFixedSize(720,1600); }
        @Override public boolean onTouchEvent(android.view.MotionEvent e) {
            if (!initialized) return true;
            pacer.touch();
            int action=e.getActionMasked(), index=e.getActionIndex();
            if (action==MotionEvent.ACTION_MOVE || action==MotionEvent.ACTION_CANCEL) {
                for(int i=0;i<e.getPointerCount();i++) send(e,action,i);
            } else send(e,action,index);
            return true;
        }
        private void send(MotionEvent e, int action, int i) {
            NativeBridge.sendTouchEvent(action,e.getPointerId(i),e.getX(i)*bufferWidth/getWidth(),e.getY(i)*bufferHeight/getHeight());
        }
        @Override public boolean onCheckIsTextEditor() { return androidKeyboard; }
        @Override public InputConnection onCreateInputConnection(EditorInfo info) {
            info.inputType=android.text.InputType.TYPE_CLASS_TEXT; info.imeOptions=EditorInfo.IME_FLAG_NO_EXTRACT_UI;
            return new BaseInputConnection(this,false) {
                @Override public boolean commitText(CharSequence text,int cursor) { if(initialized)NativeBridge.sendTextInput(text.toString()); return true; }
                @Override public boolean deleteSurroundingText(int before,int after) { for(int i=0;i<before;i++)key(KeyEvent.KEYCODE_DEL); return true; }
                @Override public boolean sendKeyEvent(KeyEvent event) { if(initialized)NativeBridge.sendKeyEvent(event.getKeyCode(),event.getAction()==KeyEvent.ACTION_DOWN); return true; }
            };
        }
        private void key(int k) { if(initialized) { NativeBridge.sendKeyEvent(k,true); NativeBridge.sendKeyEvent(k,false); } }
        @Override public boolean onKeyDown(int k,KeyEvent e) { if(k==KeyEvent.KEYCODE_BACK || k==KeyEvent.KEYCODE_VOLUME_UP || k==KeyEvent.KEYCODE_VOLUME_DOWN)return super.onKeyDown(k,e); if(initialized)NativeBridge.sendKeyEvent(k,true); return true; }
        @Override public boolean onKeyUp(int k,KeyEvent e) { if(k==KeyEvent.KEYCODE_BACK || k==KeyEvent.KEYCODE_VOLUME_UP || k==KeyEvent.KEYCODE_VOLUME_DOWN)return super.onKeyUp(k,e); if(initialized)NativeBridge.sendKeyEvent(k,false); return true; }
    }
}
