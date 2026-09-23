package dev.moto.plasma;

import android.app.*;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.IBinder;

/** Explicit camera/microphone FGS; never starts a capture by itself. */
public final class CaptureService extends Service {
    @Override public void onCreate() {
        super.onCreate();
        getSystemService(NotificationManager.class).createNotificationChannel(
            new NotificationChannel("capture","Linux 麦克风与相机",NotificationManager.IMPORTANCE_LOW));
    }
    @Override public int onStartCommand(Intent intent,int flags,int id) {
        boolean mic=intent!=null && intent.getBooleanExtra("microphone",false);
        boolean camera=intent!=null && intent.getBooleanExtra("camera",false);
        if(!mic && !camera) { stopSelf();return START_NOT_STICKY; }
        String title=mic && camera?"Linux 正在使用相机和麦克风":mic?"Linux 正在使用麦克风":"Linux 正在使用相机";
        PendingIntent open=PendingIntent.getActivity(this,0,new Intent(this,MainActivity.class),PendingIntent.FLAG_IMMUTABLE);
        startForeground(2,new Notification.Builder(this,"capture").setSmallIcon(android.R.drawable.ic_menu_camera)
            .setContentTitle(title).setContentText("退出采集应用或离开 Plasma Mobile可停止采集").setContentIntent(open).setOngoing(true).build(),
            (mic?ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE:0)|(camera?ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA:0));
        return START_NOT_STICKY;
    }
    @Override public IBinder onBind(Intent intent) { return null; }
}
