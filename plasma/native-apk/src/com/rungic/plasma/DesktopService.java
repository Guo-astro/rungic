package com.rungic.plasma;

import android.app.*;
import android.content.Context;
import android.content.Intent;
import android.os.IBinder;

public final class DesktopService extends Service {
    static void update(Context context,String state) {
        context.startForegroundService(new Intent(context,DesktopService.class).putExtra("state",state));
    }
    private Notification notification(String state) {
        PendingIntent open=PendingIntent.getActivity(this,0,new Intent(this,MainActivity.class),PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this,"desktop").setSmallIcon(android.R.drawable.ic_menu_view)
            .setContentTitle(state).setContentText(getString(R.string.notification_return)).setContentIntent(open)
            .setOnlyAlertOnce(true).setOngoing(true).build();
    }
    @Override public void onCreate() {
        super.onCreate();
        getSystemService(NotificationManager.class).createNotificationChannel(
            new NotificationChannel("desktop","Rungic",NotificationManager.IMPORTANCE_LOW));
        startForeground(1,notification(getString(R.string.state_preparing)));
    }
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public int onStartCommand(Intent intent,int flags,int id) {
        String state=intent==null?null:intent.getStringExtra("state");
        if(state!=null)getSystemService(NotificationManager.class).notify(1,notification(state));
        return START_NOT_STICKY;
    }
}
