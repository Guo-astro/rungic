// SPDX-License-Identifier: MIT
package com.rungic.cast;
import java.io.*;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.regex.*;

/** Bounded diagnostic PCAP reader. Reassembles TCP retransmits before reading RTSP.
 * Ignores unrelated ports, fragments, unsupported link/IP versions and incomplete messages.
 */
final class WfdPackets {
    static final class Video { final String offered, selected; final boolean r2;
        Video(String o,String s,boolean r){offered=o;selected=s;r2=r;}
    }
    static Video read(byte[] pcap) throws Exception {
        if(pcap.length<24 || pcap.length>1024*1024)return null;
        ByteBuffer b=ByteBuffer.wrap(pcap); int magic=b.getInt();
        if(magic==0xd4c3b2a1||magic==0x4d3cb2a1)b.order(ByteOrder.LITTLE_ENDIAN);
        else if(magic!=0xa1b2c3d4&&magic!=0xa1b23c4d)return null;
        int link=b.getInt(20); b.position(24);
        Map<String,TreeMap<Long,byte[]>> streams=new LinkedHashMap<>();
        while(b.remaining()>=16){b.getInt();b.getInt();int size=b.getInt();b.getInt();
            if(size<0||size>b.remaining())break;
            byte[] p=new byte[size];b.get(p);
            int ip=link==276?20:link==113?16:link==1?14:link==101?0:-1;
            if(ip<0||p.length<ip+20||(p[ip]&0xf0)!=0x40||p[ip+9]!=6)continue;
            if((u16(p,ip+6)&0x3fff)!=0)continue;
            int end=ip+u16(p,ip+2),tcp=ip+(p[ip]&15)*4;
            if(tcp<ip+20||end>p.length||end<tcp+20)continue;
            int src=u16(p,tcp),dst=u16(p,tcp+2),payload=tcp+((p[tcp+12]&0xf0)>>2);
            if((src!=7236&&dst!=7236)||payload<tcp+20||payload>=end)continue;
            String host=Arrays.toString(Arrays.copyOfRange(p,ip+12,ip+16));
            String peer=Arrays.toString(Arrays.copyOfRange(p,ip+16,ip+20));
            String flow=src==7236?host+":"+src+"/"+peer+":"+dst:peer+":"+dst+"/"+host+":"+src;
            String key=flow+(src==7236?"/out":"/in");
            long seq=Integer.toUnsignedLong(ByteBuffer.wrap(p,tcp+4,4).getInt());
            TreeMap<Long,byte[]> parts=streams.computeIfAbsent(key,k->new TreeMap<>());
            byte[] bytes=Arrays.copyOfRange(p,payload,end),old=parts.get(seq);
            if(old==null||old.length<bytes.length)parts.put(seq,bytes);
        }
        Video result=null;
        for(String key:streams.keySet())if(key.endsWith("/in")) {
            String input=join(streams.get(key)),output=join(streams.get(key.substring(0,key.length()-3)+"/out"));
            for(boolean r2:new boolean[]{true,false}){
                String parameter=r2?"wfd2_video_formats":"wfd_video_formats";
                String offer=parameter(input,"RTSP/1.0 200",parameter),selected=parameter(output,"SET_PARAMETER ",parameter);
                if(offer!=null&&selected!=null){if(result!=null)return null;result=new Video(offer,selected,r2);break;}
            }
        }
        return result;
    }
    private static int u16(byte[] p,int i){return ((p[i]&255)<<8)|(p[i+1]&255);}
    private static String join(TreeMap<Long,byte[]> parts)throws IOException{
        if(parts==null||parts.isEmpty())return "";
        ByteArrayOutputStream out=new ByteArrayOutputStream();long end=parts.firstKey();
        for(Map.Entry<Long,byte[]> part:parts.entrySet()) {
            if(part.getKey()>end)break; // A missing segment cannot be silently spliced.
            int skip=(int)(end-part.getKey());byte[] bytes=part.getValue();
            if(skip>=bytes.length)continue;
            out.write(bytes,skip,bytes.length-skip);end=part.getKey()+bytes.length;
        }
        return new String(out.toByteArray(),StandardCharsets.ISO_8859_1);
    }
    private static String parameter(String stream,String method,String key) {
        int p=0;String value=null;
        while(p<stream.length()) {
            int headerEnd=stream.indexOf("\r\n\r\n",p);if(headerEnd<0)break;
            String header=stream.substring(p,headerEnd);
            Matcher length=Pattern.compile("(?im)^Content-Length:\\s*(\\d+)\\s*$").matcher(header);
            int count=length.find()?Integer.parseInt(length.group(1)):0,start=headerEnd+4;
            if(count<0||count>65536||start+count>stream.length())break;
            if(header.startsWith(method)){
                Matcher field=Pattern.compile("(?m)^"+key+": ([^\\r\\n]+)").matcher(stream.substring(start,start+count));
                if(field.find())value=field.group(1);
            }
            p=start+count;
        }
        return value;
    }
}
