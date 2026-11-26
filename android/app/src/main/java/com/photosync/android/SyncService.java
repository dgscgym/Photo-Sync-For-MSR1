package com.photosync.android;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.os.*;
import java.util.concurrent.atomic.AtomicBoolean;

public final class SyncService extends Service {
    private final AtomicBoolean cancelled=new AtomicBoolean(false);private Thread thread;
    static final String CHANNEL="photosync-upload";
    static void channel(Context c){c.getSystemService(NotificationManager.class).createNotificationChannel(new NotificationChannel(CHANNEL,"相册同步",NotificationManager.IMPORTANCE_LOW));}
    static Notification notice(Context c,String text){
        Intent stop=new Intent(c,SyncService.class).setAction("stop");
        return new Notification.Builder(c,CHANNEL).setSmallIcon(android.R.drawable.stat_sys_upload).setContentTitle("PhotoSync 同步").setContentText(text).setOngoing(true)
            .setContentIntent(PendingIntent.getActivity(c,1,new Intent(c,MainActivity.class),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT))
            .addAction(new Notification.Action.Builder(null,"暂停",PendingIntent.getService(c,2,stop,PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT)).build()).build();
    }
    public int onStartCommand(Intent intent,int flags,int id){
        if(intent!=null&&"stop".equals(intent.getAction())){cancelled.set(true);stopSelf();return START_NOT_STICKY;}
        channel(this);if(Build.VERSION.SDK_INT>=29)startForeground(10,notice(this,"准备同步…"),ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);else startForeground(10,notice(this,"准备同步…"));
        if(thread!=null)return START_NOT_STICKY;
        final boolean scan=intent==null||intent.getBooleanExtra("scan",true);
        thread=new Thread(()->{try{new SyncEngine(this,cancelled,this::report,System.currentTimeMillis()+5*60*60*1000L).run(false,scan);}catch(Exception e){report(e.getMessage());}finally{stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();}},"photosync-upload");thread.start();return START_NOT_STICKY;
    }
    void report(String text){new Settings(this).put("sync_status",text);getSystemService(NotificationManager.class).notify(10,notice(this,text));}
    public void onTimeout(int id,int type){cancelled.set(true);report("达到系统同步时限，进度已保留");stopSelf();}
    public void onDestroy(){cancelled.set(true);super.onDestroy();}
    public IBinder onBind(Intent intent){return null;}
}
