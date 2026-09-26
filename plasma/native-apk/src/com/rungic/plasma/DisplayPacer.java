package com.rungic.plasma;

import android.app.Activity;
import android.hardware.display.DisplayManager;
import android.os.Handler;
import android.os.Looper;
import android.os.MessageQueue;
import android.os.ParcelFileDescriptor;
import android.os.SystemClock;
import android.view.Choreographer;
import android.view.Display;
import android.view.Surface;
import android.view.SurfaceView;
import android.util.AtomicFile;
import android.util.Log;
import com.winland.server.NativeBridge;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.concurrent.Executor;
import java.util.function.BooleanSupplier;
import java.util.TreeSet;
import org.json.JSONArray;

/** Follows Android vsync with a foreground smoothness or adaptive preference. */
final class DisplayPacer implements Choreographer.FrameCallback, DisplayManager.DisplayListener {
    private final SurfaceView view;
    private final DisplayManager manager;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final BooleanSupplier ready;
    private final Activity activity;
    private final Runnable changed;
    private final Executor worker;
    private final File status;
    private boolean running, parked;
    private ParcelFileDescriptor wakeFd;
    // On-demand vsync: the compositor signals this eventfd when it leaves the
    // parked state; callbacks resume from the next vsync.
    private final MessageQueue.OnFileDescriptorEventListener wake = (fd, events) -> {
        try { android.system.Os.read(fd, new byte[8], 0, 8); } catch(Exception e) { }
        resume();
        return MessageQueue.OnFileDescriptorEventListener.EVENT_INPUT;
    };
    private float requested = -1, current = 60, maximum = 60, minimum = 60;
    private float nativeRate = -1;
    private long sampledAt, sampledFrames, lastTouch, lastBusy;
    private final Runnable release = this::updateRequest;

    DisplayPacer(SurfaceView view, BooleanSupplier ready, Runnable changed, Executor worker) {
        this.view=view; this.ready=ready; this.changed=changed; this.worker=worker;
        activity=(Activity)view.getContext();
        manager=view.getContext().getSystemService(DisplayManager.class);
        status=new File(view.getContext().getFilesDir(),"tmp/android-refresh.ini");
    }
    void start() {
        if(running)return;
        running=true;
        manager.registerDisplayListener(this,handler);
        updateDisplay();
        nativeRate=-1;
        updateRequest();
        sampledAt=SystemClock.elapsedRealtime();
        sampledFrames=ready.getAsBoolean()?NativeBridge.getPresentedFrames():0;
        try {
            if(wakeFd==null)wakeFd=ParcelFileDescriptor.fromFd(NativeBridge.vsyncWakeFd());
            Looper.getMainLooper().getQueue().addOnFileDescriptorEventListener(wakeFd.getFileDescriptor(),
                MessageQueue.OnFileDescriptorEventListener.EVENT_INPUT,wake);
        } catch(Exception e) { Log.w("RungicRefresh","On-demand vsync unavailable",e); }
        parked=false;
        Choreographer.getInstance().postFrameCallback(this);
    }
    private void resume() {
        if(!running || !parked)return;
        parked=false;
        Choreographer.getInstance().postFrameCallback(this);
    }
    void stop() {
        if(!running)return;
        running=false;
        handler.removeCallbacks(release);
        requestRate(0);
        manager.unregisterDisplayListener(this);
        if(wakeFd!=null)Looper.getMainLooper().getQueue().removeOnFileDescriptorEventListener(wakeFd.getFileDescriptor());
        Choreographer.getInstance().removeFrameCallback(this);
    }
    void touch() {
        if(!running)return;
        lastTouch=SystemClock.elapsedRealtime();
        requestRate(policy()==0?maximum:policy());
        handler.removeCallbacks(release);
        handler.postDelayed(release,2000);
    }
    private void updateRequest() {
        long now=SystemClock.elapsedRealtime();
        // A nested compositor needs headroom above a 30fps video's cadence.
        // Keep 60Hz while frames are changing; release again on a static screen.
        int fixed=policy();
        requestRate(fixed>0?fixed:now-lastTouch<2000?maximum:now-lastBusy<2500?Math.min(60,maximum):0);
    }
    int policy() {
        return activity.getPreferences(Activity.MODE_PRIVATE).getInt("refresh_rate",
            activity.getPreferences(Activity.MODE_PRIVATE).getBoolean("smooth_display",true)?Math.round(maximum):0);
    }
    JSONArray supportedRates() {
        TreeSet<Integer> rates=new TreeSet<>();
        Display display=view.getDisplay();
        if(display!=null) {
            Display.Mode active=display.getMode();
            for(Display.Mode mode:display.getSupportedModes())
                if(mode.getPhysicalWidth()==active.getPhysicalWidth() && mode.getPhysicalHeight()==active.getPhysicalHeight())
                    rates.add(Math.round(mode.getRefreshRate()));
        }
        JSONArray values=new JSONArray();
        for(int rate:rates)values.put(rate);
        return values;
    }
    void setPolicy(int rate) {
        boolean supported=rate==0;
        JSONArray rates=supportedRates();
        for(int i=0;i<rates.length();i++)if(rates.optInt(i)==rate)supported=true;
        if(!supported)throw new IllegalArgumentException("Unsupported refresh rate");
        activity.getPreferences(Activity.MODE_PRIVATE).edit().putInt("refresh_rate",rate).apply();
        if(running)updateRequest();
        changed.run();
    }
    private void requestRate(float rate) {
        Surface surface=view.getHolder().getSurface();
        if(requested==rate)return;
        if(surface.isValid())
            surface.setFrameRate(rate,Surface.FRAME_RATE_COMPATIBILITY_DEFAULT,Surface.CHANGE_FRAME_RATE_ONLY_IF_SEAMLESS);
        else if(rate>0)return;
        // Match the activity and SurfaceView votes. A surface-only vote can
        // alternate with the vendor's 90Hz high-frame-rate category.
        android.view.WindowManager.LayoutParams attrs=activity.getWindow().getAttributes();
        int modeId=0;
        Display display=view.getDisplay();
        if(rate>0 && display!=null) {
            Display.Mode active=display.getMode();
            for(Display.Mode mode:display.getSupportedModes()) {
                if(mode.getPhysicalWidth()==active.getPhysicalWidth() && mode.getPhysicalHeight()==active.getPhysicalHeight()
                        && Math.abs(mode.getRefreshRate()-rate)<0.1f) { modeId=mode.getModeId(); break; }
            }
        }
        if(attrs.preferredDisplayModeId!=modeId) {
            attrs.preferredDisplayModeId=modeId;
            activity.getWindow().setAttributes(attrs);
        }
        if(android.os.Build.VERSION.SDK_INT>=35) {
            view.setRequestedFrameRate(rate);
            view.getRootView().setRequestedFrameRate(rate);
            view.invalidate();
        }
        requested=rate;
    }
    private void updateDisplay() {
        Display display=view.getDisplay();
        if(display==null)return;
        float previous=current;
        current=display.getRefreshRate();
        Display.Mode active=display.getMode();
        minimum=maximum=current;
        for(Display.Mode m:display.getSupportedModes()) {
            if(m.getPhysicalWidth()==active.getPhysicalWidth() && m.getPhysicalHeight()==active.getPhysicalHeight()) {
                minimum=Math.min(minimum,m.getRefreshRate());
                maximum=Math.max(maximum,m.getRefreshRate());
            }
        }
        syncNativeRate();
        if(Math.abs(previous-current)>0.1f)
            Log.i("RungicRefresh","actual="+current+" supported="+minimum+".."+maximum);
        changed.run();
    }
    private void syncNativeRate() {
        if(ready.getAsBoolean() && Math.abs(nativeRate-current)>0.1f) {
            NativeBridge.setRefreshRate(current);
            nativeRate=current;
        }
    }
    @Override public void doFrame(long timeNanos) {
        if(!running)return;
        if(ready.getAsBoolean()) {
            syncNativeRate();
            NativeBridge.frameTick(timeNanos);
            long now=SystemClock.elapsedRealtime();
            if(now-sampledAt>=1000) {
                long frames=NativeBridge.getPresentedFrames();
                double fps=(frames-sampledFrames)*1000.0/(now-sampledAt);
                if(fps>=8)lastBusy=now;
                updateRequest();
                final String value=String.format(Locale.ROOT,
                    "[refresh]\nandroid-reported-hz=%.3f\nmaximum-hz=%.3f\nminimum-hz=%.3f\nrequested-hz=%.3f\nsubmitted-fps=%.2f\nframes=%d\nsampled-uptime-ms=%d\n",
                    current,maximum,minimum,requested,fps,frames,now);
                worker.execute(() -> publish(value));
                sampledAt=now;sampledFrames=frames;
            }
            if(!NativeBridge.wantsVsync()) {
                // Static desktop: stop waking every vsync until the compositor
                // signals the wake fd. Re-evaluate the frame-rate vote once the
                // busy window has passed, as the per-second sampling would have.
                parked=true;
                handler.removeCallbacks(release);
                handler.postDelayed(release,2600);
                return;
            }
        }
        Choreographer.getInstance().postFrameCallback(this);
    }
    private void publish(String text) {
        AtomicFile file=new AtomicFile(status);
        FileOutputStream stream=null;
        try {
            stream=file.startWrite();stream.write(text.getBytes(StandardCharsets.UTF_8));file.finishWrite(stream);stream=null;
            android.system.Os.chmod(status.getAbsolutePath(),0644);
        } catch(Exception e) { if(stream!=null)file.failWrite(stream);Log.w("RungicRefresh","Writing status failed",e); }
    }
    @Override public void onDisplayChanged(int id) { if(view.getDisplay()!=null && id==view.getDisplay().getDisplayId())updateDisplay(); }
    @Override public void onDisplayAdded(int id) {}
    @Override public void onDisplayRemoved(int id) {}
}
