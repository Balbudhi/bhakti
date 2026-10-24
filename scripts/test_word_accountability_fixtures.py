"""Wire fields for existing transport fixtures; not a linguistic judgment oracle."""
import copy
import functools
import json
import bhakti_pipeline as pipeline
import bhakti_word_accountability as accounting


def records(source, draft, *, review=None):
    units=accounting.english_units(draft['literal_english'])
    links=accounting._segment_links(draft,units,pipeline.segment_english)
    result=[]
    for unit in units:
        indices=sorted(links.get(unit['unit'],set())) or [0]
        record={'unit':unit['unit'],'bases':['lexical'] if links.get(unit['unit']) else ['grammar'],
                'references':[{'line_id':source['id'],'domain':'word_glosses',
                    'word_indices':indices,'source_quote':source['source_text']}],
                'reason':'Existing synthetic transport fixture: this indexed source contribution is accounted for.'}
        if review is not None:
            record['status']='supported'
            for issue in review.get('issues',[]):
                if (issue['kind'] in {'english_realization','english_mapping','unresolved_evidence'}
                        and source['id'] in issue['target_line_ids']
                        and review.get('component_judgments',{}).get('english',{}).get('status') in {'defect','unresolved'}):
                    record['status']='unresolved' if issue['kind']=='unresolved_evidence' else 'defect'
                    record['references']=copy.deepcopy(issue['references'])
                    record['reason']=issue['explanation']
                    break
        result.append(record)
    return result


def account_response(response,prompt,schema):
    def parsed(marker):return json.JSONDecoder().raw_decode(prompt.rsplit(marker,1)[1].lstrip())[0]
    if not isinstance(response,dict):return response
    if schema=='bhakti_translation_review':
        evidence={r['source']['id']:r for r in parsed('EVIDENCE:\n')}
        for row in response.get('packet',{}).get('reviews',[]):
            if row.get('id') in evidence and 'word_judgments' not in row:
                item=evidence[row['id']]
                row['word_judgments']=records(item['source'],item['draft'],review=row)
    elif schema in {'bhakti_literal_translation','bhakti_translation_batch'}:
        sources={r['id']:r for r in parsed('TARGET audited source lines (return these IDs only):\n')}
        for row in response.get('packet',{}).get('translations',[]):
            if row.get('id') in sources and 'word_support' not in row:
                row['word_support']=records(sources[row['id']],row)
    return response


def accounted_provider(function):
    @functools.wraps(function)
    def wrapped(self,model,key,prompt,**kwargs):
        return account_response(function(self,model,key,prompt,**kwargs),prompt,kwargs['schema_name'])
    return wrapped


from contextlib import contextmanager
from unittest.mock import patch

@contextmanager
def previous_word_contract():
    """Construct a v3 acceptance through real storage/routes, without new tables.

    Only the new bookkeeping is disabled (including the historical binding tests’
    hypothetical next reviewer revision); these are not current task4 coverage. no accepted state, fingerprint, proof,
    baseline or source/gloss check is mocked. Original-source compatibility was
    separately checked with the unchanged pre-change callers before this fixture.
    """
    with patch.object(pipeline, 'REVIEW_TASK_VERSION', 3), \
         patch.object(accounting, 'identity', return_value={}), \
         patch.object(accounting, 'writer_errors', return_value=[]), \
         patch.object(accounting, 'record_errors', return_value=[]):
        yield
