package com.rungic.plasma;

import android.app.Activity;
import android.app.AlertDialog;
import android.text.InputType;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.text.method.PasswordTransformationMethod;
import java.util.function.Consumer;
import android.view.WindowManager;
import android.widget.*;
import org.json.JSONObject;
import java.util.concurrent.Executor;

/** First-run form. Passwords travel only over the root process stdin pipe. */
final class AccountSetup {
    interface Submit { void apply(String json) throws Exception; }
    static void show(Activity activity, Executor worker, Submit submit, Runnable done, Consumer<Exception> failed) {
        int padding=(int)(20*activity.getResources().getDisplayMetrics().density);
        LinearLayout fields=new LinearLayout(activity);
        fields.setOrientation(LinearLayout.VERTICAL);
        fields.setPadding(padding,padding,padding,padding);
        TextView explanation=new TextView(activity);
        explanation.setText("此密码用于安装软件和更改系统设置，与手机解锁密码不同。返回 Android 后，下次打开 Rungic 可以继续配置。");
        fields.addView(explanation);
        EditText username=new EditText(activity);
        username.setHint("用户名（小写字母开头）");
        username.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        username.setSingleLine(true); username.setText(activity.getPreferences(Activity.MODE_PRIVATE).getString("setup-username","linux"));
        username.setImeOptions(EditorInfo.IME_ACTION_NEXT);
        username.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        addField(fields,username,"用户名");
        EditText password=new EditText(activity);
        password.setHint("密码（至少8个字符）");
        password.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);
        password.setSingleLine(true); password.setSaveEnabled(false);
        password.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        password.setImeOptions(EditorInfo.IME_ACTION_NEXT);
        addField(fields,password,"密码");
        EditText confirmation=new EditText(activity);
        confirmation.setHint("再次输入密码");
        confirmation.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);
        confirmation.setSingleLine(true); confirmation.setSaveEnabled(false);
        confirmation.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        confirmation.setImeOptions(EditorInfo.IME_ACTION_DONE);
        addField(fields,confirmation,"再次输入密码");
        CheckBox visible=new CheckBox(activity); visible.setText("显示密码");
        visible.setOnCheckedChangeListener((button,checked)->{
            password.setTransformationMethod(checked?null:PasswordTransformationMethod.getInstance());
            confirmation.setTransformationMethod(checked?null:PasswordTransformationMethod.getInstance());
            password.setSelection(password.length()); confirmation.setSelection(confirmation.length());
        }); fields.addView(visible);
        TextView message=new TextView(activity); fields.addView(message);
        ScrollView scroll=new ScrollView(activity); scroll.addView(fields);
        AlertDialog dialog=new AlertDialog.Builder(activity).setTitle("创建 Rungic 账户")
            .setView(scroll).setPositiveButton("创建账户并进入桌面",null)
            .setNegativeButton("返回 Android，稍后继续",(d,w)->activity.finish()).create();
        dialog.setCancelable(false);
        dialog.setOnShowListener(ignored -> {
            dialog.getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
            dialog.getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
                String name=username.getText().toString().trim();
                String secret=password.getText().toString();
                if(!name.matches("[a-z][a-z0-9_-]{0,31}")) {username.setError("用户名最多32位，以小写字母开头");return;}
                if(secret.codePointCount(0,secret.length())<8 || secret.getBytes(java.nio.charset.StandardCharsets.UTF_8).length>256
                        || secret.indexOf('\n')>=0 || secret.indexOf('\r')>=0 || secret.indexOf('\0')>=0) {
                    password.setError("密码至少8个字符，UTF-8 编码不超过256字节，且不能包含换行或空字符");return;
                }
                if(!secret.equals(confirmation.getText().toString())) {confirmation.setError("两次密码不一致");return;}
                final String payload;
                try {payload=new JSONObject().put("username",name).put("password",secret).toString();}
                catch(Exception e) {message.setText("无法准备账户信息");return;}
                activity.getPreferences(Activity.MODE_PRIVATE).edit().putString("setup-username",name).apply();
                password.setText(""); confirmation.setText(""); visible.setChecked(false);
                username.setEnabled(false);password.setEnabled(false);confirmation.setEnabled(false);
                dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(false);
                dialog.getButton(AlertDialog.BUTTON_NEGATIVE).setEnabled(false);
                message.setText("正在设置账户…");
                worker.execute(() -> {
                    try {
                        submit.apply(payload);
                        activity.runOnUiThread(() -> {if(activity.isDestroyed())return; dialog.dismiss();done.run();});
                    } catch(Exception e) {
                        activity.runOnUiThread(() -> {
                            if(activity.isDestroyed())return;
                            String reason=e.getMessage()==null?"":e.getMessage().trim();
                            if(reason.equals("这个用户名已被使用") || reason.equals("这个用户名的主目录已存在")) {
                                username.setError("这个用户名无法使用，请换一个用户名");
                                message.setText("账户尚未创建，请修改用户名并重新输入密码。");
                                username.setEnabled(true);password.setEnabled(true);confirmation.setEnabled(true);
                                dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(true);
                                dialog.getButton(AlertDialog.BUTTON_NEGATIVE).setEnabled(true);
                            } else { dialog.dismiss(); failed.accept(e); }
                        });
                    }
                });
            });
            confirmation.setOnEditorActionListener((view,action,event)->{
                if(action==EditorInfo.IME_ACTION_DONE) { dialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick(); return true; }
                return false;
            });
        });
        dialog.show();
    }
    private static void addField(LinearLayout fields,EditText input,String label) {
        input.setId(View.generateViewId());
        TextView text=new TextView(fields.getContext()); text.setText(label); text.setLabelFor(input.getId());
        fields.addView(text); fields.addView(input);
    }
}
