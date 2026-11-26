package com.photosync.android;

import android.content.*;
import android.database.Cursor;
import android.net.*;
import android.net.wifi.*;
import android.os.*;
import android.provider.*;
import org.json.*;
import java.io.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;

final class SyncEngine {
    static final long MAX=10L*1024*1024*1024;
    static final AtomicBoolean RUNNING=new AtomicBoolean(false);
    interface Progress {void show(String message);}
    final Context context;final Settings settings;final Api api;final SyncDb db;final AtomicBoolean cancelled;final Progress progress;
    final long deadline;
    SyncEngine(Context c,AtomicBoolean cancelled,Progress progress,long deadline){context=c;settings=new Settings(c);api=new Api(settings);db=new SyncDb(c);this.cancelled=cancelled;this.progress=progress;this.deadline=deadline;}
    static boolean media(String name,String type){return type.startsWith("image/")||type.startsWith("video/")||name.toLowerCase(Locale.ROOT).matches(".*\\.(jpg|jpeg|png|gif|webp|heic|heif|mp4|mov|webm)$");}
    void enqueue(Uri uri) throws Exception {
        try(Cursor c=context.getContentResolver().query(uri,new String[]{OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE},null,null,null)){
            if(c==null||!c.moveToFirst())throw new IOException("文件不可读取");
            String name=c.getString(0);long size=c.isNull(1)?-1:c.getLong(1);long modified=0;
            if(DocumentsContract.isDocumentUri(context,uri))try(Cursor meta=context.getContentResolver().query(uri,new String[]{DocumentsContract.Document.COLUMN_LAST_MODIFIED},null,null,null)){if(meta!=null&&meta.moveToFirst())modified=meta.getLong(0);}
            if(!media(name,Objects.toString(context.getContentResolver().getType(uri),"")))return;
            if(size<=0||size>MAX)throw new IOException(name+"：文件大小未知、为空或超过 10 GiB");
            db.enqueue(settings.scope(),uri,name,size,modified);
        }
    }
    void scan() throws Exception {
        JSONArray albums=settings.albums();Set<String> visited=new HashSet<>();
        for(int i=0;i<albums.length();i++){
            Uri tree=Uri.parse(albums.getString(i));ArrayDeque<String> directories=new ArrayDeque<>();directories.add(DocumentsContract.getTreeDocumentId(tree));
            while(!directories.isEmpty()){
                check(false);String id=directories.removeFirst();if(!visited.add(tree.getAuthority()+":"+id))continue;
                if(visited.size()>100000)throw new IOException("目录超过 100000 个，请缩小同步范围");
                Uri children=DocumentsContract.buildChildDocumentsUriUsingTree(tree,id);
                try(Cursor cursor=context.getContentResolver().query(children,new String[]{DocumentsContract.Document.COLUMN_DOCUMENT_ID,DocumentsContract.Document.COLUMN_DISPLAY_NAME,DocumentsContract.Document.COLUMN_MIME_TYPE,DocumentsContract.Document.COLUMN_SIZE,DocumentsContract.Document.COLUMN_LAST_MODIFIED},null,null,null)){
                    if(cursor==null)throw new IOException("目录权限已失效，请重新选择相册");
                    while(cursor.moveToNext()){
                        check(false);String child=cursor.getString(0),name=cursor.getString(1),type=cursor.getString(2);
                        if(DocumentsContract.Document.MIME_TYPE_DIR.equals(type))directories.add(child);
                        else if(media(name,type)){
                            long size=cursor.getLong(3);if(size<=0||size>MAX)continue;
                            db.enqueue(settings.scope(),DocumentsContract.buildDocumentUriUsingTree(tree,child),name,size,cursor.getLong(4));
                        }
                    }
                }
            }
        }
    }
    static String wifi(Context context){
        try{
            ConnectivityManager cm=context.getSystemService(ConnectivityManager.class);NetworkCapabilities caps=cm.getNetworkCapabilities(cm.getActiveNetwork());
            if(caps==null||!caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI))return "";
            WifiManager wm=(WifiManager)context.getApplicationContext().getSystemService(Context.WIFI_SERVICE);String ssid=wm.getConnectionInfo().getSSID();
            if(ssid==null||ssid.equals(WifiManager.UNKNOWN_SSID))return "";return ssid.replaceAll("^\"|\"$", "");
        }catch(SecurityException e){return "";}
    }
    void check(boolean automatic) throws IOException {
        if(cancelled.get()||Thread.currentThread().isInterrupted()||System.currentTimeMillis()>deadline)throw new InterruptedIOException("同步暂停，进度已保留");
        if(automatic&&(!settings.flag("auto")||settings.get("ssid").isEmpty()||!settings.get("ssid").equals(wifi(context))))throw new InterruptedIOException("等待指定 Wi-Fi 或定位权限，未使用其他网络上传");
    }
    void upload(SyncDb.FileItem f,boolean automatic) throws Exception {
        Uri uri=Uri.parse(f.uri);
        // Detect changed files before reusing a persisted upload session.
        try(Cursor c=context.getContentResolver().query(uri,new String[]{OpenableColumns.SIZE},null,null,null)){if(c==null||!c.moveToFirst()||c.getLong(0)!=f.size)throw new IOException("源文件大小变化，请重新扫描");}
        if(DocumentsContract.isDocumentUri(context,uri))try(Cursor c=context.getContentResolver().query(uri,new String[]{DocumentsContract.Document.COLUMN_LAST_MODIFIED},null,null,null)){if(c!=null&&c.moveToFirst()&&c.getLong(0)!=f.modified)throw new IOException("源文件修改时间变化，请重新扫描");}
        JSONObject session=null;
        if(!f.session.isEmpty())try{session=api.json("/api/v1/uploads/"+f.session,"GET",null);}catch(Api.Failure error){if(error.status!=400&&error.status!=404)throw error;}
        if(session==null){session=api.json("/api/v1/uploads","POST",Api.object("name",f.name,"size",f.size));f.session=session.getString("id");}
        f.offset=session.getLong("offset");db.update(f.id,"uploading",f.session,f.offset,"","");
        try(InputStream input=context.getContentResolver().openInputStream(uri)){
            if(input==null)throw new IOException("无法打开源文件");long skipped=0;
            while(skipped<f.offset){check(automatic);long n=input.skip(f.offset-skipped);if(n==0){if(input.read()==-1)throw new EOFException("源文件不完整");n=1;}skipped+=n;}
            while(f.offset<f.size){
                check(automatic);int length=(int)Math.min(4L*1024*1024,f.size-f.offset);byte[] chunk=new byte[length];int count=0;
                while(count<length){int n=input.read(chunk,count,length-count);if(n<0)throw new EOFException("源文件读取中断");count+=n;}
                try{f.offset=api.request("/api/v1/uploads/"+f.session,"PATCH",chunk,f.offset).getLong("offset");}
                catch(Exception error){JSONObject saved=api.json("/api/v1/uploads/"+f.session,"GET",null);long offset=saved.getLong("offset");if(offset!=f.offset+length)throw error;f.offset=offset;}
                db.update(f.id,"uploading",f.session,f.offset,"","");progress.show(f.name+" · "+(f.offset*100/f.size)+"%");
            }
        }
        check(automatic);progress.show(f.name+" · 服务端 SHA256 校验中");JSONObject result=api.json("/api/v1/uploads/"+f.session+"/complete","POST",null);
        db.update(f.id,"done",f.session,f.size,result.getString("sha256"),"");progress.show(f.name+(result.optBoolean("duplicate")?" · 相同 SHA256，已去重":" · 上传完成"));
    }
    void run(boolean automatic,boolean scan) throws Exception {
        if(!RUNNING.compareAndSet(false,true))return;
        try{
            check(automatic);JSONObject auth=api.json("/api/v1/auth/status?audience=client","GET",null);
            if(!auth.optBoolean("authenticated"))throw new Api.Failure(401,"登录已过期，请重新完成 TOTP 认证");
            if(scan){progress.show("正在扫描授权相册…");scan();}
            int failed=0;
            for(SyncDb.FileItem item:db.pending(settings.scope())){
                check(automatic);
                try{upload(item,automatic);}
                catch(InterruptedIOException e){throw e;}
                catch(Api.Failure e){db.update(item.id,e.status==415?"unsupported":"failed",item.session,item.offset,"",e.getMessage());if(e.status==401||e.status==403)throw e;failed++;}
                catch(Exception e){db.update(item.id,"failed",item.session,item.offset,"",e.getMessage());failed++;}
            }
            progress.show(failed==0?"本轮同步完成":"本轮完成，"+failed+" 项失败；修复后点击同步重试");
        }finally{RUNNING.set(false);db.close();}
    }
}
