package dev.moto.plasma;

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
    private CastControls castControls;
    private TextView status;
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
        status = new TextView(this);
        status.setText("正在准备 Plasma Mobile…"); status.setTextSize(18); status.setGravity(Gravity.CENTER);
        status.setOnClickListener(v -> { if(display.getHolder().getSurface().isValid())surfaceCreated(display.getHolder()); });
        frame.addView(status, new FrameLayout.LayoutParams(-1, -1));
        setContentView(frame);
        castTest = new CastTest(this, frame);
        castControls = new CastControls(this, frame, this::setAndroidKeyboard);
        castDesktop = new CastDesktop(this, () -> initialized, castControls::setAvailable);
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
        startForegroundService(new Intent(this, DesktopService.class));
    }

    @Override public void onDestroy() {
        if (pacer == null) { super.onDestroy(); return; } // finished before setup (onCreate)
        if(android.os.Build.VERSION.SDK_INT>=34 && edgeBackCallback!=null)
            getOnBackInvokedDispatcher().unregisterOnBackInvokedCallback(edgeBackCallback);
        pacer.stop();
        castTest.release();
        castDesktop.release();
        try { capture.close(); } catch(IOException ignored) {}
        try { codecs.close(); } catch(IOException ignored) {}
        try { platform.close(); } catch(IOException ignored) {}
        super.onDestroy();
    }

    @Override public void onStart() {
        super.onStart();
        if(capture!=null)capture.setVisible(true);
        if(pacer!=null && display.getHolder().getSurface().isValid())pacer.start();
    }
    @Override public void onStop() {
        if(pacer!=null)pacer.stop();
        if(capture!=null)capture.setVisible(false);
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
            Log.i("MotoSafeArea",metrics.replace('\n',' '));
        } catch(Exception e) {
            if(stream!=null)file.failWrite(stream);
            Log.e("MotoSafeArea","Cannot publish display insets",e);
        }
    }

    @Override public void surfaceCreated(SurfaceHolder holder) {
        pacer.start();
        worker.execute(() -> {
            try {
                if (!holder.getSurface().isValid()) return;
                new File(getFilesDir(), "tmp").mkdirs();
                if (!accountReady) {
                    if (accountPromptShowing) return;
                    org.json.JSONObject account=new org.json.JSONObject(control("account-status"));
                    accountReady=account.optBoolean("configured",false);
                    if (!accountReady) {
                        accountPromptShowing=true;
                        runOnUiThread(() -> AccountSetup.show(this,worker,
                            payload -> control("account-setup",payload), () -> {
                                accountReady=true;
                                accountPromptShowing=false;
                                if(display.getHolder().getSurface().isValid()) surfaceCreated(display.getHolder());
                            }));
                        return;
                    }
                }
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
                } else NativeBridge.rebindSurface(holder.getSurface());
                NativeBridge.resumeRendering();
                android.system.Os.chmod(new File(getFilesDir(), "tmp").getAbsolutePath(), 0755);
                if (!NativeBridge.startGpuAllocator(new File(getFilesDir(), "tmp/moto-gpu-alloc").getAbsolutePath())) throw new IOException("GPU 缓冲服务启动失败");
                updateSize();
                writeDisplayInsets();
                control(newServer ? "restart-session" : "start");
                Log.i("MotoWayland", NativeBridge.getWaylandRuntimeStats());
                runOnUiThread(() -> status.setVisibility(View.GONE));
            } catch (Throwable e) {
                Log.e("MotoWayland", "Start failed", e);
                runOnUiThread(() -> { status.setVisibility(View.VISIBLE); status.setText("Plasma Mobile启动失败\n" + e.getMessage() + "\n\n点此重试"); });
            }
        });
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
            } catch(Exception e) { if(stream!=null)file.failWrite(stream);Log.w("MotoDisplay","Cannot publish modes",e); }
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
    @Override public void surfaceDestroyed(SurfaceHolder holder) { pacer.stop(); worker.execute(() -> { if (initialized) NativeBridge.suspendRendering(); }); }

    private static String control(String action) throws Exception {
        return control(action,null);
    }

    private static String control(String action, String payload) throws Exception {
        ProcessBuilder b = new ProcessBuilder("/product/bin/su", "--mount-master", "-c", "/data/adb/moto-plasma/moto-plasma " + action);
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
        if (!p.waitFor(90, TimeUnit.SECONDS)) { p.destroy(); throw new IOException("启动超时，请检查 Magisk 授权"); }
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
            catch(Exception e) { Log.w("MotoWayland","Keyboard state unavailable",e); }
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
        new AlertDialog.Builder(this).setTitle("Plasma Mobile").setItems(new String[]{"继续使用", "返回 Linux 桌面", "Android 键盘", "返回 Android", "麦克风与相机权限", "停止 Plasma Mobile", "显示流畅度"}, (d, i) -> {
            if (i == 1 && initialized) worker.execute(() -> {
                try { control("home"); }
                catch (Exception e) { runOnUiThread(() -> Toast.makeText(this, e.getMessage(), Toast.LENGTH_LONG).show()); }
            });
            if (i == 2) setAndroidKeyboard(true);
            if (i == 3) moveTaskToBack(true);
            if (i == 4) capture.requestPermissionsFromUser();
            if (i == 5) worker.execute(() -> { try { control("stop"); NativeBridge.releaseWaylandConnection(); initialized=false;
                runOnUiThread(() -> { stopService(new Intent(this, DesktopService.class)); finish(); });
            } catch(Exception e) { runOnUiThread(() -> Toast.makeText(this, e.getMessage(), Toast.LENGTH_LONG).show()); } });
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
