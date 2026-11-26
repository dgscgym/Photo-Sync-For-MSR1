package com.photosync.android;

import android.content.*;
import android.security.keystore.*;
import android.util.Base64;
import org.json.*;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;

final class Settings {
    final android.content.SharedPreferences prefs;
    Settings(Context c) { prefs=c.getSharedPreferences("photosync",Context.MODE_PRIVATE); }
    String get(String key) { return prefs.getString(key,""); }
    void put(String key,String value) { prefs.edit().putString(key,value).commit(); }
    boolean flag(String key) { return prefs.getBoolean(key,false); }
    void flag(String key,boolean value) { prefs.edit().putBoolean(key,value).commit(); }
    static String server(String raw) {
        URI uri=URI.create(raw.trim());
        if(uri.getHost()==null||uri.getUserInfo()!=null||uri.getQuery()!=null||uri.getFragment()!=null||!(uri.getPath()==null||uri.getPath().isEmpty()||uri.getPath().equals("/")))throw new IllegalArgumentException("请输入服务根地址，例如 https://photos.example.com");
        if(!"https".equals(uri.getScheme())&&!(BuildConfig.DEBUG&&"http".equals(uri.getScheme())))throw new IllegalArgumentException("正式版必须使用 HTTPS；debug APK 可连接局域网 HTTP");
        return raw.trim().replaceAll("/+$", "");
    }
    String scope() { return get("server")+"|"+get("username"); }
    JSONArray albums() { try{return new JSONArray(get("albums:"+scope()));}catch(Exception e){return new JSONArray();} }
    void albums(JSONArray value) { put("albums:"+scope(),value.toString()); }
    private javax.crypto.SecretKey key() throws Exception {
        KeyStore store=KeyStore.getInstance("AndroidKeyStore");store.load(null);
        if(!store.containsAlias("photosync-session")) {
            KeyGenerator generator=KeyGenerator.getInstance("AES","AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder("photosync-session",KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());generator.generateKey();
        }
        return (javax.crypto.SecretKey)store.getKey("photosync-session",null);
    }
    void cookie(String value) throws Exception {
        if(value.isEmpty()){put("session","");return;}
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key());
        put("session",Base64.encodeToString(cipher.getIV(),Base64.NO_WRAP)+":"+Base64.encodeToString(cipher.doFinal(value.getBytes(StandardCharsets.UTF_8)),Base64.NO_WRAP));
    }
    String cookie() throws Exception {
        String value=get("session");if(value.isEmpty())return "";
        String[] parts=value.split(":",2);Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,Base64.decode(parts[0],0)));
        return new String(cipher.doFinal(Base64.decode(parts[1],0)),StandardCharsets.UTF_8);
    }
}
