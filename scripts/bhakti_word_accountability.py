"""Source-bound accounting for English words; coverage is not linguistic proof."""
import copy
import re
import unicodedata
from bhakti_translation_policy import word_tokens

VERSION = 1
BASES = {'lexical', 'grammar', 'context'}


def identity():
    return {'english_word_accountability': VERSION}


def english_units(text):
    """Exact offsets; internal apostrophes stay, hyphenated parts are separate."""
    units = []
    i = 0
    def word(char):
        return unicodedata.category(char)[0] in 'LMN'
    while i < len(text):
        if not word(text[i]):
            i += 1
            continue
        start = i
        i += 1
        while i < len(text):
            if word(text[i]):
                i += 1
            elif text[i] in "'’" and i + 1 < len(text) and word(text[i + 1]):
                i += 1
            else:
                break
        units.append({'unit': len(units), 'text': text[start:i], 'start': start, 'end': i})
    return units


def schema(*, review=False):
    string = {'type': 'string'}
    reference = {'type': 'object', 'properties': {
        'line_id': string, 'domain': {'type': 'string', 'enum': ['word_glosses']},
        'word_indices': {'type': 'array', 'items': {'type': 'integer'}}, 'source_quote': string},
        'required': ['line_id', 'domain', 'word_indices', 'source_quote'], 'additionalProperties': False}
    fields = {'unit': {'type': 'integer'},
              'bases': {'type': 'array', 'items': {'type': 'string', 'enum': sorted(BASES)}},
              'references': {'type': 'array', 'items': reference}, 'reason': string}
    if review:
        fields['status'] = {'type': 'string', 'enum': ['supported', 'defect', 'unresolved']}
    return {'type': 'array', 'items': {'type': 'object', 'properties': fields,
        'required': list(fields), 'additionalProperties': False}}


def source_rows(lines, context=()):
    """Collect native definitions, without requiring or inventing neighbor glosses."""
    rows = {}
    def add(row):
        if not isinstance(row, dict):
            return
        if 'source' in row:
            add(row['source'])
            return
        if isinstance(row.get('id'), str) and row.get('source_text') and row.get('roman'):
            prior = rows.get(row['id'])
            if prior and (any(prior.get(key) != row.get(key) for key in ('source_text', 'roman'))
                    or any(key in prior and key in row and prior[key] != row[key]
                           for key in ('lexical_tokens', 'sourceWords'))):
                raise ValueError('accountability source definition conflicts: ' + row['id'])
            # Slim occurrence references cannot erase canonical token boundaries.
            rows[row['id']] = {**(prior or {}), **row}
        for window in row.get('performed_context', []):
            for side in ('before', 'after'):
                for neighbor in window.get(side, []):
                    # Neighbor context is not recursively interpreted as new order.
                    if isinstance(neighbor, dict):
                        add({key: value for key, value in neighbor.items() if key != 'performed_context'})
    for row in list(lines) + list(context or ()):
        add(row)
    return rows


def _reference_errors(ref, sources):
    if not isinstance(ref, dict):
        return ['word accounting reference must be an object']
    source = sources.get(ref.get('line_id'))
    indices = ref.get('word_indices')
    quote = ref.get('source_quote')
    if (source is None or ref.get('domain') != 'word_glosses'
            or not isinstance(indices, list) or not indices
            or any(type(i) is not int or not 0 <= i < len(word_tokens(source)) for i in indices)
            or len(set(indices)) != len(indices)
            or not isinstance(quote, str) or not quote.strip() or quote not in source['source_text']):
        return ['word accounting reference or native quotation is invalid']
    mapped = source.get('sourceWords')
    if isinstance(mapped, list) and mapped:
        # Bind whole mapped occurrences, not lexical substrings: राम inside
        # आराम cannot warrant the separately indexed राम occurrence.
        native = source['source_text']
        spans = [match for match in re.finditer(r'\S+', native)
                 if any(char.isalnum() for char in match.group())]
        if len(spans) != len(mapped) or any(not isinstance(item, dict) or
                item.get('text') != span.group() for item, span in zip(mapped, spans)):
            return ['word accounting native map differs from source occurrences']
        quote_starts = [match.start() for match in re.finditer('(?=' + re.escape(quote) + ')', native)]
        covered = set()
        for quote_start in quote_starts:
            occurrence = set()
            for item, span in zip(mapped, spans):
                start, end = span.span()
                while start < end and unicodedata.category(native[start])[0] not in 'LMN': start += 1
                while end > start and unicodedata.category(native[end - 1])[0] not in 'LMN': end -= 1
                if quote_start <= start and end <= quote_start + len(quote):
                    occurrence.update(item.get('wordIndices', []))
            if set(indices) <= occurrence:
                covered = occurrence
                break
        if not set(indices) <= covered:
            return ['word accounting quotation does not cover its source indices']
    return []


def _segment_links(row, units, render):
    """Use the existing renderer's spacing rules to locate each segment."""
    parts = row.get('segments', [])
    spans = []
    previous = 0
    for index, part in enumerate(parts):
        if not isinstance(part, dict):
            return {}
        end = len(render([{**p, 'word_indices': []} for p in parts[:index + 1]], ''))
        spans.append((previous, end, part.get('word_indices', [])))
        previous = end
    return {unit['unit']: {i for start, end, indices in spans
        if start < unit['end'] and end > unit['start'] for i in indices if type(i) is int}
        for unit in units}


def record_errors(row, sources, *, review=False, render=None):
    units = english_units(str(row.get('literal_english', '')))
    evidence = row.get('independent_review', {}) if review else row
    if not isinstance(evidence, dict):
        return ['word accounting requires a review object']
    records = evidence.get('word_judgments' if review else 'word_support')
    label = 'independent word judgments' if review else 'writer word support'
    if (not isinstance(records, list) or any(not isinstance(r, dict) for r in records)
            or [r.get('unit') for r in records] != list(range(len(units)))
            or any(type(r.get('unit')) is not int for r in records)):
        return [row.get('id', '?') + ': ' + label + ' must cover every English unit exactly once in order']
    errors = []
    links = _segment_links(row, units, render) if not review and render else {}
    for record in records:
        bases = record.get('bases')
        if (not isinstance(bases, list) or not bases or any(not isinstance(b, str) or b not in BASES for b in bases)
                or len(bases) != len(set(bases))):
            errors.append(label + ' has invalid bases')
        if not isinstance(record.get('reason'), str) or not record['reason'].strip():
            errors.append(label + ' needs an explicit source warrant')
        refs = record.get('references')
        if not isinstance(refs, list) or not refs:
            errors.append(label + ' needs native references')
            continue
        for ref in refs:
            ref_errors = _reference_errors(ref, sources)
            errors += ref_errors
            if (not ref_errors and not review and 'lexical' in (bases or [])
                    and ref['line_id'] == row['id'] and render
                    and not set(ref['word_indices']) <= links.get(record['unit'], set())):
                errors.append('lexical word support disagrees with its displayed source links')
        if review:
            status = record.get('status')
            if status not in {'supported', 'defect', 'unresolved'}:
                errors.append('invalid independent word judgment status')
                continue
            if status == 'supported':
                continue
            kinds = {'english_realization', 'english_mapping'} if status == 'defect' else {'unresolved_evidence'}
            def matches(issue):
                if not isinstance(issue, dict) or issue.get('kind') not in kinds or row['id'] not in issue.get('target_line_ids', []):
                    return False
                return any(isinstance(a, dict) and isinstance(b, dict) and a.get('line_id') == b.get('line_id')
                    and set(a.get('word_indices', [])) & set(b.get('word_indices', []))
                    for a in refs for b in issue.get('references', []))
            if not any(matches(issue) for issue in evidence.get('issues', [])):
                errors.append('independent word ' + status + ' lacks a matching typed issue on its source span')
            component = evidence.get('component_judgments', {}).get('english', {})
            aggregate = 'unresolved' if any(r.get('status') == 'unresolved' for r in records) else 'defect'
            if component.get('status') != aggregate:
                errors.append('independent word judgment disagrees with English component')
            if evidence.get('passes') is not False:
                errors.append('unsupported English word cannot receive a passing review')
            if status == 'unresolved' and evidence.get('human_review_recommended') is not True:
                errors.append('unresolved English word needs consequential evidence hold')
    return errors


def writer_errors(lines, rows, render, context=()):
    sources = source_rows(lines, context)
    return [error for row in rows for error in record_errors(row, sources, render=render)]


def review_projection(row):
    row = copy.deepcopy(row)
    draft = row.get('draft')
    if isinstance(draft, dict):
        draft.pop('word_support', None)
        # A previous review is not this reviewer's independent reasoning either.
        draft.pop('independent_review', None)
        row['english_units'] = english_units(str(draft.get('literal_english', '')))
    return row


GUIDANCE = '''Account for EVERY English unit, including repeated occurrences. Units are maximal Unicode
letter/mark/number runs with internal straight or curly apostrophes; hyphens separate components.
Use their zero-based order, not source token order. Punctuation is not a unit. In a possessive
or contraction, account for the entire ownership, tense/copula or negation contribution; a
"grammar" label never exempts fused semantic content. Keep proper names and every supported
compound contribution; do not force equal source/English word counts.
For each content unit apply the omission test: what specific source meaning or grammar would
be lost if it were removed? Plausible theology, rhetorical emphasis and associations are not
literal support. Distinguish lexical meaning, necessary English grammar, and contextual
interpretation in bases (lexical/grammar/context; more than one when needed). Cite the narrowest
relevant native reference with line_id, domain word_glosses, exact word_indices and source_quote,
not an entire line as a universal warrant. Necessary articles/copulas/recoverable pronouns may
use grammar with the native clause or inflection establishing the need. Native-only neighbors
remain valid source context even without a generated gloss; never invent their English.
Test attachment, degree, exclusivity, authenticity, negation, modality and agency separately.
"Old teacher's house" does not license "old house". Keep a modifier where its own source
word or compound expresses it; do not infer authenticity or exclusivity from associations.
Context can select an attested sense or resolve syntax, not add associated propositions.
Generated frames are claims, not authority; English dictionary definitions cannot establish a
source-language sense. Do not replace a valid synonym simply because another is preferred.
'''

WRITER_GUIDANCE = GUIDANCE + '''Return word_support with one ordered {unit,bases,references,reason} record
per English unit. Give a concise specific source warrant. For lexical bases, your local native
indices must agree with the display segments containing that unit. Check primary popups and
frame claims against native evidence; report a conflict for targeted glossary repair instead of
silently writing contradictory English. Preserve locked owner English exactly; a source
conflict is a separately reported hold, not permission to rewrite it.
'''

REVIEW_GUIDANCE = GUIDANCE + '''Use the supplied deterministic english_units. Independently derive your
own word_judgments, one {unit,status,bases,references,reason} per unit, without writer rationales.
For every added qualifier in popup/frame claims also test its native warrant, even when absent
from final English. A supported label requires an actual source/grammar warrant, not generic
'context' or agreement with generated analysis. A defect needs an english_realization or
english_mapping issue on that source span. If ANY unit has consequential unresolved meaning,
return its unresolved_evidence issue, English component unresolved and a human hold, retaining
separate repairable unit defects/issues. Otherwise a defect requires English component defect. A source
omission may need an issue even though no corresponding English unit exists. Ordinary repairable
defects are not unresolved choices. Resolve writer reservations independently: do not create
uncertainty merely because the writer hesitated, or approve an addition to agree with it.
'''
