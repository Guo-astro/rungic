package dev.moto.plasma;

import android.Manifest;
import android.app.Activity;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.ImageFormat;
import android.hardware.camera2.*;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.*;
import android.net.*;
import android.os.*;
import android.util.Range;
import android.util.Size;
import org.json.*;
import java.io.*;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/** Private, demand-driven capture using ordinary Android camera/mic permissions. */
final class CaptureBridge implements Closeable {
    static final int PERMISSION_REQUEST=9041;
    private final Activity activity;
    private final File path;
    private final CameraManager cameras;
    private final ExecutorService clients=Executors.newFixedThreadPool(4);
    private final Set<LocalSocket> sockets=ConcurrentHashMap.newKeySet();
    private final Semaphore slots=new Semaphore(4);
    private final AtomicBoolean microphoneBusy=new AtomicBoolean();
    private final AtomicBoolean cameraBusy=new AtomicBoolean();
    private final AtomicBoolean phoneOutputBusy=new AtomicBoolean();
    private final Object permissionLock=new Object();
    private volatile CountDownLatch permissionResult;
    private volatile boolean visible, running;
    private boolean micActive, cameraActive;
    private LocalSocket bound;
    private LocalServerSocket server;

    CaptureBridge(Activity activity) {
        this.activity=activity;path=new File(activity.getFilesDir(),"tmp/capture.sock");
        cameras=activity.getSystemService(CameraManager.class);
    }
    void setVisible(boolean value) {
        visible=value;
        if(!value) {
            for(LocalSocket socket:sockets)try { socket.close(); } catch(IOException ignored) {}
            CountDownLatch latch=permissionResult;if(latch!=null)latch.countDown();
        }
    }
    void permissionResult() { CountDownLatch latch=permissionResult;if(latch!=null)latch.countDown(); }
    void requestPermissionsFromUser() {
        activity.getPreferences(Activity.MODE_PRIVATE).edit().remove("denied-camera").remove("denied-microphone").apply();
        ArrayList<String> required=new ArrayList<>();
        for(String permission:new String[]{Manifest.permission.CAMERA,Manifest.permission.RECORD_AUDIO})
            if(activity.checkSelfPermission(permission)!=PackageManager.PERMISSION_GRANTED)required.add(permission);
        if(!required.isEmpty())activity.requestPermissions(required.toArray(new String[0]),PERMISSION_REQUEST);
        else android.widget.Toast.makeText(activity,"麦克风和相机权限已开启",android.widget.Toast.LENGTH_SHORT).show();
    }
    private void ensurePermission(String permission) throws Exception {
        synchronized(permissionLock) {
            if(!visible)throw new IOException("请先返回 Plasma Mobile");
            if(activity.checkSelfPermission(permission)==PackageManager.PERMISSION_GRANTED)return;
            String key=permission.equals(Manifest.permission.CAMERA)?"denied-camera":"denied-microphone";
            if(activity.getPreferences(Activity.MODE_PRIVATE).getBoolean(key,false))throw new SecurityException("请在 Plasma Mobile菜单中开启麦克风与相机权限");
            CountDownLatch latch=new CountDownLatch(1);permissionResult=latch;
            activity.runOnUiThread(() -> activity.requestPermissions(new String[]{permission},PERMISSION_REQUEST));
            try { latch.await(45,TimeUnit.SECONDS); } finally { permissionResult=null; }
            if(!visible)throw new IOException("采集已暂停，请返回 Plasma Mobile");
            if(activity.checkSelfPermission(permission)!=PackageManager.PERMISSION_GRANTED) {
                activity.getPreferences(Activity.MODE_PRIVATE).edit().putBoolean(key,true).apply();
                throw new SecurityException("采集权限未授予");
            }
        }
    }
    private void captureState(boolean mic,boolean active) throws Exception {
        FutureTask<Void> change=new FutureTask<>(() -> {
            if(active && !visible)throw new IOException("请先返回 Plasma Mobile");
            if(mic)micActive=active;else cameraActive=active;
            if(micActive || cameraActive) {
                Intent intent=new Intent(activity,CaptureService.class).putExtra("microphone",micActive).putExtra("camera",cameraActive);
                activity.startForegroundService(intent);
            } else activity.stopService(new Intent(activity,CaptureService.class));
            return null;
        });activity.runOnUiThread(change);change.get(2,TimeUnit.SECONDS);
    }
    JSONObject info() throws Exception {
        JSONArray list=new JSONArray();
        for(String id:cameras.getCameraIdList()) {
            CameraCharacteristics c=cameras.getCameraCharacteristics(id);
            Integer facing=c.get(CameraCharacteristics.LENS_FACING),orientation=c.get(CameraCharacteristics.SENSOR_ORIENTATION);
            if(facing==null || (facing!=CameraCharacteristics.LENS_FACING_FRONT && facing!=CameraCharacteristics.LENS_FACING_BACK))continue;
            // Export one logical front and one logical rear device, not each
            // physical lens of the same logical multi-camera.
            String name=facing==CameraCharacteristics.LENS_FACING_FRONT?"front":"back";
            boolean duplicate=false;for(int i=0;i<list.length();i++)if(list.getJSONObject(i).getString("facing").equals(name))duplicate=true;
            if(duplicate)continue;
            StreamConfigurationMap map=c.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
            Size size=chooseSize(map==null?null:map.getOutputSizes(ImageFormat.YUV_420_888));
            if(size==null)continue;
            list.put(new JSONObject().put("id",id).put("facing",name).put("width",size.getWidth()).put("height",size.getHeight())
                .put("rotation",orientation==null?0:orientation).put("fps",30));
        }
        return new JSONObject().put("version",1).put("visible",visible).put("microphonePermission",activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED)
            .put("cameraPermission",activity.checkSelfPermission(Manifest.permission.CAMERA)==PackageManager.PERMISSION_GRANTED)
            .put("cameraDenied",activity.getPreferences(Activity.MODE_PRIVATE).getBoolean("denied-camera",false))
            .put("microphoneDenied",activity.getPreferences(Activity.MODE_PRIVATE).getBoolean("denied-microphone",false)).put("cameras",list);
    }
    private static Size chooseSize(Size[] sizes) {
        if(sizes==null)return null;
        Size best=null;double score=Double.MAX_VALUE;
        for(Size size:sizes) {
            int w=size.getWidth(),h=size.getHeight();
            if(w<320 || h<240 || w>1920 || h>1080 || (w%2)!=0 || (h%2)!=0)continue;
            double value=Math.abs(Math.log((double)(w*h)/(1280*720)))+2*Math.abs((double)w/h-16.0/9);
            if(value<score) { score=value;best=size; }
        }
        return best;
    }
    synchronized void start() throws IOException {
        if(running)return;
        path.delete();bound=new LocalSocket();
        bound.bind(new LocalSocketAddress(path.getAbsolutePath(),LocalSocketAddress.Namespace.FILESYSTEM));
        server=new LocalServerSocket(bound.getFileDescriptor());
        try { android.system.Os.chmod(path.getAbsolutePath(),0666); } catch(Exception e) { throw new IOException(e); }
        running=true;
        Thread acceptor=new Thread(() -> {
            while(running)try {
                LocalSocket socket=server.accept();int uid=socket.getPeerCredentials().getUid();
                if((uid!=1000 && uid!=0) || !slots.tryAcquire()) { socket.close();continue; }
                sockets.add(socket);
                clients.execute(() -> { try(LocalSocket client=socket) { serve(client); }
                    catch(Exception ignored) {} finally { sockets.remove(socket);slots.release(); } });
            } catch(Exception ignored) {}
        },"moto-capture-accept");acceptor.setDaemon(true);acceptor.start();
    }
    private static void json(OutputStream out,JSONObject value) throws Exception {
        out.write((value.toString()+"\n").getBytes(StandardCharsets.UTF_8));out.flush();
    }
    private void serve(LocalSocket socket) throws Exception {
        socket.setSoTimeout(3000);
        socket.setSendBufferSize(131072);
        android.system.Os.setsockoptTimeval(socket.getFileDescriptor(),android.system.OsConstants.SOL_SOCKET,
            android.system.OsConstants.SO_SNDTIMEO,android.system.StructTimeval.fromMillis(1500));
        ByteArrayOutputStream line=new ByteArrayOutputStream();int b;
        while((b=socket.getInputStream().read())!=-1 && b!='\n') { if(line.size()>4096)throw new IOException("Request too large");line.write(b); }
        JSONObject request=new JSONObject(line.toString("UTF-8"));
        try {
            String op=request.getString("op");
            // Playback follows the Linux sink, like the Termux output; only capture needs the app in front.
            if(!visible && !op.equals("phone-output"))throw new IOException("请先返回 Plasma Mobile");
            switch(op) {
                case "microphone": microphone(socket);break;
                case "camera":camera(socket,request.getString("id"));break;
                case "phone-output":phoneOutput(socket);break;
                default:throw new IOException("Unsupported capture operation");
            }
        } catch(Exception e) {
            // After stream headers, closing the socket signals failure/EOS;
            // never inject error text into PCM or video payloads.
            throw e;
        }
    }
    // The audio threads forward small blocks: at normal priority, a busy phone (a call, the
    // compositor in this process) starved them and the phone heard a call in pieces (docs/63).
    private static void audioPriority() {
        try { android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_URGENT_AUDIO); } catch(Exception ignored) {}
    }
    private void microphone(LocalSocket socket) throws Exception {
        audioPriority();
        if(!microphoneBusy.compareAndSet(false,true))throw new IOException("麦克风正在使用中");
        AudioRecord recorder=null;boolean active=false,header=false;
        try {
            ensurePermission(Manifest.permission.RECORD_AUDIO);
            int min=AudioRecord.getMinBufferSize(48000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT);
            if(min<0)throw new IOException("Unsupported microphone format");
            recorder=new AudioRecord.Builder().setAudioSource(MediaRecorder.AudioSource.MIC)
                .setAudioFormat(new AudioFormat.Builder().setSampleRate(48000).setChannelMask(AudioFormat.CHANNEL_IN_MONO).setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                .setBufferSizeInBytes(Math.max(min,9600)).build();
            if(recorder.getState()!=AudioRecord.STATE_INITIALIZED)throw new IOException("Microphone unavailable");
            captureState(true,true);active=true;recorder.startRecording();
            json(socket.getOutputStream(),new JSONObject().put("ok",true).put("rate",48000).put("channels",1).put("format","s16le"));header=true;
            byte[] block=new byte[1920];
            while(running && visible) {
                int count=recorder.read(block,0,block.length,AudioRecord.READ_BLOCKING);
                if(count<=0)throw new IOException("Microphone read failed");
                socket.getOutputStream().write(block,0,count);
            }
        } catch(Exception e) { if(!header)json(socket.getOutputStream(),new JSONObject().put("error",e.getMessage()==null?"Microphone unavailable":e.getMessage())); }
        finally {
            android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_DEFAULT);   // a pool thread: others use it next
            if(recorder!=null) { try { recorder.stop(); } catch(Exception ignored) {}recorder.release(); }
            if(active)try { captureState(true,false); } catch(Exception ignored) {}
            microphoneBusy.set(false);
        }
    }
    /** The phone's own output: a wired/USB/Bluetooth headset if one is connected, else the speaker. */
    private static AudioDeviceInfo localOutput(AudioManager audio) {
        int[] order={AudioDeviceInfo.TYPE_WIRED_HEADSET,AudioDeviceInfo.TYPE_WIRED_HEADPHONES,AudioDeviceInfo.TYPE_USB_HEADSET,
            AudioDeviceInfo.TYPE_BLE_HEADSET,AudioDeviceInfo.TYPE_BLUETOOTH_A2DP,AudioDeviceInfo.TYPE_BUILTIN_SPEAKER};
        AudioDeviceInfo[] devices=audio.getDevices(AudioManager.GET_DEVICES_OUTPUTS);
        for(int type:order)for(AudioDeviceInfo device:devices)if(device.getType()==type)return device;
        return null;
    }
    /**
     * PCM from the Linux "phone" sink, played on the phone even while Android routes media to a
     * cast display. Linux keeps its default sink on Android's routing; this is the explicit
     * alternative (docs/59). Small socket buffers keep the unreported latency low.
     */
    private void phoneOutput(LocalSocket socket) throws Exception {
        if(!phoneOutputBusy.compareAndSet(false,true))throw new IOException("Phone output busy");
        audioPriority();
        AudioManager audio=activity.getSystemService(AudioManager.class);
        AudioTrack track=null;AudioDeviceCallback callback=null;boolean header=false;
        try {
            int min=AudioTrack.getMinBufferSize(48000,AudioFormat.CHANNEL_OUT_STEREO,AudioFormat.ENCODING_PCM_16BIT);
            if(min<0)throw new IOException("Unsupported output format");
            final AudioTrack out=track=new AudioTrack.Builder()
                .setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).build())
                .setAudioFormat(new AudioFormat.Builder().setSampleRate(48000).setChannelMask(AudioFormat.CHANNEL_OUT_STEREO).setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                // ~150 ms: playback here is speech and media, not latency critical, and the
                // Linux side forwards it from a Python thread that a busy phone may delay.
                .setTransferMode(AudioTrack.MODE_STREAM).setBufferSizeInBytes(Math.max(min,28800)).build();
            if(out.getState()!=AudioTrack.STATE_INITIALIZED)throw new IOException("Phone output unavailable");
            out.setPreferredDevice(localOutput(audio));
            callback=new AudioDeviceCallback() {
                @Override public void onAudioDevicesAdded(AudioDeviceInfo[] added) { out.setPreferredDevice(localOutput(audio)); }
                @Override public void onAudioDevicesRemoved(AudioDeviceInfo[] removed) { out.setPreferredDevice(localOutput(audio)); }
            };
            audio.registerAudioDeviceCallback(callback,null);
            socket.setReceiveBufferSize(16384);
            json(socket.getOutputStream(),new JSONObject().put("ok",true).put("rate",48000).put("channels",2).put("format","s16le"));header=true;
            socket.setSoTimeout(10000);
            out.play();
            InputStream in=socket.getInputStream();byte[] block=new byte[3840];int pending=0;
            while(running) {
                int count=in.read(block,pending,block.length-pending);
                if(count<0)break;
                pending+=count;
                int frames=pending-pending%4;
                if(frames==0)continue;
                if(out.write(block,0,frames,AudioTrack.WRITE_BLOCKING)<0)throw new IOException("Phone output write failed");
                System.arraycopy(block,frames,block,0,pending-frames);pending-=frames;
            }
        } catch(Exception e) { if(!header)json(socket.getOutputStream(),new JSONObject().put("error",e.getMessage()==null?"Phone output unavailable":e.getMessage())); }
        finally {
            android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_DEFAULT);   // a pool thread: others use it next
            if(callback!=null)audio.unregisterAudioDeviceCallback(callback);
            if(track!=null) {
                android.util.Log.i("MotoAudio","phone output ended, underruns="+track.getUnderrunCount());
                try { track.stop(); } catch(Exception ignored) {}track.release();
            }
            phoneOutputBusy.set(false);
        }
    }
    private void camera(LocalSocket socket,String id) throws Exception {
        long deadline=SystemClock.elapsedRealtime()+2000;
        while(!cameraBusy.compareAndSet(false,true)) {
            if(!visible || SystemClock.elapsedRealtime()>deadline)throw new IOException("相机正在使用中");
            Thread.sleep(25);
        }
        HandlerThread thread=new HandlerThread("moto-camera");thread.start();Handler handler=new Handler(thread.getLooper());
        Object cameraLock=new Object();AtomicBoolean accepting=new AtomicBoolean(true);
        AtomicReference<CameraDevice> device=new AtomicReference<>();
        AtomicReference<CameraCaptureSession> session=new AtomicReference<>();
        AtomicReference<Image> latest=new AtomicReference<>();Semaphore frames=new Semaphore(0);
        AtomicReference<String> failure=new AtomicReference<>();CountDownLatch configured=new CountDownLatch(1);
        ImageReader reader=null;boolean active=false,header=false;
        try {
            JSONObject metadata=null;JSONArray list=info().getJSONArray("cameras");
            for(int i=0;i<list.length();i++)if(list.getJSONObject(i).getString("id").equals(id))metadata=list.getJSONObject(i);
            if(metadata==null)throw new IOException("Unknown camera");
            ensurePermission(Manifest.permission.CAMERA);
            int width=metadata.getInt("width"),height=metadata.getInt("height"),rotation=metadata.getInt("rotation");
            reader=ImageReader.newInstance(width,height,ImageFormat.YUV_420_888,3);
            final ImageReader source=reader;
            reader.setOnImageAvailableListener(r -> {
                try {
                    Image image=r.acquireLatestImage();if(image==null)return;
                    if(!accepting.get()) { image.close();return; }
                    Image old=latest.getAndSet(image);if(old!=null)old.close();
                    if(frames.availablePermits()==0)frames.release();
                } catch(Exception ignored) {}
            },handler);
            CameraCharacteristics traits=cameras.getCameraCharacteristics(id);
            captureState(false,true);active=true;
            cameras.openCamera(id,new CameraDevice.StateCallback() {
                @Override public void onOpened(CameraDevice d) {
                    synchronized(cameraLock) {
                    if(!accepting.get()) { d.close();thread.quitSafely();return; }
                    device.set(d);
                    try {
                        d.createCaptureSession(Collections.singletonList(source.getSurface()),new CameraCaptureSession.StateCallback() {
                            @Override public void onConfigured(CameraCaptureSession s) {
                                synchronized(cameraLock) {
                                if(!accepting.get()) { s.close();return; }
                                session.set(s);
                                try {
                                    CaptureRequest.Builder request=d.createCaptureRequest(CameraDevice.TEMPLATE_RECORD);
                                    request.addTarget(source.getSurface());
                                    int[] modes=traits.get(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES);
                                    if(modes!=null)for(int mode:modes)if(mode==CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_VIDEO)request.set(CaptureRequest.CONTROL_AF_MODE,mode);
                                    Range<Integer>[] ranges=traits.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES);
                                    Range<Integer> best=null;
                                    if(ranges!=null)for(Range<Integer> range:ranges)
                                        if(range.getUpper()==30 && (best==null || range.getLower()>best.getLower()))best=range;
                                    if(best!=null)request.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE,best);
                                    s.setRepeatingRequest(request.build(),null,handler);
                                } catch(Exception e) { failure.set("Camera configuration failed"); }
                                configured.countDown();
                                }
                            }
                            @Override public void onConfigureFailed(CameraCaptureSession s) { failure.set("Camera configuration failed");configured.countDown(); }
                        },handler);
                    } catch(Exception e) { failure.set("Camera unavailable");configured.countDown(); }
                    }
                }
                @Override public void onDisconnected(CameraDevice d) { failure.set("Camera disconnected");d.close();configured.countDown();frames.release(); }
                @Override public void onError(CameraDevice d,int error) { failure.set("Camera error "+error);d.close();configured.countDown();frames.release(); }
            },handler);
            if(!configured.await(6,TimeUnit.SECONDS) || failure.get()!=null)throw new IOException(failure.get()==null?"Camera timed out":failure.get());
            json(socket.getOutputStream(),new JSONObject(metadata.toString()).put("ok",true).put("format","android-yuv420"));header=true;
            DataOutputStream out=new DataOutputStream(socket.getOutputStream());byte[][] data=new byte[3][];
            while(running && visible && failure.get()==null) {
                if(!frames.tryAcquire(3,TimeUnit.SECONDS))throw new IOException("No camera frames");
                Image image=latest.getAndSet(null);if(image==null)continue;
                try {
                    Image.Plane[] planes=image.getPlanes();int[] lengths=new int[3];
                    for(int i=0;i<3;i++) {
                        ByteBuffer buffer=planes[i].getBuffer();int size=buffer.remaining();lengths[i]=size;
                        if(size>width*height*2)throw new IOException("Invalid image plane");
                        if(data[i]==null || data[i].length<size)data[i]=new byte[size];
                        buffer.get(data[i],0,size);
                    }
                    out.writeInt(0x4d43414d);out.writeInt(1);out.writeInt(width);out.writeInt(height);out.writeInt(rotation);
                    for(Image.Plane plane:planes)out.writeInt(plane.getRowStride());
                    for(Image.Plane plane:planes)out.writeInt(plane.getPixelStride());
                    for(int length:lengths)out.writeInt(length);
                    out.writeLong(image.getTimestamp());
                    for(int i=0;i<3;i++)out.write(data[i],0,lengths[i]);
                } finally { image.close(); }
            }
        } catch(Exception e) { if(!header)json(socket.getOutputStream(),new JSONObject().put("error",e.getMessage()==null?"Camera unavailable":e.getMessage())); }
        finally {
            synchronized(cameraLock) {
                accepting.set(false);
                CameraCaptureSession s=session.get();if(s!=null)s.close();
                CameraDevice d=device.get();if(d!=null)d.close();
            }
            if(reader!=null)reader.setOnImageAvailableListener(null,null);
            // Keep the callback looper alive briefly if openCamera timed out;
            // a late onOpened must still close the newly delivered device.
            if(device.get()==null)handler.postDelayed(thread::quitSafely,10000);
            else { thread.quitSafely();thread.join(1500); }
            Image image=latest.getAndSet(null);if(image!=null)image.close();
            if(reader!=null)reader.close();
            if(active)try { captureState(false,false); } catch(Exception ignored) {}
            cameraBusy.set(false);
        }
    }
    @Override public synchronized void close() throws IOException {
        running=false;setVisible(false);
        if(server!=null)server.close();if(bound!=null)bound.close();path.delete();clients.shutdownNow();
        activity.stopService(new Intent(activity,CaptureService.class));
    }
}
