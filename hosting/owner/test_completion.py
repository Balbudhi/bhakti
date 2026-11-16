"""Version1 export compatibility: no live service or network required."""
import copy,json,unittest
from test_deploy import module
class CompletionExportTests(unittest.TestCase):
 def test_completed_export_preserves_original_queued_shape_and_text(self):
  pull=module('pull');queued={'id':'11111111-1111-4111-8111-111111111111','text':'  ॐ\n','createdAt':'2026-10-28T12:00:00Z','status':'queued'}
  complete=dict(queued,id='22222222-2222-4222-8222-222222222222',status='completed',completedAt='2026-11-15T12:00:00Z')
  raw=json.dumps({'version':1,'requests':[queued,complete]}).encode();self.assertEqual(pull.validate_export(raw),raw)
  for patch in [{'status':'done'},{'completedAt':''},{'completedAt':'2020-01-01T00:00:00Z'},{'completedAt':'2026-11-15T12:00:00'},{'status':'queued'}]:
   bad=dict(complete,**patch)
   with self.subTest(patch=patch),self.assertRaises(ValueError):pull.validate_export(json.dumps({'version':1,'requests':[bad]}).encode())

class CompletionBridgeTests(unittest.TestCase):
 def test_exact_id_and_text_hash_required_before_ssh(self):
  from unittest.mock import patch
  import hashlib
  deploy=module('deploy');request_id='11111111-1111-4111-8111-111111111111';expected=hashlib.sha256('private unchanged'.encode()).hexdigest()
  receipt={'id':request_id,'text':'private unchanged','createdAt':'2026-10-28T12:00:00Z','status':'completed','completedAt':'2026-11-15T12:00:00Z'}
  with patch.object(deploy,'ssh',return_value=json.dumps(receipt).encode()) as ssh:
   result=deploy.complete_request(request_id,expected)
   self.assertEqual(result,{'id':request_id,'status':'completed','completedAt':receipt['completedAt']})
   args,kwargs=ssh.call_args;self.assertEqual(args[0],'complete');self.assertEqual(json.loads(kwargs['payload']),{'requestId':request_id,'expectedTextSha256':expected})
   for bad_id,bad_hash in [('bad',expected),(request_id,''),(request_id,'not-hash')]:
    with self.assertRaises(ValueError):deploy.complete_request(bad_id,bad_hash)
   self.assertEqual(ssh.call_count,1)
  for patch_values in [{'id':'22222222-2222-4222-8222-222222222222'},{'status':'queued'},{'completedAt':'invalid'},{'text':'wrong text'}]:
   with patch.object(deploy,'ssh',return_value=json.dumps(dict(receipt,**patch_values)).encode()),self.assertRaises(ValueError):deploy.complete_request(request_id,expected)

if __name__=='__main__':unittest.main()
