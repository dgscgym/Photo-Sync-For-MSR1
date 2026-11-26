package com.photosync.android;

import android.test.AndroidTestCase;
import android.net.Uri;
import org.json.JSONArray;

/** Run with ./gradlew connectedDebugAndroidTest on a device/emulator. */
@SuppressWarnings("deprecation")
public final class SyncContractTest extends AndroidTestCase {
    public void testSessionEncryptionAndServerValidation() throws Exception {
        Settings settings=new Settings(getContext());
        settings.cookie("photosync_client_session=contract-test");
        assertEquals("photosync_client_session=contract-test",settings.cookie());
        assertFalse(settings.get("session").contains("contract-test"));settings.cookie("");
        assertEquals("https://photos.example.com",Settings.server("https://photos.example.com/"));
        for(String value:new String[]{"https://user:password@example.com","https://example.com/admin","file:///data","https://example.com?cookie=x"})try{Settings.server(value);fail(value);}catch(IllegalArgumentException expected){}
    }
    public void testQueueSurvivesReopenAndSeparatesUsers() {
        String scope="test-"+System.nanoTime();Uri uri=Uri.parse("content://test/photo");long id;
        try(SyncDb db=new SyncDb(getContext())){
            db.enqueue(scope,uri,"camera.jpg",10737418240L,123);db.enqueue(scope,uri,"camera.jpg",10737418240L,123);
            assertEquals(1,db.pending(scope).size());SyncDb.FileItem item=db.pending(scope).get(0);id=item.id;
            db.update(id,"uploading","abcdef",8388608,"","");
        }
        try(SyncDb db=new SyncDb(getContext())){
            SyncDb.FileItem item=db.pending(scope).get(0);assertEquals(10737418240L,item.size);assertEquals(8388608,item.offset);assertEquals("abcdef",item.session);
            assertTrue(db.pending(scope+"-other").isEmpty());db.update(id,"done","abcdef",item.size,"digest","");assertTrue(db.pending(scope).isEmpty());
            db.getWritableDatabase().delete("files","scope=?",new String[]{scope});
        }
    }
}
