// SPDX-License-Identifier: MIT
package com.rungic.plasma;

import android.content.Context;
import android.graphics.Rect;
import android.media.*;
import android.net.*;
import android.os.*;
import android.system.*;
import android.util.Log;
import java.io.*;
import java.nio.*;
import java.util.*;
import java.util.concurrent.*;

/** Restricted codec broker. No file paths, network operations, camera or microphone API. */
final class CodecBridge implements Closeable {
    static final int HALF=16*1024*1024, MAGIC=0x4d434231, OPEN=0x4f50454e, CHANNEL=0x4d434631;
    static final int FRAME=1,DRAIN=2,FLUSH=3,CLOSE=4,ACK=0xac;
    static final int DONE=0,ENCODED=1,DECODED=2,CONFIG=3,EOS=4,ERROR=-1;
    private final File path;
    private final Semaphore brokerSlots=new Semaphore(64),codecSlots=new Semaphore(6);
    private final Set<LocalSocket> brokers=ConcurrentHashMap.newKeySet();
    private final Set<FileDescriptor> channels=ConcurrentHashMap.newKeySet();
    private final ExecutorService workers=Executors.newCachedThreadPool();
    private volatile boolean running;
    private LocalSocket bound;
    private LocalServerSocket listener;
    CodecBridge(Context context) { path=new File(context.getFilesDir(),"tmp/codec.sock"); }
    synchronized void start() throws IOException {
        if(running)return;
        path.delete();bound=new LocalSocket();
        bound.bind(new LocalSocketAddress(path.getAbsolutePath(),LocalSocketAddress.Namespace.FILESYSTEM));
        listener=new LocalServerSocket(bound.getFileDescriptor());
        try { Os.chmod(path.getAbsolutePath(),0666); } catch(ErrnoException e) { throw new IOException(e); }
        running=true;
        Thread thread=new Thread(() -> {
            while(running)try {
                LocalSocket s=listener.accept();int uid=s.getPeerCredentials().getUid();
                if((uid!=0 && uid!=1000) || !brokerSlots.tryAcquire()) { s.close();continue; }
                brokers.add(s);
                workers.execute(() -> {try(LocalSocket socket=s){broker(socket);}catch(Exception e){if(!(e instanceof EOFException))Log.d("RungicCodec","Broker closed: "+e);}
                    finally{brokers.remove(s);brokerSlots.release();}});
            } catch(Exception e) { if(running)Log.w("RungicCodec","Accept",e); }
        },"rungic-codec-accept");thread.setDaemon(true);thread.start();
    }
    private void broker(LocalSocket socket) throws Exception {
        socket.setSoTimeout(5000);
        DataInputStream input=new DataInputStream(socket.getInputStream());
        DataOutputStream output=new DataOutputStream(socket.getOutputStream());
        if(input.readInt()!=MAGIC)throw new IOException("Broker version");
        socket.setSoTimeout(0);
        while(running) {
            if(input.readInt()!=OPEN)throw new IOException("Broker operation");
            if(!codecSlots.tryAcquire()) {output.writeInt(ERROR);output.flush();continue;}
            FileDescriptor local=new FileDescriptor(),remote=new FileDescriptor();SharedMemory memory=null;
            boolean transferred=false;
            try {
                Os.socketpair(OsConstants.AF_UNIX,OsConstants.SOCK_STREAM|OsConstants.SOCK_CLOEXEC,0,local,remote);
                memory=SharedMemory.create("rungic-codec-frames",HALF*2);
                Parcel parcel=Parcel.obtain();ParcelFileDescriptor memoryFd=null;
                try {
                    memory.writeToParcel(parcel,0);parcel.setDataPosition(0);memoryFd=parcel.readFileDescriptor();
                    socket.setFileDescriptorsForSend(new FileDescriptor[]{remote,memoryFd.getFileDescriptor()});
                    output.writeInt(CHANNEL);output.flush();
                    socket.setFileDescriptorsForSend(null);
                } finally {if(memoryFd!=null)memoryFd.close();parcel.recycle();}
                Os.close(remote);
                final SharedMemory shared=memory;channels.add(local);
                workers.execute(() -> {
                    try {new Session(local,shared).run();}catch(Exception e){Log.w("RungicCodec","Session: "+e);}
                    finally {channels.remove(local);try{Os.close(local);}catch(Exception ignored){}shared.close();codecSlots.release();}
                });
                transferred=true;
            } finally {
                if(!transferred) {try{Os.close(local);}catch(Exception ignored){}try{Os.close(remote);}catch(Exception ignored){}
                    if(memory!=null)memory.close();codecSlots.release();}
            }
        }
    }
    static final class Session {
        final FileDescriptor fd;final SharedMemory memory;
        MediaCodec codec;ByteBuffer shared;DataInputStream in;DataOutputStream out;
        boolean encoder,ended;int kind,width,height,inputCount,outputCount;
        String name;byte[] row=new byte[8192];
        final Map<Long,ArrayDeque<Integer>> frames=new HashMap<>();
        final Map<Integer,byte[]> parameters=new TreeMap<>();
        Session(FileDescriptor fd,SharedMemory memory){this.fd=fd;this.memory=memory;}
        void run() throws Exception {
            try(FileInputStream input=new FileInputStream(Os.dup(fd));FileOutputStream output=new FileOutputStream(Os.dup(fd))) {
                in=new DataInputStream(input);out=new DataOutputStream(output);
                Os.setsockoptTimeval(fd,OsConstants.SOL_SOCKET,OsConstants.SO_RCVTIMEO,StructTimeval.fromMillis(10000));
                Os.setsockoptTimeval(fd,OsConstants.SOL_SOCKET,OsConstants.SO_SNDTIMEO,StructTimeval.fromMillis(10000));
                try {
                    configure();
                    // A paused pipeline may keep a channel idle. Closing its FD cancels all waits.
                    Os.setsockoptTimeval(fd,OsConstants.SOL_SOCKET,OsConstants.SO_RCVTIMEO,StructTimeval.fromMillis(0));
                    while(true) {
                        int cmd=in.readInt();if(cmd==CLOSE)break;
                        if(cmd==FLUSH) {
                            codec.flush();frames.clear();ended=false;
                            if(!encoder && !parameters.isEmpty()) {
                                ByteArrayOutputStream csd=new ByteArrayOutputStream();for(byte[] p:parameters.values())csd.write(p);
                                int index=codec.dequeueInputBuffer(2000000);if(index<0)throw new IOException("Flush input timeout");
                                byte[] bytes=csd.toByteArray();codec.getInputBuffer(index).put(bytes);
                                codec.queueInputBuffer(index,0,bytes.length,0,MediaCodec.BUFFER_FLAG_CODEC_CONFIG);
                            }
                            out.writeInt(DONE);out.flush();continue;
                        }
                        if(ended)throw new IOException("Input after EOS");
                        if(cmd!=FRAME && cmd!=DRAIN)throw new IOException("Codec operation");
                        int id=-1,flags=0,length=0;long pts=0;
                        if(cmd==FRAME) {id=in.readInt();pts=in.readLong();flags=in.readInt();length=in.readInt();
                            if(length<=0 || length>HALF)throw new IOException("Frame size");
                            if(encoder && length!=width*height*3/2)throw new IOException("I420 size");
                            if(frames.size()>128)throw new IOException("Too many delayed frames");}
                        int index=-1;long deadline=System.nanoTime()+5000000000L;
                        while(index<0 && System.nanoTime()<deadline) {index=codec.dequeueInputBuffer(1000);if(index<0)drain(false);}
                        if(index<0)throw new IOException("Input buffer timeout");
                        if(cmd==DRAIN)codec.queueInputBuffer(index,0,0,0,MediaCodec.BUFFER_FLAG_END_OF_STREAM);
                        else {
                            if(encoder) {
                                if((flags&1)!=0) {Bundle b=new Bundle();b.putInt(MediaCodec.PARAMETER_KEY_REQUEST_SYNC_FRAME,0);codec.setParameters(b);}
                                try(Image image=codec.getInputImage(index)) { if(image==null)throw new IOException("No input image");fill(image); }
                            } else {
                                ByteBuffer b=codec.getInputBuffer(index);if(b.capacity()<length)throw new IOException("Compressed AU too large");
                                ByteBuffer src=shared.duplicate();src.position(0);src.limit(length);b.put(src);saveParameters(length);
                            }
                            frames.computeIfAbsent(pts,k -> new ArrayDeque<>()).add(id);
                            codec.queueInputBuffer(index,0,length,pts,0);inputCount++;
                        }
                        drain(cmd==DRAIN);out.writeInt(DONE);out.flush();
                    }
                } catch(EOFException ignored) {} catch(Exception e) {
                    try {byte[] message=e.toString().getBytes("UTF-8");out.writeInt(ERROR);out.writeInt(Math.min(message.length,2048));out.write(message,0,Math.min(message.length,2048));out.flush();}catch(Exception ignored){}
                    throw e;
                } finally {
                    if(codec!=null){try{codec.stop();}catch(Exception ignored){}codec.release();}
                    if(shared!=null)SharedMemory.unmap(shared);
                    Log.i("RungicCodec","CLOSE "+name+" input="+inputCount+" output="+outputCount);
                }
            }
        }
        void configure() throws Exception {
            if(in.readInt()!=MAGIC)throw new IOException("Channel version");
            int op=in.readInt();if(op<0 || op>1)throw new IOException("Mode");encoder=op==1;
            kind=in.readInt();width=in.readInt();height=in.readInt();int fpsn=in.readInt(),fpsd=in.readInt();
            int bitrate=in.readInt(),interval=in.readInt(),standard=in.readInt(),range=in.readInt(),transfer=in.readInt();
            if(kind<0 || kind>2 || (encoder && kind==2) || width<16 || height<16 || width>2560 || height>2560 || (encoder && ((width|height)&1)!=0))throw new IOException("Unsupported dimensions/codec");
            String[] kinds={"avc","hevc","vp9"},mimes={"video/avc","video/hevc","video/x-vnd.on2.vp9"};
            name="c2.qti."+kinds[kind]+(encoder?".encoder":".decoder");
            MediaCodecInfo info=null;
            for(MediaCodecInfo c:new MediaCodecList(MediaCodecList.REGULAR_CODECS).getCodecInfos())if(c.getName().equals(name))info=c;
            if(info==null || !info.isHardwareAccelerated() || info.isSoftwareOnly())throw new IOException("Hardware codec unavailable");
            MediaCodecInfo.VideoCapabilities video=info.getCapabilitiesForType(mimes[kind]).getVideoCapabilities();
            if(!video.isSizeSupported(width,height))throw new IOException("Size unsupported by hardware");
            MediaFormat format=MediaFormat.createVideoFormat(mimes[kind],width,height);
            format.setInteger(MediaFormat.KEY_COLOR_FORMAT,MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible);
            if(standard>0)format.setInteger(MediaFormat.KEY_COLOR_STANDARD,standard);
            if(range>0)format.setInteger(MediaFormat.KEY_COLOR_RANGE,range);
            if(transfer>0)format.setInteger(MediaFormat.KEY_COLOR_TRANSFER,transfer);
            if(encoder) {
                double fps=fpsn>0 && fpsd>0?(double)fpsn/fpsd:30;
                if(fps<1 || fps>60 || !video.areSizeAndRateSupported(width,height,fps))throw new IOException("Frame rate unsupported");
                format.setFloat(MediaFormat.KEY_FRAME_RATE,(float)fps);
                format.setInteger(MediaFormat.KEY_BIT_RATE,Math.max(64000,Math.min(40000000,bitrate)));
                format.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL,Math.max(1,Math.min(10,interval)));
                format.setInteger(MediaFormat.KEY_MAX_B_FRAMES,0);
                format.setInteger(MediaFormat.KEY_PROFILE,kind==0?MediaCodecInfo.CodecProfileLevel.AVCProfileBaseline:MediaCodecInfo.CodecProfileLevel.HEVCProfileMain);
            } else format.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE,HALF);
            codec=MediaCodec.createByCodecName(name);codec.configure(format,null,null,encoder?MediaCodec.CONFIGURE_FLAG_ENCODE:0);codec.start();
            shared=memory.mapReadWrite();byte[] bytes=name.getBytes("UTF-8");out.writeInt(DONE);out.writeInt(bytes.length);out.write(bytes);out.flush();
            Log.i("RungicCodec","OPEN "+name+" "+width+"x"+height+" uid="+android.os.Process.myUid());
        }
        void fill(Image image) throws Exception {
            Image.Plane[] planes=image.getPlanes();int offset=0;
            for(int p=0;p<3;p++) {
                int w=p==0?width:width/2,h=p==0?height:height/2;
                Image.Plane plane=planes[p];int step=plane.getPixelStride(),stride=plane.getRowStride();ByteBuffer dst=plane.getBuffer();int start=dst.position();
                if(step!=1 && step!=2)throw new IOException("Input pixel stride");
                for(int y=0;y<h;y++) {
                    ByteBuffer src=shared.duplicate();src.position(offset+y*w);src.limit(offset+(y+1)*w);dst.position(start+y*stride);
                    if(step==1)dst.put(src);
                    else for(int x=0;x<w;x++)dst.put(start+y*stride+x*step,src.get());
                }
                offset+=w*h;
            }
        }
        void saveParameters(int length) {
            if(kind==2)return;
            int start=-1,prefix=0;
            for(int i=0;i+3<=length;i++) {
                int n=0;if(i+4<=length && shared.get(i)==0 && shared.get(i+1)==0 && shared.get(i+2)==0 && shared.get(i+3)==1)n=4;
                else if(shared.get(i)==0 && shared.get(i+1)==0 && shared.get(i+2)==1)n=3;
                if(n==0)continue;
                if(start>=0)saveParameter(start,prefix,i);
                start=i;prefix=n;i+=n-1;
            }
            if(start>=0)saveParameter(start,prefix,length);
        }
        void saveParameter(int start,int prefix,int end) {
            if(start+prefix>=end || end-start>65536)return;
            int type=kind==0?shared.get(start+prefix)&31:(shared.get(start+prefix)>>1)&63;
            if(kind==0?(type!=7 && type!=8):(type<32 || type>34))return;
            byte[] value=new byte[end-start];ByteBuffer b=shared.duplicate();b.position(start);b.get(value);parameters.put(type,value);
        }
        void drain(boolean eos) throws Exception {
            long deadline=System.nanoTime()+10000000000L;MediaCodec.BufferInfo info=new MediaCodec.BufferInfo();
            while(System.nanoTime()<deadline) {
                int index=codec.dequeueOutputBuffer(info,eos?10000:2000);
                if(index==MediaCodec.INFO_TRY_AGAIN_LATER){if(eos)continue;return;}
                if(index==MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {Log.i("RungicCodec","FORMAT "+name+" "+codec.getOutputFormat());continue;}
                if(index<0)continue;
                boolean outputEos=(info.flags&MediaCodec.BUFFER_FLAG_END_OF_STREAM)!=0;
                int type=0,id=-1,size=0;int[] meta=new int[13];
                try {
                    if(info.size>0) {
                        if((info.flags&MediaCodec.BUFFER_FLAG_CODEC_CONFIG)!=0)type=CONFIG;
                        else {ArrayDeque<Integer> queue=frames.get(info.presentationTimeUs);
                            if(queue==null || queue.isEmpty())throw new IOException("Unmatched output PTS "+info.presentationTimeUs);
                            id=queue.removeFirst();if(queue.isEmpty())frames.remove(info.presentationTimeUs);outputCount++;
                            type=encoder?ENCODED:DECODED;}
                        ByteBuffer dst=shared.duplicate();dst.position(HALF);dst.limit(HALF*2);
                        if(type==DECODED) {
                            try(Image image=codec.getOutputImage(index)) {
                                if(image==null)throw new IOException("No decoded image");Rect crop=image.getCropRect();
                                meta[0]=crop.width();meta[1]=crop.height();meta[2]=crop.left;meta[3]=crop.top;
                                Image.Plane[] planes=image.getPlanes();
                                for(int p=0;p<3;p++) {
                                    ByteBuffer src=planes[p].getBuffer().duplicate();int n=src.remaining();
                                    if(n>dst.remaining())throw new IOException("Output image too large");
                                    meta[4+p*3]=planes[p].getRowStride();meta[5+p*3]=planes[p].getPixelStride();meta[6+p*3]=n;
                                    dst.put(src);size+=n;
                                }
                            }
                        } else {ByteBuffer src=codec.getOutputBuffer(index).duplicate();src.position(info.offset);src.limit(info.offset+info.size);size=info.size;if(size>HALF)throw new IOException("Output AU too large");dst.put(src);}
                    }
                } finally {codec.releaseOutputBuffer(index,false);}
                // Hardware buffer is released before waiting for a paused Linux sink.
                if(type!=0) {
                    out.writeInt(type);out.writeInt(id);out.writeInt(info.flags);out.writeInt(size);out.writeLong(info.presentationTimeUs);
                    for(int v:meta)out.writeInt(v);out.flush();
                    if(in.readInt()!=ACK)throw new IOException("Frame acknowledgment");
                    deadline=System.nanoTime()+10000000000L;
                }
                if(outputEos) {ended=true;out.writeInt(EOS);return;}
            }
            throw new IOException("Output EOS timeout");
        }
    }
    @Override public synchronized void close() throws IOException {
        running=false;
        for(LocalSocket socket:brokers)try{socket.close();}catch(Exception ignored){}
        for(FileDescriptor fd:channels)try{Os.shutdown(fd,OsConstants.SHUT_RDWR);}catch(Exception ignored){}
        if(listener!=null)listener.close();if(bound!=null)bound.close();path.delete();workers.shutdownNow();
    }
}
