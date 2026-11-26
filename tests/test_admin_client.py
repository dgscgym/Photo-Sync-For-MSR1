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

    def test_separate_surfaces_and_settings_do_not_reset_setup(self):
        self.ready()
        admin=self.call('/admin');client=self.call('/client')
        self.assertEqual(admin[0],200);self.assertEqual(client[0],200)
        self.assertIn(b'/admin/assets/app.js',admin[1]);self.assertNotIn(b'id="pick"',admin[1])
        self.assertIn(b'id="pick"',client[1]);self.assertNotIn(b'id="storage-alert"',client[1])
        settings=self.call('/admin/settings/snapraid')
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
        self.assertEqual(self.call('/admin/settings/snapraid')[0],302)
        self.assertEqual(self.call('/api/v1/client/status')[0],401)
