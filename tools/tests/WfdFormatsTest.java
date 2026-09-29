// SPDX-License-Identifier: MIT
package com.rungic.cast;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.io.*;
import java.util.*;

/** Protocol fixtures are synthetic; optional argument accepts a locally captured handshake. */
public final class WfdFormatsTest {
    static final String OFFER="40 01 02 0040 0000000001e0 000180000000 000000000000 10 0000 001f 11 00";
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    static byte[] bytes(String s){return s.getBytes(StandardCharsets.ISO_8859_1);}
    static String message(String method,String body){return method+"\r\nCSeq: 3\r\nContent-Length: "+bytes(body).length+"\r\n\r\n"+body;}
    static byte[] packet(boolean incoming,int seq,String payload){
        byte[] b=new byte[40+bytes(payload).length];ByteBuffer p=ByteBuffer.wrap(b);
        b[0]=0x45;p.putShort(2,(short)b.length);b[9]=6;
        b[12]=10;b[15]=(byte)(incoming?2:1);b[16]=10;b[19]=(byte)(incoming?1:2);
        p.putShort(20,(short)(incoming?45678:7236));p.putShort(22,(short)(incoming?7236:45678));
        p.putInt(24,seq);b[32]=0x50;System.arraycopy(bytes(payload),0,b,40,bytes(payload).length);return b;
    }
    static byte[] pcap(byte[]... packets)throws Exception{
        ByteArrayOutputStream b=new ByteArrayOutputStream();
        b.write(ByteBuffer.allocate(24).order(ByteOrder.LITTLE_ENDIAN).putInt(0xa1b2c3d4).putShort((short)2).putShort((short)4)
                .putInt(0).putInt(0).putInt(65535).putInt(101).array());
        for(byte[] p:packets){b.write(ByteBuffer.allocate(16).order(ByteOrder.LITTLE_ENDIAN).putInt(0).putInt(0).putInt(p.length).putInt(p.length).array());b.write(p);}
        return b.toByteArray();
    }
    public static void main(String[] args)throws Exception{
        List<WfdFormats.Codec> codecs=WfdFormats.parse(OFFER,true);
        check(codecs.size()==1,"R2 codec");
        for(String id:new String[]{"1280x720@30","1280x720@60","1920x1080@30","1920x1080@60","2560x1440@60","2560x1600@30"})
            check(codecs.get(0).contains(WfdFormats.find(id)),"Advertised "+id);
        check(!codecs.get(0).contains(WfdFormats.find("3840x2160@60")),"Do not invent 4K");
        check(!codecs.get(0).contains(WfdFormats.find("2560x1600@60")),"64-bit bitmap boundary");
        check(WfdFormats.find("1920x1080@60i").interlaced,"Interlace distinct from progressive");
        List<WfdFormats.Codec> r1=WfdFormats.parse("00 00 02 10 ffffffff ffffffff ffffffff 00 0000 0000 00 none none",false);
        check(!r1.get(0).contains(WfdFormats.find("2560x1440@60")),"R1 reserved bits cannot become R2 modes");
        try{WfdFormats.parse("40 01 02",true);throw new AssertionError("Truncation");}catch(IllegalArgumentException expected){}
        String input=message("RTSP/1.0 200 OK","wfd2_video_formats: "+OFFER+"\r\n");
        String output=message("SET_PARAMETER rtsp://localhost/wfd1.0 RTSP/1.0","wfd2_video_formats: "+OFFER+"\r\n");
        WfdPackets.Video video=WfdPackets.read(pcap(packet(true,1080,input.substring(80)),packet(false,3000,output),
                packet(true,1000,input.substring(0,80)),packet(true,1000,input.substring(0,100))));
        check(video!=null&&video.r2&&video.offered.equals(OFFER),"TCP segmentation, reorder, overlap, retransmit");
        check(WfdPackets.read(pcap(packet(true,1000,input.substring(0,40)),packet(true,1041,input.substring(41)),packet(false,3000,output)))==null,"Gap rejected");
        check(WfdPackets.read(pcap(packet(true,1000,input)))==null,"No source selection: unknown");
        check(WfdPackets.read(new byte[20])==null,"Short PCAP");
        if(args.length>0){video=WfdPackets.read(Files.readAllBytes(Paths.get(args[0])));check(video!=null,"Real capture parse");System.out.println("Observed receiver: "+video.offered);}
        System.out.println("WFD protocol/reassembly tests passed");
    }
}
