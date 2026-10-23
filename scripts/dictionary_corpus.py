"""Private dictionary acquisition/normalization; entries are candidates, not song glosses."""
from __future__ import annotations
import argparse, collections, hashlib, html, json, re, unicodedata, urllib.parse, urllib.request
from html.parser import HTMLParser
from pathlib import Path

PLATTS='https://dsal.uchicago.edu/cgi-bin/app/platts_query.py'

def sha(data): return hashlib.sha256(data).hexdigest()
def text(value): return ' '.join(value.split())
def valid_hash(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value): raise ValueError('invalid witness SHA256')
def unique(values): return list(dict.fromkeys(v for v in values if v))
def canonical_forms(value): return unique([value,unicodedata.normalize('NFC',value)])
def query_forms(value):
    if not isinstance(value,str) or not value.strip(): raise ValueError('empty query')
    value=value.strip();legacy=value
    for cp in range(0x958,0x960):
        legacy=legacy.replace(unicodedata.normalize('NFD',chr(cp)),chr(cp))
    return unique([value,legacy])

class PlattsParser(HTMLParser):
    def __init__(self,source):
        super().__init__(convert_charrefs=True);self.source=source;self.offsets=[0]
        for line in source.splitlines(True):self.offsets.append(self.offsets[-1]+len(line))
        self.records=[];self.current=None;self.depth=0;self.page=None;self.in_hw=False;self.field=None
    def source_offset(self):
        line,col=self.getpos();return self.offsets[line-1]+col
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='a' and self.current is None:
            match=re.search(r'[?&]page=(\d+)(?:$|[&#])',attrs.get('href',''))
            if match:self.page=int(match[1])
        if tag=='div':
            if self.current is not None:self.depth+=1
            elif 'px-4' in attrs.get('class','').split():
                self.current={'page':self.page,'start':self.source_offset(),'whole':[],'head':[],'native':[],'roman':[],'entry_seen':False};self.depth=1;self.page=None
        if self.current is not None:
            if tag=='entry':self.current['entry_seen']=True
            if tag=='hw':self.in_hw=True
            if self.in_hw and tag in ('d','i'):
                self.field='native' if tag=='d' else 'roman';self.current[self.field].append([])
    def handle_endtag(self,tag):
        if self.current is None:return
        if tag in ('d','i'):self.field=None
        if tag=='hw':self.in_hw=False
        if tag=='div':
            self.depth-=1
            if self.depth==0:
                self.current['raw']=self.source[self.current['start']:self.source_offset()]
                self.records.append(self.current);self.current=None;self.in_hw=False;self.field=None
    def handle_data(self,data):
        if self.current is None:return
        self.current['whole'].append(data)
        if self.in_hw:self.current['head'].append(data)
        if self.field:self.current[self.field][-1].append(data)

def parse_platts_html(source, *, query, url, witness_sha256):
    valid_hash(witness_sha256)
    parser=PlattsParser(source);parser.feed(source);parser.close()
    if parser.current is not None:raise ValueError('unterminated dictionary entry container')
    if not parser.records:
        if 'No results for search term' in source:return []
        raise ValueError('not a recognized Platts result/miss page')
    entries=[];homographs=collections.Counter()
    for r in parser.records:
        head=text(''.join(r['head']));whole=text(''.join(r['whole']))
        if not r['entry_seen'] or not r['page'] or not head or not whole:raise ValueError('entry lacks headword, citation, or body')
        native=unique(f for chunks in r['native'] for f in canonical_forms(text(''.join(chunks))))
        roman=unique(alias.strip() for chunks in r['roman'] for alias in text(''.join(chunks)).split(','))
        if not native and not roman:raise ValueError('entry has no attested lookup form')
        key=(r['page'],unicodedata.normalize('NFC',head));homographs[key]+=1
        eid=f'platts1884.p{r["page"]}.hw{sha(key[1].encode())[:16]}.h{homographs[key]}'
        dictionary={'work':'John T. Platts, A Dictionary of Urdu, Classical Hindi, and English (1884)',
            'institution':'Digital Dictionaries of South Asia, University of Chicago',
            'url':f'{PLATTS}?page={r["page"]}','query_url':url,'print_page':r['page'],
            'entry_locator':f'{head}; homograph {homographs[key]} on printed page {r["page"]}',
            'whole_entry_text':whole,'headword_text':head,'witness_sha256':witness_sha256,
            'entry_html_sha256':sha(r['raw'].encode()),'source_revision':'DSAL digitization, site reports June 2024; exact downloaded HTML bound by hash',
            'license':'CC BY-NC-ND 2.0; private candidate index only',
            'license_url':'https://creativecommons.org/licenses/by-nc-nd/2.0/',
            'evidence_status':'direct dictionary HTML; no semantic sense selection',
            'query':query}
        entries.append({'entry_id':eid,'language':'hi','register':'classical Hindi / Hindustani, as covered by Platts1884',
            'lemma':roman[0] if roman else native[0],'source_spellings':native,'roman_search_aliases':roman,
            'dictionary':dictionary,'senses':[{'sense_id':eid+':entry','short_english':whole,
                'dictionary_anchor':whole,'context_hints':[],'prohibitions':['Entry context supplies alternatives; do not treat every listed meaning as simultaneously intended.'],
                'granularity':'entry_context','semantic_review_needed':True,'selection_status':'unselected'}]})
    return entries

DICTIONARIES = {
    'platts1884': {'endpoint': PLATTS, 'language': 'hi', 'cache_name': 'platts-hi'},
    'singh1895': {'endpoint': 'https://dsal.uchicago.edu/cgi-bin/app/singh_query.py',
        'language': 'pa', 'cache_name': 'singh-pa', 'title': 'The Panjabi Dictionary',
        'work': 'Bhai Maya Singh, The Panjabi Dictionary (1895)', 'native_tag': 'pan'},
    'madras-tamil-lexicon': {'endpoint': 'https://dsal.uchicago.edu/cgi-bin/app/tamil-lex_query.py',
        'language': 'ta', 'cache_name': 'tamil-lex-ta', 'title': 'Tamil Lexicon',
        'work': 'University of Madras, Tamil Lexicon (1924–1936), with supplement', 'native_tag': 'tam'},
}


def dictionary_spec(dictionary_id):
    if dictionary_id not in DICTIONARIES:
        raise ValueError('unsupported source dictionary')
    return DICTIONARIES[dictionary_id]


def validate_query_url(dictionary_id, query, url, matchtype='exact'):
    expected = urllib.parse.urlparse(dictionary_spec(dictionary_id)['endpoint'])
    parsed = urllib.parse.urlparse(url); params = urllib.parse.parse_qs(parsed.query)
    if ((parsed.scheme, parsed.netloc, parsed.path) != (expected.scheme, expected.netloc, expected.path)
            or params.get('qs') != [query] or params.get('matchtype') != [matchtype]
            or params.get('searchhws') != ['yes']):
        raise ValueError('dictionary query identity mismatch')


class IndicDictionaryParser(HTMLParser):
    """Observed DDSA Punjabi/Tamil entry containers; raw spans remain intact."""
    def __init__(self, source, dictionary_id):
        super().__init__(convert_charrefs=True)
        self.source=source; self.spec=dictionary_spec(dictionary_id); self.offsets=[0]
        for line in source.splitlines(True):self.offsets.append(self.offsets[-1]+len(line))
        self.records=[];self.current=None;self.depth=0;self.page=None;self.printed_page=None
        self.head_link=None;self.anchor=None;self.anchor_text=[];self.in_hw=False;self.field=None
    def source_offset(self):
        line,col=self.getpos();return self.offsets[line-1]+col
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if self.current is None and tag=='a':
            parsed=urllib.parse.urlparse(urllib.parse.urljoin(self.spec['endpoint'],attrs.get('href','')))
            expected=urllib.parse.urlparse(self.spec['endpoint']);params=urllib.parse.parse_qs(parsed.query)
            if (parsed.scheme,parsed.netloc,parsed.path)==(expected.scheme,expected.netloc,expected.path):
                if len(params.get('page',[]))==1 and params['page'][0].isdigit():
                    self.page=int(params['page'][0]);self.anchor='page';self.anchor_text=[]
                elif 'qs' in params:
                    self.anchor='head';self.anchor_text=[]
        if tag=='div':
            if self.current is not None:self.depth+=1
            elif 'px-4' in attrs.get('class','').split():
                self.current={'page':self.page,'print_page':self.printed_page,'lookup_head':self.head_link,
                    'start':self.source_offset(),'whole':[],'head':[],'native':[],'roman':[]}
                self.depth=1;self.page=None;self.printed_page=None;self.head_link=None
        if self.current is not None:
            if tag=='hw':self.in_hw=True
            if self.in_hw and tag in (self.spec['native_tag'],'t'):
                self.field='native' if tag==self.spec['native_tag'] else 'roman'
                self.current[self.field].append([])
    def handle_endtag(self,tag):
        if self.current is None:
            if tag=='a' and self.anchor:
                value=text(''.join(self.anchor_text))
                if self.anchor=='head':self.head_link=value
                else:
                    match=re.fullmatch(r'p\.\s*(S\d+|\d+)',value)
                    if match:self.printed_page=int(match[1]) if match[1].isdigit() else match[1]
                self.anchor=None;self.anchor_text=[]
            return
        if tag in (self.spec['native_tag'],'t'):self.field=None
        if tag=='hw':self.in_hw=False
        if tag=='div':
            self.depth-=1
            if self.depth==0:
                self.current['raw']=self.source[self.current['start']:self.source_offset()]
                self.records.append(self.current);self.current=None;self.in_hw=False;self.field=None
    def handle_data(self,data):
        if self.current is None:
            if self.anchor:self.anchor_text.append(data)
            return
        self.current['whole'].append(data)
        if self.in_hw:self.current['head'].append(data)
        if self.field:self.current[self.field][-1].append(data)
        elif self.in_hw and self.spec['language']=='pa':
            if not self.current['roman']:self.current['roman'].append([])
            self.current['roman'][0].append(data)


def dictionary_parser(source, dictionary_id='platts1884'):
    parser=PlattsParser(source) if dictionary_id=='platts1884' else IndicDictionaryParser(source,dictionary_id)
    parser.feed(source);parser.close()
    return parser


def parse_dictionary_html(dictionary_id, source, *, query, url, witness_sha256):
    spec=dictionary_spec(dictionary_id);valid_hash(witness_sha256)
    mode='containing' if query.startswith('containing:') else 'exact'
    requested=query[len('containing:'):] if mode=='containing' else query
    validate_query_url(dictionary_id,requested,url,mode)
    if dictionary_id=='platts1884':
        return parse_platts_html(source,query=query,url=url,witness_sha256=witness_sha256)
    title=re.search(r'<title>(.*?)</title>',source,re.I|re.S)
    if title is None or text(html.unescape(title[1]))!=spec['title']:
        raise ValueError('dictionary response identity differs')
    parser=dictionary_parser(source,dictionary_id)
    if parser.current is not None:raise ValueError('unterminated dictionary entry container')
    if not parser.records:
        if 'No results for search term' in source:return []
        raise ValueError('not a recognized dictionary result/miss page')
    entries=[];homographs=collections.Counter()
    for record in parser.records:
        head=text(''.join(record['head']));whole=text(''.join(record['whole']))
        native=unique(f for chunks in record['native'] for f in canonical_forms(text(''.join(chunks))))
        if record['lookup_head']:native=unique(native+canonical_forms(record['lookup_head']))
        roman=unique(text(''.join(chunks)) for chunks in record['roman'])
        if not head or not whole or not native or not record['page'] or record['print_page'] is None:
            raise ValueError('entry lacks witnessed headword, citation or body')
        key=(record['print_page'],unicodedata.normalize('NFC',head));homographs[key]+=1
        eid=f'{dictionary_id}.p{record["print_page"]}.hw{sha(key[1].encode())[:16]}.h{homographs[key]}'
        dictionary={'dictionary_id':dictionary_id,'work':spec['work'],
            'institution':'Digital Dictionaries of South Asia, University of Chicago',
            'url':spec['endpoint']+'?page='+str(record['page']),'query_url':url,
            'print_page':record['print_page'],'transport_page':record['page'],
            'entry_locator':f'{head}; homograph {homographs[key]} on printed page {record["print_page"]}',
            'whole_entry_text':whole,'headword_text':head,'witness_sha256':witness_sha256,
            'entry_html_sha256':sha(record['raw'].encode()),
            'source_revision':'DDSA digitization; exact downloaded HTML bound by hash',
            'license':'CC BY-NC-ND 2.0; private candidate index only',
            'license_url':'https://creativecommons.org/licenses/by-nc-nd/2.0/',
            'evidence_status':'direct dictionary HTML; no semantic sense selection','query':query}
        entries.append({'entry_id':eid,'language':spec['language'],'register':'historical dictionary usage',
            'lemma':roman[0] if roman else native[0],'source_spellings':native,'roman_search_aliases':roman,
            'dictionary':dictionary,'senses':[{'sense_id':eid+':entry','short_english':whole,
                'dictionary_anchor':whole,'context_hints':[],
                'prohibitions':['Entry context supplies alternatives; do not treat every listed meaning as simultaneously intended.'],
                'granularity':'entry_context','semantic_review_needed':True,'selection_status':'unselected'}]})
    return entries

def merge_entries(entries):
    by_id={}
    for entry in entries:
        eid=entry['entry_id']
        if eid in by_id:
            old=by_id[eid]
            for field in ('whole_entry_text','headword_text','print_page'):
                if old['dictionary'].get(field)!=entry['dictionary'].get(field):raise ValueError(f'conflicting witness for {eid}')
            if old['senses']!=entry['senses'] or old['language']!=entry['language']:raise ValueError(f'conflicting senses/language for {eid}')
            old.setdefault('additional_witnesses',[])
            witness={k:entry['dictionary'].get(k) for k in ('query','query_url','witness_sha256','entry_html_sha256')}
            if witness not in old['additional_witnesses']:old['additional_witnesses'].append(witness)
        else:by_id[eid]=json.loads(json.dumps(entry,ensure_ascii=False))
    return list(by_id.values())

def load_cached_witness(root,record):
    valid_hash(record['sha256']);path=(Path(root)/record['path']).resolve()
    if not path.is_relative_to(Path(root).resolve()):raise ValueError('witness path escapes private cache')
    raw=path.read_bytes()
    if sha(raw)!=record['sha256']:raise ValueError('cached witness SHA256 mismatch')
    return raw

def acquire_queries(root, queries, *, opener=None, timeout=25, matchtype='exact', dictionary_id='platts1884'):
    """Fetch explicitly requested dictionary queries; cache failures are never lexical misses."""
    spec=dictionary_spec(dictionary_id)
    root=Path(root);root.mkdir(parents=True,exist_ok=True);(root/'witnesses').mkdir(exist_ok=True)
    manifest=root/'acquisition.json';records=json.loads(manifest.read_text()) if manifest.exists() else []
    if matchtype not in ('exact','containing'):raise ValueError('unsupported query mode')
    if any(r.get('dictionary_id','platts1884')!=dictionary_id for r in records):
        raise ValueError('cached dictionary adapter identity mismatch')
    existing={r['query']:r for r in records};selected=[];open_url=opener or urllib.request.urlopen
    for query in unique(queries):
        if not isinstance(query,str) or not query.strip():raise ValueError('query must be nonempty text')
        query=query.strip();key=query if matchtype=='exact' else matchtype+':'+query
        if key in existing:
            record=existing[key]
            validate_query_url(dictionary_id,query,record.get('url',''),matchtype)
            if 'error' not in record:load_cached_witness(root,record)
            selected.append(record);continue
        url=spec['endpoint']+'?'+urllib.parse.urlencode({'qs':query,'searchhws':'yes','matchtype':matchtype})
        try:
            response=open_url(url,timeout=timeout)
            try:raw=response.read()
            finally:response.close()
            digest=sha(raw);path='witnesses/'+digest+'.html';(root/path).write_bytes(raw)
            record={'query':key,'url':url,'path':path,'sha256':digest,'status':'fetched'}
        except (OSError,TimeoutError) as exc:
            record={'query':key,'url':url,'status':'fetch_error','error':str(exc)}
        if dictionary_id!='platts1884':record['dictionary_id']=dictionary_id
        records.append(record);existing[key]=record;selected.append(record)
        temporary=manifest.with_suffix('.json.tmp');temporary.write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n');temporary.replace(manifest)
    return selected

def import_csl_json(payload, *, dictionary_code, edition, witness_sha256, forms=None, rejected_records=None):
    valid_hash(witness_sha256)
    data=payload.get('data',payload);words=data.get('words');records=data.get('text')
    if not isinstance(words,dict) or not isinstance(records,dict):raise ValueError('CSL requires words/text maps')
    by_l={};row_l={}
    for rid,record in records.items():
        if not isinstance(record,list) or len(record)!=3 or any(not isinstance(x,str) for x in record):raise ValueError('malformed CSL record')
        body,page,lnum=record
        if not re.fullmatch(r'\d+(?:\.\d+)*',lnum) or not page:raise ValueError('malformed CSL page/L')
        if not body.strip():
            if rejected_records is None:raise ValueError('empty CSL definition requires explicit gap report')
            rejected_records.append({'source_row_id':rid,'source_fragment_id':lnum,'print_locus':page,'witness_sha256':witness_sha256,'reason':'source definition is empty; no candidate invented'})
        if lnum in by_l:raise ValueError('duplicate stable CSL L')
        by_l[lnum]=(body,page);row_l[rid]=lnum
    aliases=collections.defaultdict(list);selected=set()
    for form,joined in words.items():
        if not isinstance(form,str) or not isinstance(joined,str):raise ValueError('malformed native lookup form')
        for rid in joined.split(','):
            if rid not in row_l:raise ValueError('CSL alias references missing record')
            root=row_l[rid].split('.')[0]
            if form not in aliases[root]:aliases[root].append(form)
            if forms is None or form in forms:selected.add(root)
    groups=collections.defaultdict(list)
    for lnum,(body,page) in by_l.items():
        root=lnum.split('.')[0]
        if root in selected and body.strip():groups[root].append((lnum,body,page))
    entries=[]
    for root,rows in groups.items():
        rows.sort(key=lambda x:tuple(map(int,x[0].split('.'))))
        eid=f'csl.{dictionary_code}{edition}.L{root}';whole=''.join(x[1] for x in rows)
        senses=[{'sense_id':f'{eid}:L{lnum}','short_english':body,'dictionary_anchor':body,
            'source_fragment_id':lnum,'print_locus':page,'context_hints':[],'prohibitions':['Read this source fragment with the complete parent entry; inherited grammatical restrictions remain applicable.'],
            'granularity':'source_fragment','semantic_review_needed':True,'selection_status':'unselected'} for lnum,body,page in rows]
        entries.append({'entry_id':eid,'language':'sa','register':'Sanskrit; source-specific literary restrictions remain in whole entry',
            'lemma':aliases[root][0],'source_spellings':aliases[root],'roman_search_aliases':[],
            'dictionary':{'work':f'Cologne {dictionary_code.upper()}, print edition {edition}',
                'url':payload.get('source',''),'print_page':rows[0][2],'entry_locator':f'Cologne L={root}; page-column {rows[0][2]}',
                'whole_entry_text':whole,'witness_sha256':witness_sha256,'source_revision':'local official-CSL-derived JSON witness; exact file bound by hash',
                'license':'CC BY-SA 4.0','license_url':'https://github.com/sanskrit-lexicon/csl-json/blob/main/LICENSE',
                'source_fragments':[{'L':l,'page_column':p,'text':b} for l,b,p in rows]},'senses':senses})
    return entries

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('acquire');p.add_argument('--queries',required=True,type=Path);p.add_argument('--cache',required=True,type=Path);p.add_argument('--matchtype',choices=['exact','containing'],default='exact');p.add_argument('--timeout',type=float,default=25)
    p=sub.add_parser('platts-cache');p.add_argument('cache',type=Path);p.add_argument('--output',required=True,type=Path)
    p=sub.add_parser('csl');p.add_argument('input',type=Path);p.add_argument('--code',required=True);p.add_argument('--edition',required=True);p.add_argument('--forms',type=Path);p.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if args.command=='acquire':
        queries=json.loads(args.queries.read_text());queries=list(queries) if isinstance(queries,dict) else queries
        if not isinstance(queries,list):raise ValueError('queries JSON must be array or vocabulary object')
        queries=unique(form for q in queries for form in query_forms(q)) if args.matchtype=='exact' else queries
        rows=acquire_queries(args.cache,queries,timeout=args.timeout,matchtype=args.matchtype)
        print(json.dumps({'queries':len(rows),'errors':[r for r in rows if 'error' in r]},ensure_ascii=False));return
    if args.command=='platts-cache':
        entries=[];misses=[];errors=[]
        for r in json.loads((args.cache/'acquisition.json').read_text()):
            if 'error' in r:errors.append(r);continue
            try:
                found=parse_platts_html(load_cached_witness(args.cache,r).decode('utf-8'),query=r['query'],url=r['url'],witness_sha256=r['sha256'])
                entries.extend(found)
                if not found:misses.append(r['query'])
            except (ValueError,UnicodeError) as exc:errors.append({'query':r['query'],'error':str(exc)})
        entries=merge_entries(entries);report={'queries':len(json.loads((args.cache/'acquisition.json').read_text())),'misses':misses,'errors':errors}
    else:
        raw=args.input.read_bytes();forms=json.loads(args.forms.read_text()) if args.forms else None
        gaps=[]
        entries=import_csl_json(json.loads(raw),dictionary_code=args.code,edition=args.edition,witness_sha256=sha(raw),forms=set(forms) if forms else None,rejected_records=gaps);report={'source':str(args.input),'witness_sha256':sha(raw),'rejected_source_fragments':gaps}
    result={'schema_version':1,'status':'private dictionary candidates; not song gloss authority','automatic_replacement':False,'report':report,'entries':entries}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'entries':len(entries),'sense_candidates':sum(len(e['senses']) for e in entries),'output':str(args.output),'errors':report.get('errors',[])},ensure_ascii=False))
if __name__=='__main__':main()
