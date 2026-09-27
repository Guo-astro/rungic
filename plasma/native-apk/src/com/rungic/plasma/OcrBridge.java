package com.rungic.plasma;

import android.content.Context;
import android.net.LocalSocket;
import android.util.Log;
import org.json.JSONObject;
import java.io.*;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;

/**
 * Text recognition for the Linux desktop on the phone's GPU (docs/64): PP-OCRv6 Small on LiteRT
 * (librungicocr.so, plasma/native-apk/jni/ocr). Serves the platform bridge's "ocr" request:
 * {"op":"ocr","width":W,"height":H,"format":"rgb","bytes":W*H*3,"det_scale":S} and the raw RGB
 * pixels after the newline; the reply is one JSON line {"lines":[{"text","score","box"}],"ms":{...}}.
 * {"op":"ocr","info":true} describes the engine. The engine is created on first use and lives on one
 * thread, as GPU contexts must; requests queue behind each other.
 */
final class OcrBridge {
    private static final String TAG="RungicOcr";
    private static final String[] MODEL_FILES={"det.tflite","rec_320.tflite","rec_640.tflite","rec_960.tflite","classes.txt"};
    private static final int MAX_SIDE=8192;
    private final Context context;
    private final ExecutorService engineThread=Executors.newSingleThreadExecutor(r -> new Thread(r,"rungic-ocr"));
    private long engine;
    private boolean engineFp32;

    OcrBridge(Context context) { this.context=context.getApplicationContext(); }

    /** Answer one request on its own thread: read the pixels, recognize on the engine thread, reply. */
    void answer(LocalSocket client,JSONObject request) {
        Thread thread=new Thread(() -> {
            try(LocalSocket c=client) {
                JSONObject result;
                try { result=handle(c.getInputStream(),request); }
                catch(Exception e) { result=new JSONObject().put("error",e.getMessage()==null?e.toString():e.getMessage()); }
                c.getOutputStream().write((result.toString()+"\n").getBytes(StandardCharsets.UTF_8));
            } catch(Exception e) { Log.w(TAG,"OCR request failed: "+e); }
        },"rungic-ocr-request");
        thread.setDaemon(true);
        thread.start();
    }

    /** Whether this APK has OCR built in (plasma/build-apk.sh RUNGIC_APK_OCR=1): its models are assets. */
    private boolean available() {
        try { context.getAssets().open("ocr/"+MODEL_FILES[0]).close(); return true; }
        catch(IOException e) { return false; }
    }

    private JSONObject handle(InputStream in,JSONObject request) throws Exception {
        // Without OCR the Linux side reads text on its CPU (plasma/cua/typesafe/linux_ocr.py, docs/73).
        if(!available())return new JSONObject().put("available",false)
            .put("error","OCR is not built into this APK (plasma/build-apk.sh RUNGIC_APK_OCR=1)");
        boolean fp32=request.optBoolean("fp32",false);
        if(request.optBoolean("info",false))
            return new JSONObject().put("engine",onEngine(() -> nativeDescribe(engine(fp32))));
        int width=request.getInt("width"),height=request.getInt("height");
        long bytes=request.getLong("bytes");
        if(!"rgb".equals(request.optString("format","rgb")))throw new IllegalArgumentException("format must be rgb");
        if(width<1 || height<1 || width>MAX_SIDE || height>MAX_SIDE || bytes!=(long)width*height*3)
            throw new IllegalArgumentException("bytes must be width*height*3 with sides up to "+MAX_SIDE);
        ByteBuffer pixels=ByteBuffer.allocateDirect((int)bytes);
        byte[] chunk=new byte[1<<16];
        while(pixels.hasRemaining()) {
            int n=in.read(chunk,0,Math.min(chunk.length,pixels.remaining()));
            if(n<0)throw new EOFException("pixels ended after "+pixels.position()+" of "+bytes+" bytes");
            pixels.put(chunk,0,n);
        }
        float scale=(float)request.optDouble("det_scale",0);
        return new JSONObject(onEngine(() -> nativeRecognize(engine(fp32),pixels,width,height,scale)));
    }

    private <T> T onEngine(Callable<T> task) throws Exception {
        try { return engineThread.submit(task).get(120,TimeUnit.SECONDS); }
        catch(ExecutionException e) { throw e.getCause() instanceof Exception?(Exception)e.getCause():e; }
    }

    /** The engine at this precision, created on the engine thread; models come out of the APK once per version. */
    private long engine(boolean fp32) throws IOException {
        if(engine!=0 && engineFp32==fp32)return engine;
        if(engine!=0) { nativeDestroy(engine);engine=0; }
        System.loadLibrary("rungicocr");
        long version;
        try { version=context.getPackageManager().getPackageInfo(context.getPackageName(),0).getLongVersionCode(); }
        catch(Exception e) { throw new IOException(e); }
        File root=new File(context.getFilesDir(),"ocr");
        File models=new File(root,"models-"+version),cache=new File(root,"cache-"+version);
        if(!new File(models,"ready").exists()) {
            deleteTree(root);
            if(!models.mkdirs() || !cache.mkdirs())throw new IOException("Cannot create "+models);
            for(String name:MODEL_FILES) {
                try(InputStream src=context.getAssets().open("ocr/"+name);OutputStream dst=new FileOutputStream(new File(models,name))) {
                    byte[] buffer=new byte[1<<16];
                    for(int n;(n=src.read(buffer))>0;)dst.write(buffer,0,n);
                }
            }
            new FileOutputStream(new File(models,"ready")).close();
        }
        cache.mkdirs();
        long started=System.nanoTime();
        engine=nativeCreate(models.getPath(),context.getApplicationInfo().nativeLibraryDir,cache.getPath(),fp32);
        engineFp32=fp32;
        Log.i(TAG,"engine ready in "+(System.nanoTime()-started)/1000000+" ms: "+nativeDescribe(engine));
        return engine;
    }

    private static void deleteTree(File file) {
        File[] children=file.listFiles();
        if(children!=null)for(File child:children)deleteTree(child);
        file.delete();
    }

    private static native long nativeCreate(String modelDir,String libDir,String cacheDir,boolean fp32) throws IOException;
    private static native String nativeDescribe(long engine);
    private static native String nativeRecognize(long engine,ByteBuffer pixels,int width,int height,float detScale) throws IOException;
    private static native void nativeDestroy(long engine);
}
