"""Isolated source-stage candidates; preserve reviewed text and never publish."""
from __future__ import annotations
import copy,hashlib,json,math,subprocess,time,unicodedata
from pathlib import Path
from typing import Any

VERSION=1

def _source_lexical_key(line):
    """Lexical equality for adoption; do not fold meaningful vowel marks."""
    return (unicodedata.normalize('NFC', line['source_text']),
            canonical_iast(line['roman']), line.get('kind', 'verse'))


def _source_key(line):
    import bhakti_lexical_retrieval as lexical
    return (*_source_lexical_key(line), lexical.language(line.get('sourceLanguage') or line.get('language')))


def _certain_occurrence_matches(old, new):
    """Pairs present in every longest exact, order-preserving match.

    Every maximum alignment contains one pair at each match rank. A rank with
    only one possible pair therefore identifies a retained performance. Other
    ranks deliberately supply no timestamp lineage. O(n*m) time and storage;
    there is no exponential enumeration of repeated-refrain alternatives.
    """
    n, m = len(old), len(new)
    prefix = [[0] * (m + 1) for _ in range(n + 1)]
    suffix = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n):
        for j in range(m):
            prefix[i + 1][j + 1] = (prefix[i][j] + 1 if old[i] == new[j]
                                     else max(prefix[i][j + 1], prefix[i + 1][j]))
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            suffix[i][j] = (suffix[i + 1][j + 1] + 1 if old[i] == new[j]
                            else max(suffix[i + 1][j], suffix[i][j + 1]))
    ranks = {}; possible_old = set()
    for i in range(n):
        for j in range(m):
            if old[i] == new[j] and prefix[i][j] + 1 + suffix[i + 1][j + 1] == prefix[n][m]:
                ranks.setdefault(prefix[i][j] + 1, []).append((i, j))
                possible_old.add(i)
    certain = sorted(values[0] for values in ranks.values() if len(values) == 1)
    return certain, sorted(possible_old - {i for i, _ in certain})


def reconcile_source_observations(reader, plan, observed):
    """Propose source/order differences from bound observations, without effects.

    The caller must first verify the durable observation receipt/router history.
    This checks its supplied identity/digests again; it does not turn a model
    observation into publication approval. Changed source requires subsequent
    independent audio confirmation, and timing is always a separate obligation.
    """
    import bhakti_lexical_retrieval as lexical
    def hold(detail):
        return {'status': 'unresolved', 'issues': [{'kind': 'source_reconciliation', 'detail': detail}]}
    identity = plan.get('identity')
    if (not isinstance(identity, dict) or identity != observed.get('source_identity')
            or identity.get('reader_source_sha256') != reader_source_identity(reader)):
        raise ValueError('source observation identity differs from current recording/source')
    if observed.get('status') != 'observed' or observed.get('issues'):
        return hold('Not every requested audio unit has a usable observation')
    original = source_draft(reader)
    definitions = {line['id']: line for line in original['lines']}
    old_languages = {}
    song_languages = reader.get('SONG_META', {}).get('languages', [])
    for lid, line in definitions.items():
        current = reader['SONG_LINES'][lid]
        code = lexical.line_language(current, song_languages)
        if 'sourceLanguage' in current:
            line['sourceLanguage'] = copy.deepcopy(current['sourceLanguage'])
        elif code:
            line['sourceLanguage'] = code
        if code:
            old_languages.setdefault(_source_lexical_key(line), set()).add(code)
    old_events = original['performance_order']
    old_rows = [definitions[event['line_id']] for event in old_events]
    old_keys = [_source_key(row) for row in old_rows]
    results = observed.get('unit_results')
    if not isinstance(results, list) or not results:
        return hold('No source observations')
    prepared = []; unit_ids = set(); covered_targets = []
    for item in results:
        unit, raw = item.get('unit'), item.get('result')
        if not isinstance(unit, dict) or not isinstance(raw, dict) or item.get('result_digest') != digest(raw):
            raise ValueError('source observation content digest changed')
        if unit.get('id') in unit_ids:
            raise ValueError('duplicate source observation unit')
        unit_ids.add(unit.get('id'))
        errors = _observation_errors(unit, raw)
        if errors:
            return hold('; '.join(error['detail'] for error in errors))
        segment = raw['segment_audits'][0]['segment']
        if (segment.get('index') != unit.get('segment_index')
                or any(segment.get(k) != unit.get(k) for k in ('clip_start', 'clip_end', 'core_start', 'core_end'))):
            raise ValueError('observed segment differs from requested audio bounds')
        if (any(type(unit.get(k)) not in (int, float) or not math.isfinite(unit[k])
                for k in ('clip_start', 'clip_end', 'core_start', 'core_end'))
                or not 0 <= unit['clip_start'] <= unit['core_start'] < unit['core_end'] <= unit['clip_end']):
            raise ValueError('invalid observed core/clip bounds')
        context = unit.get('context_occurrence_indices', [])
        if unit.get('expanded_draft') != source_draft(reader, context):
            raise ValueError('observation draft differs from exact current context')
        targets = unit.get('target_occurrence_ids', [])
        expected_targets = [f'occ-{i:03d}' for i in unit.get('core_occurrence_indices', [])]
        if targets != expected_targets:
            raise ValueError('observation target lineage differs from requested core')
        covered_targets.extend(targets)
        packet = raw['segment_audits'][0]['audit']['packet']
        by_id = {row['id']: row for row in packet['lines']}
        rows = [copy.deepcopy(by_id[event['line_id']]) for event in packet['performance_order']]
        for row in rows:
            heard = row.get('language', '')
            if not isinstance(heard, str) or heard.strip() and not lexical.language(heard):
                return hold('Observed source language is malformed or unidentified')
            code = lexical.language(heard)
            previous = old_languages.get(_source_lexical_key(row), set())
            if code and previous and code not in previous:
                return hold('Observed language conflicts with the existing explicit source language')
            if not code:
                code = next(iter(previous)) if len(previous) == 1 else lexical.line_language({}, song_languages)
            if not code:
                return hold('Observed source in a mixed-language performance lacks an identified language')
            row['sourceLanguage'] = code
        prepared.append((unit, rows))
    expected_targets = {target for unit in plan.get('units', []) for target in unit['target_occurrence_ids']}
    if set(covered_targets) != expected_targets or len(covered_targets) != len(set(covered_targets)):
        return hold('Observed units lost or duplicated requested source cores')
    prepared.sort(key=lambda value: (value[0]['core_start'], value[0]['core_end']))
    whole = plan.get('mode') == 'whole_recording'
    source_unit_coverage = []
    observation_by_unit = {item['unit']['id']:item['result_digest'] for item in results}
    def unit_coverage(unit, context_indices, owned_indices):
        return {**{key:copy.deepcopy(unit[key]) for key in ('id','core_start','core_end','clip_start','clip_end')},
                'observation_digest':observation_by_unit[unit['id']],
                'expanded_context_indices':list(context_indices),'expanded_indices':list(owned_indices)}
    if whole:
        requested = plan.get('units', [])
        if len(requested) != 1:
            return hold('Whole-recording plan does not have one complete parent scope')
        start, end = requested[0]['clip_start'], requested[0]['clip_end']
        if (start != 0 or abs(prepared[0][0]['core_start'] - start) > .0005
                or abs(prepared[-1][0]['core_end'] - end) > .0005
                or any(abs(left[0]['core_end'] - right[0]['core_start']) > .0005
                       for left, right in zip(prepared, prepared[1:]))):
            return hold('Whole-recording cores have a gap, overlap, or missing edge')
        rows = []
        for index, (unit, current) in enumerate(prepared):
            original_count = len(current); overlap = 0
            if index and prepared[index - 1][0]['clip_end'] > unit['clip_start']:
                left = prepared[index - 1][1]
                seams = [length for length in range(1, min(len(left), len(current)) + 1)
                         if [_source_key(r) for r in left[-length:]] == [_source_key(r) for r in current[:length]]]
                if len(seams) != 1:
                    return hold('Overlapping source observations conflict or have ambiguous repeated context')
                overlap = seams[0]
                current = current[overlap:]
            source_unit_coverage.append(unit_coverage(unit,
                range(len(rows)-overlap,len(rows)-overlap+original_count),
                range(len(rows),len(rows)+len(current))))
            rows.extend(current)
        if any(row.get('partial') != 'none' for row in rows):
            return hold('Whole source retains an unresolved clipped fragment')
    else:
        # Focused units contain unchanged context as anchors. Preserve all
        # outside-target performances, including unselected interior neighbors.
        replacements = []
        for unit, current in prepared:
            context_ids = {f'occ-{i:03d}' for i in unit['context_occurrence_indices']}
            indices = [i for i, event in enumerate(old_events) if event['display_occurrence_id'] in context_ids]
            if not indices or indices != list(range(indices[0], indices[-1] + 1)):
                return hold('Focused context is not one contiguous source span')
            local_old = [old_keys[i] for i in indices]
            pairs, _ = _certain_occurrence_matches(local_old, [_source_key(row) for row in current])
            by_old = dict(pairs)
            targets = set(unit['target_occurrence_ids'])
            core_positions = [i for i, absolute in enumerate(indices)
                              if old_events[absolute]['display_occurrence_id'] in targets]
            if not core_positions:
                return hold('Focused observation has no core occurrence')
            prefix_count = core_positions[0]
            suffix_count = len(indices) - core_positions[-1] - 1
            current_keys = [_source_key(row) for row in current]
            if (current_keys[:prefix_count] != local_old[:prefix_count]
                    or suffix_count and current_keys[-suffix_count:] != local_old[-suffix_count:]):
                return hold('Focused observation inserts or changes source beyond its context anchors')
            for local, absolute in enumerate(indices):
                if old_events[absolute]['display_occurrence_id'] not in targets and local not in by_old:
                    return hold('Focused observation changes or ambiguously identifies outside-core context')
            for local, absolute in enumerate(indices):
                if local in by_old and old_events[absolute]['display_occurrence_id'] not in targets:
                    # Retain exact complete context; an allowable partial edge
                    # is only routing evidence, never a replacement definition.
                    current[by_old[local]] = {**copy.deepcopy(old_rows[absolute]), 'partial': 'none'}
            if any(row.get('partial') != 'none' for row in current):
                return hold('Focused observation retains unresolved partial core source')
            replacements.append((indices[0], indices[-1] + 1, current, unit))
        if any(left[1] > right[0] for left, right in zip(replacements, replacements[1:])):
            return hold('Focused replacement contexts overlap; combine and review their source together')
        rows = []; cursor = 0
        for start, end, replacement, unit in replacements:
            rows.extend(copy.deepcopy(old_rows[cursor:start]))
            span = range(len(rows),len(rows)+len(replacement))
            source_unit_coverage.append(unit_coverage(unit,span,span))
            rows.extend(replacement); cursor = end
        rows.extend(copy.deepcopy(old_rows[cursor:]))
    if not rows:
        return hold('Audio observation would remove the entire performance')
    new_keys = [_source_key(row) for row in rows]
    certain, ambiguous_old = _certain_occurrence_matches(old_keys, new_keys)
    old_for_new = {j: i for i, j in certain}
    definition_ids = {}
    for lid, line in definitions.items():
        definition_ids.setdefault(_source_key(line), []).append(lid)
    canonical = {}; fresh = []; reused = []; order = []; counts = {}
    fresh_by_key = {}
    for j, row in enumerate(rows):
        key = new_keys[j]
        if j in old_for_new:
            lid = old_events[old_for_new[j]]['line_id']
        elif len(definition_ids.get(key, [])) == 1:
            lid = definition_ids[key][0]
        elif len(definition_ids.get(key, [])) > 1:
            return hold('Identical source definitions have distinct editorial identity and ambiguous occurrence context')
        else:
            if key not in fresh_by_key:
                candidate = 'source-new-' + digest(key)[:16]
                if candidate in reader['SONG_LINES']:
                    raise ValueError('fresh source ID collides with current definition')
                fresh_by_key[key] = candidate
            lid = fresh_by_key[key]
        if lid not in canonical:
            if lid in definitions:
                canonical[lid] = copy.deepcopy(definitions[lid]); reused.append(lid)
            else:
                heard_language = row.get('language', '')
                if not isinstance(heard_language, str):
                    return hold('Fresh source language is malformed')
                language_code = row['sourceLanguage']
                if heard_language.strip() and not language_code:
                    return hold('Fresh source language is not a supported identified language')
                if not language_code:
                    language_code = lexical.line_language({}, reader.get('SONG_META', {}).get('languages', []))
                if not language_code:
                    return hold('Fresh source in a mixed-language performance lacks an identified language')
                canonical[lid] = {'id': lid, 'source_text': row['source_text'], 'roman': row['roman'],
                                  'kind': row['kind'], 'language': heard_language,
                                  'sourceLanguage': language_code, 'translation_notes': row.get('notes', '')}
                fresh.append(lid)
        counts[lid] = counts.get(lid, 0) + 1
        order.append({'line_id': lid, 'occurrence': counts[lid], 'notes': ''})
    lineage = []; old_cursor = new_cursor = 0
    for i, j in certain + [(len(old_rows), len(rows))]:
        lineage.extend({'old_index': k, 'new_index': None} for k in range(old_cursor, i))
        lineage.extend({'old_index': None, 'new_index': k} for k in range(new_cursor, j))
        if i < len(old_rows):
            lineage.append({'old_index': i, 'new_index': j})
        old_cursor, new_cursor = i + 1, j + 1
    return {'status': 'proposed', 'issues': [], 'before_identity': copy.deepcopy(identity),
            'rebuilt': {'metadata': {'languages': copy.deepcopy(reader.get('SONG_META', {}).get('languages', []))},
                        'verified_lines': list(canonical.values()), 'performance_order': order,
                        'changes': [], 'uncertainties': []},
            'reused_line_ids': reused, 'fresh_line_ids': fresh,
            'removed_line_ids': [lid for lid in definitions if lid not in canonical],
            'requires_confirmation': old_keys != new_keys,
            'coverage_scope': 'whole_recording' if whole else 'focused',
            'occurrence_lineage': lineage, 'timing_unresolved_old_indices': ambiguous_old,
            'source_unit_coverage': source_unit_coverage,
            'observation_digests': [item['result_digest'] for item in results]}

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temporary.replace(path)

def canonical_iast(value):
    # Unicode equivalence only. Reviewed lexical/roman aliases need an explicit map.
    return unicodedata.normalize('NFC',value).strip()

def plan_source(reader,rebuilt,*,reviewed_map=None,accepted_delta=None):
    if rebuilt.get('uncertainties'):raise ValueError('rebuilt source has unresolved uncertainty')
    old=reader.get('SONG_LINES',{});raw=copy.deepcopy(rebuilt.get('verified_lines',[]));order=rebuilt.get('performance_order',[])
    bootstrap = bool(accepted_delta and accepted_delta.get('bootstrap_source') is True and source_reader_is_empty(reader))
    if not isinstance(old,dict) or (not old and not bootstrap) or not isinstance(raw,list) or not raw or not isinstance(order,list) or not order:raise ValueError('incomplete source population')
    raw_by={}
    for line in raw:
        lid=line.get('id')
        if not isinstance(lid,str) or not lid or lid in raw_by:raise ValueError('duplicate/invalid audited line ID')
        if any(not isinstance(line.get(k),str) or not line[k].strip() for k in ('source_text','roman')):raise ValueError('audited line lacks source/roman')
        raw_by[lid]=line
    if any(not isinstance(r,dict) or r.get('line_id') not in raw_by for r in order):raise ValueError('unknown source occurrence reference')
    if {r['line_id'] for r in order}!=set(raw_by):raise ValueError('unperformed audited source rows')
    if accepted_delta is not None:
        if reviewed_map is not None or accepted_delta.get('rebuilt') != rebuilt:
            raise ValueError('accepted source delta differs from normalized source')
        reused = accepted_delta.get('reused_line_ids', [])
        fresh = accepted_delta.get('fresh_line_ids', [])
        removed = accepted_delta.get('removed_line_ids', [])
        if (len(reused) != len(set(reused)) or len(fresh) != len(set(fresh))
                or set(reused) & set(fresh) or set(reused) | set(fresh) != set(raw_by)
                or set(reused) | set(removed) != set(old) or set(reused) & set(removed)
                or set(fresh) & set(old)):
            raise ValueError('accepted source delta populations are inconsistent')
        reuse = {}
        for lid in reused:
            row = raw_by[lid]
            if (row['source_text'] != old[lid]['source'] or row['roman'] != old[lid]['roman']):
                raise ValueError('accepted reuse changes existing source identity')
            reuse[lid] = copy.deepcopy(old[lid])
            for field in ('sourceWords', 'sourceLanguage'):
                if field in old[lid]: row[field] = copy.deepcopy(old[lid][field])
        return {'lines':copy.deepcopy(raw), 'performance_order':copy.deepcopy(order),
                'raw_to_final':{lid:lid for lid in raw_by}, 'new_target_ids':list(fresh),
                'removed_line_ids':list(removed), 'reuse_by_id':reuse,
                'rebuilt_source_digest':digest(rebuilt), 'adopted_delta':copy.deepcopy(accepted_delta)}
    mapping={}
    if reviewed_map is not None:
        for item in reviewed_map.get('mapping',[]):
            rid=item.get('new_line_id')
            if rid not in raw_by or rid in mapping:raise ValueError('duplicate/unknown reviewed raw ID')
            if item.get('audited_source')!=raw_by[rid]['source_text'] or item.get('audited_roman')!=raw_by[rid]['roman']:raise ValueError('stale reviewed source/roman')
            previous=item.get('old_line_id')
            if previous is not None:
                if previous not in old or item.get('baseline_line')!=old[previous] or item.get('preserve_english')!=old[previous].get('english'):raise ValueError('stale reviewed public baseline')
            mapping[rid]=previous
        if set(mapping)!=set(raw_by):raise ValueError('reviewed map does not cover complete source')
        targets={x.get('new_line_id') for x in reviewed_map.get('new_gloss_targets',[])}
        if targets!={rid for rid,prior in mapping.items() if prior is None}:raise ValueError('reviewed fresh-target population mismatch')
    else:
        identities={}
        for lid,line in old.items():
            identity=(line.get('source'),canonical_iast(line.get('roman','')))
            identities.setdefault(identity,[]).append(lid)
        for line in raw:
            matches=identities.get((line['source_text'],canonical_iast(line['roman'])),[])
            if len(matches)>1:raise ValueError('ambiguous source identity needs reviewed mapping')
            mapping[line['id']]=matches[0] if matches else None
    used={lid for lid in mapping.values() if lid is not None}
    if used!=set(old):raise ValueError('old reviewed source would be dropped or changed without explicit mapping')
    lines=[];seen=set();raw_to_final={};new_targets=[];reuse={}
    for raw_line in raw:
        rid=raw_line['id'];prior=mapping[rid]
        if prior is not None:
            final=prior;line={**copy.deepcopy(raw_line),'id':final,'source_text':old[prior]['source'],'roman':old[prior]['roman']}
            for field in ('sourceWords','sourceLanguage'):
                if field in old[prior]:line[field]=copy.deepcopy(old[prior][field])
            reuse[final]=copy.deepcopy(old[prior])
        else:
            final='source-new-'+rid
            if final in old or final in seen:raise ValueError('new source ID collides with old reader')
            line={**copy.deepcopy(raw_line),'id':final};new_targets.append(final)
        raw_to_final[rid]=final
        if final not in seen:lines.append(line);seen.add(final)
    counts={};new_order=[]
    for event in order:
        lid=raw_to_final[event['line_id']];counts[lid]=counts.get(lid,0)+1
        new_order.append({**copy.deepcopy(event),'line_id':lid,'occurrence':counts[lid]})
    return {'lines':lines,'performance_order':new_order,'raw_to_final':raw_to_final,
            'new_target_ids':new_targets,'reuse_by_id':reuse,'rebuilt_source_digest':digest(rebuilt)}

def remap_sequence_metadata(reader, plan, new_sequence):
    """Keep positional credits/markers with their evidenced performances.

    Lineage indexes expanded performances, while public metadata indexes display
    blocks. A heading owns its original span until the next heading. Only its
    position may move; lost or ambiguous attribution is an explicit hold.
    """
    meta = copy.deepcopy(reader['SONG_META'])
    notices = meta.get('sectionNotices', [])
    adapted = meta.get('adaptedSequenceIndices', [])
    if not isinstance(notices, list) or not isinstance(adapted, list):
        raise ValueError('sequence metadata must contain lists')
    if not notices and not adapted:
        return meta

    def expand(sequence):
        refs, displays, starts = [], [], []
        for index, row in enumerate(sequence):
            repeats = row.get('repeats', 1)
            if (type(repeats) is not int or repeats < 1
                    or not isinstance(row.get('ref'), str) or not row['ref']):
                raise ValueError('sequence metadata has an invalid performance block')
            starts.append(len(refs))
            refs.extend([row['ref']] * repeats)
            displays.extend([index] * repeats)
        return refs, displays, starts

    old_refs, old_displays, old_starts = expand(reader['SONG_SEQUENCE'])
    new_refs, new_displays, new_starts = expand(new_sequence)
    notice_indices = []
    for notice in notices:
        if (not isinstance(notice, dict) or type(notice.get('sequenceIndex')) is not int
                or not 0 <= notice['sequenceIndex'] < len(old_starts)):
            raise ValueError('section notice has an invalid original sequence index')
        notice_indices.append(notice['sequenceIndex'])
    if len(set(notice_indices)) != len(notice_indices):
        raise ValueError('section notices share an ambiguous original index')
    if any(type(index) is not int or not 0 <= index < len(old_starts) for index in adapted):
        raise ValueError('adaptation marker has an invalid original sequence index')

    delta = plan.get('adopted_delta')
    if delta is None:
        if old_refs != new_refs:
            raise ValueError('changed source order needs occurrence lineage for positional metadata')
        lineage = [{'old_index': i, 'new_index': i} for i in range(len(old_refs))]
    else:
        lineage = delta.get('occurrence_lineage')
    if not isinstance(lineage, list):
        raise ValueError('positional metadata lacks complete occurrence lineage')
    old_seen, new_seen, old_to_new, new_to_old = set(), set(), {}, {}
    for row in lineage:
        if not isinstance(row, dict) or set(row) != {'old_index', 'new_index'}:
            raise ValueError('positional metadata has malformed occurrence lineage')
        old, new = row['old_index'], row['new_index']
        if old is None and new is None:
            raise ValueError('positional metadata lineage contains no occurrence')
        for index, size, seen in ((old, len(old_refs), old_seen), (new, len(new_refs), new_seen)):
            if index is not None:
                if type(index) is not int or not 0 <= index < size or index in seen:
                    raise ValueError('positional metadata has invalid or duplicate lineage')
                seen.add(index)
        if old is not None and new is not None:
            if old_refs[old] != new_refs[new]:
                raise ValueError('positional metadata lineage changes source identity')
            old_to_new[old] = new
            new_to_old[new] = old
    if old_seen != set(range(len(old_refs))) or new_seen != set(range(len(new_refs))):
        raise ValueError('positional metadata lineage does not cover the complete performance')
    mapped_order = [old_to_new[i] for i in sorted(old_to_new)]
    if mapped_order != sorted(mapped_order):
        raise ValueError('positional metadata lineage interleaves original sections')

    spans = []
    ordered = sorted(notice_indices)
    for position, index in enumerate(ordered):
        first = old_starts[index]
        end = old_starts[ordered[position + 1]] if position + 1 < len(ordered) else len(old_refs)
        retained = [old_to_new[i] for i in range(first, end) if i in old_to_new]
        if not retained:
            raise ValueError('section attribution span was fully removed; review its credit')
        low, high = min(retained), max(retained)
        if new_starts[new_displays[low]] != low:
            raise ValueError('merged display block crosses a section credit boundary')
        spans.append((index, low, high))
    for position, (_, low, high) in enumerate(spans):
        next_start = spans[position + 1][1] if position + 1 < len(spans) else len(new_refs)
        if high >= next_start:
            raise ValueError('section attribution spans overlap after source repair')
        if any(i not in new_to_old for i in range(high + 1, next_start)):
            raise ValueError('new source at a section boundary needs attribution review')
    positions = {index: new_displays[low] for index, low, _ in spans}
    if notices:
        meta['sectionNotices'] = [{**notice, 'sequenceIndex': positions[notice['sequenceIndex']]}
            for notice in notices]

    if adapted:
        marked = set(adapted)
        states = [set() for _ in new_sequence]
        for index, display in enumerate(new_displays):
            old = new_to_old.get(index)
            states[display].add(None if old is None else old_displays[old] in marked)
        if any(True in values and values != {True} for values in states):
            raise ValueError('merged display block has conflicting or unknown adaptation status')
        meta['adaptedSequenceIndices'] = [i for i, values in enumerate(states) if values == {True}]
    return meta


def assert_source_candidate(before,after,plan,timing):
    expected_meta = remap_sequence_metadata(before, plan, after.get('SONG_SEQUENCE', []))
    if expected_meta!=after.get('SONG_META'):raise ValueError('source stage changed metadata outside verified sequence positions')
    old=before['SONG_LINES'];new=after.get('SONG_LINES',{});expected={r['id']:r for r in plan['lines']}
    if set(new)!=set(expected):raise ValueError('candidate source population mismatch')
    preserved=plan.get('reuse_by_id',old) if 'adopted_delta' in plan else old
    for lid,line in preserved.items():
        if new.get(lid)!=line:raise ValueError('changed existing reviewed row '+lid)
    if 'adopted_delta' in plan and set(old)-set(preserved)!=set(plan['removed_line_ids']):
        raise ValueError('source candidate removed unexpected old definitions')
    for lid,line in expected.items():
        if new[lid].get('source')!=line['source_text'] or new[lid].get('roman')!=line['roman']:raise ValueError('candidate changed planned source/roman '+lid)
    expanded=[]
    for event in after.get('SONG_SEQUENCE',[]):
        repeats=event.get('repeats')
        if type(repeats) is not int or repeats<1 or event.get('ref') not in expected:raise ValueError('invalid candidate sequence')
        if event.get('section')!=expected[event['ref']].get('kind','verse'):raise ValueError('candidate section changed')
        expanded.extend([event['ref']]*repeats)
    if expanded!=[r['line_id'] for r in plan['performance_order']]:raise ValueError('candidate order/repeats differ from reviewed source')
    seq=timing.get('sequence',[])
    measured=[{'ref':e['ref'],'section':e.get('section','verse'),'repeats':e.get('repeats',1)} for e in seq]
    times=[{'start':round(e['start'],3),'end':round(e['end'],3)} for e in seq]
    if measured!=after['SONG_SEQUENCE'] or times!=after.get('SONG_TIMINGS'):raise ValueError('candidate differs from approved timing artifact')
    if len(times)!=len(measured) or any(not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in t.values()) for t in times):raise ValueError('invalid numeric timing')

def save_checkpoint(path,input_fingerprint,result):
    if result.get('status')!='accepted' or result.get('publicationEligible') is not True or result.get('issues'):raise ValueError('only accepted source stage may checkpoint')
    atomic_json(path,{'version':VERSION,'input_fingerprint':input_fingerprint,'result_digest':digest(result),'result':result})

def load_checkpoint(path,input_fingerprint):
    path=Path(path)
    if not path.exists():return None
    data=json.loads(path.read_text())
    if data.get('version')!=VERSION or data.get('input_fingerprint')!=input_fingerprint:return None
    result=data.get('result')
    if data.get('result_digest')!=digest(result):raise ValueError('accepted checkpoint result digest mismatch')
    if not isinstance(result,dict) or result.get('status')!='accepted' or result.get('publicationEligible') is not True or result.get('issues'):raise ValueError('checkpoint is not accepted source evidence')
    return result


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plan_source_timing(reader, delta, prior_timing, *, audio_sha256, trim, duration_seconds, model_audio_sha256=None, audio_transform=None):
    """Plan fresh timing only where exact source lineage lacks audio evidence.

    A retained value is a corroborated measurement of the same performed block,
    never an old display timestamp shifted by position. Caller validates the
    durable source receipt and prior timing artifact before supplying them.
    Unsupported historical report shapes simply contribute no measurements.
    """
    import bhakti_pipeline as pipeline
    before = delta.get('before_identity', {})
    if (delta.get('status') != 'proposed' or before.get('audio_sha256') != audio_sha256
            or before.get('reader_source_sha256') != reader_source_identity(reader)):
        raise ValueError('source timing delta no longer matches recording/source')
    if type(duration_seconds) not in (int, float) or not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError('source timing duration invalid')
    bootstrap = delta.get('bootstrap_source') is True and source_reader_is_empty(reader)
    if bootstrap and prior_timing:
        raise ValueError('empty source cannot reuse historical timing without performed source lineage')
    old_draft = {'lines': [], 'performance_order': []} if bootstrap else source_draft(reader)
    old = pipeline.display_occurrences({'verified_lines': old_draft['lines'],
                                       'performance_order': old_draft['performance_order']})
    new = pipeline.display_occurrences(delta['rebuilt'])
    measurements = {}; expanded_measurements = {}
    prior_context={'audio_sha256':audio_sha256,'trim':trim,'duration_seconds':duration_seconds}
    if audio_transform is not None and prior_timing:
        from bhakti_boundary_adoption import timing_transform_context
        prior_context=timing_transform_context(audio_transform,prior_timing.get('source_identity',{}),
            audio_sha256=audio_sha256,trim=trim,duration_seconds=duration_seconds)
    if prior_timing:
        identity = prior_timing.get('source_identity', {})
        fingerprint = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()
        if (identity.get('version') != 2 or identity.get('audio_sha256') != prior_context['audio_sha256']
                or identity.get('source_identity', {}).get('trim') != prior_context['trim']
                or prior_timing.get('input_fingerprint') != fingerprint
                or prior_timing.get('duration_seconds') != prior_context['duration_seconds']):
            raise ValueError('prior timing identity differs from current recording/trim/duration')
        bound = identity.get('ordered_occurrences', [])
        if len(bound) != len(old) or prior_timing.get('ordered_occurrences') != bound:
            raise ValueError('prior timing order differs from original source')
        for expected, actual in zip(old, bound):
            if any(actual.get(key) != value for key, value in expected.items()):
                raise ValueError('prior timing source differs from original performance')
        measurements = pipeline.retained_timing_measurements(bound,
            prior_timing.get('refinements', []), prior_context['duration_seconds'], require_consensus=True)
        expanded_measurements.update({f'{oid}-r01':point for oid,point in measurements.items()})
        for report in prior_timing.get('refinements', []):
            if report.get('kind') not in {'joint', 'joint-selection'}:
                continue
            if audio_transform is not None:
                raise ValueError('boundary timing canonical model clock origin is not qualified')
            if not isinstance(model_audio_sha256, str) or len(model_audio_sha256) != 64:
                raise ValueError('prior joint measurements need current canonical model audio binding')
            if report['kind'] == 'joint-selection':
                if report['audio_sha256'] != model_audio_sha256:
                    raise ValueError('prior joint selection canonical audio changed')
                errors = pipeline.joint_selection_errors(report, prior_timing)
                if errors:raise ValueError('; '.join(errors))
                measurements.update({row['occurrence_id']:row['start'] for row in prior_timing['sequence']})
                expanded_measurements.update({row['timing_id']:row['start'] for row in report['expanded_starts']})
                continue
            region = report['region']
            pipeline.validate_joint_region_source(region, bound, duration_seconds)
            fingerprint = pipeline.joint_region_fingerprint(model_audio_sha256, region, duration_seconds, identity)
            pairs = pipeline.joint_pair_evidence(report, expected_region=region,
                expected_fingerprint=fingerprint, duration=duration_seconds)
            agreed = {row['timing_id']:row for row in pairs['agreed']}
            expanded_measurements.update({tid:row['start'] for tid,row in agreed.items()})
            for occurrence in region['target_occurrences']:
                required = pipeline.expanded_timing_targets([occurrence])
                if all(row['timing_id'] in agreed for row in required):
                    measurements[occurrence['occurrence_id']] = agreed[required[0]['timing_id']]['start']
        if any(row.get('kind') == 'source-adoption' for row in prior_timing.get('refinements', [])):
            import bhakti_model_routes as routes
            try:
                expanded_measurements = pipeline.source_adoption_timing_measurements(prior_timing)
            except (KeyError, TypeError, OSError, routes.RunFatal) as exc:
                raise ValueError('prior source adoption timing evidence: ' + str(exc)) from exc
            measurements = {row['occurrence_id']:row['start'] for row in prior_timing['sequence']}

    if audio_transform is not None and prior_timing:
        interval=prior_context['interval'];offset=prior_context['offset']
        def mapped(values):
            return {key:point-offset for key,point in values.items()
                if interval['start']<=point-offset<min(interval['end'],duration_seconds)}
        measurements=mapped(measurements)
        expanded_measurements=mapped(expanded_measurements)

    # Reconciliation lineage describes expanded performances. A displayed
    # repeated block can retain its start only when every constituent maps
    # consecutively to the complete old block, including its first performance.
    lineage = {row['new_index']: row['old_index'] for row in delta['occurrence_lineage']
               if row['old_index'] is not None and row['new_index'] is not None}
    old_blocks = {}; offset = 0
    for occurrence in old:
        old_blocks[offset] = occurrence
        offset += occurrence['repeats']
    retained = {}; provenance = {}; offset = 0
    for occurrence in new:
        count = occurrence['repeats']; old_first = lineage.get(offset)
        original = old_blocks.get(old_first)
        if (original and count == original['repeats']
                and all(lineage.get(offset+i) == old_first+i for i in range(count))
                and all(occurrence[key] == original[key] for key in ('ref','source_text','roman','section'))
                and original['occurrence_id'] in measurements):
            oid = occurrence['occurrence_id']
            retained[oid] = measurements[original['occurrence_id']]
            provenance[oid] = {'old_occurrence_id': original['occurrence_id'],
                               'old_expanded_index': old_first, 'new_expanded_index': offset}
        offset += count
    previous = -1.
    for occurrence in new:
        point = retained.get(occurrence['occurrence_id'])
        if point is not None:
            if point <= previous:
                raise ValueError('retained performance measurements contradict source order')
            previous = point
    retained_expanded = {}
    for occurrence in new:
        oid = occurrence['occurrence_id']
        if oid not in retained:
            continue
        old_oid = provenance[oid]['old_occurrence_id']
        retained_expanded[f'{oid}-r01'] = retained[oid]
        for repeat in range(1, occurrence['repeats'] + 1):
            old_tid = f'{old_oid}-r{repeat:02d}'
            if old_tid in expanded_measurements:
                retained_expanded[f'{oid}-r{repeat:02d}'] = expanded_measurements[old_tid]
    # A display-only proof does not locate the last repeated performance.
    # Include just that adjacent block when a new following onset needs it.
    # Reverse order also handles adjacent repeated blocks needing one another.
    for index in range(len(new) - 1, 0, -1):
        if new[index]['occurrence_id'] in retained:
            continue
        neighbor = new[index - 1]; oid = neighbor['occurrence_id']
        last_tid = f"{oid}-r{neighbor['repeats']:02d}"
        if oid in retained and neighbor['repeats'] > 1 and last_tid not in retained_expanded:
            del retained[oid]; del provenance[oid]
            for target in pipeline.expanded_timing_targets([neighbor]):
                retained_expanded.pop(target['timing_id'], None)
    pending = [i for i,row in enumerate(new) if row['occurrence_id'] not in retained]
    groups = []
    for index in pending:
        if groups and index == groups[-1][-1]+1: groups[-1].append(index)
        else: groups.append([index])
    regions = []
    for group in groups:
        first,last = group[0],group[-1]
        preceding = copy.deepcopy(new[first-1]) if first else None
        following = copy.deepcopy(new[last+1]) if last+1 < len(new) else None
        left = retained[preceding['occurrence_id']] if preceding else None
        right = retained[following['occurrence_id']] if following else None
        regions.append({'index': len(regions), 'grid': 'joint-context',
            'clip_start': max(0., left-10.) if left is not None else 0.,
            'clip_end': min(duration_seconds, right+20.) if right is not None else duration_seconds,
            'target_indices': group, 'target_occurrences': copy.deepcopy(new[first:last+1]),
            'preceding_context': preceding, 'following_context': following,
            'preceding_timing_id': pipeline.expanded_timing_targets([preceding])[-1]['timing_id'] if preceding else None,
            'following_timing_id': pipeline.expanded_timing_targets([following])[0]['timing_id'] if following else None,
            'retained_anchor_starts': {row['occurrence_id']: retained[row['occurrence_id']]
                                       for row in (preceding,following) if row}})
    if duration_seconds > 900 and regions:
        coverage = delta.get('source_unit_coverage')
        if not isinstance(coverage, list) or not coverage:
            raise ValueError('long source timing needs accepted bounded source unit ownership')
        expanded = pipeline.expanded_timing_targets(new)
        owners = {}; unit_ids = set(); previous_core_end = None
        for unit in coverage:
            if unit.get('id') in unit_ids:
                raise ValueError('duplicate source unit ownership identity')
            unit_ids.add(unit.get('id'))
            if (unit.get('observation_digest') not in delta['observation_digests']
                    or any(type(unit.get(key)) not in (int,float) or not math.isfinite(unit[key])
                           for key in ('clip_start','clip_end','core_start','core_end'))
                    or not 0 <= unit['clip_start'] <= unit['core_start'] < unit['core_end'] <= unit['clip_end'] <= duration_seconds
                    or unit['clip_end']-unit['clip_start'] > 900):
                raise ValueError('invalid bounded source unit ownership evidence')
            if previous_core_end is not None and (unit['core_start'] < previous_core_end
                    or delta['coverage_scope'] == 'whole_recording' and abs(unit['core_start']-previous_core_end) > .0005):
                raise ValueError('source unit ownership core gap or overlap')
            previous_core_end = unit['core_end']
            context = unit.get('expanded_context_indices'); owned = unit.get('expanded_indices')
            if any(not isinstance(indices,list) or any(type(i) is not int or not 0 <= i < len(expanded) for i in indices)
                   or indices != sorted(set(indices)) for indices in (context,owned)):
                raise ValueError('invalid source unit expanded ownership indices')
            if not set(owned).issubset(context):
                raise ValueError('source unit ownership outside observed context')
            for index in owned:
                if index in owners:raise ValueError('duplicate source unit expanded ownership')
                owners[index] = unit['id']
        if delta['coverage_scope'] == 'whole_recording' and (
                set(owners) != set(range(len(expanded))) or coverage[0]['core_start'] != 0
                or abs(coverage[-1]['core_end']-duration_seconds) > .0005):
            raise ValueError('incomplete whole source unit ownership')
        needed = [i for i,row in enumerate(expanded) if row['occurrence_id'] not in retained]
        if not set(needed).issubset(owners):
            raise ValueError('missing source unit ownership for pending timing')
        positions = {row['occurrence_id']:i for i,row in enumerate(new)}
        regions = []
        for unit in coverage:
            indices = [i for i in needed if owners[i] == unit['id']]
            if not indices:continue
            display_indices = sorted({positions[expanded[i]['occurrence_id']] for i in indices})
            first,last = display_indices[0],display_indices[-1]
            preceding = copy.deepcopy(new[first-1]) if first else None
            following = copy.deepcopy(new[last+1]) if last+1<len(new) else None
            regions.append({'index':len(regions),'grid':'joint-context',
                'clip_start':unit['clip_start'],'clip_end':unit['clip_end'],
                'source_unit_id':unit['id'],'target_indices':display_indices,
                'target_occurrences':[copy.deepcopy(new[i]) for i in display_indices],
                'target_timing_ids':[expanded[i]['timing_id'] for i in indices],
                'preceding_context':preceding,'following_context':following,
                'preceding_timing_id':expanded[indices[0]-1]['timing_id'] if indices[0] else None,
                'following_timing_id':expanded[indices[-1]+1]['timing_id'] if indices[-1]+1<len(expanded) else None,
                'retained_anchor_starts':{row['occurrence_id']:retained[row['occurrence_id']]
                    for row in (preceding,following) if row and row['occurrence_id'] in retained}})
    return {'retained_starts': retained, 'retained_expanded_starts': retained_expanded,
            'regions': regions, 'ordered_occurrences': new,
            'retained_lineage': provenance, 'prior_timing_digest': digest(prior_timing),
            'source_delta_digest': digest(delta)}


def process_new_targets(song_dir, plan, metadata, options, route_dir, deadline_at):
    """Fresh text is a routed, independently reviewed subset, never old English."""
    import bhakti_pipeline as pipeline
    import bhakti_library_pass as library
    import bhakti_model_routes as routes
    targets = [line for line in plan['lines'] if line['id'] in plan['new_target_ids']]
    languages = metadata.get('languages', [])
    options = copy.copy(options)
    options.semantic_full_source = plan['lines']
    options = library.lexical_options(options, song_dir.name, plan['lines'], languages)
    reused = plan.get('reuse_by_id', {})
    planned = {line['id']: line for line in plan['lines']}
    if set(reused) != set(planned) - set(plan['new_target_ids']):
        raise ValueError('translation context lacks preserved source rows')
    for line_id, old in reused.items():
        if (old.get('source') != planned[line_id]['source_text']
                or old.get('roman') != planned[line_id]['roman']
                or not isinstance(old.get('english'), str)):
            raise ValueError('translation context differs from preserved source/English')
    context_evidence = []
    if reused:
        old_reader = {'SONG_META': metadata, 'SONG_LINES': copy.deepcopy(reused),
            'SONG_SEQUENCE': [{'ref': event['line_id'], 'section': planned[event['line_id']].get('kind', 'verse'),
                               'repeats': 1}
                              for event in plan['performance_order'] if event['line_id'] in reused]}
        old_sources, old_glosses, old_drafts = library.reader_evidence(old_reader)
        context_evidence = [{'source': copy.deepcopy(planned[source['id']]),
                             'gloss': gloss, 'draft': draft}
                            for source, gloss, draft in zip(old_sources, old_glosses, old_drafts)]
    # New English does not exist yet. These empty drafts check only known order,
    # row availability and scope bounds; they are discarded, never model evidence.
    pending_glosses = [{'id': line['id']} for line in targets]
    pending_drafts = [{'id': line['id'], 'literal_english': ''} for line in targets]
    for offset in range(0, len(targets), 10):
        pipeline.translation_reading_context(targets, pending_glosses, pending_drafts,
            [line['id'] for line in targets[offset:offset + 10]],
            performance_order=plan['performance_order'], full_evidence=context_evidence)
    options.semantic_context_evidence = copy.deepcopy(context_evidence)
    options.semantic_full_source = copy.deepcopy(plan["lines"])
    options.semantic_performance_order = plan['performance_order']
    options.semantic_source_identity = digest({'lines': plan['lines'], 'order': plan['performance_order']})
    audited = {'packet': {'metadata': metadata, 'verified_lines': targets,
                         'performance_order': [event for event in plan['performance_order'] if event['line_id'] in plan['new_target_ids']],
                         'uncertainties': []}}
    pre_source_policy = pipeline.semantic_stage_policy(options)
    options = pipeline.bhakti_lexical_producer.prepare_gloss_source(targets, languages, options)
    evidence = {'targets': targets, 'source': plan['lines'], 'order': plan['performance_order'],
                'languages': languages, 'reading_context': context_evidence, 'policy': pipeline.semantic_stage_policy(options)}
    identity = digest(evidence)
    validation_song = Path(route_dir) / 'fresh-source-support' / identity / 'songs' / song_dir.name
    def candidate_errors(value, *, expected_review_task_version=None):
        errors = fresh_target_errors(plan, metadata, value, expected_review_task_version=expected_review_task_version)
        if not errors:
            errors.extend(pipeline.bhakti_semantic_repair.derived_support_errors(
                pipeline, validation_song, audited, value['glosses'], value['translations'], options))
        return errors
    unit_id = song_dir.name + ':new-source-semantics'
    decisions = getattr(options, 'editorial_adjudications', None) or {}
    if not isinstance(decisions, dict):
        raise ValueError('editorial_adjudications must map exact unit IDs to decision paths')
    if unit_id in decisions:
        from bhakti_editorial_adjudication import recover_editorial_candidate
        decision_path = Path(decisions[unit_id])
        recovered = recover_editorial_candidate(decision_path,
            unit_id=unit_id, input_fingerprint=identity,
            dependency_fingerprint=digest(evidence['policy']),
            source_evidence=evidence, policy_payload=evidence['policy'],
            validate_candidate=candidate_errors,
            output_dir=Path(route_dir) / 'editorial-adjudications' / digest(unit_id)[:16] / file_hash(decision_path)[:16])
        return {**recovered['candidate'], 'editorial_receipt': recovered['receipt']}
    # A source/context-stable workspace lets the existing selective coordinator
    # renew materialized English evidence without creating a parallel repair loop.
    source_identity = digest({key: value for key, value in evidence.items() if key != 'policy'})
    semantic_song = Path(route_dir) / 'fresh-source-semantics' / source_identity / 'songs' / song_dir.name
    pipeline.semantic_write_json(semantic_song / '.transcription/source-proposal.json',
                                 {'plan': copy.deepcopy(plan), 'metadata': metadata})
    baseline = pipeline.editorial_baselines.load_baselines(pipeline.ROOT).get(song_dir.name)
    if baseline and set(baseline['plainEnglishByLine']) != {line['id'] for line in targets}:
        raise RuntimeError('owner baseline line population changed: locked_baseline_population')
    local = copy.copy(options)
    local.semantic_deadline_at = min(float(deadline_at),
        float(getattr(options, 'semantic_deadline_at', deadline_at)))
    local.unit_deadline_at = min(float(deadline_at),
        float(getattr(options, 'unit_deadline_at', deadline_at)))
    packet_dir = semantic_song / '.transcription/pipeline'
    if not (packet_dir / 'semantic-repair-state.json').exists():
        legacy_writer = None
        # Exact historical pending effects retain their original attempt identity.
        legacy_states = []
        for old_policy in (evidence['policy'], pre_source_policy):
            old_evidence = {**evidence, 'policy':old_policy}
            path = routes.unit_state_path(route_dir, unit_id, digest(old_evidence),
                dependency_fingerprint=digest(old_policy), base_model=options.model, pro_model=options.pro_model)
            if path not in legacy_states:
                legacy_states.append(path)
            if path.exists():
                prior = routes.read_unit_cache(path)
                if prior['state']['status'] != 'accepted':
                    raise routes.UnitUnresolved(unit_id, prior['state'].get('reason', 'historical attempt unresolved'),
                        prior['state'].get('issues', []), path)
        legacy_state = next((path for path in legacy_states if path.exists()), legacy_states[0])
        if legacy_state.exists():
            previous = routes.read_unit_cache(legacy_state)
            if previous['state']['status'] != 'accepted':
                raise routes.UnitUnresolved(unit_id, previous['state'].get('reason', 'historical attempt unresolved'),
                    previous['state'].get('issues', []), legacy_state)
            old = previous['result']
            errors = candidate_errors(old, expected_review_task_version=old['translations'].get('review_task_version', 0))
            if not errors:
                if old['translations'].get('review_task_version', 0) == pipeline.REVIEW_TASK_VERSION:
                    return old
                legacy_writer = copy.deepcopy(old['translations'])
                legacy_writer['historical_translation_route'] = str(legacy_state)
            if errors and errors not in (['automatic model-input evidence receipt changed or missing'],
                                         ['source glossary evidence changed or missing']):
                raise RuntimeError('historical semantic acceptance invalid: ' + str(errors[:3]))
        # Match the source-stage fingerprint, not the changed English policy.
        # Route hashes authenticate prior acceptance; source policy/context bind
        # which glossary is reusable under today's target request.
        seeds = []
        for path in Path(route_dir).rglob('route-state.json'):
            saved = pipeline.read_packet(path) or {}
            if saved.get('unit_id') != unit_id or saved.get('base_model') != options.model:
                continue
            prior = routes.read_unit_cache(path)
            if prior['state']['status'] != 'accepted':
                continue
            value = prior['result']; glossary = value.get('glosses', {})
            model = glossary.get('resolved_model', prior['state'].get('accepted_model'))
            expected = pipeline.text_stage_fingerprint('gloss', model,
                {'lines': targets, 'languages': languages}, pipeline.semantic_stage_policy(local, stage='gloss'))
            if (glossary.get('fingerprint') != expected
                    or pipeline.fresh_gloss_contract_errors(targets, glossary.get('packet', {}).get('glosses', []), languages)):
                continue
            seeds.append((path, glossary))
        if seeds:
            if len({digest(value) for _, value in seeds}) != 1:
                raise RuntimeError('historical accepted source glossary is ambiguous')
            path, glossary = seeds[0]
            glossary = copy.deepcopy(glossary)
            glossary['historical_gloss_route'] = str(path)
            pipeline.semantic_write_json(packet_dir / '04-glosses.json', glossary)
            if legacy_writer is not None:
                pipeline.semantic_write_json(packet_dir / 'translation-candidate.json', legacy_writer)
    glosses, translations = pipeline.complete_semantics(semantic_song, audited,
        {'slug': song_dir.name, 'languages': languages}, local)
    # The adapter returns source-producing evidence, not mutable coordinator
    # checkpoint labels. The complete acceptance retains and verifies those labels.
    glosses = copy.deepcopy(glosses)
    glosses['fingerprint'] = glosses.pop('producer_fingerprint', glosses.get('fingerprint'))
    for key in ('semantic_request_identity', 'semantic_repair_version', 'semantic_run_id', 'historical_gloss_route'):
        glosses.pop(key, None)
    result = {'glosses': glosses, 'translations': translations}
    errors = candidate_errors(result)
    if errors:
        raise RuntimeError('fresh source semantic evidence invalid: ' + '; '.join(errors))
    return result

def fresh_target_errors(plan, metadata, value, *, expected_review_task_version=None):
    import bhakti_pipeline as pipeline
    targets = [line for line in plan['lines'] if line['id'] in plan['new_target_ids']]
    try:
        glosses = value['glosses']['packet']['glosses']
        translations = value['translations']['packet']['translations']
        if not isinstance(glosses, list) or not isinstance(translations, list):
            return ['fresh target rows are not lists']
        if any(not isinstance(row, dict) for row in glosses + translations):
            return ['fresh target rows are not objects']
        import argparse
        import bhakti_library_pass as library
        reused = plan.get('reuse_by_id', {})
        context = []
        if reused:
            planned = {line['id']: line for line in plan['lines']}
            reader = {'SONG_META': metadata, 'SONG_LINES': copy.deepcopy(reused),
                      'SONG_SEQUENCE': [{'ref': event['line_id'], 'section': planned[event['line_id']].get('kind', 'verse'), 'repeats': 1}
                                        for event in plan.get('performance_order', []) if event['line_id'] in reused]}
            sources, old_glosses, drafts = library.reader_evidence(reader)
            context = [{'source': copy.deepcopy(planned[row['id']]), 'gloss': gloss, 'draft': draft}
                       for row, gloss, draft in zip(sources, old_glosses, drafts)]
        options = argparse.Namespace(semantic_full_source=plan['lines'],
            semantic_performance_order=plan.get('performance_order', []), semantic_context_evidence=context)
        kwargs = pipeline.translation_packet_contract_kwargs(targets, value['translations'], options, expected_review_task_version=expected_review_task_version, final_consumer=True)
        return (pipeline.fresh_gloss_contract_errors(targets, glosses, metadata.get('languages', []))
                + pipeline.fresh_translation_contract_errors(targets, glosses, translations, **kwargs)
                + pipeline.validate_line_contract(targets, glosses, translations, **kwargs))
    except (KeyError, TypeError, ValueError) as exc:
        return ['incomplete or invalid fresh target artifact: ' + str(exc)]


def source_semantic_merge_errors(audited, glosses, translations, evidence):
    """Validate fresh proof and exact retained reader evidence before mixed rendering."""
    import bhakti_library_pass as library
    try:
        plan = evidence['plan']; metadata = evidence['metadata']; new = evidence['new']
        if (audited['packet']['verified_lines'] != plan['lines']
                or audited['packet'].get('performance_order') != plan['performance_order']):
            return ['mixed source publication differs from authoritative source plan']
        errors = fresh_target_errors(plan, metadata, new) if plan['new_target_ids'] else []
        if errors:
            return errors
        reused = plan['reuse_by_id']
        old_reader = {'SONG_META': metadata, 'SONG_LINES': copy.deepcopy(reused),
                      'SONG_SEQUENCE': [{'ref': event['line_id'], 'section': next(row for row in plan['lines'] if row['id'] == event['line_id']).get('kind', 'verse'), 'repeats': 1}
                                        for event in plan['performance_order'] if event['line_id'] in reused]}
        _, old_glosses, old_translations = library.reader_evidence(old_reader)
        for field, actual, old, fresh in (
                ('gloss', glosses['packet']['glosses'], old_glosses, new['glosses']['packet']['glosses']),
                ('translation', translations['packet']['translations'], old_translations, new['translations']['packet']['translations'])):
            expected = {row['id']: row for row in old + fresh}
            if set(expected) != {row['id'] for row in plan['lines']}:
                errors.append('mixed ' + field + ' evidence population mismatch')
            elif actual != [expected[row['id']] for row in plan['lines']]:
                errors.append('mixed ' + field + ' changed independently verified fresh or retained evidence')
        return errors
    except (KeyError, TypeError, ValueError) as exc:
        return ['invalid mixed source semantic handoff: ' + str(exc)]


def _source_confirmation_units(reader, delta, observation):
    """Ask only changed local hearings again, with complete source/order."""
    import bhakti_lexical_retrieval as lexical
    units=[]; expected={}
    for item in observation['unit_results']:
        original=item['unit']; packet=item['result']['segment_audits'][0]['audit']['packet']
        by_id={row['id']:row for row in packet['lines']}
        heard=[by_id[event['line_id']] for event in packet['performance_order']]
        old_by={row['id']:row for row in original['expanded_draft']['lines']}
        old=[old_by[event['line_id']] for event in original['expanded_draft']['performance_order']]
        if [_source_lexical_key(row) for row in heard]==[_source_lexical_key(row) for row in old]:
            continue
        unit=copy.deepcopy(original)
        unit['id']='confirmation-'+original['id']+'-'+digest(delta)[:16]
        lines=copy.deepcopy(packet['lines']); rows={row['id']:row for row in lines}
        canonical={_source_lexical_key(row):row for row in delta['rebuilt']['verified_lines']}
        for row in lines:
            code=lexical.language(row.get('language'))
            if not code:
                approved=canonical.get(_source_lexical_key(row),{})
                code=lexical.language(approved.get('sourceLanguage'))
            if not code:raise ValueError('confirmation source lacks a resolved language')
            row['language']=code
        order=[]; targets=[]
        for index,event in enumerate(packet['performance_order']):
            locator=f'occ-{index:03d}'
            row=rows[event['line_id']]
            order.append({**copy.deepcopy(event),'display_occurrence_id':locator,
                          'repeat_index':0,'kind':row['kind']})
            if row['partial']=='none':targets.append(locator)
        if not targets:raise ValueError('confirmation has no complete target source')
        unit['expanded_draft']={'lines':lines,'performance_order':order}
        unit['target_occurrence_ids']=targets
        unit['hypotheses']=[{'id':'prior-source-'+original['id'],
            'reason':'The prior reader differs from this proposed hearing; decide from the attached recording.',
            'alternatives':copy.deepcopy(original['expanded_draft']['lines'])}]
        unit['prior_evidence']=[]
        units.append(unit)
        expected[unit['id']]=[list(_source_key(rows[event['line_id']])) for event in order]
    if delta['requires_confirmation'] and not units:
        raise ValueError('changed source has no confirmable local observation')
    return units,expected


def _checked_adoption_receipt(declaration, reader):
    path=Path(declaration['path'])
    if file_hash(path)!=declaration.get('sha256'):
        raise ValueError('accepted source receipt changed')
    receipt=json.loads(path.read_text())
    delta=receipt.get('delta')
    if (receipt.get('version')!=1 or receipt.get('status')!='accepted-source'
            or receipt.get('original_reader_digest')!=digest(reader)
            or receipt.get('delta_digest')!=digest(delta)
            or not isinstance(delta,dict) or delta.get('status')!='proposed'
            or receipt.get('approved_source_order_digest')!=digest(delta.get('rebuilt'))):
        raise ValueError('invalid accepted source receipt')
    # Re-entered observations and confirmation validated these paths before
    # constructing the declaration. Recheck their bytes at the builder boundary.
    import bhakti_model_routes as routes
    for filename,expected in receipt.get('evidence_files',{}).items():
        if file_hash(filename)!=expected:raise ValueError('accepted source evidence changed')
        if Path(filename).name == 'route-state.json':
            try:
                cached = routes.read_unit_cache(Path(filename))
            except routes.RunFatal as exc:
                raise ValueError('accepted source route evidence invalid: ' + str(exc)) from exc
            if cached['state']['status'] != 'accepted':
                raise ValueError('accepted source route is no longer accepted')
    if receipt.get('audio_transform') is not None:
        from bhakti_boundary_adoption import checked_audio_transform, require_removed_membership
        declared=receipt['audio_transform']
        body=json.loads(Path(declared['path']).read_text())
        native=next(iter(body['native'].values()))
        original=Path(native['before']['path']).parent; staged=Path(native['after']['path']).parent
        checked=checked_audio_transform(declared,original,staged,reader)
        require_removed_membership(checked,reader,delta,original)
    return receipt


def verify_source_result_evidence(result, reader):
    """Revalidate saved source authorization without provider dispatch."""
    if (result.get('status')!='accepted' or result.get('publicationEligible') is not True
            or result.get('issues')):
        raise ValueError('source checkpoint is not accepted evidence')
    evidence=result['evidence']
    import bhakti_pipeline as pipeline
    errors = pipeline.timing_uncertainty_errors(evidence['timing'])
    if errors:raise ValueError('source checkpoint timing evidence invalid: ' + '; '.join(errors))
    assert_source_candidate(reader,result['reader'],evidence['plan'],evidence['timing'])
    declaration=evidence.get('source_adoption_receipt')
    if declaration is not None:
        receipt=_checked_adoption_receipt(declaration,reader)
        if evidence['plan'].get('adopted_delta')!=receipt['delta']:
            raise ValueError('source checkpoint differs from accepted source receipt')


def run_observed_source_candidate(*, root, slug, reader, workspace, route_dir, options, deadline_at):
    """Existing observer -> source confirmation -> existing private builder."""
    import bhakti_pipeline as pipeline
    song=Path(root)/'songs'/slug; target=Path(workspace)/'songs'/slug
    audio=target/pipeline.preferred_listener_audio(song).name
    initial=observe_source_candidate(reader=reader,song_dir=target,original_song=song,audio=audio,
        route_dir=route_dir,options=options,deadline_at=deadline_at)
    observation=initial['evidence']['audio_review']
    if observation['status']!='observed':return initial
    flags=copy.deepcopy(getattr(options,'source_review_flags',{}))
    requested=set(getattr(options,'source_requested_stages',[]) or [])
    if requested.intersection({'audio-review','focused-audio-review'}):flags['audio']=True
    transform_declaration=getattr(options,'source_audio_transform',None)
    transform=None
    if transform_declaration is not None:
        from bhakti_boundary_adoption import checked_audio_transform, staged_source_evidence
        transform=checked_audio_transform(transform_declaration,song,target,reader)
        evidence=staged_source_evidence(transform,song,target,reader,flags,
            getattr(options,'source_coverage_requested',False))
    else:
        evidence=collect_source_evidence(song,reader,flags=flags,
            coverage_requested=getattr(options,'source_coverage_requested',False))
    evidence['disagreements']=copy.deepcopy(flags.get('disagreements',[]))
    source_plan=plan_audio_review(reader,source_evidence=evidence,flags=flags,
                                  duration_seconds=evidence['duration_seconds'])
    pure_input={**copy.deepcopy(observation),'source_identity':evidence['identity']}
    for item in pure_input['unit_results']:item['result_digest']=digest(item['result'])
    delta=reconcile_source_observations(reader,source_plan,pure_input)
    def hold(kind,detail,extra=None):
        return {'status':'unresolved','reader':reader,'source_changed':False,'publicationEligible':False,
                'issues':[{'kind':kind,'detail':detail}],
                'evidence':{'audio_review':observation,'source_delta':delta,**(extra or {})}}
    if delta['status']!='proposed':return hold('source_reconciliation',delta['issues'])
    if transform is not None:
        from bhakti_boundary_adoption import require_removed_membership, review_boundary_memberships
        removed = any(row['old_index'] is not None and row['new_index'] is None
            for row in delta['occurrence_lineage'])
        if removed and not transform.get('original_edge_membership'):
            proof = review_boundary_memberships(transform_declaration, song, target, reader, delta,
                options=options, route_dir=Path(route_dir)/'original-boundary-memberships',
                deadline_at=deadline_at)
            if proof['status'] != 'observed':
                return hold('original_boundary_membership', proof['issues'],
                    {'boundary_memberships': proof})
            completed = {**transform, 'original_edge_membership': proof['memberships']}
            path = Path(route_dir)/'boundary-transforms'/(digest(completed)+'.json')
            if path.is_file():
                if json.loads(path.read_text()) != completed:
                    raise ValueError('completed boundary transform changed')
            else:
                atomic_json(path, completed)
            local = copy.copy(options)
            local.source_audio_transform = {'path': str(path), 'sha256': file_hash(path)}
            # Re-enter with the complete immutable declaration. Exact audio
            # question identities reuse the first staged hearing, while the
            # receipt and subsequent timing now bind the new original proof.
            return run_observed_source_candidate(root=root, slug=slug, reader=reader,
                workspace=workspace, route_dir=route_dir, options=local, deadline_at=deadline_at)
        require_removed_membership(transform,reader,delta,song)
    confirmations={'status':'observed','unit_results':[],'issues':[]}
    if delta['requires_confirmation']:
        units,expected=_source_confirmation_units(reader,delta,observation)
        confirmations=review_audio_units(song_dir=target,units=units,audio=audio,
            source_identity=evidence['identity'],options=options,route_dir=route_dir,
            deadline_at=deadline_at,expected_orders=expected)
        if confirmations['status']!='observed':
            return hold('source_confirmation',confirmations['issues'],{'confirmation':confirmations})
    files={observation['receipt_path']:file_hash(observation['receipt_path'])}
    for item in observation['unit_results']+confirmations['unit_results']:
        state=Path(item['route_state_path']);files[str(state)]=file_hash(state)
        accepted=state.parent/'accepted-result.json'
        files[str(accepted)]=file_hash(accepted)
    receipt={'version':1,'status':'accepted-source','original_reader_digest':digest(reader),
        'before_identity':evidence['identity'],'delta':delta,'delta_digest':digest(delta),
        'approved_source_order_digest':digest(delta['rebuilt']),
        'coverage_scope':delta['coverage_scope'],'confirmation':confirmations,
        'observation_fingerprint':observation['input_fingerprint'],'evidence_files':files,
        'remaining_obligations':['timing','semantics','candidate-validation']}
    if transform is not None:
        receipt['audio_transform']=copy.deepcopy(transform_declaration)
        receipt['evidence_files'][transform_declaration['path']]=transform_declaration['sha256']
    identity=digest({'before':evidence['identity'],'reader':digest(reader),
                     'observation':observation['input_fingerprint'],'delta':delta})
    path=Path(route_dir)/'source-adoptions'/identity/'accepted-source-delta.json'
    if path.is_file():
        if json.loads(path.read_text())!=receipt:raise ValueError('accepted source receipt changed or no longer matches routed evidence')
    else:atomic_json(path,receipt)
    local=copy.copy(options)
    local.source_requested_stages=[stage for stage in requested if stage not in {'audio-review','focused-audio-review'}]
    local.source_coverage_requested=False
    local._source_adoption_receipt={'path':str(path),'sha256':file_hash(path)}
    return run_source_candidate(root=root,slug=slug,reader=reader,workspace=workspace,
        route_dir=route_dir,options=local,deadline_at=deadline_at)


def bootstrap_source_units(audited, duration):
    """Map accepted merged performances to the actual bounded audit clips.

    The assembly's source occurrence provenance supplies ownership. Neither
    core fractions nor old reader timestamps are syllable measurements.
    """
    import bhakti_pipeline as pipeline
    segments = audited.get('segment_audits')
    if not segments:
        return [], [digest(audited)]
    merged = pipeline.merge_audited_segments(segments)
    if any(merged.get(key) != audited['packet'].get(key) for key in ('verified_lines', 'performance_order')):
        raise ValueError('bootstrap merged source/order differs from accepted segment evidence')
    assembly = pipeline.assemble_audited_segment_occurrences(segments)
    if assembly['uncertainties']:
        raise ValueError('bootstrap segment correspondence unresolved: ' + '; '.join(assembly['uncertainties']))
    if len(assembly['occurrences']) != len(merged['performance_order']):
        raise ValueError('bootstrap source ownership population differs from complete order')
    units = []; digests = []; previous_end = 0.; seen = set()
    for position, item in enumerate(segments):
        segment = item['segment']; index = segment.get('index')
        if type(index) is not int or index in seen:
            raise ValueError('bootstrap source segments need unique integer identities')
        seen.add(index)
        fields = ('clip_start', 'clip_end', 'core_start', 'core_end')
        if (any(type(segment.get(key)) not in (int, float) or not math.isfinite(segment[key]) for key in fields)
                or not 0 <= segment['clip_start'] <= segment['core_start'] < segment['core_end'] <= segment['clip_end'] <= duration
                or segment['clip_end'] - segment['clip_start'] > 900
                or abs(segment['core_start'] - previous_end) > .0005):
            raise ValueError('bootstrap source clips/core do not form complete bounded recording coverage')
        previous_end = segment['core_end']
        owned = [i for i, row in enumerate(assembly['occurrences']) if row['segment_position'] == position]
        evidence_digest = digest(item['audit']); digests.append(evidence_digest)
        units.append({'id': f'bootstrap-segment-{index}', 'segment_index': index,
            **{key: segment[key] for key in fields}, 'expanded_indices': owned,
            'expanded_context_indices': list(owned), 'observation_digest': evidence_digest})
    if abs(previous_end - duration) > .0005:
        raise ValueError('bootstrap source cores do not cover recording end')
    if sorted(i for unit in units for i in unit['expanded_indices']) != list(range(len(merged['performance_order']))):
        raise ValueError('bootstrap source ownership is missing or duplicates a performance')
    return units, digests


def run_empty_source_candidate(*, root, slug, reader, workspace, route_dir, options, deadline_at):
    """Acquire missing source with the same two stages as ordinary intake."""
    import bhakti_pipeline as pipeline
    import bhakti_source_stages as stages
    import bhakti_lexical_retrieval as lexical
    if not source_reader_is_empty(reader):
        raise ValueError('source bootstrap requires exactly empty definitions, order and timing')
    song = Path(root) / 'songs' / slug
    target = Path(workspace) / 'songs' / slug
    audio = target / pipeline.preferred_listener_audio(song).name
    local = copy.copy(options)
    local.unit_deadline_at = min(deadline_at, getattr(options, 'unit_deadline_at', None) or deadline_at)
    original_trim = song / '.transcription/trim-applied.json'
    staged_trim = target / '.transcription/trim-applied.json'
    if ((file_hash(original_trim) if original_trim.is_file() else None)
            != (file_hash(staged_trim) if staged_trim.is_file() else None)):
        raise ValueError('workspace trim evidence differs from original recording')
    source = pipeline.read_packet(song / '.transcription/source.json') or {}
    raw = pipeline.transcript(target, source, audio, local)
    audited = pipeline.audit_transcript(target, raw, audio, local)
    errors = stages.source_errors(audited, audited=True)
    if errors:
        raise ValueError('missing-source audit unresolved: ' + str(errors))
    units, observation_digests = bootstrap_source_units(audited, pipeline.gemini.duration_seconds(audio))
    rebuilt = copy.deepcopy(audited['packet'])
    mapping = {}
    languages = rebuilt.get('metadata', {}).get('languages', [])
    for row in rebuilt['verified_lines']:
        original = row['id']
        language = lexical.line_language(row, languages)
        if not language and row.get('kind') != 'instrumental':
            raise ValueError('new source lacks an identified line language')
        if language:
            row['sourceLanguage'] = language
        row['id'] = 'source-new-' + digest({'id': original, 'source': _source_key(row)})[:16]
        mapping[original] = row['id']
    for event in rebuilt['performance_order']:
        event['line_id'] = mapping[event['line_id']]
    trim = song / '.transcription/trim-applied.json'
    before = {'audio_sha256': file_hash(audio), 'trim_sha256': file_hash(trim) if trim.is_file() else None,
              'reader_source_sha256': reader_source_identity(reader)}
    delta = {'status': 'proposed', 'issues': [], 'bootstrap_source': True, 'before_identity': before,
        'rebuilt': rebuilt, 'reused_line_ids': [], 'fresh_line_ids': [row['id'] for row in rebuilt['verified_lines']],
        'removed_line_ids': [], 'requires_confirmation': False, 'coverage_scope': 'whole_recording',
        'occurrence_lineage': [{'old_index': None, 'new_index': i} for i in range(len(rebuilt['performance_order']))],
        'timing_unresolved_old_indices': [], 'source_unit_coverage': units,
        'observation_digests': observation_digests}
    files = {}
    for name, artifact in [('01-transcript.json', raw), ('02-transcript-audit.json', audited)]:
        path = target / '.transcription/pipeline' / name
        files[str(path)] = file_hash(path)
        projections = [artifact]
        if name == '01-transcript.json' and artifact.get('segment_responses'):
            projections = [item['response'] for item in artifact['segment_responses']]
        elif name == '02-transcript-audit.json' and artifact.get('segment_audits'):
            projections = [item['audit'] for item in artifact['segment_audits']]
        for projection in projections:
            declaration = projection.get('_source_route')
            if declaration is None:
                if name == '02-transcript-audit.json':
                    raise ValueError('missing-source audit lacks durable routed evidence')
                continue  # A legacy draft is explicitly untrusted by the independent audit.
            stages._checked_projection(projection, declaration['input_fingerprint'])
            state = Path(declaration['state_path'])
            for evidence in [state, state.parent / 'accepted-result.json']:
                files[str(evidence)] = file_hash(evidence)
    receipt = {'version': 1, 'status': 'accepted-source', 'original_reader_digest': digest(reader),
        'before_identity': before, 'delta': delta, 'delta_digest': digest(delta),
        'approved_source_order_digest': digest(rebuilt), 'coverage_scope': 'whole_recording',
        'confirmation': {'kind': 'independent-source-audit', 'audit_digest': digest(audited)},
        'observation_fingerprint': digest([raw, audited]), 'evidence_files': files,
        'remaining_obligations': ['timing', 'semantics', 'candidate-validation']}
    path = Path(route_dir) / 'source-adoptions' / digest(receipt) / 'accepted-source-delta.json'
    if path.is_file():
        if json.loads(path.read_text()) != receipt:
            raise ValueError('accepted bootstrap source receipt changed')
    else:
        atomic_json(path, receipt)
    local.source_requested_stages = [stage for stage in getattr(options, 'source_requested_stages', [])
                                     if stage not in {'audio-review', 'focused-audio-review'}]
    local.source_coverage_requested = False
    local._source_adoption_receipt = {'path': str(path), 'sha256': file_hash(path)}
    return run_source_candidate(root=root, slug=slug, reader=reader, workspace=workspace,
        route_dir=route_dir, options=local, deadline_at=deadline_at)


def run_source_candidate(*, root, slug, reader, workspace, route_dir, options, deadline_at):
    """Derive a private reader, preserving every existing editorial field exactly."""
    import re
    import shutil
    import bhakti_pipeline as pipeline
    import bhakti_library_pass as library
    import bhakti_model_routes as routes
    import audit_bhakti_contract as contract
    import apply_translation_style_review as writer
    import editorial_baselines
    root, workspace, route_dir = Path(root).resolve(), Path(workspace).resolve(), Path(route_dir).resolve()
    evidence = {}
    def hold(kind, detail):
        return {'status': 'unresolved', 'reader': reader, 'source_changed': False,
                'publicationEligible': False, 'evidence': evidence,
                'issues': [{'kind': kind, 'detail': str(detail)}]}
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
        return hold('source_input', 'invalid slug')
    if root == workspace or root in workspace.parents or workspace in root.parents:
        return hold('source_input', 'source and workspace must be isolated roots')
    song = root / 'songs' / slug
    target = workspace / 'songs' / slug
    original_audit = song / '.transcription/pipeline/02-transcript-audit.json'
    original_timing = song / '.transcription/pipeline/03-timing.json'
    try:
        if contract.load_data(song / 'data.js') != reader:
            raise ValueError('current reader differs from supplied original')
        if (root / 'data/editorial_baselines.json').read_bytes() != (workspace / 'data/editorial_baselines.json').read_bytes():
            raise ValueError('workspace owner registry differs from authoritative registry')
        baselines = editorial_baselines.load_baselines(root)
        editorial_baselines.assert_english_preserved(slug, reader['SONG_LINES'], root=root)
        original_audio = pipeline.preferred_listener_audio(song)
        audio = target / original_audio.name
        transform_declaration=getattr(options,'source_audio_transform',None)
        transform=None
        if transform_declaration is not None:
            from bhakti_boundary_adoption import checked_audio_transform
            transform=checked_audio_transform(transform_declaration,song,target,reader)
        elif file_hash(audio) != file_hash(original_audio):
            raise ValueError('workspace audio differs from original native listener audio')
        requested = set(getattr(options, 'source_requested_stages', []) or [])
        coverage_requested = getattr(options, 'source_coverage_requested', False)
        if type(coverage_requested) is not bool:
            raise ValueError('source coverage selection must be boolean')
        if source_reader_is_empty(reader) and getattr(options, '_source_adoption_receipt', None) is None:
            return run_empty_source_candidate(root=root, slug=slug, reader=reader, workspace=workspace,
                route_dir=route_dir, options=options, deadline_at=deadline_at)
        if requested.intersection({'audio-review', 'focused-audio-review'}) or coverage_requested:
            return run_observed_source_candidate(root=root,slug=slug,reader=reader,workspace=workspace,
                route_dir=route_dir,options=options,deadline_at=deadline_at)
        old_lines, old_glosses, old_translations = ([], [], []) if source_reader_is_empty(reader) else library.reader_evidence(reader)
        declaration=getattr(options,'_source_adoption_receipt',None)
        adoption=_checked_adoption_receipt(declaration,reader) if declaration is not None else None
        audit = ({'packet':copy.deepcopy(adoption['delta']['rebuilt'])} if adoption
                 else json.loads(original_audit.read_text()))
        timing_before = (pipeline.read_packet(original_timing) or {}) if adoption else json.loads(original_timing.read_text())
        mapping_path = (getattr(options, 'source_reuse_maps', {}) or {}).get(slug)
        mapping = json.loads(Path(mapping_path).read_text()) if mapping_path else None
        source = pipeline.read_packet(song / '.transcription/source.json') or {}
        dependencies = {str(path.relative_to(root)): file_hash(path)
                        for path in [song / 'data.js', original_audit, original_timing, original_audio,
                                     *sorted((root / 'data').glob('*.json'))] if path.is_file()}
        for path in [song / '.transcription/source.json', song / '.transcription/trim-applied.json',
                     song / '.transcription/pipeline/01-transcript.json', song / '.transcription/pipeline/song-packet.json']:
            if path.is_file(): dependencies[str(path.relative_to(root))] = file_hash(path)
        editorial_paths = getattr(options, 'editorial_adjudications', None) or {}
        if not isinstance(editorial_paths, dict):
            raise ValueError('editorial_adjudications must be an exact unit-to-path mapping')
        editorial_unit = slug + ':new-source-semantics'
        editorial_identity = ({editorial_unit: file_hash(editorial_paths[editorial_unit])}
                              if editorial_unit in editorial_paths else {})
        identity = digest({'version': VERSION, 'dependencies': dependencies, 'map': mapping,
                           'source_adoption':declaration,
                           'editorial_adjudications': editorial_identity,
                           'requested_stages': getattr(options, 'source_requested_stages', []),
                           'confirmed_issues': getattr(options, 'source_confirmed_issues', []),
                           'policy': pipeline.translation_policy_payload(),
                           'code': {name: file_hash(Path(pipeline.__file__).parent / name)
                                    for name in ['bhakti_pipeline.py', 'bhakti_model_routes.py']},
                           'adapter': file_hash(__file__)})
        evidence['input_fingerprint'] = identity
        checkpoint = route_dir / (slug + '-source-accepted.json')
        saved = load_checkpoint(checkpoint, identity)
        if saved:
            if contract.load_data(target / 'data.js') != saved['reader']:
                raise ValueError('accepted source checkpoint workspace reader drifted')
            expected_script = 'data.js?v=' + file_hash(target / 'data.js')[:12]
            if (file_hash(target / 'index.html') != saved['evidence'].get('candidate_html_sha256')
                    or expected_script not in (target / 'index.html').read_text()):
                raise ValueError('accepted source checkpoint workspace HTML drifted')
            if contract.audit_song(target)['status'] != 'ready':
                raise ValueError('accepted source checkpoint workspace contract no longer ready')
            verify_source_result_evidence(saved, reader)
            editorial_baselines.assert_english_preserved(slug, saved['reader']['SONG_LINES'], root=root)
            return saved
        # On a changed input do not reuse a previously mutated workspace.
        if contract.load_data(target / 'data.js') != reader:
            raise ValueError('workspace reader is stale for the changed input; prepare a new isolated workspace')
        segments = audit.get('segment_audits')
        rebuilt = pipeline.merge_audited_segments(segments) if segments else copy.deepcopy(audit['packet'])
        if mapping:
            if (mapping.get('original_public_sha256') != file_hash(song / 'data.js')
                    or mapping.get('original_audit_sha256') != file_hash(original_audit)
                    or mapping.get('rebuilt_audit_sha256') != hashlib.sha256((json.dumps(rebuilt, ensure_ascii=False, indent=2) + '\n').encode()).hexdigest()):
                raise ValueError('reviewed source map input hashes changed')
        plan = plan_source(reader, rebuilt, reviewed_map=mapping,
                           accepted_delta=adoption['delta'] if adoption else None)
        population_changed = {line['id'] for line in plan['lines']} != set(reader['SONG_LINES'])
        if slug in baselines and population_changed:
            raise ValueError('locked_baseline_conflict: owner English population cannot change automatically')
        # Stored human declarations also cannot be silently extended or rewritten.
        summary = pipeline.read_packet(song / '.transcription/pipeline/song-packet.json') or {}
        declarations = [obj[field] for obj in [reader.get('SONG_META', {}), source, summary, summary.get('job', {})]
                        if isinstance(obj, dict) for field in ['humanTranslation','human_translation','providedTranslation','provided_translation']
                        if obj.get(field) not in (None, '', False, '(none supplied)')]
        if declarations and population_changed:
            raise ValueError('locked_baseline_conflict: supplied human translation requires a reviewed population mapping')
        metadata = copy.deepcopy(rebuilt.get('metadata', {}))
        metadata['languages'] = reader['SONG_META'].get('languages') or metadata.get('languages', [])
        normalized = copy.deepcopy(audit)
        normalized['packet'] = {**copy.deepcopy(rebuilt), 'metadata': metadata,
                                'verified_lines': plan['lines'], 'performance_order': plan['performance_order']}
        mapped_metadata = remap_sequence_metadata(reader, plan,
            pipeline.display_occurrences(normalized['packet']))
        old_order = [event['ref'] for event in reader['SONG_SEQUENCE'] for _ in range(event.get('repeats', 1))]
        source_changed = bool(plan['new_target_ids'] or old_order != [event['line_id'] for event in plan['performance_order']])
        requested = set(getattr(options, 'source_requested_stages', []) or [])
        unsupported = requested.intersection({'audio-review', 'focused-audio-review'})
        if unsupported:
            return hold('unsupported_audio_source_review', {'stages': sorted(unsupported),
                'issues': getattr(options, 'source_confirmed_issues', []),
                'reason': 'Cached merge/timing repair does not independently resolve broader audio/source flags.'})
        evidence.update({'plan': plan, 'original_dependencies': dependencies,
                         'new_target_ids': plan['new_target_ids'], 'audio_sha256': file_hash(original_audio)})
        local = copy.copy(options)
        if adoption:
            # The selective timing consumer must validate this receipt and its
            # old/new occurrence lineage; caller tests replace align only.
            local.timing_source_adoption=copy.deepcopy(declaration)
        # Hash guards and whole original-line validation above authorize this map.
        local.timing_reviewed_source_map = copy.deepcopy(mapping) if mapping else None
        for name, value in {'force': False, 'refresh_timing': False, 'source_witness_audit': False,
                            'timeout': 300, 'model': pipeline.MODEL, 'pro_model': 'google/gemini-3.1-pro-preview'}.items():
            if not hasattr(local, name): setattr(local, name, value)
        local.timing_deadline_at = min(deadline_at, getattr(options, 'timing_deadline_at', None) or deadline_at)
        if time.time() >= deadline_at: return hold('source_deadline', 'source-stage deadline exhausted before dispatch')
        archive = target / '.transcription/source-pass-original'
        archive.mkdir(parents=True, exist_ok=True)
        for name in ['data.js', 'index.html']:
            if not (archive / name).exists(): shutil.copy2(song / name, archive / name)
        for name in ['01-transcript.json', '02-transcript-audit.json', '03-timing.json']:
            original = song / '.transcription/pipeline' / name
            if original.exists() and not (archive / name).exists(): shutil.copy2(original, archive / name)
        if adoption:
            archived_reader = archive / 'data.js'
            archived_timing = archive / '03-timing.json'
            if file_hash(archived_reader) != dependencies[str((song/'data.js').relative_to(root))]:
                raise ValueError('source timing original reader archive changed')
            prior_timing = None
            if original_timing.is_file() and not adoption['delta'].get('bootstrap_source'):
                expected_timing = dependencies[str(original_timing.relative_to(root))]
                if file_hash(archived_timing) != expected_timing:
                    raise ValueError('source timing original measurement archive changed')
                prior_timing = {'path':str(archived_timing),'sha256':expected_timing}
            local.timing_source_adoption = {**copy.deepcopy(declaration),
                'original_reader':{'path':str(archived_reader),'sha256':file_hash(archived_reader)},
                'prior_timing':prior_timing}
            if transform_declaration is not None:
                local.timing_source_adoption['audio_transform']=copy.deepcopy(transform_declaration)
        new = process_new_targets(target, plan, metadata, local, route_dir, deadline_at) if plan['new_target_ids'] else {'glosses': {'packet': {'glosses': []}}, 'translations': {'packet': {'translations': []}}}
        if plan['new_target_ids']:
            errors = fresh_target_errors(plan, metadata, new)
            if errors: return hold('source_semantic_contract', '; '.join(errors))
        # Target only explicit saved uncertainty for a source-identical timing repair.
        if not source_changed and timing_before.get('uncertain_occurrence_ids'):
            local.timing_repair_occurrence_ids = copy.deepcopy(timing_before['uncertain_occurrence_ids'])
            local.timing_legacy_evidence_identity = {'audio_sha256': file_hash(original_audio),
                'timing_sha256': file_hash(original_timing),
                'trim': pipeline.read_packet(song / '.transcription/trim-applied.json') or {}}
            # Retain the exact original audited rows/order for the timing cache identity.
            timing_audit = audit
        else:
            timing_audit = normalized
        timing = pipeline.align(target, timing_audit, audio, local)
        gloss_by = {row['id']: row for row in old_glosses + new['glosses']['packet']['glosses']}
        english_by = {row['id']: row for row in old_translations + new['translations']['packet']['translations']}
        glosses = {'packet': {'glosses': [gloss_by[line['id']] for line in plan['lines']]}}
        translations = {'packet': {'translations': [english_by[line['id']] for line in plan['lines']]}}
        semantic_evidence = {'plan': plan, 'metadata': metadata, 'new': new}
        errors = pipeline.publication_errors(normalized, timing, glosses, translations, source_semantic_evidence=semantic_evidence)
        if errors: return hold('source_publication_contract', '; '.join(errors))
        job = {**copy.deepcopy(mapped_metadata), 'slug': slug,
               'displayTitle': reader['SONG_META']['title'], 'languages': metadata['languages']}
        pipeline.generate(target, job, source, normalized, timing, glosses, translations,
            write_catalogue_after=False, source_reader_metadata=mapped_metadata, source_semantic_evidence=semantic_evidence)
        candidate = contract.load_data(target / 'data.js')
        candidate['SONG_META'] = copy.deepcopy(mapped_metadata)
        candidate['SONG_LINES'].update(copy.deepcopy(plan['reuse_by_id'] if adoption else reader['SONG_LINES']))
        assert_source_candidate(reader, candidate, plan, timing)
        # Native/English links of every new row are checked after actual rendering.
        library.reader_evidence(candidate)
        editorial_baselines.assert_english_preserved(slug, candidate['SONG_LINES'], root=root)
        writer.write_reader(slug, candidate, root=workspace)
        # Regenerate HTML with the exact preserved metadata, avoiding metadata churn.
        html = pipeline.page_html(candidate['SONG_META'], slug)
        html, count = re.subn(r'(?<=src=")data\.js(?:\?v=[^"\s]+)?(?=")',
                              'data.js?v=' + file_hash(target / 'data.js')[:12], html)
        if count != 1: raise ValueError('candidate HTML lacks a unique data script')
        (target / 'index.html').write_text(html, encoding='utf-8')
        inspection = contract.audit_song(target)
        if inspection['status'] != 'ready': return hold('source_reader_contract', inspection)
        evidence.update({'timing': timing, 'contract': inspection,
                         'source_adoption_receipt':declaration,
                         'candidate_html_sha256': file_hash(target / 'index.html'),
                         'new_semantic_artifacts': new if plan['new_target_ids'] else None})
        atomic_json(target / '.transcription/source-pass-derived.json',
                    {'original_input_fingerprint': identity, 'audit': normalized,
                     'glosses': glosses, 'translations': translations, 'timing': timing,
                     'derivation': 'Original reviewed line objects retained; new units independently processed.'})
        result = {'status': 'accepted', 'reader': candidate, 'source_changed': source_changed,
                  'publicationEligible': True, 'evidence': evidence, 'issues': []}
        save_checkpoint(checkpoint, identity, result)
        return result
    except (routes.RunFatal, routes.UnitTransportFailure):
        raise
    except routes.UnitUnresolved as exc:
        return hold('source_unit_unresolved', exc)
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        # Deterministic input/contract failures are holds, never model escalation.
        return hold('source_stage_hold', exc)


AUDIO_REVIEW_CONTRACT_VERSION = 1


def source_draft(reader, occurrence_indices=None):
    """Expand actual performances for audio review, excluding English/glosses."""
    lines = reader.get('SONG_LINES')
    sequence = reader.get('SONG_SEQUENCE')
    if not isinstance(lines, dict) or not lines or not isinstance(sequence, list) or not sequence:
        raise ValueError('source draft requires definitions and performed sequence')
    sections = {'invocation', 'refrain', 'verse', 'bridge', 'closing', 'spoken', 'instrumental'}
    kinds_by_id = {}
    for event in sequence:
        if not isinstance(event, dict) or event.get('ref') not in lines:
            raise ValueError('source draft contains an unknown performed reference')
        if type(event.get('repeats', 1)) is not int or event.get('repeats', 1) < 1:
            raise ValueError('source draft repeat count must be a positive integer')
        if event.get('section', 'verse') not in sections:
            raise ValueError('source draft contains an unknown section kind')
        kinds_by_id.setdefault(event['ref'], set()).add(event.get('section', 'verse'))
    indices = list(range(len(sequence))) if occurrence_indices is None else list(occurrence_indices)
    if (any(type(index) is not int or not 0 <= index < len(sequence) for index in indices)
            or indices != sorted(set(indices))):
        raise ValueError('source draft occurrence indices must be unique and ordered')
    definitions = {}; order = []; counts = {}
    for index in indices:
        event = sequence[index]; lid = event['ref']; line = lines[lid]
        instrumental_only = kinds_by_id[lid] == {'instrumental'}
        if (not isinstance(line, dict) or any(not isinstance(line.get(key), str) for key in ('source', 'roman'))
                or (not instrumental_only and any(not line[key].strip() for key in ('source', 'roman')))):
            raise ValueError('source draft requires exact native and Roman source for lyrics')
        definitions.setdefault(lid, {'id': lid, 'source_text': line['source'], 'roman': line['roman'],
                                     'kind': event.get('section', 'verse')})
        for repeat in range(event.get('repeats', 1)):
            counts[lid] = counts.get(lid, 0) + 1
            order.append({'line_id': lid, 'occurrence': counts[lid],
                          'display_occurrence_id': f'occ-{index:03d}', 'repeat_index': repeat,
                          'kind': event.get('section', 'verse')})
    return {'lines': list(definitions.values()), 'performance_order': order}


def source_reader_is_empty(reader):
    return (type(reader.get('SONG_LINES')) is dict and reader['SONG_LINES'] == {}
            and type(reader.get('SONG_SEQUENCE')) is list and reader['SONG_SEQUENCE'] == []
            and type(reader.get('SONG_TIMINGS')) is list and reader['SONG_TIMINGS'] == [])


def reader_source_identity(reader):
    if source_reader_is_empty(reader):
        return digest({'kind': 'empty-source', 'reader_digest': digest(reader)})
    draft = source_draft(reader)
    lines = {lid: {key: line.get(key) for key in ('source', 'roman', 'sourceWords')}
             for lid, line in reader['SONG_LINES'].items()}
    order = [{'ref': event['line_id'], 'section': event['kind']} for event in draft['performance_order']]
    return digest({'lines': lines, 'order': order})


def plan_audio_review(reader, *, source_evidence, flags, duration_seconds):
    """Plan coverage/source/timing independently; no provider or file mutations.

    Receipt hashes identify evidence. This planner never decides a sung word or
    certifies first-syllable timing from a display interval.
    """
    import re
    if (not isinstance(duration_seconds, (int, float)) or isinstance(duration_seconds, bool)
            or not math.isfinite(duration_seconds) or duration_seconds <= 0):
        raise ValueError('audio planning requires a finite positive measured duration')
    if not isinstance(source_evidence, dict) or not isinstance(flags, dict):
        raise ValueError('audio evidence and flags must be objects')
    draft = source_draft(reader)
    identity = source_evidence.get('identity')
    if (not isinstance(identity, dict) or set(identity) != {'audio_sha256', 'trim_sha256', 'reader_source_sha256'}
            or any(not isinstance(identity.get(key), str) or not re.fullmatch(r'[0-9a-f]{64}', identity[key])
                   for key in ('audio_sha256', 'reader_source_sha256'))
            or (identity.get('trim_sha256') is not None and not re.fullmatch(r'[0-9a-f]{64}', str(identity['trim_sha256'])))
            or identity['reader_source_sha256'] != reader_source_identity(reader)):
        raise ValueError('audio planning identity does not match exact current source')
    sequence = reader['SONG_SEQUENCE']; lines = reader['SONG_LINES']
    disagreements = source_evidence.get('disagreements', [])
    receipts = source_evidence.get('focused_receipts', [])
    if (not isinstance(disagreements, list) or any(not isinstance(row, dict) for row in disagreements)
            or not isinstance(receipts, list) or any(not isinstance(row, dict) for row in receipts)):
        raise ValueError('audio disagreements/receipts must be object lists')
    ids = [row.get('id') for row in disagreements]
    if any(not isinstance(value, str) or not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError('audio disagreements need unique stable IDs')
    def receipt_bound(receipt):
        return (type(receipt.get('version')) is int and receipt['version'] == 1
                and receipt.get('status') == 'accepted'
                and type(receipt.get('source_contract_version')) is int
                and receipt['source_contract_version'] == AUDIO_REVIEW_CONTRACT_VERSION
                and receipt.get('identity') == identity)
    def focused_bound(receipt):
        # Changed-source lineage is accepted only by the later reviewed delta
        # producer. This first planner slice reuses source-preserving decisions.
        return (receipt_bound(receipt) and receipt.get('before_identity') == identity
                and receipt.get('source_lineage') == [])
    pending = [row for row in disagreements if not any(
        focused_bound(receipt) and receipt.get('resolved_disagreement_id') == row['id']
        and receipt.get('disagreement_sha256') == digest(row) for receipt in receipts)]
    receipt = source_evidence.get('coverage_receipt')
    covered = bool(isinstance(receipt, dict) and receipt_bound(receipt)
        and receipt.get('scope') == 'whole_recording'
        and isinstance(source_evidence.get('audit_sha256'), str)
        and re.fullmatch(r'[0-9a-f]{64}', source_evidence['audit_sha256'])
        and receipt.get('audit_sha256') == source_evidence['audit_sha256']
        and receipt.get('unresolved_disagreements') == []
        and receipt.get('observed_start') is True and receipt.get('observed_end') is True)
    if 'audio' in flags and type(flags['audio']) is not bool:
        raise ValueError('audio flag must be a boolean')
    targets = set(); hypotheses_by_target = {}
    def locate(value):
        line_ids = value.get('line_ids', []); occurrence_ids = value.get('occurrence_ids', [])
        if (not isinstance(line_ids, list) or not isinstance(occurrence_ids, list)
                or any(not isinstance(lid, str) or lid not in lines for lid in line_ids)):
            raise ValueError('audio flag/disagreement uses unknown source line IDs')
        selected = {index for index, event in enumerate(sequence) if event['ref'] in line_ids}
        for value in occurrence_ids:
            if not isinstance(value, str) or not re.fullmatch(r'occ-[0-9]{3,}', value):
                raise ValueError('invalid audio occurrence locator')
            index = int(value[4:])
            if index >= len(sequence): raise ValueError('unknown audio occurrence locator')
            selected.add(index)
        return selected
    # Validate even already-resolved locators: malformed input is not silently
    # swallowed just because a receipt names its digest.
    for disagreement in disagreements: locate(disagreement)
    for disagreement in pending:
        selected = locate(disagreement)
        if not selected: raise ValueError('focused audio disagreement lacks an occurrence scope')
        targets.update(selected)
        for index in selected: hypotheses_by_target.setdefault(index, []).append(disagreement)
    flag_targets = locate(flags)
    flag_pending = flags.get('audio') is True
    if flag_pending:
        desired = flag_targets or set(range(len(sequence)))
        covered_flags = set()
        for receipt in receipts:
            if focused_bound(receipt) and receipt.get('flag_sha256') == digest(flags):
                values = receipt.get('target_occurrence_ids', [])
                if isinstance(values, list):
                    covered_flags.update(index for index in desired if f'occ-{index:03d}' in values)
        flag_targets = desired - covered_flags
        flag_pending = bool(flag_targets)
        targets.update(flag_targets)
    pending_source = bool(pending or flag_pending)
    whole_flag = flag_pending and not flags.get('line_ids') and not flags.get('occurrence_ids')
    needs_coverage = not covered and source_evidence.get('coverage_requested') is True
    mode = 'focused' if targets and not whole_flag else 'whole_recording' if whole_flag or needs_coverage else 'reuse'
    units = []
    if mode == 'whole_recording':
        indices = list(range(len(sequence)))
        units.append({'id': 'whole-recording', 'kind': 'coverage',
                      'target_occurrence_ids': [f'occ-{index:03d}' for index in indices],
                      'core_occurrence_indices': indices, 'context_occurrence_indices': indices,
                      'clip_start': 0.0, 'clip_end': float(duration_seconds),
                      'hypotheses': copy.deepcopy(pending),
                      'prior_evidence': [copy.deepcopy(item) for row in pending for item in row.get('evidence', [])],
                      'expanded_draft': draft})
    elif mode == 'focused':
        timings = source_evidence.get('routing_intervals', reader.get('SONG_TIMINGS'))
        if not isinstance(timings, list) or len(timings) != len(sequence):
            raise ValueError('focused audio routing lacks displayed intervals')
        groups = []
        for index in sorted(targets):
            context = set(range(max(0, index - 1), min(len(sequence), index + 2)))
            if groups and context.intersection(groups[-1]['context']):
                groups[-1]['targets'].add(index); groups[-1]['context'].update(context)
            else: groups.append({'targets': {index}, 'context': context})
        for group in groups:
            indices = sorted(group['context']); selected = sorted(group['targets'])
            for index in indices:
                interval = timings[index]
                if (not isinstance(interval, dict)
                        or any(not isinstance(interval.get(key), (int, float)) or isinstance(interval[key], bool)
                               or not math.isfinite(interval[key]) for key in ('start', 'end'))
                        or interval['start'] < 0 or interval['end'] < interval['start']
                        or (interval['end'] == interval['start'] and not (
                            source_evidence.get('routing_intervals_kind') == 'boundary-projected'
                            and interval['start'] in (0., duration_seconds)))
                        or interval['end'] > duration_seconds + .0005):
                    raise ValueError('invalid existing interval cannot route a focused audio clip')
            if any(timings[left]['end'] > timings[right]['start'] + .0005
                   for left, right in zip(indices, indices[1:])):
                raise ValueError('focused audio context intervals are not ordered and nonoverlapping')
            start = 0.0 if indices[0] == 0 else float(timings[indices[0]]['start'])
            end = float(duration_seconds) if indices[-1] == len(sequence) - 1 else float(timings[indices[-1]]['end'])
            if start >= end: raise ValueError('focused audio context has reversed routing bounds')
            hypotheses = [row for row in pending if any(row in hypotheses_by_target.get(index, []) for index in selected)]
            units.append({'id': 'focused-' + '-'.join(str(index) for index in selected), 'kind': 'focused-source',
                          'target_occurrence_ids': [f'occ-{index:03d}' for index in selected],
                          'core_occurrence_indices': selected, 'context_occurrence_indices': indices,
                          'clip_start': start, 'clip_end': min(end, float(duration_seconds)),
                          'hypotheses': copy.deepcopy(hypotheses),
                          'prior_evidence': [copy.deepcopy(item) for row in hypotheses for item in row.get('evidence', [])],
                          'expanded_draft': source_draft(reader, indices)})
    timing_pending = source_evidence.get('timing_required') is True
    remaining = ([] if covered else ['coverage']) + (['source'] if pending_source else []) + (['timing'] if timing_pending else [])
    return {'version': 1, 'identity': copy.deepcopy(identity),
            'coverage': {'status': 'accepted' if covered else 'pending', 'reason': 'bound-complete-audio-receipt' if covered else 'coverage-unverified'},
            'source': {'status': 'pending' if pending_source else 'accepted', 'reason': 'audio-discrepancy-pending' if pending_source else 'no-unresolved-discrepancy'},
            'timing': {'status': 'pending' if timing_pending else 'accepted'},
            'mode': mode, 'units': units, 'expanded_draft': draft, 'remaining_obligations': remaining}

# Observations retain audio evidence; only the later source-delta consumer may
# accept a mutation or establish whole-recording coverage.
SOURCE_OBSERVATION_VERSION = 1
SOURCE_ROUTING_VERSION = 1


def collect_source_evidence(song_dir, reader, *, flags, coverage_requested):
    import bhakti_pipeline as pipeline
    song_dir = Path(song_dir)
    if not isinstance(flags, dict) or type(coverage_requested) is not bool:
        raise ValueError('invalid source review selection')
    audio = pipeline.preferred_listener_audio(song_dir)
    duration = pipeline.gemini.duration_seconds(audio)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('invalid recording duration')
    trim = song_dir / '.transcription/trim-applied.json'
    artifacts = {}
    for name in ('01-transcript.json', '02-transcript-audit.json', '03-timing.json'):
        path = song_dir / '.transcription/pipeline' / name
        artifacts[name] = ({'path': str(path), 'sha256': file_hash(path)} if path.is_file() else None)
    # A current byte hash cannot retroactively certify historical API inputs.
    return {'identity': {'audio_sha256': file_hash(audio),
                         'trim_sha256': file_hash(trim) if trim.is_file() else None,
                         'reader_source_sha256': reader_source_identity(reader)},
            'audio_path': str(audio), 'duration_seconds': duration,
            'artifacts': artifacts, 'historical_audio_binding': 'unbound',
            'coverage_requested': coverage_requested, 'timing_required': True,
            'routing_intervals': copy.deepcopy(reader.get('SONG_TIMINGS', [])),
            'disagreements': [], 'flags': copy.deepcopy(flags)}


def materialize_source_units(plan, evidence, *, duration_seconds):
    if (plan.get('identity') != evidence.get('identity')
            or evidence.get('duration_seconds') != duration_seconds
            or not isinstance(duration_seconds, (int, float)) or isinstance(duration_seconds, bool)
            or not math.isfinite(duration_seconds) or duration_seconds <= 0):
        raise ValueError('source plan identity or duration mismatch')
    units = copy.deepcopy(plan.get('units', []))
    for index, unit in enumerate(units):
        if unit['clip_end'] - unit['clip_start'] > 900:
            raise ValueError('long audio requires independently bounded segment partition')
        unit['segment_index'] = index
        if unit['kind'] == 'coverage':
            unit['core_start'], unit['core_end'] = unit['clip_start'], unit['clip_end']
        else:
            indices = unit['core_occurrence_indices']
            intervals = evidence.get('routing_intervals', [])
            if not indices or any(type(i) is not int or not 0 <= i < len(intervals) for i in indices):
                raise ValueError('focused unit lacks exact core routing intervals')
            unit['core_start'] = intervals[min(indices)]['start']
            unit['core_end'] = min(intervals[max(indices)]['end'], duration_seconds)
            if (unit['core_start'] == unit['core_end']
                    and evidence.get('routing_intervals_kind') == 'boundary-projected'):
                # A wholly excluded edge has no remaining routing duration.
                # Ask within its bounded adjacent context; this creates neither
                # a retained onset nor authority to delete that occurrence.
                unit['core_start'], unit['core_end'] = unit['clip_start'], unit['clip_end']
    return units


def _observation_draft(draft):
    """Validate and project source-only fields; never leak public English."""
    if not isinstance(draft, dict):
        raise ValueError('source observation draft must be an object')
    lines, order = draft.get('lines'), draft.get('performance_order')
    if not isinstance(lines, list) or not lines or not isinstance(order, list) or not order:
        raise ValueError('source observation draft lacks ordered source')
    by_id = {}
    allowed = {'invocation', 'refrain', 'verse', 'bridge', 'closing', 'spoken', 'instrumental'}
    for row in lines:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'] or row['id'] in by_id:
            raise ValueError('source observation duplicate/invalid source ID')
        if (row.get('kind') not in allowed or any(not isinstance(row.get(k), str) for k in ('source_text','roman'))
                or (row['kind'] != 'instrumental' and any(not row[k].strip() for k in ('source_text','roman')))):
            raise ValueError('source observation invalid source text')
        by_id[row['id']] = {k: copy.deepcopy(row[k]) for k in ('id','source_text','roman','kind')}
        by_id[row['id']].update(language=str(row.get('language','')), partial='none', notes='')
    clean_order = []
    for row in order:
        if (not isinstance(row, dict) or row.get('line_id') not in by_id
                or type(row.get('occurrence')) is not int or row['occurrence'] < 1):
            raise ValueError('source observation invalid performed reference')
        clean_order.append({k: copy.deepcopy(row[k]) for k in ('line_id','occurrence','display_occurrence_id','repeat_index','kind') if k in row})
    if {row['line_id'] for row in clean_order} != set(by_id):
        raise ValueError('source observation contains unperformed definitions')
    return {'lines': list(by_id.values()), 'performance_order': clean_order, 'uncertainties': []}


def _observation_errors(unit, result):
    def issue(message): return {'kind': 'source_observation', 'detail': message}
    try:
        segments = result['segment_audits']
        if len(segments) != 1:
            return [issue('observation must retain exactly one raw segment')]
        packet = segments[0]['audit']['packet']
        rows, order = packet['lines'], packet['performance_order']
        if not isinstance(rows,list) or not rows or not isinstance(order,list) or not order:
            return [issue('empty source observation')]
        by_id = {}
        for row in rows:
            if (not isinstance(row,dict) or not isinstance(row.get('id'),str) or not row['id']
                    or row['id'] in by_id or row.get('kind') not in {'invocation','refrain','verse','bridge','closing','spoken','instrumental'}
                    or row.get('partial') not in {'none','leading','trailing'}
                    or any(not isinstance(row.get(k),str) for k in ('source_text','roman'))
                    or (row['kind'] != 'instrumental' and any(not row[k].strip() for k in ('source_text','roman')))):
                return [issue('invalid or duplicate observed source')]
            by_id[row['id']] = row
        if (any(not isinstance(row,dict) or row.get('line_id') not in by_id
                or type(row.get('occurrence')) is not int or row['occurrence'] < 1 for row in order)
                or {r['line_id'] for r in order} != set(by_id)):
            return [issue('invalid observed performance order')]
        uncertainties=packet.get('uncertainties')
        if not isinstance(uncertainties,list) or uncertainties:
            return [issue('source observation has unresolved uncertainty')]
        original = unit['expanded_draft']; old_by = {row['id']:row for row in original['lines']}
        key=lambda row: (row['source_text'],row['roman'],row['kind'])
        target_ids=set(unit['target_occurrence_ids'])
        targets={key(old_by[e['line_id']]) for e in original['performance_order'] if e['display_occurrence_id'] in target_ids}
        contexts=[key(old_by[e['line_id']]) for e in original['performance_order'] if e['display_occurrence_id'] not in target_ids]
        for i,event in enumerate(order):
            row=by_id[event['line_id']];partial=row['partial']
            if partial=='none':continue
            outside=(partial=='leading' and i==0 and unit['clip_start'] < unit['core_start']) or (partial=='trailing' and i==len(order)-1 and unit['core_end'] < unit['clip_end'])
            if not outside or key(row) in targets or contexts.count(key(row)) != 1:
                return [issue('partial target or ambiguous clipped context remains unresolved')]
        return []
    except (KeyError,TypeError,ValueError):
        return [issue('malformed raw source observation')]


def _source_observation_context(unit):
    """Source-only projections; preserve original raw files separately by hash."""
    hypotheses = unit.get('hypotheses', [])
    if not isinstance(hypotheses, list):
        raise ValueError('invalid source hypotheses')
    projected = []
    source_fields = ('source_text','roman','language','kind','partial','notes')
    for item in hypotheses:
        if not isinstance(item,dict) or not isinstance(item.get('alternatives',[]),list):
            raise ValueError('invalid source hypothesis alternatives')
        alternatives=[]
        for value in item.get('alternatives',[]):
            if isinstance(value,str):alternatives.append(value)
            elif isinstance(value,dict):alternatives.append({k:copy.deepcopy(value[k]) for k in source_fields if k in value})
            else:raise ValueError('invalid source hypothesis')
        projected.append({**{k:copy.deepcopy(item[k]) for k in ('id','reason') if k in item},'alternatives':alternatives})
    prior=[]
    for item in unit.get('prior_evidence',[]):
        value=json.loads(Path(item['path']).read_text())
        packet=value.get('packet',value) if isinstance(value,dict) else None
        if not isinstance(packet,dict):raise ValueError('unsupported prior source packet')
        lines=packet.get('lines');order=packet.get('performance_order');uncertainties=packet.get('uncertainties')
        if not isinstance(lines,list) or not lines or not isinstance(order,list) or not order or not isinstance(uncertainties,list):
            raise ValueError('unsupported prior source packet shape')
        definitions=[];ids=set()
        for row in lines:
            if (not isinstance(row,dict) or not isinstance(row.get('id'),str) or not row['id'] or row['id'] in ids
                    or any(not isinstance(row.get(k),str) for k in ('source_text','roman'))):
                raise ValueError('invalid prior source definition')
            ids.add(row['id']);definitions.append({k:copy.deepcopy(row[k]) for k in ('id',*source_fields) if k in row})
        if any(not isinstance(row,dict) or row.get('line_id') not in ids for row in order):
            raise ValueError('invalid prior source order')
        prior.append({'sha256':item['sha256'],'lines':definitions,
                      'performance_order':[{k:copy.deepcopy(row[k]) for k in ('line_id','occurrence') if k in row} for row in order],
                      'uncertainties':copy.deepcopy(uncertainties)})
    return {'hypotheses':projected,'prior_source_observations':prior}


def _prepare_audio_observations(*, song_dir, units, audio, source_identity, deadline_at):
    import re
    import bhakti_pipeline as pipeline
    song_dir, audio = Path(song_dir), Path(audio)
    if not math.isfinite(deadline_at) or deadline_at <= time.time():
        raise ValueError('source observation deadline exhausted')
    if (not isinstance(source_identity,dict) or source_identity.get('audio_sha256') != file_hash(audio)
            or source_identity.get('trim_sha256') is not None and not re.fullmatch('[0-9a-f]{64}',str(source_identity['trim_sha256']))):
        raise ValueError('source observation native audio identity mismatch')
    trim = song_dir / '.transcription/trim-applied.json'
    if source_identity.get('trim_sha256') != (file_hash(trim) if trim.is_file() else None):
        raise ValueError('source observation trim identity mismatch')
    duration=pipeline.gemini.duration_seconds(audio)
    if not math.isfinite(duration) or duration <= 0 or not isinstance(units,list):
        raise ValueError('invalid observation recording/units')
    prepared=[]; seen=set()
    for unit in units:
        if not isinstance(unit,dict) or not isinstance(unit.get('id'),str) or not unit['id'] or unit['id'] in seen:
            raise ValueError('duplicate/invalid source observation unit')
        seen.add(unit['id'])
        if any(not isinstance(unit.get(k),(int,float)) or isinstance(unit[k],bool) or not math.isfinite(unit[k]) for k in ('clip_start','clip_end','core_start','core_end')):
            raise ValueError('invalid source observation bounds')
        if not 0 <= unit['clip_start'] <= unit['core_start'] < unit['core_end'] <= unit['clip_end'] <= duration:
            raise ValueError('source observation bounds outside recording/core')
        if unit['clip_end']-unit['clip_start'] > 900:
            raise ValueError('long audio requires segment partition')
        if type(unit.get('segment_index')) is not int or unit['segment_index'] < 0:
            raise ValueError('invalid source segment index')
        draft=_observation_draft(unit.get('expanded_draft'))
        targets=unit.get('target_occurrence_ids')
        if (not isinstance(targets,list) or not targets or any(not isinstance(v,str) for v in targets)
                or len(set(targets))!=len(targets)
                or not set(targets).issubset({e.get('display_occurrence_id') for e in draft['performance_order']})):
            raise ValueError('unknown or duplicate source target lineage')
        for event in draft['performance_order']:
            if (not isinstance(event.get('display_occurrence_id'),str) or not re.fullmatch(r'occ-[0-9]{3,}',event['display_occurrence_id'])
                    or type(event.get('repeat_index')) is not int or event['repeat_index'] < 0):
                raise ValueError('invalid source occurrence lineage')
        evidence=unit.get('prior_evidence',[])
        if not isinstance(evidence,list):raise ValueError('invalid prior source evidence')
        for item in evidence:
            if not isinstance(item,dict) or not isinstance(item.get('path'),str) or file_hash(item['path']) != item.get('sha256'):
                raise ValueError('prior source evidence identity mismatch')
        prepared.append((copy.deepcopy(unit),draft,_source_observation_context(unit)))
    # The actual witness used by the pipeline must participate in cache identity.
    witness_record=pipeline.source_witness.record_for_slug(song_dir.name)
    witness_path=pipeline.source_witness.cache_path(song_dir)
    if witness_record and not witness_path.is_file():
        raise ValueError('registered source witness must be acquired and bound before observation dispatch')
    witness_snapshot=None
    if witness_record:
        witness_snapshot=json.loads(witness_path.read_text())
        if (not isinstance(witness_snapshot,dict) or type(witness_snapshot.get('schema_version')) is not int
                or witness_snapshot['schema_version'] != 1 or witness_snapshot.get('work') != song_dir.name
                or witness_snapshot.get('witness') != witness_record or not isinstance(witness_snapshot.get('lines'),list)
                or not witness_snapshot['lines'] or any(not isinstance(row,dict)
                    or not isinstance(row.get('text'),str) or not row['text'].strip() or 'page' not in row
                    for row in witness_snapshot['lines'])):
            raise ValueError('registered source witness snapshot is empty, malformed, or mismatched')
    contracts = []
    for unit, draft, source_context in prepared:
        segment = {'index':unit['segment_index'], **{k:unit[k] for k in
            ('clip_start','clip_end','core_start','core_end')}}
        request = pipeline.audio_audit_request_contract(draft, segment,
            witness=witness_snapshot, source_context=source_context)
        contracts.append((unit, draft, source_context, request))
    return contracts, duration, {'record':witness_record,'snapshot':witness_snapshot}


def review_audio_units(*, song_dir, units, audio, source_identity, options, route_dir, deadline_at,
                       expected_orders=None):
    import bhakti_pipeline as pipeline
    import bhakti_library_pass as library
    import bhakti_model_routes as routes
    song_dir, audio = Path(song_dir), Path(audio)
    prepared, duration, witness = _prepare_audio_observations(song_dir=song_dir, units=units,
        audio=audio, source_identity=source_identity, deadline_at=deadline_at)
    witness_snapshot = witness['snapshot']
    import bhakti_source_cache_compat as compatibility
    legacy_history = (compatibility.index_history(route_dir, song_dir.name,
        ledger_paths=getattr(options,'source_legacy_ledgers',())) if expected_orders is None else None)
    observed=[];issues=[]
    for unit,draft,source_context,request in prepared:
        # The exact stage-owned request, not unrelated module bytes, owns reuse.
        dependency_input={'version':SOURCE_OBSERVATION_VERSION,'request':request,'witness':witness}
        if expected_orders is not None:
            if unit['id'] not in expected_orders:
                raise ValueError('confirmation lacks exact expected local source/order')
            dependency_input['confirmation_expected_order']=expected_orders[unit['id']]
        dependency=digest(dependency_input)
        fingerprint=digest({'unit':unit,'draft':draft,'source_identity':source_identity,'duration':duration,'dependency':dependency})
        def execute(context):
            local=library.route_options(options,context);local.source_witness_audit=False
            attempt_song=context.attempt_dir/'songs'/song_dir.name
            segment={'index':unit['segment_index'],**{k:unit[k] for k in ('clip_start','clip_end','core_start','core_end')}}
            raw={'packet':{'segmented':True,'source_first_witness':False,'segments':[{'segment':segment,'transcript':draft}]}}
            return pipeline.audit_long_transcript(attempt_song,raw,audio,local,
                observation_context={'witness':witness_snapshot,'source_context':source_context})
        def validate(result):
            errors = _observation_errors(unit,result)
            if not errors and expected_orders is not None:
                packet = result['segment_audits'][0]['audit']['packet']
                by_id = {row['id']:row for row in packet['lines']}
                actual = [list(_source_key(by_id[event['line_id']])) for event in packet['performance_order']]
                if actual != expected_orders[unit['id']]:
                    errors.append({'kind':'source_confirmation_disagreement',
                                   'detail':'Independent audio confirmation differs from the complete proposed local source/order'})
            return errors
        try:
            reused = None if expected_orders is not None else compatibility.lookup(history=legacy_history,
                unit_id=song_dir.name+':source-observation:'+unit['id'],unit=unit,draft=draft,
                source_context=source_context,source_identity=source_identity,duration=duration,
                request=request,witness=witness,audio=audio,route_dir=route_dir,
                base_model=options.model,pro_model=options.pro_model,
                current_fingerprint=fingerprint,current_dependency=dependency,
                ledger_paths=getattr(options,'source_legacy_ledgers',()))
            if reused is not None:
                if _observation_errors(unit,reused['result']):
                    raise compatibility.LegacyHold('legacy observation no longer validates')
                observed.append({'unit':unit,**reused})
                continue
            result=routes.run_unit(route_dir,song_dir.name+':source-observation:'+unit['id'],fingerprint,execute,
                                  validate,deadline_at=deadline_at,
                                  dependency_fingerprint=dependency,base_model=options.model,pro_model=options.pro_model)
            errors=validate(result)
            if errors:raise routes.RunFatal('cached source observation no longer validates')
            state_path = routes.unit_state_path(route_dir, song_dir.name+':source-observation:'+unit['id'],
                fingerprint, dependency_fingerprint=dependency, base_model=options.model, pro_model=options.pro_model)
            observed.append({'unit':unit,'result':result,'input_fingerprint':fingerprint,
                             'route_state_path':str(state_path)})
        except routes.UnitUnresolved as exc:
            issues.append({'unit_id':unit['id'],'reason':exc.reason,'issues':exc.issues,'state_path':str(exc.state_path)})
    return {'status':'unresolved' if issues else 'observed','unit_results':observed,'issues':issues}


def partition_source_plan(reader, plan, evidence, *, segments):
    """Partition routing hypotheses; no core boundary certifies a sung onset."""
    duration = evidence.get('duration_seconds')
    if (plan.get('identity') != evidence.get('identity')
            or evidence['identity'].get('reader_source_sha256') != reader_source_identity(reader)
            or type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0):
        raise ValueError('source partition identity/duration mismatch')
    if not isinstance(segments, list) or not segments:
        raise ValueError('source partition requires acoustic cores')
    previous = 0.0
    for i, segment in enumerate(segments):
        if (not isinstance(segment, dict) or type(segment.get('index')) is not int or segment['index'] != i
                or any(type(segment.get(k)) not in (int, float) or not math.isfinite(segment[k])
                       for k in ('core_start','core_end','clip_start','clip_end'))
                or not 0 <= segment['clip_start'] <= segment['core_start'] < segment['core_end'] <= segment['clip_end'] <= duration
                or abs(segment['core_start'] - previous) > .0005):
            raise ValueError('source partition has invalid, overlapping or gapped core bounds')
        previous = segment['core_end']
    if abs(previous - duration) > .0005:
        raise ValueError('source partition omits recording end')
    intervals = reader.get('SONG_TIMINGS')
    sequence = reader['SONG_SEQUENCE']
    if (not isinstance(intervals, list) or len(intervals) != len(sequence)
            or intervals != evidence.get('routing_intervals')):
        raise ValueError('bounded transcription needed: missing exact source routing intervals')
    for i, interval in enumerate(intervals):
        if (not isinstance(interval, dict)
                or any(type(interval.get(k)) not in (int,float) or not math.isfinite(interval[k]) for k in ('start','end'))
                or not 0 <= interval['start'] < interval['end'] <= duration
                or i and intervals[i-1]['end'] > interval['start'] + .0005):
            raise ValueError('bounded transcription needed: invalid source routing intervals')
    # A short selected unit can remain intact; long units follow validated acoustic
    # cores. Every selected display occurrence owns its whole contiguous repeat group.
    units = []
    for parent in plan.get('units', []):
        if parent['clip_end'] - parent['clip_start'] <= 900:
            single = {**copy.deepcopy(plan), 'units': [parent]}
            units.extend(materialize_source_units(single, evidence, duration_seconds=duration))
            continue
        targets = set(parent['core_occurrence_indices'])
        covered = []
        for segment in segments:
            if segment['core_end'] <= parent['clip_start'] or segment['core_start'] >= parent['clip_end']:
                continue
            core_start = max(segment['core_start'], parent['clip_start'])
            core_end = min(segment['core_end'], parent['clip_end'])
            selected = [i for i in sorted(targets) if core_start <= intervals[i]['start'] < core_end]
            if not selected:
                raise ValueError('bounded transcription needed: empty source core has no target draft')
            start = max(parent['clip_start'], segment['clip_start'])
            end = min(parent['clip_end'], segment['clip_end'])
            start = min(start, *(intervals[i]['start'] for i in selected))
            end = max(end, *(intervals[i]['end'] for i in selected))
            if end-start > 900:
                raise ValueError('bounded transcription needed: target repeat group exceeds 900-second clip')
            context = {i for i,t in enumerate(intervals) if t['start'] < end and t['end'] > start}
            for i in selected:
                context.update(range(max(0,i-1),min(len(sequence),i+2)))
            unit = copy.deepcopy(parent)
            unit.update(id=parent['id']+'-segment-'+str(segment['index']),
                segment_index=len(units), clip_start=start, clip_end=end,
                core_start=core_start, core_end=core_end,
                target_occurrence_ids=[f'occ-{i:03d}' for i in selected],
                core_occurrence_indices=selected,context_occurrence_indices=sorted(context),
                expanded_draft=source_draft(reader,sorted(context)))
            units.append(unit);covered.extend(selected)
        if sorted(covered) != sorted(targets) or len(covered) != len(set(covered)):
            raise ValueError('source partition lost or duplicated a target occurrence')
    for index,unit in enumerate(units):unit['segment_index']=index
    return units


def observe_source_candidate(*, reader, song_dir, original_song, audio, route_dir, options, deadline_at):
    """Connect explicit library requests to retained, nonpublishable observations."""
    import bhakti_pipeline as pipeline
    song_dir, original_song, route_dir = Path(song_dir), Path(original_song), Path(route_dir)
    requested = set(getattr(options, 'source_requested_stages', []) or [])
    flags = copy.deepcopy(getattr(options, 'source_review_flags', {}))
    if not isinstance(flags, dict):raise ValueError('source review flags must be an object')
    coverage = getattr(options, 'source_coverage_requested', False)
    if type(coverage) is not bool:raise ValueError('source coverage selection must be boolean')
    if 'audio' in flags and type(flags['audio']) is not bool:
        raise ValueError('audio flag must be a boolean')
    if requested.intersection({'audio-review','focused-audio-review'}):
        # The stage may be scheduled by an independent saved uncertainty even
        # when no user audio flag is set. It must never become empty observation.
        flags['audio'] = True
    if 'focused-audio-review' in requested and not (flags.get('line_ids') or flags.get('occurrence_ids')):
        raise ValueError('focused source review requires explicit line or occurrence locators')
    original_evidence = collect_source_evidence(original_song, reader, flags=flags, coverage_requested=coverage)
    evidence = collect_source_evidence(song_dir, reader, flags=flags, coverage_requested=coverage)
    transform_declaration=getattr(options,'source_audio_transform',None)
    if transform_declaration is not None:
        from bhakti_boundary_adoption import checked_audio_transform, staged_source_evidence
        transform=checked_audio_transform(transform_declaration,original_song,song_dir,reader)
        evidence=staged_source_evidence(transform,original_song,song_dir,reader,flags,coverage)
    elif original_evidence['identity'] != evidence['identity']:
        raise ValueError('workspace source/trim/audio identity differs from original')
    # Historical packets are evidence, not an acceptance prerequisite. Freeze their
    # original hashes, while dispatching only the verified private native recording.
    if transform_declaration is None:
        evidence['artifacts'] = original_evidence['artifacts']
    evidence['disagreements'] = copy.deepcopy(flags.get('disagreements', []))
    plan = plan_audio_review(reader, source_evidence=evidence, flags=flags,
                             duration_seconds=evidence['duration_seconds'])
    routing_identity = digest({'version':SOURCE_ROUTING_VERSION,'source':evidence['identity'],
        **({'audio_transform':transform_declaration} if transform_declaration is not None else {}),
        'duration':evidence['duration_seconds'],'intervals':evidence['routing_intervals'],
        'flags':flags,'coverage_requested':coverage,
        'artifacts':{name:value['sha256'] if value else None for name,value in evidence['artifacts'].items()}})
    directory = route_dir/'source-observations'/routing_identity
    plan_path = directory/'routing-plan.json'
    stored_plan = json.loads(plan_path.read_text()) if plan_path.is_file() else None
    if stored_plan is not None:
        if (not isinstance(stored_plan,dict) or stored_plan.get('input_fingerprint') != routing_identity
                or stored_plan.get('digest') != digest(stored_plan.get('units'))):
            raise ValueError('source routing plan identity/digest changed')
        units = stored_plan['units']
        # Compare deterministic partition output as well as its self hash. The
        # original acoustic segments are retained; resume never rescans audio.
        if 'segments' in stored_plan:
            expected = partition_source_plan(reader,plan,evidence,segments=stored_plan['segments'])
        else:
            expected = materialize_source_units(plan,evidence,duration_seconds=evidence['duration_seconds'])
        if units != expected:raise ValueError('source routing plan differs from bound source')
    else:
        segments = None
        if any(u['clip_end']-u['clip_start']>900 for u in plan['units']):
            segments = pipeline.adaptive_audio_segments(audio)
            units = partition_source_plan(reader,plan,evidence,segments=segments)
        else:
            units = materialize_source_units(plan,evidence,duration_seconds=evidence['duration_seconds'])
        record = {'input_fingerprint':routing_identity,'units':units,'digest':digest(units)}
        if segments is not None:record['segments']=segments
        atomic_json(plan_path,record)
    if not units:
        raise ValueError('explicit source observation request has no audio units')
    prepared, duration, witness = _prepare_audio_observations(song_dir=song_dir, units=units,
        audio=audio, source_identity=evidence['identity'], deadline_at=deadline_at)
    identity = digest({'routing_identity':routing_identity,'version':SOURCE_OBSERVATION_VERSION,
        'requests':[{'unit':unit,'request':request} for unit,_,_,request in prepared],
        'witness':witness,'models':{'base':options.model,'pro':options.pro_model}})
    receipt_path = directory/identity/(song_dir.name+'-source-observed.json')
    saved = json.loads(receipt_path.read_text()) if receipt_path.is_file() else None
    if saved is not None and (not isinstance(saved,dict) or saved.get('version') != 1
            or saved.get('input_fingerprint') != identity or saved.get('result_digest') != digest(saved.get('result'))):
        raise ValueError('source observation receipt identity/digest changed')
    # Always enter the existing router to verify all candidate digests. Successful
    # units return before FFmpeg/provider; a receipt is never a substitute for them.
    if saved is not None:
        prior = saved['result']
        paths = [item.get('route_state_path') for item in prior.get('unit_results', [])]
        paths.extend(item.get('state_path') for item in prior.get('issues', []))
        if len(paths) != len(units) or any(not isinstance(value,str)
                or not Path(value).resolve().is_relative_to(route_dir.resolve())
                or not Path(value).is_file() for value in paths):
            raise ValueError('source observation receipt lacks its durable route history')
    observed = review_audio_units(song_dir=song_dir,units=units,audio=audio,
        source_identity=evidence['identity'],options=options,route_dir=route_dir,deadline_at=deadline_at)
    result = {**observed,'input_fingerprint':identity,'units':units,
              'remaining_obligations':['source-adjudication','coverage','timing']}
    if saved is not None and saved['result'] != result:
        raise ValueError('source observation receipt no longer matches routed evidence')
    if saved is None:
        atomic_json(receipt_path,{'version':1,'input_fingerprint':identity,'result':result,'result_digest':digest(result),
            'code_provenance':{'adapter_sha256':file_hash(__file__),'pipeline_sha256':file_hash(pipeline.__file__)}})
    return {'status':'unresolved','reader':reader,'source_changed':False,'publicationEligible':False,
        'evidence':{'audio_review':{**result,'receipt_path':str(receipt_path)}},
        'issues':[{'kind':'source_observation_only',
                   'detail':'Audio observations retained; source adjudication, coverage acceptance and exact timing remain required.'}]}
