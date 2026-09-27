package com.rungic.plasma;

import android.app.Activity;
import android.app.AlertDialog;
import android.view.Gravity;
import android.view.View;
import android.widget.*;

/** Shared waiting/recovery surface. Buttons describe actions, never raw shell errors. */
final class StartupScreen extends ScrollView {
    private final TextView title, message;
    private final ProgressBar spinner;
    private final Button retry, details;
    private String detailText="";
    StartupScreen(Activity activity,Runnable check,Runnable leave) {
        super(activity);
        setFillViewport(true);
        LinearLayout body=new LinearLayout(activity); body.setOrientation(LinearLayout.VERTICAL); body.setGravity(Gravity.CENTER);
        addView(body,new ScrollView.LayoutParams(-1,-1));
        int pad=(int)(24*getResources().getDisplayMetrics().density);
        body.setPadding(pad,pad,pad,pad); setBackgroundColor(0xff16212b);
        title=new TextView(activity); title.setTextColor(0xffeef3f8); title.setTextSize(24);
        title.setGravity(Gravity.CENTER); title.setAccessibilityHeading(true); body.addView(title);
        spinner=new ProgressBar(activity); spinner.setIndeterminate(true); body.addView(spinner);
        message=new TextView(activity); message.setTextColor(0xffeef3f8); message.setTextSize(17);
        message.setGravity(Gravity.CENTER); message.setPadding(0,pad,0,pad);
        message.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE); body.addView(message);
        retry=new Button(activity); retry.setText("重新检查"); retry.setOnClickListener(v->check.run()); body.addView(retry);
        details=new Button(activity); details.setText("查看详情");
        details.setOnClickListener(v->{
            TextView text=new TextView(activity); text.setText(detailText); text.setTextIsSelectable(true); text.setPadding(pad,pad,pad,pad);
            new AlertDialog.Builder(activity).setTitle("Rungic 状态详情").setView(text).setPositiveButton("关闭",null).show();
        }); body.addView(details);
        Button exit=new Button(activity); exit.setText("返回 Android，稍后继续"); exit.setOnClickListener(v->leave.run()); body.addView(exit);
    }
    void show(String heading,String body,boolean busy,boolean canRetry,String info) {
        setVisibility(VISIBLE); title.setText(heading);
        if(!message.getText().toString().equals(body))message.setText(body);
        spinner.setVisibility(busy?VISIBLE:GONE); retry.setVisibility(canRetry?VISIBLE:GONE);
        detailText=info; details.setVisibility(info.isEmpty()?GONE:VISIBLE);
    }
}
