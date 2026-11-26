import json
from pathlib import Path
from unittest.mock import patch
from tests.test_setup_auth import SetupAuthTests
from tests.test_disks import disk

class AdminClientTests(SetupAuthTests):
    def ready(self):
        credentials=self.bootstrap()
        self.call('/api/v1/setup/snapraid',{'skip':True});self.call('/api/v1/setup/finish',{})
        self.call('/api/v1/auth/login',credentials)
        client={'username':'viewer','password':'viewer-password-123'}
        self.call('/api/v1/admin/users',client)
        self.call('/api/v1/auth/login',dict(client,audience='client'))

    def test_profile_and_app_local_settings(self):
        self.ready()
        auth=self.call('/api/v1/auth/status')[1]
        self.assertEqual(auth['username'],'owner')
        for home,other in [('/client','/admin'),('/admin','/client')]:
            page=self.call(home)[1].decode()
            self.assertIn('id="user-toggle"',page)
            self.assertIn('id="user-settings" href="'+home+'/settings"',page)
            self.assertNotIn('href="'+other+'"',page)
            settings=self.call(home+'/settings')
            self.assertEqual(settings[0],200)
            text=settings[1].decode()
            self.assertIn('id="choose-folder"' if home=='/client' else 'id="album-save"',text)
            if home=='/client':self.assertNotIn('id="mode"',text)
            else:self.assertIn('id="mode"',text)
            self.assertNotIn('href="'+other,text)
        self.assertEqual(self.call('/shared/assets/profile.js')[0],200)
        self.assertEqual(self.call('/shared/assets/upload.js')[0],200)
        self.call('/api/v1/auth/logout',{})
        self.call('/api/v1/auth/logout',{'audience':'client'})
        self.assertIsNone(self.call('/api/v1/auth/status')[1]['username'])
        self.assertEqual(self.call('/client/settings')[0],302)

    def test_directory_browse_requires_review_before_ui_confirmation(self):
        from urllib.parse import quote
        self.ready()
        folder=self.media/'one'
        content=b'\x89PNG\r\n\x1a\npreview'
        (folder/'photo.png').write_bytes(content)
        result=self.call('/api/v1/library/browse?path='+quote(str(folder)))
        self.assertEqual(result[0],200)
        self.assertEqual(result[1]['entries'][0]['name'],'photo.png')
        self.assertEqual(self.server.library.sources(),[])
        self.assertEqual(self.call('/api/v1/library/browse-preview?path='+quote(str(folder/'photo.png')))[1],content)
        rejected=self.call('/api/v1/library/sources',{'path':str(folder),'review_token':'stale'})
        self.assertEqual(rejected[0],400)
        self.assertEqual(self.server.library.sources(),[])
        accepted=self.call('/api/v1/library/sources',{'path':str(folder),'review_token':result[1]['review_token']})
        self.assertEqual(accepted[0],201)
        self.assertEqual(len(self.server.library.sources()),1)
        self.assertEqual(self.call('/api/v1/library/browse?path='+quote(self.tmp.name))[0],400)
        outside=Path(self.tmp.name)/'secret.png';outside.write_bytes(content)
        (folder/'escape.png').symlink_to(outside)
        self.assertEqual(self.call('/api/v1/library/browse-preview?path='+quote(str(folder/'escape.png')))[0],400)

    def test_navigation_and_log_levels(self):
        self.ready()
        page=self.call('/admin')[1].decode()
        for view in ('directories','snapraid','backup','activity'):
            self.assertNotIn('data-view="'+view+'"',page)
        self.assertIn('id="overview"',page)
        self.assertNotIn('id="events"',page)
        self.assertIn('id="events"',self.call('/admin/logs')[1].decode())
        self.assertEqual(self.call('/admin/settings/snapraid')[0],302)
        for level in ('INFO','DEBUG','WARN','ERROR'):
            self.server.library.store.log('test',level,'test','','level check',{})
            rows=self.call('/api/v1/logs?category=test&level='+level)[1]['items']
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['level'],level)
        self.server.library.store.log('test','warning','legacy','','legacy warning',{})
        self.assertEqual(len(self.call('/api/v1/logs?category=test&level=warning')[1]['items']),2)
        settings=self.call('/admin/settings')[1].decode()
        for section in ('album-settings','snapraid-settings','backup-settings'):
            self.assertIn('id="'+section+'"',settings)

    def test_separate_surfaces_and_settings_do_not_reset_setup(self):
        self.ready()
        admin=self.call('/admin');client=self.call('/client')
        self.assertEqual(admin[0],200);self.assertEqual(client[0],200)
        self.assertIn(b'/admin/assets/app.js',admin[1]);self.assertIn(b'id="pick"',admin[1])
        self.assertIn(b'id="pick"',client[1]);self.assertNotIn(b'id="storage-alert"',client[1])
        settings=self.call('/admin/settings')
        self.assertEqual(settings[0],200);self.assertNotIn(b'/setup/review',settings[1])
        self.assertNotIn('library',self.call('/api/v1/snapraid/settings')[1])
        self.assertNotIn('events',self.call('/api/v1/client/status')[1])
        disks=[disk('d'),disk('p',2000,1900)]
        request={'mode':'single','disks':[{'id':'d','role':'data'},{'id':'p','role':'parity'}],'confirmed':True}
        with patch('server.setup.inventory',return_value=disks):
            self.assertEqual(self.call('/api/v1/snapraid/settings',request)[0],200)
            state=self.call('/api/v1/snapraid/settings')[1]
            changed=dict(request,interval_seconds=7200,expected_revision=state['plan_revision'])
            self.assertEqual(self.call('/api/v1/snapraid/settings',changed)[0],200)
            self.assertEqual(self.call('/api/v1/snapraid/settings',changed)[0],400)
            self.assertEqual(self.call('/api/v1/snapraid/settings')[1]['disk_plan']['interval_seconds'],7200)
        self.assertTrue(self.server.auth.complete())
        self.assertEqual(self.call('/api/v1/client/status')[0],200)
        self.assertEqual(len(self.server.library.sources()),0)
        self.call('/api/v1/auth/logout',{})
        self.call('/api/v1/auth/logout',{'audience':'client'})
        self.assertEqual(self.call('/admin/settings/snapraid')[0],302)
        self.assertEqual(self.call('/api/v1/client/status')[0],401)
