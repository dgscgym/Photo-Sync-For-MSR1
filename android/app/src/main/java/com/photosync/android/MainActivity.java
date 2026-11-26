package com.photosync.android;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.*;
import android.graphics.drawable.*;
import android.hardware.biometrics.BiometricPrompt;
import android.net.*;
import android.os.*;
import android.provider.Settings;
import android.text.InputType;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.net.HttpURLConnection;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

public final class MainActivity extends Activity {
    private com.photosync.android.Settings settings;private Api api;private LinearLayout body;private TextView message;
    private final ExecutorService executor=Executors.newSingleThreadExecutor();private int page=0;private VideoView player;private JSONArray photos=new JSONArray();
    private boolean foreground,unlocked;private long lastVisible;private ConnectivityManager.NetworkCallback callback;private CancellationSignal biometric;
    private static final int FILES=10,TREE=11;private static final int GREEN=0xff2d634a;
    private final Handler handler=new Handler(android.os.Looper.getMainLooper());
    private final Runnable statusPoll=new Runnable(){public void run(){if(foreground){if(message!=null&&SyncEngine.RUNNING.get())message.setText(settings.get("sync_status"));handler.postDelayed(this,1500);}}};
    public void onCreate(Bundle state){super.onCreate(state);settings=new com.photosync.android.Settings(this);api=new Api(settings);entry();}
    private void entry(){if(settings.get("server").isEmpty()){login();return;}task(()->api.json("/api/v1/auth/status?audience=client","GET",null),state->{if(state.optBoolean("authenticated")){settings.put("username",state.optString("username"));if(settings.flag("biometric")&&!unlocked)unlock();else gallery();}else login();});}
    private void screen(String title){
        page++;if(player!=null){player.stopPlayback();player=null;}
        LinearLayout outer=new LinearLayout(this);outer.setOrientation(LinearLayout.VERTICAL);outer.setBackgroundColor(0xfff4f7f1);
        outer.setOnApplyWindowInsetsListener((v,insets)->{v.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());return insets;});
        TextView heading=new TextView(this);heading.setText(title);heading.setTextSize(24);heading.setTextColor(GREEN);heading.setPadding(dp(20),dp(20),dp(20),dp(12));outer.addView(heading);
        ScrollView scroll=new ScrollView(this);body=new LinearLayout(this);body.setOrientation(LinearLayout.VERTICAL);body.setPadding(dp(20),0,dp(20),dp(24));scroll.addView(body);outer.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));setContentView(outer);
        message=text("");message.setTextColor(0xff8c492a);message.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
    }
    private int dp(int n){return (int)(n*getResources().getDisplayMetrics().density+.5f);}
    private TextView text(String value){TextView v=new TextView(this);v.setText(value);v.setTextColor(0xff294633);v.setTextSize(15);v.setPadding(0,dp(8),0,dp(8));v.setTextIsSelectable(true);body.addView(v);return v;}
    private Button button(String label,Runnable action){Button b=new Button(this);b.setText(label);b.setAllCaps(false);b.setOnClickListener(v->action.run());body.addView(b,new LinearLayout.LayoutParams(-1,-2));return b;}
    private EditText input(String hint,String value,boolean password){EditText e=new EditText(this);e.setHint(hint);e.setText(value);e.setSingleLine(true);e.setInputType(password?InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD:InputType.TYPE_CLASS_TEXT);body.addView(e);return e;}
    interface Work {JSONObject run() throws Exception;}interface Done {void accept(JSONObject data) throws Exception;}
    private void enableButtons(){for(int i=0;i<body.getChildCount();i++)if(body.getChildAt(i) instanceof Button)body.getChildAt(i).setEnabled(true);}
    private void task(Work work,Done done){int generation=page;executor.execute(()->{try{JSONObject data=work.run();runOnUiThread(()->{if(generation!=page)return;try{done.accept(data);}catch(Exception e){error(e);}finally{if(generation==page)enableButtons();}});}catch(Exception e){runOnUiThread(()->{if(generation==page){error(e);enableButtons();}});}});}
    private void error(Exception e){if(message==null){login();}message.setText(e.getMessage()==null?"操作失败，请重试":e.getMessage());if(e instanceof Api.Failure&&((Api.Failure)e).status==401&&!settings.get("session").isEmpty())message.setText("登录已过期，请通过用户菜单退出后重新登录并完成验证码认证");}
    private boolean idle(){if(SyncEngine.RUNNING.get()){message.setText("请先暂停同步，等待当前请求结束后再切换账户或退出");return false;}return true;}
    private void login(){
        screen("PhotoSync · 连接照片库");text("由服务端管理员创建客户端账户。客户端不提供服务端管理入口。");
        EditText server=input("服务地址，例如 https://photos.example.com",settings.get("server"),false);
        EditText name=input("客户端用户名",settings.get("username"),false);EditText password=input("密码","",true);
        Button connect=button("登录 / 连接本机原型",()->{
            if(!idle())return;try{String endpoint=com.photosync.android.Settings.server(server.getText().toString());settings.cookie("");settings.put("server",endpoint);settings.put("username",name.getText().toString().trim());}
            catch(Exception e){error(e);return;}
            String raw=password.getText().toString();password.setText("");
            for(int i=0;i<body.getChildCount();i++)if(body.getChildAt(i) instanceof Button)body.getChildAt(i).setEnabled(false);
            task(()->{
                JSONObject state=api.json("/api/v1/auth/status?audience=client","GET",null);
                if(state.optBoolean("demo"))return state;
                if(!state.optBoolean("setup_complete"))throw new IOException("请先在服务端完成初始化");
                return api.json("/api/v1/auth/login","POST",Api.object("username",settings.get("username"),"password",raw,"audience","client"));
            },result->{for(int i=0;i<body.getChildCount();i++)if(body.getChildAt(i) instanceof Button)body.getChildAt(i).setEnabled(true);if(result.optBoolean("demo")){settings.put("username",result.optString("username"));unlocked=true;gallery();}else mfa(result);});

        });
        if(BuildConfig.DEBUG)text("debug 版允许局域网 HTTP。模拟器通过 10.0.2.2:8080 访问电脑；实体手机需要服务端局域网地址或 adb reverse。");
    }
    private void mfa(JSONObject challenge){
        screen(challenge.optBoolean("enroll")?"绑定验证器":"双因素认证");getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        if(challenge.optBoolean("enroll")){
            text("将以下密钥添加到 Google Authenticator 等验证器（基于时间、6 位验证码）：");text(challenge.optString("secret"));
            button("复制绑定密钥",()->{((ClipboardManager)getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(ClipData.newPlainText("PhotoSync TOTP",challenge.optString("secret")));message.setText("密钥已复制，请妥善保管");});
            button("使用本机验证器打开",()->{try{startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(challenge.optString("otpauth_uri"))));}catch(ActivityNotFoundException e){message.setText("未找到验证器，请手动输入密钥");}});
        }
        EditText code=input("6 位验证码或恢复码","",false);code.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        button("验证并登录",()->{String value=code.getText().toString().trim();code.setText("");task(()->api.json("/api/v1/auth/mfa/verify","POST",Api.object("ticket",challenge.optString("ticket"),"code",value,"audience","client")),result->{unlocked=true;settings.put("username",result.optString("username",settings.get("username")));if(result.optJSONArray("recovery_codes")!=null&&result.optJSONArray("recovery_codes").length()>0){screen("保存恢复码");text("以下恢复码仅显示一次，请离线保存；丢失验证器时可配合密码使用。");text(result.getJSONArray("recovery_codes").join("\n").replace("\"",""));button("我已保存，进入照片库",this::gallery);}else gallery();});});
        button("重新登录",this::login);
    }
    private void unlock(){
        screen("PhotoSync · 已锁定");button("使用指纹 / 面容解锁",this::promptBiometric);button("退出并重新登录",this::logout);promptBiometric();
    }
    private void promptBiometric(){
        if(Build.VERSION.SDK_INT<28){settings.flag("biometric",false);gallery();return;}
        biometric=new CancellationSignal();new BiometricPrompt.Builder(this).setTitle("解锁 PhotoSync").setDescription("仅解锁当前有效客户端会话；过期后仍需验证码").setNegativeButton("取消",getMainExecutor(),(d,w)->{}).build().authenticate(biometric,getMainExecutor(),new BiometricPrompt.AuthenticationCallback(){
            public void onAuthenticationSucceeded(BiometricPrompt.AuthenticationResult result){unlocked=true;entry();}
            public void onAuthenticationError(int code,CharSequence text){if(message!=null)message.setText(text);}
        });
    }
    private void gallery(){
        getWindow().clearFlags(WindowManager.LayoutParams.FLAG_SECURE);screen("PhotoSync · 照片库");button(settings.get("username")+" ▾",()->new AlertDialog.Builder(this).setItems(new String[]{"设置","退出登录"},(d,index)->{if(index==0)preferences();else logout();}).show());
        button("＋ 上传照片 / 视频",()->{Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").putExtra(Intent.EXTRA_MIME_TYPES,new String[]{"image/*","video/*"}).putExtra(Intent.EXTRA_ALLOW_MULTIPLE,true).addCategory(Intent.CATEGORY_OPENABLE).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);startActivityForResult(intent,FILES);});
        button("刷新照片库",this::gallery);text("照片与视频 · 原片保留 · SHA256 精确去重");
        task(()->api.json("/api/v1/client/status","GET",null),result->{photos=result.getJSONArray("photos");if(photos.length()==0)text("照片库还是空的，上传或同步本机相册开始整理。");for(int i=0;i<photos.length();i++){JSONObject photo=photos.getJSONObject(i);button(((photo.isNull("live_video")?"":photo.optString("live_video")).isEmpty()?photo.optString("media_type").startsWith("video/")?"▷ ":"▧ ":"◎ LIVE · ")+photo.optString("name")+"\n"+size(photo.optLong("size")),()->detail(photo));if(photo.optString("media_type").startsWith("image/"))image("/api/v1/thumbnails/"+photo.optString("sha256"));}});
    }
    private static String size(long n){return n>=1024L*1024*1024?String.format(Locale.ROOT,"%.2f GiB",n/(1024.0*1024*1024)):String.format(Locale.ROOT,"%.1f MiB",n/(1024.0*1024));}
    private void detail(JSONObject photo){
        screen(photo.optString("name"));button("← 返回照片库",this::gallery);
        boolean video=photo.optString("media_type").startsWith("video/");String digest=photo.optString("sha256"),live=(photo.isNull("live_video")?"":photo.optString("live_video"));
        if(video)play("/api/v1/photos/"+digest);else image("/api/v1/photos/"+digest);
        if(!live.isEmpty())button("播放 Live Photo 动态片段",()->play("/api/v1/photos/"+live));
        button("生成 / 打开兼容预览",()->preview(live.isEmpty()?digest:live,video||!live.isEmpty()));
        if(!video)button("关联 Live Photo 视频",()->pair(photo));
        task(()->api.json("/api/v1/media-details/"+digest,"GET",null),data->{
            text("存储位置");JSONArray locations=data.optJSONArray("locations");if(locations!=null)for(int i=0;i<locations.length();i++)text(locations.getJSONObject(i).optString("path"));
            text("格式："+data.optString("format")+"\n大小："+size(data.optLong("size"))+"\n分辨率："+(data.isNull("resolution")?"未提供":data.optString("resolution"))+"\nSHA256："+digest);
            JSONObject camera=data.optJSONObject("camera");text("相机参数："+(camera==null||camera.length()==0?"未提供":camera.toString(2)));
            if(data.has("duration")&&!data.isNull("duration"))text("时长："+data.optDouble("duration")+" 秒");
        });
    }
    private void pair(JSONObject photo){
        ArrayList<JSONObject> videos=new ArrayList<>();ArrayList<String> labels=new ArrayList<>();for(int i=0;i<photos.length();i++){JSONObject p=photos.optJSONObject(i);if(p!=null&&p.optString("media_type").startsWith("video/")){videos.add(p);labels.add(p.optString("name"));}}
        if(videos.isEmpty()){message.setText("请先上传配对的视频资源");return;}
        new AlertDialog.Builder(this).setTitle("选择同一张实况照片的视频").setItems(labels.toArray(new String[0]),(d,index)->new AlertDialog.Builder(this).setMessage("确认它们属于同一张实况照片？文件名不作为身份验证依据。").setPositiveButton("确认配对",(dialog,which)->task(()->api.json("/api/v1/live-pairs","POST",Api.object("photo",photo.optString("sha256"),"video",videos.get(index).optString("sha256"))),r->gallery())).setNegativeButton("取消",null).show()).show();
    }
    private void image(String path){
        ImageView image=new ImageView(this);image.setAdjustViewBounds(true);body.addView(image,new LinearLayout.LayoutParams(-1,dp(320)));int generation=page;
        executor.execute(()->{if(generation!=page)return;HttpURLConnection connection=null;File file=null;try{
            connection=api.connect(path,"GET");if(connection.getResponseCode()!=200)throw new IOException("原片读取失败");file=File.createTempFile("photosync-preview-",".img",getCacheDir());
            try(InputStream in=connection.getInputStream();OutputStream out=new FileOutputStream(file)){byte[] buffer=new byte[16384];long size=0;int n;while((n=in.read(buffer))!=-1){size+=n;if(size>32L*1024*1024)throw new IOException("原片较大，请生成兼容预览后查看");out.write(buffer,0,n);}}
            BitmapFactory.Options bounds=new BitmapFactory.Options();bounds.inJustDecodeBounds=true;BitmapFactory.decodeFile(file.toString(),bounds);BitmapFactory.Options opts=new BitmapFactory.Options();opts.inSampleSize=1;while(bounds.outWidth/opts.inSampleSize>2048||bounds.outHeight/opts.inSampleSize>2048)opts.inSampleSize*=2;
            if(Build.VERSION.SDK_INT>=28){
                final Drawable drawable=ImageDecoder.decodeDrawable(ImageDecoder.createSource(file),(decoder,info,source)->{int width=info.getSize().getWidth(),height=info.getSize().getHeight();double scale=Math.min(1.0,2048.0/Math.max(width,height));decoder.setTargetSize(Math.max(1,(int)(width*scale)),Math.max(1,(int)(height*scale)));});
                runOnUiThread(()->{if(generation==page){image.setImageDrawable(drawable);if(drawable instanceof AnimatedImageDrawable)((AnimatedImageDrawable)drawable).start();}});return;
            }
            Bitmap bitmap=BitmapFactory.decodeFile(file.toString(),opts);if(bitmap==null)throw new IOException("系统无法解码此原片，请尝试兼容预览");runOnUiThread(()->{if(generation==page)image.setImageBitmap(bitmap);else bitmap.recycle();});
        }catch(Exception e){runOnUiThread(()->{if(generation==page)error(e);});}finally{if(connection!=null)connection.disconnect();if(file!=null)file.delete();}});
    }
    private void play(String path){
        try{if(player!=null){player.stopPlayback();body.removeView(player);}player=new VideoView(this);body.addView(player,new LinearLayout.LayoutParams(-1,dp(300)));MediaController controls=new MediaController(this);controls.setAnchorView(player);player.setMediaController(controls);player.setVideoURI(Uri.parse(api.path(path)),Collections.singletonMap("Cookie",settings.cookie()));VideoView current=player;player.setOnPreparedListener(mp->{if(player==current)current.start();});player.setOnErrorListener((mp,what,extra)->{message.setText("系统不支持该编码，请生成兼容预览；原片仍完整保存");return true;});}catch(Exception e){error(e);}
    }
    private void preview(String digest,boolean video){
        task(()->api.json("/api/v1/previews/"+digest,"POST",null),result->{String state=result.optString("state");if(state.equals("ready")){if(video)play("/api/v1/previews/"+digest);else image("/api/v1/previews/"+digest);}else if(state.equals("queued")||state.equals("processing")){message.setText("服务端正在生成预览，稍后再次点击查看");}else message.setText(result.optString("error","预览生成失败，请检查服务端 FFmpeg"));});
    }
    private void preferences(){
        screen("设置 · 本机相册同步");button("← 返回照片库",this::gallery);text("授权多个本机相册目录，原文件不移动、不删除。移除目录只停止后续扫描，不删除已上传照片。");
        JSONArray albums=settings.albums();for(int i=0;i<albums.length();i++){final int index=i;String path=albums.optString(i);text(Uri.decode(path));button("移除此相册",()->{JSONArray next=settings.albums();next.remove(index);settings.albums(next);preferences();});}
        button("＋ 选择相册文件夹",()->startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION|Intent.FLAG_GRANT_PREFIX_URI_PERMISSION),TREE));
        button("立即扫描并同步",()->startSync(true));button("暂停同步",()->{startService(new Intent(this,SyncService.class).setAction("stop"));message.setText("正在暂停，已上传分片会保留");});
        try(SyncDb db=new SyncDb(this)){text(db.summary(settings.scope()));}
        text(settings.get("sync_status"));
        EditText wifi=input("指定 Wi-Fi 名称（SSID，精确匹配）",settings.get("ssid"),false);
        Switch automatic=new Switch(this);automatic.setText("启用指定 Wi-Fi 自动同步");automatic.setChecked(settings.flag("auto"));body.addView(automatic);
        button("保存自动同步策略",()->{String ssid=wifi.getText().toString().trim();if(automatic.isChecked()&&ssid.isEmpty()){message.setText("请填写 Wi-Fi 名称");return;}settings.put("ssid",ssid);settings.flag("auto",automatic.isChecked());SyncJob.schedule(this);SyncJob.wake(this);message.setText("已保存。后台按系统调度扫描；SSID 不可读取或不匹配时不会上传。");});
        button("授权读取 Wi-Fi 名称",()->requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION,Manifest.permission.ACCESS_COARSE_LOCATION},20));
        text("指定 Wi-Fi 需要定位权限和系统定位开关。后台读取 SSID 还需在应用权限中允许后台定位；无法识别网络时暂停，不回退到移动网络。自动任务至少约 15 分钟调度一次，省电策略可能延迟。");
        button("打开应用权限 / 后台运行设置",()->startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,Uri.parse("package:"+getPackageName()))));
        if(Build.VERSION.SDK_INT>=29)button("授权后台定位（用于后台匹配 Wi-Fi）",()->{if(checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)!=PackageManager.PERMISSION_GRANTED){message.setText("请先授权精确定位，再设置后台权限");return;}requestPermissions(new String[]{Manifest.permission.ACCESS_BACKGROUND_LOCATION},21);});
        if(Build.VERSION.SDK_INT>=28){Switch bio=new Switch(this);bio.setText("返回应用时使用设备生物认证");bio.setChecked(settings.flag("biometric"));body.addView(bio);bio.setOnCheckedChangeListener((v,checked)->{settings.flag("biometric",checked);if(checked){unlocked=false;unlock();}});text("生物认证只保护本机当前有效会话，不能延长服务端会话。当前服务端每 12 小时过期，届时必须重新密码 + TOTP；未实现原生 passkey 跨登录替代。");}
        text("PhotoSync Android "+BuildConfig.VERSION_NAME+" · 客户端不包含运行日志或服务端管理功能");
    }
    private void startSync(boolean scan){if(Build.VERSION.SDK_INT>=33&&checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},22);startForegroundService(new Intent(this,SyncService.class).putExtra("scan",scan));message.setText("同步已启动，通知栏可暂停；可离开当前页面。");}
    protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(result!=RESULT_OK||data==null)return;
        try{
            if(request==TREE){Uri uri=data.getData();if(uri==null)return;getContentResolver().takePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION);JSONArray albums=settings.albums();for(int i=0;i<albums.length();i++)if(albums.getString(i).equals(uri.toString())){preferences();return;}albums.put(uri.toString());settings.albums(albums);preferences();}
            else if(request==FILES){ArrayList<Uri> uris=new ArrayList<>();if(data.getClipData()!=null)for(int i=0;i<data.getClipData().getItemCount();i++)uris.add(data.getClipData().getItemAt(i).getUri());else if(data.getData()!=null)uris.add(data.getData());
                for(Uri uri:uris)getContentResolver().takePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION);
                task(()->{SyncEngine engine=new SyncEngine(this,new AtomicBoolean(false),t->{},Long.MAX_VALUE);try{for(Uri uri:uris)engine.enqueue(uri);}finally{engine.db.close();}return new JSONObject();},r->startSync(false));
            }
        }catch(Exception e){error(e);}
    }
    private void logout(){if(!idle())return;task(()->{try{api.json("/api/v1/auth/logout","POST",Api.object("audience","client"));}catch(Exception ignored){}finally{settings.cookie("");settings.flag("auto",false);SyncJob.schedule(this);}return new JSONObject();},r->{unlocked=false;login();});}
    protected void onResume(){super.onResume();foreground=true;handler.post(statusPoll);if(settings!=null&&settings.flag("biometric")&&SystemClock.elapsedRealtime()-lastVisible>30000&&lastVisible!=0){unlocked=false;unlock();}if(settings!=null)SyncJob.wake(this);}
    protected void onPause(){super.onPause();foreground=false;lastVisible=SystemClock.elapsedRealtime();handler.removeCallbacks(statusPoll);if(player!=null)player.pause();}
    protected void onStart(){super.onStart();callback=new ConnectivityManager.NetworkCallback(){public void onAvailable(Network n){SyncJob.wake(MainActivity.this);}};getSystemService(ConnectivityManager.class).registerDefaultNetworkCallback(callback);}
    protected void onStop(){if(callback!=null){getSystemService(ConnectivityManager.class).unregisterNetworkCallback(callback);callback=null;}super.onStop();}
    protected void onDestroy(){if(biometric!=null)biometric.cancel();executor.shutdownNow();super.onDestroy();}
}
