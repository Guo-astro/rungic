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
            require(!state.ready && !state.failed && !state.message.isEmpty());
        }
        write(status,"release=release-new\nstate=failed\n");
        require(FirstBootState.read(seed.toFile(),status.toFile()).failed);
        write(status,"release=release-new\nstate=ready\n");
        require(FirstBootState.read(seed.toFile(),status.toFile()).ready);
        write(status,"release=release-new\nstate=re");
        require(!FirstBootState.read(seed.toFile(),status.toFile()).ready);
        write(status,"release=release-new\nstate=\\uNOPE\n");
        require(!FirstBootState.read(seed.toFile(),status.toFile()).ready);
        System.out.println("PASS first-install readiness, release mismatch, stages, failure, truncated and malformed status");
    }
}
