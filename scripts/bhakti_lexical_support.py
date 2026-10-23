"""Targeted witnessed lexical support for existing production text stages.

This module retrieves evidence, not meanings. No model/network calls are made.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, re
from pathlib import Path
import bhakti_lexical_retrieval as lexical

VERSION = 1
KINDS = {'current_language_usage','traditional_definition','traditional_formation',
         'traditional_nirvacana','language_relationship','english_definition'}
POS = {'noun':'n','verb':'v','adj':'a','adv':'r'}

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def content_digest(packet, *, english_grammar=True):
    """Hash evidence and coverage, excluding relocatable local transport paths."""
    content=copy.deepcopy(packet)
    for evidence in content.get('evidence',[]):
        evidence.pop('witness_path',None)
        if evidence.get('kind') == 'english_definition':
            grammar = wordnet_grammar(evidence)
            if english_grammar:
                evidence['grammar'] = grammar
            else:
                evidence.pop('grammar', None)
    if content.get('english_lookup'):
        content['english_lookup'].pop('directory',None)
    return digest(content)

def normalize_english_lemma(value):
    return value.casefold().replace('_',' ').strip()

def english_queries(values):
    require(isinstance(values,list) and all(isinstance(v,str) for v in values),'English lookup queries invalid')
    requested=list(dict.fromkeys(normalize_english_lemma(v) for v in values))
    require(all(requested),'empty WordNet lemma')
    return requested

def file_hash(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read_json(path): return json.loads(Path(path).read_text())
def require(ok, message):
    if not ok: raise ValueError(message)

def local_path(base, name):
    result=(base/str(name)).resolve()
    require(result.is_relative_to(base.resolve()),'witness path escapes manifest directory')
    return result

def _parse_wordnet_row(raw, offset, pos):
    head,sep,gloss=raw.partition('|');fields=head.split()
    require(bool(sep) and len(fields)>=5,'malformed WordNet row')
    require(int(fields[0])==offset and fields[2] in ({'a','s'} if pos=='a' else {pos}),'WordNet offset/POS mismatch')
    count=int(fields[3],16);cursor=4;words=[]
    for _ in range(count):
        word,lexid=fields[cursor:cursor+2];int(lexid,16);cursor+=2
        words.append(re.sub(r'\((?:a|p|ip)\)$','',word).replace('_',' '))
    pointers=int(fields[cursor]);cursor+=1
    for _ in range(pointers):
        _,target,target_pos,indices=fields[cursor:cursor+4];int(target);int(indices,16)
        require(target_pos in 'nvasr','invalid WordNet pointer POS');cursor+=4
    if pos=='v':
        frames=int(fields[cursor]);cursor+=1
        for _ in range(frames):
            plus,number,index=fields[cursor:cursor+3];require(plus=='+','invalid WordNet frame');int(number);int(index,16);cursor+=3
    require(cursor==len(fields) and count>0 and bool(gloss.strip()),'incomplete WordNet fields/gloss')
    return words,gloss.strip()

def parse_wordnet_row(raw, offset, pos):
    try:
        return _parse_wordnet_row(raw, offset, pos)
    except (IndexError, TypeError, UnicodeError, ValueError) as exc:
        raise ValueError('Malformed WordNet record: ' + str(exc)) from exc

# Princeton WordNet's generic sentence frames:
# https://wordnet.princeton.edu/documentation/wninput5wn
VERB_FRAMES = {1: 'Something ----s',
 2: 'Somebody ----s',
 3: 'It is ----ing',
 4: 'Something is ----ing PP',
 5: 'Something ----s something Adjective/Noun',
 6: 'Something ----s Adjective/Noun',
 7: 'Somebody ----s Adjective',
 8: 'Somebody ----s something',
 9: 'Somebody ----s somebody',
 10: 'Something ----s somebody',
 11: 'Something ----s something',
 12: 'Something ----s to somebody',
 13: 'Somebody ----s on something',
 14: 'Somebody ----s somebody something',
 15: 'Somebody ----s something to somebody',
 16: 'Somebody ----s something from somebody',
 17: 'Somebody ----s somebody with something',
 18: 'Somebody ----s somebody of something',
 19: 'Somebody ----s something on somebody',
 20: 'Somebody ----s somebody PP',
 21: 'Somebody ----s something PP',
 22: 'Somebody ----s PP',
 23: "Somebody's (body part) ----s",
 24: 'Somebody ----s somebody to INFINITIVE',
 25: 'Somebody ----s somebody INFINITIVE',
 26: 'Somebody ----s that CLAUSE',
 27: 'Somebody ----s to somebody',
 28: 'Somebody ----s to INFINITIVE',
 29: 'Somebody ----s whether INFINITIVE',
 30: 'Somebody ----s somebody into V-ing something',
 31: 'Somebody ----s something with something',
 32: 'Somebody ----s INFINITIVE',
 33: 'Somebody ----s VERB-ing',
 34: 'It ----s that CLAUSE',
 35: 'Something ----s INFINITIVE'}


def wordnet_grammar(evidence):
    """Derive lexical position/frame restrictions from the verified raw record.

    Frame source word00 covers every lemma; other word numbers are one-based.
    Expose zero-based lemma indices, never spread a lemma-only frame to synonyms.
    """
    words, _ = parse_wordnet_row(evidence['raw'], evidence['synset_offset'], evidence['pos'])
    fields = evidence['raw'].partition('|')[0].split()
    count = int(fields[3], 16)
    positions = []
    labels = {'a': 'attributive', 'p': 'predicative', 'ip': 'immediately_postnominal'}
    for index in range(count):
        marker = re.search(r'\((a|p|ip)\)$', fields[4 + 2 * index])
        if marker:
            require(evidence['pos'] == 'a', 'WordNet grammar marker on non-adjective')
            positions.append({'word_index': index, 'lemma': words[index], 'position': labels[marker.group(1)]})
    cursor = 4 + 2 * count
    cursor += 1 + 4 * int(fields[cursor])
    frames = []
    if evidence['pos'] == 'v':
        total = int(fields[cursor]); cursor += 1
        for _ in range(total):
            _, number, word = fields[cursor:cursor + 3]; cursor += 3
            number, word = int(number), int(word, 16)
            require(number in VERB_FRAMES and 0 <= word <= count, 'WordNet grammar frame/index invalid')
            frames.append({'number': number, 'template': VERB_FRAMES[number],
                           'word_indices': list(range(count)) if word == 0 else [word - 1]})
    grammar = {'adjective_positions': positions, 'verb_frames': frames}
    require('grammar' not in evidence or evidence['grammar'] == grammar,
            'English grammar differs from raw witness')
    return grammar


def lookup_wordnet(directory, lemmas, *, edition):
    directory=Path(directory)
    if (directory/'manifest.json').is_file():
        manifest=read_json(directory/'manifest.json')
    else:
        require(edition in {'3.0','3.1'} and all((directory/(prefix+name)).is_file() for name in POS for prefix in ('index.','data.')), 'installed WordNet needs all four POS files or explicit subset manifest')
        manifest={'edition':edition,'available_pos':list(POS),'source':'https://wordnet.princeton.edu/',
                  'data_sha256':{name:file_hash(directory/('data.'+name)) for name in POS},
                  'index_sha256':{name:file_hash(directory/('index.'+name)) for name in POS}}
    require(manifest.get('edition')==edition,'WordNet edition mismatch')
    requested=english_queries(lemmas)
    coverage=manifest.get('complete_for_lemmas')
    if coverage is not None:
        require(set(requested)<=set(english_queries(coverage)),'WordNet subset lacks complete lemma coverage')
    available=manifest.get('available_pos');require(isinstance(available,list) and available and set(available)<=set(POS),'WordNet POS coverage undeclared')
    rows={}
    for name in available:
        pos=POS[name];index=directory/('index.'+name);data=directory/('data.'+name)
        require(file_hash(index)==manifest['index_sha256'][name] and file_hash(data)==manifest['data_sha256'][name],'WordNet witness hash mismatch')
        indexes={}
        for line in index.read_text().splitlines():
            if line.startswith('  ') or not line.strip():continue
            a=line.split();lemma=a[0].replace('_',' ')
            if lemma not in requested:continue
            require(a[1]==pos,'WordNet index POS mismatch');n=int(a[2]);p=int(a[3]);offsets=list(map(int,a[6+p:]))
            require(len(offsets)==n==int(a[4+p]) and lemma not in indexes,'WordNet index sense cardinality mismatch')
            indexes[lemma]=offsets
        with data.open('rb') as stream:
            for lemma,offsets in indexes.items():
                for offset in offsets:
                    stream.seek(offset);raw=stream.readline().decode('ascii');words,gloss=parse_wordnet_row(raw,offset,pos)
                    require(lemma in [w.casefold() for w in words],'WordNet index points to different lemma')
                    eid=f'wordnet:{edition}:{pos}:{offset:08d}'
                    if eid not in rows:
                        rows[eid]={'id':eid,'kind':'english_definition','language':'en','edition':edition,'pos':pos,'synset_offset':offset,'lemmas':words,'requested_lemmas':[],'gloss':gloss,'raw':raw,'work':'Princeton WordNet '+edition,'locus':f'data.{name}:{offset:08d}','source_url':manifest.get('source','https://wordnet.princeton.edu/'),'witness_path':str(data.resolve()),'witness_sha256':manifest['data_sha256'][name],'limitations':['Definition/example evidence; not a complete connotation dictionary.']}
                    if lemma not in rows[eid]['requested_lemmas']:rows[eid]['requested_lemmas'].append(lemma)
    for row in rows.values():
        row['requested_lemmas'].sort()
        row['grammar'] = wordnet_grammar(row)
    return sorted(rows.values(),key=lambda row:row['id'])

def wordnet_receipt(directory, edition, lemmas):
    directory=Path(directory).resolve()
    files={path.name:file_hash(path) for path in directory.iterdir()
           if path.name=='manifest.json' or path.name in {prefix+name for prefix in ('index.','data.') for name in POS}}
    return {'directory':str(directory),'edition':edition,'lemmas':english_queries(lemmas),'files':files}

def build_support(manifest_path, lines, languages):
    manifest_path=Path(manifest_path).resolve();base=manifest_path.parent;manifest=read_json(manifest_path)
    require(manifest.get('version')==VERSION,'unsupported support manifest version')
    evidence=[]
    for item in manifest.get('witnesses',[]):
        item=copy.deepcopy(item);witness=item.pop('witness');path=local_path(base,witness['path']);raw=path.read_bytes()
        require(hashlib.sha256(raw).hexdigest()==witness['sha256'],'source witness hash mismatch')
        quotation=item['quotation'];text=raw.decode('utf-8');span=witness.get('span')
        if span is not None:
            require(isinstance(span,list) and len(span)==2 and all(type(v)is int for v in span),'invalid source character span')
            require(0<=span[0]<span[1]<=len(text) and text[span[0]:span[1]]==quotation,'source quotation/span mismatch')
        else:require(bool(quotation) and text.count(quotation)==1,'source quotation absent or ambiguous')
        item.update(witness_path=str(path),witness_sha256=witness['sha256'],quotation_sha256=hashlib.sha256(quotation.encode()).hexdigest(),witness_span=span)
        evidence.append(item)
    wn=manifest.get('wordnet');english=[]
    if wn:english=lookup_wordnet(local_path(base,wn['directory']),wn['lemmas'],edition=wn['edition']);evidence+=english
    targets=copy.deepcopy(manifest.get('targets',[]))
    for target in targets:
        for candidate in target['english_candidates']:
            wanted=english_queries(candidate.get('english_lemmas',[]))
            candidate['english_lemmas']=wanted
            candidate['english_evidence_ids']=[e['id'] for e in english if set(wanted)&set(e['requested_lemmas'])]
            require(candidate.get('kind')!='word' or bool(candidate['english_evidence_ids']),'word candidate lacks acquired English evidence')
    packet={'version':VERSION,'evidence':evidence,'targets':targets}
    if wn:packet['english_lookup']=wordnet_receipt(local_path(base,wn['directory']),wn['edition'],wn['lemmas'])
    validate_support(packet,lines,languages);return packet

def validate_support(packet, lines, languages):
    require(isinstance(packet,dict) and packet.get('version')==VERSION,'unsupported lexical support packet')
    evidence=packet.get('evidence');targets=packet.get('targets');require(isinstance(evidence,list) and isinstance(targets,list),'support arrays missing')
    by={};checked={}
    for e in evidence:
        require(isinstance(e,dict) and isinstance(e.get('id'),str) and e['id'] and e['id'] not in by,'invalid/duplicate evidence ID')
        require(e.get('kind') in KINDS and e.get('work') and e.get('locus') and isinstance(e.get('limitations'),list),'evidence source/kind missing')
        path=e.get('witness_path');require(isinstance(path,str) and bool(path),'evidence witness missing')
        if path not in checked:checked[path]=Path(path).read_bytes()
        raw=checked[path];require(hashlib.sha256(raw).hexdigest()==e.get('witness_sha256'),'evidence witness changed')
        if e['kind']=='english_definition':
            offset=e['synset_offset'];end=raw.find(b'\n',offset)
            require(type(offset)is int and offset>=0 and end>=offset,'invalid English witness offset')
            record=raw[offset:end+1].decode('ascii')
            require(record==e['raw'],'English raw witness differs')
            words,gloss=parse_wordnet_row(record,offset,e['pos'])
            require(gloss==e['gloss'] and words==e['lemmas'] and e['language']=='en','English definition differs from witness')
            require(e['id']==f"wordnet:{e['edition']}:{e['pos']}:{offset:08d}",'English citation ID differs')
        else:
            quotation=e.get('quotation');require(isinstance(quotation,str) and quotation,'source quotation missing')
            require(hashlib.sha256(quotation.encode()).hexdigest()==e.get('quotation_sha256'),'source quotation identity changed')
            text=raw.decode();span=e.get('witness_span')
            require(text[span[0]:span[1]]==quotation if span else text.count(quotation)==1,'source quotation differs from witness')
        by[e['id']]=e
    english={eid:{**e, 'grammar':wordnet_grammar(e)} for eid,e in by.items() if e['kind']=='english_definition'}
    receipt=packet.get('english_lookup');expected={}
    if english or receipt is not None:
        require(isinstance(receipt,dict),'English lookup identity missing')
        directory=Path(receipt['directory'])
        require(wordnet_receipt(directory,receipt['edition'],receipt['lemmas'])==receipt,'English lookup witness/coverage identity changed')
        expected={e['id']:e for e in lookup_wordnet(directory,receipt['lemmas'],edition=receipt['edition'])}
        require(english==expected,'English lookup population/definitions differ; complete alternatives required')
    source={line['id']:line for line in lines};seen=set()
    for target in targets:
        require(target.get('id') and target['id'] not in seen,'duplicate/missing support target');seen.add(target['id'])
        line=source.get(target.get('line_id'));require(line is not None,'unknown support line')
        code=lexical.line_language(line,languages);require(code and target.get('source_language')==code,'support source language mismatch')
        indices=target.get('word_indices');tokens=lexical.word_tokens(line)
        require(isinstance(indices,list) and indices and all(type(i)is int and 0<=i<len(tokens) for i in indices) and indices==sorted(set(indices)),'invalid support word indices')
        require(target.get('surfaces')==[tokens[i] for i in indices],'support source surface changed')
        operative=target.get('source_evidence_ids',[]);background=target.get('background_evidence_ids',[]);links=target.get('language_link_evidence_ids',[])
        for eid in operative+background+links:require(eid in by,'unknown support evidence ID')
        for eid in links:
            e=by[eid];require(e['kind']=='language_relationship' and e.get('target_language')==code and e.get('target_form') in target['surfaces'],'unbound language relationship')
        for eid in operative:
            e=by[eid]
            if e['language']!=code:
                require(any(by[k].get('source_language')==e['language'] and by[k].get('source_lemma')==e.get('lemma') for k in links),'cross-language evidence requires relationship or background role')
        candidates=target.get('english_candidates');require(isinstance(candidates,list) and candidates,'English candidates missing');ids=set()
        for c in candidates:
            require(c.get('id') and c['id'] not in ids and c.get('expression'),'duplicate/empty English candidate');ids.add(c['id'])
            require(c.get('kind') in {'word','compositional_phrase','transparent_compound'},'invalid English candidate kind')
            refs=c.get('english_evidence_ids');require(isinstance(refs,list) and len(refs)==len(set(refs)),'English evidence IDs missing/duplicated')
            for ref in refs:require(ref in by and by[ref]['kind']=='english_definition','unknown/invalid English evidence ID')
            queries=english_queries(c.get('english_lemmas',[]))
            require(queries==c.get('english_lemmas',[]),'English lookup queries must be canonical')
            expected_refs={eid for eid,e in expected.items() if set(queries)&set(e['requested_lemmas'])}
            require(set(refs)==expected_refs,'English candidate lookup alternatives incomplete')
            if c['kind']=='word':require(refs and any(c['expression'].casefold() in [x.casefold() for x in by[r]['lemmas']] for r in refs),'English candidate not attested by supplied definition')

def project_support(packet,target_ids):
    if packet is None:return None
    targets=[copy.deepcopy(t) for t in packet['targets'] if t['line_id'] in target_ids]
    if not targets:return None
    ids=set()
    for t in targets:
        for key in ('source_evidence_ids','background_evidence_ids','language_link_evidence_ids'):ids.update(t.get(key,[]))
        for c in t['english_candidates']:ids.update(c['english_evidence_ids'])
    projected = {'version':VERSION,'targets':targets,'evidence':[copy.deepcopy(e) for e in packet['evidence'] if e['id'] in ids]}
    if packet.get('english_lookup'):
        projected['english_lookup']=copy.deepcopy(packet['english_lookup'])
        queries={q for t in targets for c in t['english_candidates'] for q in c.get('english_lemmas',[])}
        projected['english_lookup']['lemmas']=[q for q in packet['english_lookup']['lemmas'] if q in queries]
        for e in projected['evidence']:
            if e['kind']=='english_definition':e['requested_lemmas']=[q for q in e['requested_lemmas'] if q in queries]
    return projected

def expression_matches_segments(row, expression, indices):
    segments=row.get('segments',[]);text='';spans=[]
    for segment in segments:
        start=len(text);text+=segment['text'];spans.append((start,len(text),segment['word_indices']))
    if text!=row.get('literal_english'):return False
    for match in re.finditer(r'(?<!\w)'+re.escape(expression)+r'(?!\w)',text,re.IGNORECASE):
        mapped={i for start,end,word_indices in spans if start<match.end() and end>match.start() for i in word_indices}
        if mapped==set(indices):return True
    return False

def support_decision_errors(packet,gloss_rows,translation_rows=None):
    if not packet:return []
    errors=[];targets={t['id']:t for t in packet['targets']}
    evidence={e['id']:e for e in packet['evidence']}
    for rows,key in [(gloss_rows,'support_decisions')]+([(translation_rows,'wording_decisions')] if translation_rows is not None else []):
        seen=set()
        for row in rows:
            decisions=row.get(key,[])
            if not isinstance(decisions,list):errors.append(key+' must be an array');continue
            for d in decisions:
                try:
                    tid=d['target_id'];require(tid in targets and tid not in seen,'unknown/duplicate target decision');seen.add(tid);t=targets[tid]
                    require(row['id']==t['line_id'] and isinstance(d.get('reason'),str) and d['reason'].strip(),'decision line/reason missing')
                    if key=='support_decisions':
                        allowed=set(t.get('source_evidence_ids',[])+t.get('background_evidence_ids',[])+t.get('language_link_evidence_ids',[]));used=d['used_evidence_ids']
                        require(isinstance(used,list) and set(used)<=allowed,'unknown source evidence reference')
                        require(d['role'] in {'operative_meaning','activated_image','background_only'},'invalid source support role')
                        if d['role']!='background_only':require(not set(used)&set(t.get('background_evidence_ids',[])),'background evidence used as operative meaning')
                    else:
                        require(d['word_indices']==t['word_indices'],'wording decision source indices differ')
                        cs={c['id']:c for c in t['english_candidates']};cid=d.get('chosen_candidate_id');kind=d.get('kind')
                        refs=d.get('english_evidence_ids');allowed={r for c in cs.values() for r in c['english_evidence_ids']}
                        require(isinstance(refs,list) and set(refs)<=allowed,'unknown English evidence reference')
                        require(isinstance(d.get('expression'),str) and d['expression'],'missing English expression')
                        require(expression_matches_segments(row,d['expression'],t['word_indices']),'chosen expression/source indices differ from English segments')
                        if cid is not None:
                            require(cid in cs and d['expression']==cs[cid]['expression'] and kind==cs[cid]['kind'],'chosen candidate differs from evidence')
                            require(set(refs)<=set(cs[cid]['english_evidence_ids']),'English sense belongs to different candidate')
                        if kind=='word':
                            require(cid is not None and refs,'word decision needs supplied dictionary sense')
                            require(any(normalize_english_lemma(d['expression']) in
                                        [normalize_english_lemma(lemma) for lemma in evidence[ref]['lemmas']]
                                        for ref in refs),'selected English definition does not attest chosen word')
                        elif kind in {'compositional_phrase','transparent_compound'}:
                            require(isinstance(d.get('ordinary_paraphrase'),str) and d['ordinary_paraphrase'].strip(),'composition needs plain paraphrase')
                            parts=d.get('component_word_indices');require(isinstance(parts,list) and parts and all(isinstance(p,list) and p and all(type(i)is int and i in t['word_indices'] for i in p) for p in parts),'composition members lack source support')
                        else:raise ValueError('invalid wording kind')
                except (ValueError,KeyError,TypeError) as exc:errors.append(key+': '+str(exc))
        missing=set(targets)-seen
        if missing:errors.append(key+' missing targets: '+','.join(sorted(missing)))
    return errors

def prepare_options(options, lines, languages):
    packet=getattr(options,'semantic_lexical_support',None)
    path=getattr(options,'lexical_support',None)
    if path:
        loaded=read_json(path)
        if packet is not None:require(packet==loaded,'lexical support file/options differ')
        packet=loaded
    if packet is not None:
        full=getattr(options,'semantic_full_source',lines)
        validate_support(packet,full,languages);options.semantic_lexical_support=packet
    return project_support(packet,[line['id'] for line in lines])

def prompt(packet, target_ids, stage):
    projected=project_support(packet,target_ids)
    if projected is None:return ''
    # Private file paths are transport metadata, not model reasoning evidence.
    projected.pop('english_lookup',None)
    for e in projected['evidence']:
        if e.get('kind') == 'english_definition':
            e['grammar'] = wordnet_grammar(e)
        for field in ('raw', 'witness_path', 'witness_sha256', 'witness_span', 'quotation_sha256'):
            e.pop(field, None)
    for target in projected['targets']:
        discovery = target.get('english_discovery')
        if discovery is not None:
            discovery.get('pool', {}).pop('records', None)
            coverage = discovery.get('query_coverage')
            if coverage is not None:
                coverage['part_count'] = len(coverage.pop('parts', []))
                coverage['ranking_role'] = 'Exploration only; compare the complete source and English definitions independently.'
            for candidate in discovery.get('candidates', []):
                for score in candidate.get('scores', []):
                    score.pop('part_scores', None)
                    score.pop('group_scores', None)
    instruction=('Return support_decisions only for targeted lines: target_id, used_evidence_ids, role (operative_meaning, activated_image, background_only), reason. Background evidence cannot establish an inherited-language sense.' if stage=='gloss' else
        'Return wording_decisions only for targeted lines: target_id, chosen_candidate_id (null for a new composition), expression, kind (word, compositional_phrase, transparent_compound), english_evidence_ids, reason, word_indices, ordinary_paraphrase, component_word_indices. Prefer precise intelligible English. Compare word, phrase and transparent compound by meaning, image, connotation and tone, not a mandatory phrase-failure rule. A dictionary sense is not proof of its fit here.' if stage=='translation' else
        'Independently check source and wording decisions against these exact witnesses, passage grammar and English. Reject unsupported inherited meanings, unwanted connotations, opaque compounds and gloss/English disagreement. Writer decisions are claims, not authority. Preserve owner English; report alternatives privately.')
    return '\nTARGETED LEXICAL SUPPORT:\n'+json.dumps(projected,ensure_ascii=False,separators=(',',':'))+'\n'+instruction+'\n'

def extend_schema(schema,packet,stage):
    if not packet:return schema
    schema=copy.deepcopy(schema);rows='glosses' if stage=='gloss' else 'translations';field='support_decisions' if stage=='gloss' else 'wording_decisions'
    string={'type':'string'};ints={'type':'array','items':{'type':'integer'}};strings={'type':'array','items':string}
    fields={'target_id':string,'reason':string}
    if stage=='gloss':fields.update(used_evidence_ids=strings,role={'type':'string','enum':['operative_meaning','activated_image','background_only']})
    else:fields.update(chosen_candidate_id={'type':['string','null']},expression=string,kind={'type':'string','enum':['word','compositional_phrase','transparent_compound']},english_evidence_ids=strings,word_indices=ints,ordinary_paraphrase=string,component_word_indices={'type':'array','items':ints})
    schema['properties'][rows]['items']['properties'][field]={'type':'array','items':{'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}}
    return schema

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['build']);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--lines',type=Path,required=True);p.add_argument('--languages',nargs='+',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args(argv)
    packet=build_support(a.manifest,read_json(a.lines),a.languages);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(packet,ensure_ascii=False,indent=2)+'\n');a.output.chmod(0o600)
    return 0
if __name__=='__main__':raise SystemExit(main())
