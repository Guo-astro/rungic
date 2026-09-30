package com.rungic.plasma;

import java.nio.file.*;
import java.nio.charset.StandardCharsets;

/** Boundary checks for the first-install account gate; no Android device needed. */
public final class FirstBootStateTest {
    static void write(Path p,String text) throws Exception { Files.write(p,text.getBytes(StandardCharsets.UTF_8)); }
    static void require(boolean value) { if(!value)throw new AssertionError(); }
    public static void main(String[] args) throws Exception {
        Path root=Files.createTempDirectory(Paths.get(args[0]),"firstboot-state-");
        Path seed=root.resolve("seed.env"), status=root.resolve("status");
        require(FirstBootState.read(seed.toFile(),status.toFile()).ready);
        write(seed,"RELEASE_ID='release-new'\n");
        require(!FirstBootState.read(seed.toFile(),status.toFile()).ready);
        write(status,"release=release-old\nstate=ready\n");
        require(!FirstBootState.read(seed.toFile(),status.toFile()).ready);
        for(String phase:new String[]{"verify","runtime","rootfs","configure","storage","finish"}) {
            write(status,"release=release-new\nstate=installing\nphase="+phase+"\n");
            FirstBootState state=FirstBootState.read(seed.toFile(),status.toFile());
            require(!state.ready && !state.failed && state.message!=FirstBootState.Message.NONE && state.reason==null);
        }
        write(status,"release=release-new\nstate=failed\n");
        require(FirstBootState.read(seed.toFile(),status.toFile()).failed);
        write(status,"release=release-new\nstate=ready\n");
        require(FirstBootState.read(seed.toFile(),status.toFile()).ready);
        write(status,"release=release-new\nstate=re");
        require(!FirstBootState.read(seed.toFile(),status.toFile()).ready);
        write(status,"release=release-new\nstate=\\uNOPE\n");
        require(!FirstBootState.read(seed.toFile(),status.toFile()).ready);
        write(status,"schema=2\nrelease=release-new\nstate=failed\nerror=checksum\nphase=verify\n");
        FirstBootState corrupt=FirstBootState.read(seed.toFile(),status.toFile());
        require(corrupt.failed && corrupt.message==FirstBootState.Message.FAILED_CHECKSUM && !corrupt.ready);
        write(status,"schema=2\nrelease=release-new\nstate=waiting\nphase=storage\n");
        require(FirstBootState.read(seed.toFile(),status.toFile()).attention);
        write(status,"schema=2\nrelease=release-new\nstate=installing\nphase=rootfs\n");
        FirstBootState stale=FirstBootState.read(seed.toFile(),status.toFile(),status.toFile().lastModified()+181000);
        require(stale.attention && stale.stale && stale.message==FirstBootState.Message.ROOTFS);
        require(!FirstBootState.read(seed.toFile(),status.toFile(),status.toFile().lastModified()).attention);
        write(status,"schema=999\nrelease=release-new\nstate=ready\n");
        FirstBootState future=FirstBootState.read(seed.toFile(),status.toFile());
        require(!future.ready && future.message==FirstBootState.Message.WAITING && future.reason==FirstBootState.Reason.SCHEMA_UNSUPPORTED);
        write(status,"schema=2\nrelease=release-new\nstate=ready\nphase=complete\n");
        require(FirstBootState.read(seed.toFile(),status.toFile()).ready);
        System.out.println("PASS readiness, v1/v2, unknown schema, stale state, user action, checksum failure and malformed input");
    }
}
