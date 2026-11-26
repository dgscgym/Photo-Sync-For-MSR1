package com.photosync.android;
import android.content.*;
public final class BootReceiver extends BroadcastReceiver {public void onReceive(Context context,Intent intent){if(Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction()))SyncJob.schedule(context);}}
