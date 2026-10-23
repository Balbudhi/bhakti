"""Exact source-language retrieval plus cached context ranking of attested senses.

Dense order is evidence presentation, never a sense decision or a source rewrite.
"""
from __future__ import annotations
import argparse, hashlib, json, math, os, sqlite3, time, unicodedata
from pathlib import Path
from bhakti_embedding_client import EmbeddingClient, MODEL, DIMENSIONS, MAX_INPUT_BYTES, validate_vector, file_lock
import source_word_map

DEFAULT_SPACE={'model':MODEL,'dimensions':DIMENSIONS,'provider':'google-vertex','task':'default','format_version':1}
LANGUAGES={'hindi':'hi','hindustani':'hi','classical hindi':'hi','punjabi':'pa','sanskrit':'sa','marathi':'mr','kannada':'kn','tamil':'ta','telugu':'te','odia':'or','bengali':'bn','malayalam':'ml','urdu':'ur','persian':'fa','awadhi':'awa','braj':'bra','rajasthani':'raj'}

def canonical(value): return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()
def token(value): return unicodedata.normalize('NFC',value).casefold().strip().strip('.,;:!?।॥()[]{}"\'“”‘’')
def language(value):
    key=str(value or '').strip().casefold()
    return key if key in LANGUAGES.values() else LANGUAGES.get(key,'')

def line_language(line, languages):
    if 'sourceLanguage' in line: return language(line['sourceLanguage'])
    codes={language(item) for item in languages or []}
    return next(iter(codes)) if len(codes)==1 and '' not in codes else ''

def validate_lexicon(lexicon):
    if not isinstance(lexicon,dict) or not isinstance(lexicon.get('entries'),list): raise ValueError('lexicon entries missing')
    seen=set()
    for entry in lexicon['entries']:
        if not isinstance(entry,dict) or not isinstance(entry.get('entry_id'),str) or not entry['entry_id'] or entry['entry_id'] in seen: raise ValueError('invalid/duplicate entry ID')
        seen.add(entry['entry_id'])
        if entry.get('language') not in LANGUAGES.values(): raise ValueError('entry needs explicit supported language')
        if not isinstance(entry.get('register'),str) or not entry['register']: raise ValueError('entry register missing')
        for field in ('source_spellings','roman_search_aliases'):
            if not isinstance(entry.get(field),list) or any(not isinstance(v,str) or not v for v in entry[field]): raise ValueError('invalid entry aliases')
        citation=entry.get('dictionary')
        if not isinstance(citation,dict) or not citation.get('url') or not citation.get('work'): raise ValueError('entry source citation missing')
        senses=entry.get('senses');ids=set()
        if not isinstance(senses,list) or not senses: raise ValueError('entry has no attested senses')
        for sense in senses:
            if not isinstance(sense,dict) or not isinstance(sense.get('sense_id'),str) or not sense['sense_id'] or sense['sense_id'] in ids or not isinstance(sense.get('short_english'),str) or not sense['short_english']: raise ValueError('invalid/duplicate sense')
            ids.add(sense['sense_id'])
        for link in entry.get('lemma_links',[]):
            if not isinstance(link,dict) or link.get('language')!=entry['language'] or any(not isinstance(link.get(k),str) or not link[k] for k in ('source_form','roman_form','reason')) or not link.get('evidence'): raise ValueError('lemma link lacks exact language/form/evidence')
    return lexicon['entries']

def lookup_tables(lexicon):
    native={};roman={};links={}
    for entry in validate_lexicon(lexicon):
        code=entry['language']
        for field,table in [('source_spellings',native),('roman_search_aliases',roman)]:
            for alias in entry[field]:
                bucket=table.setdefault((code,token(alias)),[])
                if entry not in bucket: bucket.append(entry)
        for link in entry.get('lemma_links',[]): links.setdefault((code,token(link['roman_form'])),[]).append((entry,link))
    return native,roman,links

def exact_entries(surface, code, lexicon):
    native,roman,_=lookup_tables(lexicon);result={}
    for entry in native.get((code,token(surface)),[])+roman.get((code,token(surface)),[]): result[entry['entry_id']]=entry
    return list(result.values())

def word_tokens(line):
    """Preserve validated reader compound subdivisions; never infer new splits."""
    roman=unicodedata.normalize('NFC',str(line.get('roman',''))).casefold()
    if 'lexical_tokens' in line:
        tokens=line['lexical_tokens']
    elif 'words' in line:
        words=line['words']
        if not isinstance(words,list) or any(not isinstance(w,dict) for w in words):raise ValueError('invalid reader word map')
        tokens=[w.get('roman') for w in words]
    else:
        return source_word_map.lexical_tokens(line.get('roman',''))
    if not isinstance(tokens,list) or any(not isinstance(t,str) or not any(c.isalnum() for c in t) for t in tokens):raise ValueError('invalid lexical tokens')
    cursor=0
    for surface in tokens:
        folded=unicodedata.normalize('NFC',surface).casefold();position=roman.find(folded,cursor)
        if position<0:raise ValueError('lexical token does not match ordered roman span')
        if any(unicodedata.category(c)[0] in {'L','M'} for c in roman[cursor:position]):raise ValueError('roman letters lack a lexical token')
        cursor=position+len(folded)
    if any(unicodedata.category(c)[0] in {'L','M'} for c in roman[cursor:]):raise ValueError('roman letters lack a lexical token')
    return list(tokens)

def token_candidates(lines,languages,lexicon):
    native,roman,links=lookup_tables(lexicon);result={}
    for line in lines:
        tokens=word_tokens(line)
        code=line_language(line,languages);register=line.get('lexicalRegister');mapped={}
        if line.get('sourceWords') is not None:
            errors=source_word_map.validate_source_words(line.get('source_text',line.get('source','')), [{'roman':t} for t in tokens],line['sourceWords'])
            if errors: raise ValueError('invalid sourceWords for lexical retrieval: '+'; '.join(errors))
            for row in line['sourceWords']:
                for i in row['wordIndices']:mapped.setdefault(i,[]).append(row)
        rows=[]
        for i,surface in enumerate(tokens):
            entries={e['entry_id']:e for e in roman.get((code,token(surface)),[])};evidence=[]
            # Use only an existing unambiguous one-native-token/one-roman-token map.
            maps=mapped.get(i,[])
            if len(maps)==1 and maps[0]['wordIndices']==[i]:
                for e in native.get((code,token(maps[0]['text'])),[]):entries[e['entry_id']]=e
            for entry,link in links.get((code,token(surface)),[]):
                if maps and (len(maps)!=1 or token(maps[0]['text'])!=token(link['source_form'])): continue
                entries[entry['entry_id']]=entry;evidence.append(link)
            candidates=[e for e in entries.values() if not register or e['register']==register]
            row={'word_index':i,'roman':surface,'candidates':candidates}
            if evidence:row['lemma_evidence']=evidence
            rows.append(row)
        result[line['id']]=rows
    return result

def source_view(line):
    return {'id':line.get('id'),'source_text':line.get('source_text',line.get('source','')),'roman':line.get('roman','')}

def query_context(line, surface, languages, *, context_lines=None, performance_order=None):
    if 'performed_context' in line:
        contexts=line['performed_context']
    elif context_lines is not None and performance_order is not None:
        by_id={item['id']:item for item in context_lines};ordered=[]
        for event in performance_order:
            ref=event.get('ref',event.get('line_id'))
            if ref not in by_id:raise ValueError('lexical context has unknown performance reference')
            ordered.append(source_view(by_id[ref]))
        contexts=[]
        for index,item in enumerate(ordered):
            if item['id']==line['id']:
                context={'before':ordered[max(0,index-2):index],'after':ordered[index+1:index+3]}
                if context not in contexts:contexts.append(context)
    else:contexts=[]
    # Never use arbitrary batch list positions as performed neighbors.
    return canonical({'language':line_language(line,languages),'surface':surface,'target':source_view(line),'performed_context':contexts})

class LexicalIndex:
    def __init__(self,path,space=None):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.space=space or DEFAULT_SPACE
        self.db=sqlite3.connect(str(self.path));self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL); CREATE TABLE IF NOT EXISTS entries(entry_id TEXT PRIMARY KEY,entry_hash TEXT,entry_json TEXT); CREATE TABLE IF NOT EXISTS senses(entry_id TEXT REFERENCES entries(entry_id),sense_id TEXT,sense_json TEXT,document TEXT,PRIMARY KEY(entry_id,sense_id)); CREATE TABLE IF NOT EXISTS aliases(language TEXT,kind TEXT,surface TEXT,entry_id TEXT REFERENCES entries(entry_id),PRIMARY KEY(language,kind,surface,entry_id)); CREATE TABLE IF NOT EXISTS vectors(key TEXT PRIMARY KEY,space TEXT,text TEXT,kind TEXT,vector TEXT);')
        old=self.db.execute("SELECT value FROM metadata WHERE key='space'").fetchone()
        if old and json.loads(old[0])!=self.space:
            self.db.close();raise ValueError('index embedding space differs; use a new index')
        with self.db:self.db.execute("INSERT OR IGNORE INTO metadata VALUES('space',?)",(canonical(self.space),))
    def close(self): self.db.close()
    def __enter__(self): return self
    def __exit__(self,*args): self.close()
    def __del__(self):
        if hasattr(self,'db'): self.db.close()
    def build(self,lexicon):
        entries=validate_lexicon(lexicon);count=0
        with self.db:
            self.db.execute('DELETE FROM aliases');self.db.execute('DELETE FROM senses');self.db.execute('DELETE FROM entries');self.db.execute("DELETE FROM metadata WHERE key='corpus_receipt'")
            for entry in entries:
                self.db.execute('INSERT INTO entries VALUES(?,?,?)',(entry['entry_id'],digest(entry),canonical(entry)))
                aliases=[('native',a) for a in entry['source_spellings']]+[('roman',a) for a in entry['roman_search_aliases']]+[('roman',a['roman_form']) for a in entry.get('lemma_links',[])]
                self.db.executemany('INSERT OR IGNORE INTO aliases VALUES(?,?,?,?)',[(entry['language'],kind,token(alias),entry['entry_id']) for kind,alias in aliases])
                for sense in entry['senses']:
                    document=canonical({'language':entry['language'],'register':entry['register'],'lemma':entry.get('lemma',''),'sense_id':sense['sense_id'],'definition':sense['short_english'],'anchor':sense.get('dictionary_anchor',''),'context_hints':sense.get('context_hints',[]),'restrictions':sense.get('prohibitions',[])})
                    self.db.execute('INSERT INTO senses VALUES(?,?,?,?)',(entry['entry_id'],sense['sense_id'],canonical(sense),document));count+=1
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES('lexicon_hash',?)",(digest(lexicon),))
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES('lookup_schema','1')")
        return {'entries':len(entries),'senses':count,'lexicon_hash':digest(lexicon)}
    @staticmethod
    def _file_stat(path):
        path=Path(path).resolve();st=path.stat()
        return {'path':str(path),'size':st.st_size,'mtime_ns':st.st_mtime_ns,'ctime_ns':st.st_ctime_ns,'device':st.st_dev,'inode':st.st_ino}
    @staticmethod
    def _file_hash(path):
        h=hashlib.sha256()
        with Path(path).open('rb') as source:
            for block in iter(lambda:source.read(1024*1024),b''):h.update(block)
        return h.hexdigest()
    def build_file(self,path):
        before=self._file_stat(path)
        with Path(path).open(encoding='utf-8') as source:lexicon=json.load(source)
        raw_hash=self._file_hash(path)
        if self._file_stat(path)!=before:raise RuntimeError('corpus changed while building index')
        result=self.build(lexicon)
        with self.db:self.db.execute("INSERT OR REPLACE INTO metadata VALUES('corpus_receipt',?)",(canonical({'stat':before,'sha256':raw_hash}),))
        return result
    def verify_corpus(self,path):
        row=self.db.execute("SELECT value FROM metadata WHERE key='corpus_receipt'").fetchone()
        if not row:raise RuntimeError('index lacks configured corpus identity; rebuild from file')
        receipt=json.loads(row[0]);current=self._file_stat(path)
        if current==receipt['stat']:return
        raw_hash=self._file_hash(path)
        if self._file_stat(path)!=current or raw_hash!=receipt['sha256']:raise RuntimeError('configured corpus differs from indexed corpus; rebuild explicitly')
        with self.db:self.db.execute("UPDATE metadata SET value=? WHERE key='corpus_receipt'",(canonical({'stat':current,'sha256':raw_hash}),))
    def lexicon_for(self,lines,languages):
        schema=self.db.execute("SELECT value FROM metadata WHERE key='lookup_schema'").fetchone()
        if not schema or schema[0]!='1':raise RuntimeError('index needs exact-alias rebuild')
        keys=set()
        for line in lines:
            code=line_language(line,languages)
            keys.update((code,'roman',token(surface)) for surface in word_tokens(line))
            for field,kind in [('source_text','native'),('source','native'),('roman','roman')]:
                keys.update((code,kind,token(surface)) for surface in str(line.get(field,'')).split())
            for mapping in line.get('sourceWords') or []:
                if isinstance(mapping,dict) and isinstance(mapping.get('text'),str):keys.add((code,'native',token(mapping['text'])))
        found={}
        for key in sorted(keys):
            for ordinal,raw in self.db.execute('SELECT e.rowid,e.entry_json FROM aliases a JOIN entries e ON e.entry_id=a.entry_id WHERE a.language=? AND a.kind=? AND a.surface=?',key):found[ordinal]=raw
        return {'entries':[json.loads(found[k]) for k in sorted(found)]}
    def fingerprint(self):
        row=self.db.execute("SELECT value FROM metadata WHERE key='lexicon_hash'").fetchone()
        if not row:raise RuntimeError('lexical index has not been built')
        return {'space':self.space,'lexicon_hash':row[0]}
    def _rows(self,candidates):
        result=[]
        for entry in candidates:
            rows=self.db.execute('SELECT s.entry_id,s.sense_id,e.entry_hash,e.entry_json,s.sense_json,s.document FROM senses s JOIN entries e ON e.entry_id=s.entry_id WHERE s.entry_id=? ORDER BY s.sense_id',(entry['entry_id'],)).fetchall()
            if not rows or any(row[2]!=digest(entry) for row in rows):raise RuntimeError('stale or missing indexed dictionary entry: '+entry['entry_id'])
            result.extend(rows)
        return result
    def _key(self,text,kind,entry_hash=''):return digest({'space':self.space,'text':text,'kind':kind,'entry_hash':entry_hash})
    def _cached(self,text,kind,entry_hash=''):
        row=self.db.execute('SELECT space,text,kind,vector FROM vectors WHERE key=?',(self._key(text,kind,entry_hash),)).fetchone()
        if row is None:return None
        if json.loads(row[0])!=self.space or row[1]!=text or row[2]!=kind:raise ValueError('cached vector identity mismatch')
        vector=json.loads(row[3]);validate_vector(vector,self.space['dimensions']);return vector
    def _save(self,text,kind,vector,entry_hash=''):
        validate_vector(vector,self.space['dimensions'])
        with self.db:self.db.execute('INSERT OR REPLACE INTO vectors VALUES(?,?,?,?,?)',(self._key(text,kind,entry_hash),canonical(self.space),text,kind,canonical(vector)))
    def embed_documents(self,encoder,candidates):
        with file_lock(self.path.with_suffix(self.path.suffix+'.embedding.lock')):
            return self._embed_documents(encoder,candidates)
    def _embed_documents(self,encoder,candidates):
        rows=self._rows(candidates);pending=[];holds=[]
        for row in rows:
            if len(row[5].encode())>MAX_INPUT_BYTES:holds.append({'entry_id':row[0],'sense_id':row[1],'reason':'input_too_long'});continue
            if self._cached(row[5],'document',row[2]) is None:pending.append(row)
        for offset in range(0,len(pending),16):
            batch=pending[offset:offset+16];vectors=encoder.embed([row[5] for row in batch])
            if len(vectors)!=len(batch):raise ValueError('encoder cardinality differs')
            for row,vector in zip(batch,vectors):self._save(row[5],'document',vector,row[2])
        return {'embedded':len(pending),'size_holds':holds}
    def embed_queries(self,encoder,texts):
        with file_lock(self.path.with_suffix(self.path.suffix+'.embedding.lock')):
            pending=[text for text in dict.fromkeys(texts) if len(text.encode())<=MAX_INPUT_BYTES and self._cached(text,'query') is None]
            for offset in range(0,len(pending),16):
                batch=pending[offset:offset+16];vectors=encoder.embed(batch)
                if len(vectors)!=len(batch):raise ValueError('query encoder cardinality differs')
                for text,vector in zip(batch,vectors):self._save(text,'query',vector)
            return {'embedded':len(pending),'size_holds':sum(len(text.encode())>MAX_INPUT_BYTES for text in texts)}
    def rank(self,candidates,query_text,encoder=None):
        if not candidates:return []
        rows=self._rows(candidates)
        if encoder:self.embed_documents(encoder,candidates)
        query=None;query_status='query_input_too_long' if len(query_text.encode())>MAX_INPUT_BYTES else 'query_not_cached'
        if query_status!='query_input_too_long':
            query=self._cached(query_text,'query')
            if query is None and encoder:
                self.embed_queries(encoder,[query_text]);query=self._cached(query_text,'query')
        results=[]
        for entry_id,sense_id,entry_hash,entry_json,sense_json,document in rows:
            vector=self._cached(document,'document',entry_hash);score=None
            if len(document.encode())>MAX_INPUT_BYTES:status='input_too_long'
            elif query is None:status=query_status
            elif vector is None:status='document_not_cached'
            else:
                status='ranked';score=sum(a*b for a,b in zip(query,vector))/(math.sqrt(sum(a*a for a in query))*math.sqrt(sum(b*b for b in vector)))
            entry=json.loads(entry_json)
            results.append({'entry_id':entry_id,'sense_id':sense_id,'language':entry['language'],'register':entry['register'],'dictionary':entry['dictionary'],'sense':json.loads(sense_json),'score':score,'status':status})
        return sorted(results,key=lambda row:(row['score'] is None,-(row['score'] or 0),row['entry_id'],row['sense_id']))

def configured_encoder():
    path=os.environ.get('BHAKTI_EMBEDDING_LEDGER')
    if not path:return None
    return EmbeddingClient(path,budget_usd=float(os.environ['BHAKTI_EMBEDDING_BUDGET_USD']),max_calls=int(os.environ['BHAKTI_EMBEDDING_MAX_CALLS']),deadline_at=float(os.environ['BHAKTI_EMBEDDING_DEADLINE_AT']))

def guidance_rankings(lines,languages,lexicon,*,context_lines=None,performance_order=None):
    path=os.environ.get('BHAKTI_LEXICAL_INDEX')
    if not path:return []
    candidates=token_candidates(lines,languages,lexicon);encoder=configured_encoder();out=[];jobs=[];needed={}
    for line in lines:
        for word in candidates[line['id']]:
            if not word['candidates']:continue
            context=query_context(line,word['roman'],languages,context_lines=context_lines,performance_order=performance_order)
            jobs.append((line,word,context))
            for entry in word['candidates']:needed[entry['entry_id']]=entry
    with LexicalIndex(path) as index:
        if encoder:
            index.embed_documents(encoder,list(needed.values()))
            index.embed_queries(encoder,[context for _,_,context in jobs])
        for line,word,context in jobs:
            out.append({'line_id':line['id'],'word_index':word['word_index'],'roman':word['roman'],'context':json.loads(context),'senses':index.rank(word['candidates'],context)})
    return out

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('operation',choices=['build','query']);parser.add_argument('--lexicon',type=Path,required=True);parser.add_argument('--index',type=Path,required=True);parser.add_argument('--token');parser.add_argument('--language');parser.add_argument('--context',default='');parser.add_argument('--embed',action='store_true')
    args=parser.parse_args();index=LexicalIndex(args.index)
    if args.operation=='build':result=index.build_file(args.lexicon)
    else:
        if not args.token or not args.language:parser.error('query requires --token and --language')
        index.verify_corpus(args.lexicon)
        lexicon=index.lexicon_for([{'roman':args.token,'source_text':args.token}],[args.language])
        entries=exact_entries(args.token,language(args.language),lexicon)
        encoder=configured_encoder() if args.embed else None
        if args.embed and encoder is None:parser.error('--embed requires explicit embedding ledger/budget/call/deadline environment')
        result=index.rank(entries,canonical({'language':language(args.language),'surface':args.token,'context':args.context}),encoder)
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
