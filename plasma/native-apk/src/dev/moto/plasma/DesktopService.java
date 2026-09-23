package dev.moto.plasma;

import android.app.*;
import android.content.Intent;
import android.os.IBinder;

public final class DesktopService extends Service {
    @Override public void onCreate() {
        super.onCreate();
        getSystemService(NotificationManager.class).createNotificationChannel(
            new NotificationChannel("desktop", "Plasma Mobile", NotificationManager.IMPORTANCE_LOW));
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        startForeground(1, new Notification.Builder(this, "desktop")
            .setSmallIcon(android.R.drawable.ic_menu_view).setContentTitle("Plasma Mobile正在运行")
            .setContentText("点此返回 Plasma Mobile").setContentIntent(open).setOngoing(true).build());
    }
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public int onStartCommand(Intent intent, int flags, int id) { return START_NOT_STICKY; }
}
