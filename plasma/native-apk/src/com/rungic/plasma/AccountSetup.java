package com.rungic.plasma;

import android.app.Activity;
import android.app.AlertDialog;
import android.text.InputType;
import android.view.View;
import android.view.WindowManager;
import android.widget.*;
import org.json.JSONObject;
import java.util.concurrent.Executor;

/** First-run form. Passwords travel only over the root process stdin pipe. */
final class AccountSetup {
    interface Submit { void apply(String json) throws Exception; }
    static void show(Activity activity, Executor worker, Submit submit, Runnable done) {
        int padding=(int)(20*activity.getResources().getDisplayMetrics().density);
        LinearLayout fields=new LinearLayout(activity);
        fields.setOrientation(LinearLayout.VERTICAL);
        fields.setPadding(padding,padding,padding,padding);
        TextView explanation=new TextView(activity);
        explanation.setText("设置你的 Linux 账户。安装软件和更改系统设置时，会使用这个密码。现有应用和文件会保留。");
        fields.addView(explanation);
        EditText username=new EditText(activity);
        username.setHint("用户名（小写字母开头）");
        username.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        username.setSingleLine(true); username.setText("linux");
        username.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        fields.addView(username);
        EditText password=new EditText(activity);
        password.setHint("密码（至少8个字符）");
        password.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);
        password.setSingleLine(true); password.setSaveEnabled(false);
        password.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        fields.addView(password);
        EditText confirmation=new EditText(activity);
        confirmation.setHint("再次输入密码");
        confirmation.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);
        confirmation.setSingleLine(true); confirmation.setSaveEnabled(false);
        confirmation.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        fields.addView(confirmation);
        TextView message=new TextView(activity); fields.addView(message);
        ScrollView scroll=new ScrollView(activity); scroll.addView(fields);
        AlertDialog dialog=new AlertDialog.Builder(activity).setTitle("设置 Plasma Mobile 账户")
            .setView(scroll).setPositiveButton("保存并进入桌面",null)
            .setNegativeButton("稍后",(d,w)->activity.finish()).create();
        dialog.setCancelable(false);
        dialog.setOnShowListener(ignored -> {
            dialog.getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
            dialog.getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
                String name=username.getText().toString().trim();
                String secret=password.getText().toString();
                if(!name.matches("[a-z][a-z0-9_-]{0,31}")) {username.setError("用户名最多32位，以小写字母开头");return;}
                if(secret.length()<8 || secret.getBytes(java.nio.charset.StandardCharsets.UTF_8).length>256
                        || secret.indexOf('\n')>=0 || secret.indexOf('\r')>=0 || secret.indexOf('\0')>=0) {
                    password.setError("密码至少8个字符，且不能包含换行");return;
                }
                if(!secret.equals(confirmation.getText().toString())) {confirmation.setError("两次密码不一致");return;}
                final String payload;
                try {payload=new JSONObject().put("username",name).put("password",secret).toString();}
                catch(Exception e) {message.setText("无法准备账户信息");return;}
                password.setText(""); confirmation.setText("");
                username.setEnabled(false);password.setEnabled(false);confirmation.setEnabled(false);
                dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(false);
                dialog.getButton(AlertDialog.BUTTON_NEGATIVE).setEnabled(false);
                message.setText("正在设置账户…");
                worker.execute(() -> {
                    try {
                        submit.apply(payload);
                        activity.runOnUiThread(() -> {dialog.dismiss();done.run();});
                    } catch(Exception e) {
                        // The helper returns only predefined messages, never request data.
                        activity.runOnUiThread(() -> {
                            message.setText(e.getMessage()==null?"设置失败，请重试":e.getMessage());
                            username.setEnabled(true);password.setEnabled(true);confirmation.setEnabled(true);
                            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(true);
                            dialog.getButton(AlertDialog.BUTTON_NEGATIVE).setEnabled(true);
                        });
                    }
                });
            });
        });
        dialog.show();
    }
}
