package com.photosync.android;

import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

final class Api {
    static class Failure extends IOException { final int status;Failure(int status,String message){super(message);this.status=status;} }
    final Settings settings;
    Api(Settings settings){this.settings=settings;}
    static JSONObject object(Object... pairs) throws JSONException {JSONObject data=new JSONObject();for(int i=0;i<pairs.length;i+=2)data.put((String)pairs[i],pairs[i+1]);return data;}
    String path(String path){return settings.get("server")+path+(path.contains("?")?"&":"?")+"app=client";}
    HttpURLConnection connect(String path,String method) throws Exception {
        HttpURLConnection c=(HttpURLConnection)new URL(path(path)).openConnection();c.setInstanceFollowRedirects(false);c.setConnectTimeout(15000);c.setReadTimeout(120000);c.setRequestMethod(method);
        String cookie=settings.cookie();if(!cookie.isEmpty())c.setRequestProperty("Cookie",cookie);c.setRequestProperty("Accept","application/json");return c;
    }
    JSONObject json(String path,String method,JSONObject body) throws Exception {
        byte[] bytes=body==null?null:body.toString().getBytes(StandardCharsets.UTF_8);return request(path,method,bytes,null);
    }
    JSONObject request(String path,String method,byte[] body,Long offset) throws Exception {
        HttpURLConnection c=connect(path,method);
        try{
            if(offset!=null)c.setRequestProperty("Upload-Offset",Long.toString(offset));
            if(body!=null){c.setDoOutput(true);c.setRequestProperty("Content-Type",offset==null?"application/json":"application/octet-stream");c.setFixedLengthStreamingMode(body.length);try(OutputStream out=c.getOutputStream()){out.write(body);}}
            else if(method.equals("POST")){c.setDoOutput(true);c.setFixedLengthStreamingMode(0);}
            int status=c.getResponseCode();InputStream in=status<400?c.getInputStream():c.getErrorStream();
            String text=in==null?"{}":read(in,16*1024*1024);JSONObject data;
            try{data=new JSONObject(text);}catch(JSONException e){throw new Failure(status,"服务响应不是 JSON，请检查服务地址或反向代理");}
            if(status<200||status>=300)throw new Failure(status,data.optString("error","HTTP "+status));
            List<String> cookies=c.getHeaderFields().get("Set-Cookie");if(cookies==null)cookies=c.getHeaderFields().get("set-cookie");
            if(cookies!=null)for(String cookie:cookies)if(cookie.startsWith("photosync_client_session="))settings.cookie(cookie.split(";",2)[0]);
            return data;
        }finally{c.disconnect();}
    }
    static String read(InputStream input,int limit) throws IOException {try(InputStream in=input;ByteArrayOutputStream out=new ByteArrayOutputStream()){byte[] buffer=new byte[8192];int n;while((n=in.read(buffer))!=-1){if(out.size()+n>limit)throw new IOException("响应超过安全读取限制");out.write(buffer,0,n);}return out.toString("UTF-8");}}
}
