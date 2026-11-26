package com.photosync.android;

import android.content.*;
import android.database.*;
import android.database.sqlite.*;
import android.net.Uri;
import java.util.*;

final class SyncDb extends SQLiteOpenHelper {
    SyncDb(Context c){super(c,"sync.sqlite3",null,1);setWriteAheadLoggingEnabled(true);}
    public void onCreate(SQLiteDatabase db){db.execSQL("CREATE TABLE files(id INTEGER PRIMARY KEY,scope TEXT NOT NULL,uri TEXT NOT NULL,name TEXT NOT NULL,size INTEGER NOT NULL,modified INTEGER NOT NULL,session TEXT NOT NULL DEFAULT '',offset INTEGER NOT NULL DEFAULT 0,state TEXT NOT NULL DEFAULT 'queued',sha TEXT NOT NULL DEFAULT '',error TEXT NOT NULL DEFAULT '',UNIQUE(scope,uri,size,modified))");}
    public void onUpgrade(SQLiteDatabase db,int old,int next){throw new IllegalStateException("不支持的数据库升级，请保留原数据库");}
    void enqueue(String scope,Uri uri,String name,long size,long modified){ContentValues v=new ContentValues();v.put("scope",scope);v.put("uri",uri.toString());v.put("name",name);v.put("size",size);v.put("modified",modified);getWritableDatabase().insertWithOnConflict("files",null,v,SQLiteDatabase.CONFLICT_IGNORE);}
    static final class FileItem {long id,size,modified,offset;String uri,name,session,state,sha;}
    List<FileItem> pending(String scope){List<FileItem> items=new ArrayList<>();try(Cursor c=getReadableDatabase().query("files",null,"scope=? AND state NOT IN ('done','unsupported')",new String[]{scope},null,null,"id","500")){while(c.moveToNext()){FileItem f=new FileItem();f.id=c.getLong(c.getColumnIndexOrThrow("id"));f.uri=c.getString(c.getColumnIndexOrThrow("uri"));f.name=c.getString(c.getColumnIndexOrThrow("name"));f.size=c.getLong(c.getColumnIndexOrThrow("size"));f.modified=c.getLong(c.getColumnIndexOrThrow("modified"));f.session=c.getString(c.getColumnIndexOrThrow("session"));f.offset=c.getLong(c.getColumnIndexOrThrow("offset"));f.state=c.getString(c.getColumnIndexOrThrow("state"));f.sha=c.getString(c.getColumnIndexOrThrow("sha"));items.add(f);}}return items;}
    void update(long id,String state,String session,long offset,String sha,String error){ContentValues v=new ContentValues();v.put("state",state);v.put("session",session);v.put("offset",offset);v.put("sha",sha);v.put("error",error);getWritableDatabase().update("files",v,"id=?",new String[]{Long.toString(id)});}
    String summary(String scope){StringBuilder text=new StringBuilder();try(Cursor c=getReadableDatabase().rawQuery("SELECT state,COUNT(*) FROM files WHERE scope=? GROUP BY state",new String[]{scope})){while(c.moveToNext())text.append(c.getString(0)).append(": ").append(c.getInt(1)).append("  ");}try(Cursor c=getReadableDatabase().rawQuery("SELECT name,error FROM files WHERE scope=? AND error<>'' ORDER BY id DESC LIMIT 3",new String[]{scope})){while(c.moveToNext())text.append("\n").append(c.getString(0)).append("：").append(c.getString(1));}return text.toString();}
}
