package com.rungic.plasma;

import android.content.Context;
import android.net.LocalSocket;
import android.util.Log;
import org.json.JSONObject;
import java.io.*;
import java.net.HttpURLConnection;
import java.net.InetSocketAddress;
import java.net.Proxy;
import java.net.URI;
import java.net.URL;
import java.nio.ByteBuffer;
import java.security.MessageDigest;
import org.json.JSONArray;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;

/**
 * Text recognition for the Linux desktop on the phone's GPU (docs/64): PP-OCRv6 Small on LiteRT
 * (librungicocr.so, plasma/native-apk/jni/ocr). Serves the platform bridge's "ocr" request:
 * {"op":"ocr","width":W,"height":H,"format":"rgb","bytes":W*H*3,"det_scale":S} and the raw RGB
 * pixels after the newline; the reply is one JSON line {"lines":[{"text","score","box"}],"ms":{...}}.
 * {"op":"ocr","info":true} describes the engine. The engine is created on first use and lives on one
 * thread, as GPU contexts must; requests queue behind each other.
 *
 * The models come with the APK (RUNGIC_APK_OCR=bundle) or, by default, are downloaded on first use
 * (docs/73): assets/ocr/sources.json pins their URLs and SHA-256; a request's optional "proxy"
 * (http://host:port, the Linux side's) is used for the download. Until they are in place a request
 * is answered at once with {"available":false,"downloading":true,...} and an error, and the Linux side
 * reads text on its CPU meanwhile.
 */
final class OcrBridge {
    private static final String TAG="RungicOcr";
    private static final String[] MODEL_FILES={"det.tflite","rec_320.tflite","rec_640.tflite","rec_960.tflite","classes.txt"};
    private static final int MAX_SIDE=8192;
    private final Context context;
    private final ExecutorService engineThread=Executors.newSingleThreadExecutor(r -> new Thread(r,"rungic-ocr"));
    private static final String[] DOWNLOADS={"det.tflite","rec_320.tflite","rec_640.tflite","rec_960.tflite",
        "characters.json","LICENSE-PP-OCRv6-Small-LiteRT"};
    private long engine;
    private boolean engineFp32;
    private final ExecutorService downloader=Executors.newSingleThreadExecutor(r -> new Thread(r,"rungic-ocr-download"));
    private boolean downloading;
    private volatile long received,total;
    private volatile String downloadError;
    private volatile long failedAt;

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

    private boolean asset(String name) {
        try { context.getAssets().open("ocr/"+name).close(); return true; }
        catch(IOException e) { return false; }
    }
    private boolean bundled() { return asset(MODEL_FILES[0]); }

    /** Downloaded models live in files/ocr/models-<first 12 hex of the pinned sources' SHA-256>. */
    private File downloadedModels() throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        try(InputStream in=context.getAssets().open("ocr/sources.json")) {
            byte[] buffer=new byte[1<<14];
            for(int n;(n=in.read(buffer))>0;)digest.update(buffer,0,n);
        }
        StringBuilder hex=new StringBuilder();
        for(byte b:digest.digest())hex.append(String.format("%02x",b));
        return new File(new File(context.getFilesDir(),"ocr"),"models-"+hex.substring(0,12));
    }

    private JSONObject handle(InputStream in,JSONObject request) throws Exception {
        // Without OCR the Linux side reads text on its CPU (plasma/cua/typesafe/linux_ocr.py, docs/73).
        if(!bundled() && !asset("sources.json"))return new JSONObject().put("available",false)
            .put("error","OCR is not built into this APK (plasma/build-apk.sh RUNGIC_APK_OCR)");
        if(!bundled() && !new File(downloadedModels(),"ready").exists()) {
            startDownload(request.optString("proxy",""));
            String error=downloadError!=null?"OCR model download failed: "+downloadError
                :"OCR models are downloading ("+received/1048576+" of "+Math.max(total,received)/1048576+" MB)";
            return new JSONObject().put("available",false).put("downloading",downloadError==null)
                .put("received",received).put("total",total).put("error",error);
        }
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
        try { System.loadLibrary("rungicocr"); }
        catch(UnsatisfiedLinkError e) { throw new IOException("OCR runtime missing: "+e.getMessage()); }
        File root=new File(context.getFilesDir(),"ocr");
        File models,cache;
        if(!bundled()) {
            try { models=downloadedModels(); } catch(Exception e) { throw new IOException(e); }
            cache=new File(root,"cache-"+models.getName().substring("models-".length()));
        } else {
        long version;
        try { version=context.getPackageManager().getPackageInfo(context.getPackageName(),0).getLongVersionCode(); }
        catch(Exception e) { throw new IOException(e); }
        models=new File(root,"models-"+version);cache=new File(root,"cache-"+version);
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
        }
        cache.mkdirs();
        long started=System.nanoTime();
        engine=nativeCreate(models.getPath(),context.getApplicationInfo().nativeLibraryDir,cache.getPath(),fp32);
        engineFp32=fp32;
        Log.i(TAG,"engine ready in "+(System.nanoTime()-started)/1000000+" ms: "+nativeDescribe(engine));
        return engine;
    }

    /** Download the pinned models once, off every other thread; a failure may be retried after a minute. */
    private synchronized void startDownload(String proxy) {
        if(downloading || (downloadError!=null && System.currentTimeMillis()-failedAt<60000))return;
        downloading=true;downloadError=null;
        downloader.execute(() -> {
            try {
                download(proxy);
            } catch(Exception e) {
                downloadError=e.getMessage()==null?e.toString():e.getMessage();
                failedAt=System.currentTimeMillis();
                Log.w(TAG,"model download failed: "+downloadError);
            } finally {
                synchronized(this) { downloading=false; }
            }
        });
    }

    private void download(String proxyUrl) throws Exception {
        JSONObject files;
        try(InputStream in=context.getAssets().open("ocr/sources.json")) {
            files=new JSONObject(new String(readAll(in),StandardCharsets.UTF_8)).getJSONObject("files");
        }
        Proxy proxy=Proxy.NO_PROXY;
        if(!proxyUrl.isEmpty()) {
            URI uri=URI.create(proxyUrl);
            proxy=new Proxy(Proxy.Type.HTTP,new InetSocketAddress(uri.getHost(),uri.getPort()>0?uri.getPort():80));
        }
        File models=downloadedModels(),root=models.getParentFile(),partial=new File(root,"download-"+models.getName());
        if(!partial.isDirectory() && !partial.mkdirs())throw new IOException("Cannot create "+partial);
        received=0;total=0;
        for(String name:DOWNLOADS) {
            File target=new File(partial,name);
            String sha=files.getJSONObject(name).getString("sha256");
            if(target.exists() && sha.equals(sha256(target))) { received+=target.length(); continue; }
            File part=new File(partial,name+".part");
            HttpURLConnection connection=(HttpURLConnection)new URL(files.getJSONObject(name).getString("url")).openConnection(proxy);
            connection.setConnectTimeout(30000);connection.setReadTimeout(60000);connection.setInstanceFollowRedirects(true);
            if(connection.getResponseCode()!=200)throw new IOException(name+": HTTP "+connection.getResponseCode());
            total=Math.max(total,received+Math.max(0,connection.getContentLengthLong()));
            try(InputStream in=connection.getInputStream();OutputStream out=new FileOutputStream(part)) {
                byte[] buffer=new byte[1<<16];
                for(int n;(n=in.read(buffer))>0;) { out.write(buffer,0,n);received+=n; }
            } finally { connection.disconnect(); }
            if(!sha.equals(sha256(part))) { part.delete();throw new IOException(name+": SHA-256 mismatch"); }
            if(!part.renameTo(target))throw new IOException("Cannot keep "+target);
        }
        // The layout the engine reads: det/rec models, classes.txt from the CTC character list, LICENSE.
        File staged=new File(root,"staged-"+models.getName());
        deleteTree(staged);
        if(!staged.mkdirs())throw new IOException("Cannot create "+staged);
        for(String name:new String[]{"det.tflite","rec_320.tflite","rec_640.tflite","rec_960.tflite"})
            if(!new File(partial,name).renameTo(new File(staged,name)))throw new IOException("Cannot move "+name);
        JSONArray classes=new JSONArray(new String(readAll(new FileInputStream(new File(partial,"characters.json"))),StandardCharsets.UTF_8));
        try(Writer out=new OutputStreamWriter(new FileOutputStream(new File(staged,"classes.txt")),StandardCharsets.UTF_8)) {
            for(int i=0;i<classes.length();i++)out.write(classes.getString(i)+"\n");
        }
        if(!new File(partial,"LICENSE-PP-OCRv6-Small-LiteRT").renameTo(new File(staged,"LICENSE")))throw new IOException("Cannot move LICENSE");
        new FileOutputStream(new File(staged,"ready")).close();
        deleteTree(models);
        if(!staged.renameTo(models))throw new IOException("Cannot install "+models);
        deleteTree(partial);
        // Models of earlier pins and of bundled builds are no longer used.
        File[] entries=root.listFiles();
        if(entries!=null)for(File entry:entries)
            if(!entry.equals(models) && !entry.getName().equals("cache-"+models.getName().substring("models-".length())))deleteTree(entry);
        Log.i(TAG,"models downloaded to "+models);
    }

    private static byte[] readAll(InputStream in) throws IOException {
        try(InputStream source=in) {
            ByteArrayOutputStream out=new ByteArrayOutputStream();
            byte[] buffer=new byte[1<<16];
            for(int n;(n=source.read(buffer))>0;)out.write(buffer,0,n);
            return out.toByteArray();
        }
    }

    private static String sha256(File file) throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        try(InputStream in=new FileInputStream(file)) {
            byte[] buffer=new byte[1<<16];
            for(int n;(n=in.read(buffer))>0;)digest.update(buffer,0,n);
        }
        StringBuilder hex=new StringBuilder();
        for(byte b:digest.digest())hex.append(String.format("%02x",b));
        return hex.toString();
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
