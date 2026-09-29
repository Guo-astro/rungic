// SPDX-License-Identifier: MIT
package com.rungic.clipboardtest;
import android.app.Activity;
import android.os.*;
import android.content.*;
import android.net.Uri;
import android.widget.*;
import java.io.*;
/** Independent foreground application for on-device clipboard acceptance. Never stores pasted text. */
public final class MainActivity extends Activity {
    public static final String TEXT="Rungic 后台 Android 📋\n第二行";
    private ClipboardManager clipboard;
    private TextView status;
    private void button(LinearLayout root,String label,Runnable run){
        Button b=new Button(this);b.setText(label);b.setOnClickListener(v->run.run());root.addView(b,new LinearLayout.LayoutParams(-1,150));
    }
    @Override public void onCreate(Bundle b){
        super.onCreate(b);clipboard=getSystemService(ClipboardManager.class);
        LinearLayout root=new LinearLayout(this);root.setOrientation(1);root.setPadding(30,100,30,50);
        status=new TextView(this);status.setText("Independent Android clipboard test");root.addView(status);
        button(root,"Copy Android test",()->clipboard.setPrimaryClip(ClipData.newPlainText("test",TEXT)));
        button(root,"Paste and check Linux test",()->{
            ClipData c=clipboard.getPrimaryClip();CharSequence t=c==null?null:c.getItemAt(0).getText();
            boolean ok=t!=null && t.toString().equals("Rungic 后台 Linux 📋\n历史选择");
            status.setText("Paste matches Linux: "+ok);
            try(FileWriter f=new FileWriter(new File(getFilesDir(),"result.json"))){f.write("{\"paste_matches\":"+ok+"}");}catch(Exception ignored){}
        });
        button(root,"Copy sensitive test",()->{
            ClipData c=ClipData.newPlainText("test", "Rungic SENSITIVE TEST ONLY");
            PersistableBundle extras=new PersistableBundle();extras.putBoolean("android.content.extra.IS_SENSITIVE",true);
            c.getDescription().setExtras(extras);clipboard.setPrimaryClip(c);
        });
        button(root,"Copy non-text test",()->clipboard.setPrimaryClip(ClipData.newRawUri("test",Uri.parse("https://example.invalid/rungic-test"))));
        button(root,"Clear Android",()->clipboard.clearPrimaryClip());
        setContentView(root);
    }
}
