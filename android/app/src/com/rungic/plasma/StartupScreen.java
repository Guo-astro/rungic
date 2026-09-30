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
        retry=new Button(activity); retry.setText(R.string.startup_retry); retry.setOnClickListener(v->check.run()); body.addView(retry);
        details=new Button(activity); details.setText(R.string.startup_details);
        details.setOnClickListener(v->{
            TextView text=new TextView(activity); text.setText(detailText); text.setTextIsSelectable(true); text.setPadding(pad,pad,pad,pad);
            new AlertDialog.Builder(activity).setTitle(R.string.startup_details_title).setView(text).setPositiveButton(R.string.action_close,null).show();
        }); body.addView(details);
        Button exit=new Button(activity); exit.setText(R.string.leave_for_later); exit.setOnClickListener(v->leave.run()); body.addView(exit);
    }
    void show(String heading,String body,boolean busy,boolean canRetry,String info) {
        setVisibility(VISIBLE); title.setText(heading);
        if(!message.getText().toString().equals(body))message.setText(body);
        spinner.setVisibility(busy?VISIBLE:GONE); retry.setVisibility(canRetry?VISIBLE:GONE);
        detailText=info; details.setVisibility(info.isEmpty()?GONE:VISIBLE);
    }
    /** The install state's message in the system language (FirstBootState stays free of Android). */
    static String message(android.content.Context context,FirstBootState state) {
        int id;
        switch(state.message) {
            case VERIFY: id=R.string.install_verify; break;
            case RUNTIME: id=R.string.install_runtime; break;
            case ROOTFS: id=R.string.install_rootfs; break;
            case CONFIGURE: id=R.string.install_configure; break;
            case STORAGE_WAIT: id=R.string.install_storage; break;
            case FINISH: id=R.string.install_finish; break;
            case FAILED_CHECKSUM: id=R.string.install_failed_checksum; break;
            case FAILED_SPACE: id=R.string.install_failed_space; break;
            case FAILED_STORAGE: id=R.string.install_failed_storage; break;
            case FAILED: id=R.string.install_failed; break;
            case WAITING: id=R.string.install_waiting; break;
            default: return "";
        }
        String text=context.getString(id);
        return state.stale ? text+"\n"+context.getString(R.string.install_stale) : text;
    }
    static String details(android.content.Context context,FirstBootState state) {
        if(state.reason==null)
            return context.getString(R.string.install_details,state.release,state.phase,state.state,state.code);
        switch(state.reason) {
            case STANDALONE: return context.getString(R.string.install_reason_standalone);
            case RELEASE_MISMATCH: return context.getString(R.string.install_reason_release);
            case SCHEMA_UNSUPPORTED: return context.getString(R.string.install_reason_schema);
            case STATE_INCOMPLETE: return context.getString(R.string.install_reason_incomplete);
            case PHASE_UNKNOWN: return context.getString(R.string.install_reason_phase);
            default: return context.getString(R.string.install_reason_unreadable);
        }
    }
}
