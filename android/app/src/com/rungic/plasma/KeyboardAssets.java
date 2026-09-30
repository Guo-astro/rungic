package com.rungic.plasma;

import android.content.Context;
import java.io.*;
import java.util.zip.*;

/** Native xkbcommon data, installed by the APK under its own SELinux label. */
final class KeyboardAssets {
    static void ensure(Context context) throws IOException {
        File root = new File(context.getFilesDir(), "rootfs_ubuntu/usr/share/X11/xkb");
        File marker = new File(root, ".rungic-assets-1");
        if (marker.isFile() && new File(root, "rules/evdev").isFile()) return;
        if (!root.isDirectory() && !root.mkdirs()) throw new IOException("无法创建键盘目录");
        String prefix = root.getCanonicalPath() + File.separator;
        try (ZipInputStream input = new ZipInputStream(context.getAssets().open("xkb.zip"))) {
            ZipEntry entry;
            byte[] block = new byte[16384];
            while ((entry = input.getNextEntry()) != null) {
                File target = new File(root, entry.getName());
                if (!target.getCanonicalPath().startsWith(prefix)) throw new IOException("Invalid keyboard asset");
                if (entry.isDirectory()) { target.mkdirs(); continue; }
                File parent = target.getParentFile();
                if (!parent.isDirectory() && !parent.mkdirs()) throw new IOException("无法创建键盘目录");
                try (OutputStream output = new FileOutputStream(target)) {
                    int count;
                    while ((count = input.read(block)) != -1) output.write(block, 0, count);
                }
            }
        }
        if (!new File(root, "rules/evdev").isFile()) throw new IOException("键盘布局数据不完整");
        try (OutputStream output = new FileOutputStream(marker)) { output.write(1); }
    }
}
