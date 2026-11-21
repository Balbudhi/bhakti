"""Actual bounded caller/storage tests; only external child launch is replaced."""
import sys,json,os,time,tempfile,unittest,copy,math
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import process_song_gemini as client
MODEL='google/gemini-3.8-flash'
class Flash38CallerTests(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name);self.path=self.root/'ledger.json';self.jobs=[]
  env=patch.dict(os.environ,{'BHAKTI_GEMINI_PROVIDER':'openrouter','BHAKTI_API_RUN_LEDGER':str(self.path),'BHAKTI_API_RUN_BUDGET_USD':'.5','BHAKTI_API_RUN_MAX_CALLS':'6'});env.start();self.addCleanup(env.stop)
 def payload(self,model=MODEL):return {'model':model,'max_tokens':8192,'messages':[{'role':'user','content':[{'type':'text','text':'fixed source first-syllable fixture'}]}]}
 def test_explicit38_reaches_real_reservation_and_persisted_route(self):
  payload=self.payload();before=copy.deepcopy(payload);outer=self
  class Worker:
   pid=731;returncode=0
   def communicate(self,input=None,timeout=None):
    job=json.loads(input);outer.jobs.append(job);Path(job['response_path']).write_text(json.dumps({'model':MODEL,'usage':{'cost':.001},'choices':[]}));return b'{"http_status":200}',b''
   def poll(self):return 0
  def execute(ctx):
   result,context=client._bounded_call(payload,'test-not-a-real-secret',None,5,unit_context=ctx.transport_context)
   return {'model':result['model'],'issues':[]}
  with patch.object(client.subprocess,'Popen',return_value=Worker()) as child,patch.object(client.urllib.request,'urlopen',side_effect=AssertionError('network forbidden')):
   result=client.model_routes.run_unit(self.root/'routes','same-context','a'*64,execute,lambda _:[],deadline_at=time.time()+20,base_model=MODEL,pro_model=MODEL)
  self.assertEqual(result['model'],MODEL);child.assert_called_once();self.assertEqual(payload,before);self.assertEqual(client.model_routes.FLASH_MODEL,'google/gemini-3.7-flash')
  ledger=json.loads(self.path.read_text());self.assertEqual(len(ledger['requests']),1);row=ledger['requests'][0];self.assertEqual(row['status'],'response-received');self.assertEqual(row['model'],MODEL);self.assertEqual(row['price_per_million'],{'prompt':.825,'completion':4.125});self.assertEqual(row['reported_cost_usd'],.001)
  evidence=before;bound=len(json.dumps(evidence,ensure_ascii=False).encode())+1024;expected=math.ceil((bound*.825+8192*4.125)/1e6*1e8)/1e8;self.assertEqual(row['reservation_usd'],expected)
  wire=self.jobs[0]['payload'];self.assertEqual(wire['provider']['max_price'],{'prompt':.825,'completion':4.125});self.assertEqual(wire['provider']['only'],['google-ai-studio']);self.assertFalse(wire['provider']['allow_fallbacks'])
  state=json.loads(next((self.root/'routes').rglob('route-state.json')).read_text());self.assertEqual(state['status'],'accepted');self.assertEqual(len(state['attempts']),1)
  self.assertNotIn('test-not-a-real-secret',''.join(f.read_text() for f in self.root.rglob('*.json')))
 def test_unsupported_model_rejected_before_reservation_or_child(self):
  with patch.object(client.subprocess,'Popen') as child,patch.object(client,'_locked_run_ledger') as lock:
   with self.assertRaisesRegex(RuntimeError,'supported OpenRouter'):client._bounded_call(self.payload('unreviewed/model'),'',None,5)
  child.assert_not_called();lock.assert_not_called();self.assertFalse(self.path.exists())
 def test_existing_unknown_consumes_original_call_slot(self):
  row={'id':'prior','status':'unknown-outcome','reservation_usd':.2};ledger={'version':1,'budget_usd':.5,'max_calls':1,'blocked':False,'requests':[row]};self.path.write_text(json.dumps(ledger));before=self.path.read_bytes()
  with patch.dict(os.environ,{'BHAKTI_API_RUN_MAX_CALLS':'1'}),patch.object(client.subprocess,'Popen') as child:
   with self.assertRaisesRegex(client.model_routes.RunFatal,'call limit exhausted'):client._bounded_call(self.payload(),'',None,5)
  child.assert_not_called();self.assertEqual(self.path.read_bytes(),before)
if __name__=='__main__':unittest.main()
