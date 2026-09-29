// SPDX-License-Identifier: MIT
package com.rungic.cast;

import java.util.*;

/** Wi-Fi Display 2.1 tables 71-73. Protocol data, not receiver or phone profiles. */
final class WfdFormats {
    static final class Mode {
        final int family, bit, width, height, fps; final boolean interlaced;
        Mode(int f,int b,int w,int h,int rate,boolean i) {family=f;bit=b;width=w;height=h;fps=rate;interlaced=i;}
        String id() { return width+"x"+height+"@"+fps+(interlaced ? "i" : ""); }
        String label() { return width+" × "+height+" · "+fps+" fps"; }
    }
    static final List<Mode> TABLE = new ArrayList<>();
    static {
        int[][] cea={{640,480,60},{720,480,60},{720,480,60},{720,576,50},{720,576,50},
            {1280,720,30},{1280,720,60},{1920,1080,30},{1920,1080,60},{1920,1080,60},
            {1280,720,25},{1280,720,50},{1920,1080,25},{1920,1080,50},{1920,1080,50},
            {1280,720,24},{1920,1080,24},{3840,2160,24},{3840,2160,25},{3840,2160,30},
            {3840,2160,50},{3840,2160,60},{4096,2160,24},{4096,2160,25},{4096,2160,30},
            {4096,2160,50},{4096,2160,60}};
        for(int b=0;b<cea.length;b++) TABLE.add(new Mode(0,b,cea[b][0],cea[b][1],cea[b][2],b==2||b==4||b==9||b==14));
        int[][] vesa={{800,600},{1024,768},{1152,864},{1280,768},{1280,800},{1360,768},{1366,768},
            {1280,1024},{1400,1050},{1440,900},{1600,900},{1600,1200},{1680,1024},{1680,1050},
            {1920,1200},{2560,1440},{2560,1600}};
        for(int b=0;b<vesa.length*2;b++) TABLE.add(new Mode(1,b,vesa[b/2][0],vesa[b/2][1],b%2==0?30:60,false));
        int[][] hh={{800,480},{854,480},{864,480},{640,360},{960,540},{848,480}};
        for(int b=0;b<hh.length*2;b++) TABLE.add(new Mode(2,b,hh[b/2][0],hh[b/2][1],b%2==0?30:60,false));
    }
    static Mode find(String id) { for(Mode m:TABLE)if(m.id().equals(id))return m; return null; }
    static final class Codec {
        final int codec, profile, level; final long[] masks;
        Codec(int c,int p,int l,long[] m){codec=c;profile=p;level=l;masks=m;}
        boolean contains(Mode m){return (masks[m.family] & (1L<<m.bit))!=0;}
    }
    static List<Codec> parse(String value, boolean r2) {
        List<Codec> out=new ArrayList<>();
        String[] entries=value.trim().split(",");
        for(int i=0;i<entries.length;i++) {
            String[] t=entries[i].trim().split("\\s+");
            int p=i==0?(r2?1:2):0;
            if(t.length-p<(r2?10:9))throw new IllegalArgumentException("Truncated WFD video formats");
            int codec=r2?hex(t[p++]):1;
            int profile=hex(t[p++]),level=hex(t[p++]);
            long[] masks={Long.parseLong(t[p++],16),Long.parseLong(t[p++],16),Long.parseLong(t[p++],16)};
            if((codec!=1&&codec!=2)||profile==0||level==0)continue;
            if(!r2) { masks[0]&=(1L<<17)-1; masks[1]&=(1L<<29)-1; masks[2]&=(1L<<12)-1; }
            for(long mask:masks)if(mask<0 || mask>0xffffffffffffL)throw new IllegalArgumentException("Invalid mode bitmap");
            out.add(new Codec(codec,profile,level,masks));
        }
        return out;
    }
    private static int hex(String v) {return Integer.parseInt(v,16);}
}
