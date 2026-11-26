import copy
import unittest
from server.disks import build_plan,decode_mount
from tests.test_setup_auth import SetupAuthTests
from unittest.mock import patch
import json
from pathlib import Path


def disk(name,total=1000,free=900,parent=None):
    return {'id':name,'path':'/media/'+name,'device':'/dev/'+name,'filesystem':'ext4','device_key':name,
            'physical_disks':[parent or name],'total':total,'free':free,'selectable':True,'readonly':False,'reason':''}

class DiskPlanTests(unittest.TestCase):
    def test_modes_and_content(self):
        for mode,count in [('single',1),('double',2),('triple',3)]:
            disks=[disk('data')]+[disk('p'+str(i),2000,1900) for i in range(count)]
            request={'mode':mode,'disks':[{'id':d['id'],'role':'data' if d['id']=='data' else 'parity','content':True} for d in disks]}
            plan=build_plan(request,disks)
            self.assertEqual(plan['parity_level'],count)
            self.assertEqual(plan['configuration'].count('content '),count+1)
            self.assertIn('parity /media/p0/snapraid.parity',plan['configuration'])
            if count>1:self.assertIn('2-parity /media/p1/snapraid.2-parity',plan['configuration'])
            request['disks'][0]['content']=False
            with self.assertRaises(ValueError):build_plan(request,disks)

    def test_roles_capacity_and_physical_domains(self):
        request={'mode':'single','disks':[{'id':'d','role':'data'},{'id':'p','role':'parity'}]}
        with self.assertRaises(ValueError):build_plan(request,[disk('d'),disk('p',900,800)])
        with self.assertRaises(ValueError):build_plan(request,[disk('d',parent='same'),disk('p',parent='same')])
        with self.assertRaises(ValueError):build_plan(request,[disk('d'),dict(disk('p'),selectable=False)])
        self.assertEqual(decode_mount('/mnt/my\\040disk'),'/mnt/my disk')

class DiskSetupTests(SetupAuthTests):
    def test_graphical_plan_saved_without_touching_disks(self):
        self.bootstrap()
        inventory=[disk('d'),disk('p',2000,1900)]
        request={'mode':'single','disks':[{'id':'d','role':'data'},{'id':'p','role':'parity'}]}
        with patch('server.setup.inventory',return_value=inventory):
            self.assertEqual(len(self.call('/api/v1/setup/disks')[1]['disks']),2)
            status,plan,_=self.call('/api/v1/setup/snapraid',dict(request,preview=True))
            self.assertEqual(status,200)
            path=Path(self.tmp.name)/'data'/'snapraid'/'snapraid.conf'
            self.assertFalse(path.exists())
            self.assertEqual(self.call('/api/v1/setup/snapraid',dict(request,confirmed=True))[0],200)
            self.assertEqual(path.read_text(),plan['configuration'])
            self.assertEqual(self.call('/api/v1/setup/snapraid',dict(request,confirmed=True))[0],400)
            state=self.call('/api/v1/setup')[1]
            self.assertEqual(state['snapraid_mode'],'planned')
            self.assertEqual(state['snapraid']['state'],'warning')
