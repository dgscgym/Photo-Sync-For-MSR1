package com.photosync.android;

import android.app.job.*;
import android.content.*;
import android.os.PersistableBundle;
import java.util.concurrent.atomic.AtomicBoolean;

public final class SyncJob extends JobService {
    static final int PERIODIC=12001,ONCE=12002;
    private final AtomicBoolean cancelled=new AtomicBoolean(false);
    static void schedule(Context context){
        JobScheduler jobs=context.getSystemService(JobScheduler.class);Settings s=new Settings(context);
        if(!s.flag("auto")){jobs.cancel(PERIODIC);jobs.cancel(ONCE);return;}
        jobs.schedule(new JobInfo.Builder(PERIODIC,new ComponentName(context,SyncJob.class)).setRequiredNetworkType(JobInfo.NETWORK_TYPE_UNMETERED).setPeriodic(15*60*1000L).setPersisted(true).build());
    }
    static void wake(Context context){if(new Settings(context).flag("auto"))context.getSystemService(JobScheduler.class).schedule(new JobInfo.Builder(ONCE,new ComponentName(context,SyncJob.class)).setRequiredNetworkType(JobInfo.NETWORK_TYPE_UNMETERED).setMinimumLatency(1000).setBackoffCriteria(30000,JobInfo.BACKOFF_POLICY_EXPONENTIAL).build());}
    public boolean onStartJob(JobParameters params){
        cancelled.set(false);new Thread(()->{
            boolean retry=false;Settings s=new Settings(this);
            try{new SyncEngine(this,cancelled,text->s.put("sync_status",text),System.currentTimeMillis()+7*60*1000).run(true,true);}
            catch(Exception e){s.put("sync_status",e.getMessage());retry=!(e instanceof Api.Failure&&((Api.Failure)e).status==401);}
            if(!cancelled.get())jobFinished(params,retry);
        },"photosync-auto").start();return true;
    }
    public boolean onStopJob(JobParameters params){cancelled.set(true);return true;}
}
