# Translation, reference tags and search repair — 23 November 2026

This work reopens the library after the owner's concrete reports about Prabh Jū,
missing divine forms and misleading English. Historical `finished` marks do not
override a demonstrated defect. The active checklist is in
[`LIBRARY_REPAIR_TASKS.md`](../LIBRARY_REPAIR_TASKS.md).

## What failed

The requirements already asked for source-constrained, intelligible English and
literal word meanings. The failures are not adequately explained by unclear
documentation. Review execution and completion reporting fell short of those
requirements:

- `song.py release` could create a finished translation entry or move its file
  hash without doing a translation review. Release mechanics now leave that
  ledger alone.
- Deity detection depended on exact aliases. The common spelling conversion of
  Kṛṣṇa produced `krshna`, while the tag alias expected `krishna`. Regional forms,
  compounds, epithets and narrative relationships also escaped those lists.
- The newer song compiler did not apply the reviewed subject override registry
  used by the older pipeline. Both now consume the same decisions.
- Subject decisions inconsistently meant either the main addressee or every
  evidenced reference. The maintained rule now explicitly includes named forms
  and established relationships, including within Gurbāṇī, while rejecting names
  that exist only in commentary or artist credits.
- Public search covered metadata, not performed lyrics or word meanings. It now
  loads a release-bound lyric index on the first nonempty search, keeps title/name
  matches first, and supports source script, ordinary roman spellings and English.
  A conservative fallback also matches phonetic spellings and small typing errors.
  It uses local cached tokens, with no provider calls or added index payload.
- Structural validity, semantic shuffle classification and translation accuracy
  were conflated. Passing code checks or a model's thematic classification does
  not certify a sentence's grammar, agency or divine identity.

## Evidence and limits

The current population is 386 readers. The complete English was read in song
context, with targeted source, word-map and prior-research investigation. Proposed
changes receive a separate integration reading; plausible but unsupported rewrites
are rejected or kept open. This is not a new transcription of all recordings or an
independent reconstruction of every inherited word analysis.

The selected repairs change 261 English definitions, 217 word maps and 267 language
labels across 80 readers (526 distinct definitions; categories overlap). Public tags
gain 351 entries across 158 readers, including declared umbrella tags. The separate
registry has 294 reviewed witnesses across 159 records; those are different counts.
Source scripts, Roman text, performance order, timestamps and audio are preserved.
The ledger now distinguishes 361 screened readers, 23 readers with 33 open source
questions, and two owner-protected readers. No new blanket `finished` marks were made.

Source and literal strangeness are preserved when supported. Prabh Jū's
`nirbikh narak nivārī` now reads “without poison, who wards off hell!” The wording
removes the misleading attachment without erasing poison or hell. Its air-eating
and fever-free epithets remain. Comparison witnesses include the
[SGGS Academy Shabad Hazare commentary](https://sikhibookclub.com/wp-content/uploads/2020/01/click-here-to-download-shabad-hazare-sggs-academy.pdf)
and the [Dasam Granth text](https://sikhsamridhi.com/en/literature/dasam-granth/710).

Tag additions have exact performed source witnesses in
`data/song_tag_overrides.json`. Rejected keyword leads have concrete contextual
reasons in `data/subject-tag-review.json`; their hashes include performed meaning,
so changed English or glosses require reinspection. The detector is a finite lead
list and cannot certify that all divine references have been understood.

Translation amendments preserve the original model assessment and audio evidence.
The separate source-review receipt records exact before/after definitions and a
disposition for each original semantic feature. Unsupported features can only be
reduced. Binding hashes establish which text was reviewed, not whether a reviewer's
judgment is correct. Private receipts are excluded from public assembly.

## Release verification before publication

The release runner executed 45 commands: 44 passed, with the historical trim audit
the only failure. All 386 readers pass structural contracts. Automated player tests
cover 15,320 occurrence buttons through both ready and deferred paths (30,640 seeks)
at the stored timestamps. Public assembly and revision/resource integrity pass.
The final alias and lyric-index/DOM regressions also pass after the spelling changes.
Actual catalogue examples include `prab joo laaj hamari` (the intended reader),
`krishan`, `shiv shanker`, `hanumaan`, and `take my hnad`. Exact person-name matches
retain priority; mixed source-script and Latin queries preserve native spelling.
Every supplied term must match: semantic paraphrase is not implemented.
The 386-reader index is about 3.92 MB (1.12 MB gzip), loaded on demand. Local Node
measurements put the first fuzzy-cache build at about 123 ms with 11 MB additional
heap, and warm example queries at 4–9 ms. These are not phone measurements.

No deployment, fresh acoustic verification or browser visual pass is claimed.
Original streams have been preserved for the six historical trim conflicts; packet
and waveform comparisons establish copied intervals but do not settle whether every
edge belongs to the performance. The in-app Browser still returns a native-pipe
connection failure. These remain explicit release blockers; neither is waived.

## Bounded follow-up

The continuation rechecked the same browser failure and six historical trim failures;
no release was made. It also compared the unresolved Kākaḍ `paramāyā` passage with
Madhyāhna line-045. The official Sansthan hymn PDF confirms the printed wording,
but contains no commentary resolving the disputed interpretation. Madhyāhna's
corresponding passage is therefore explicitly reopened too: 33 open questions
across the same 23 readers. No public text, audio or timing changed in this follow-up.
The downloaded primary witness is preserved privately with its digest in the review
record. A previously accepted parallel passage is not independent evidence.

## Owner-authorized publication

The owner explicitly requested publication of the prepared website changes and
waived browser verification for this release. Publish the translation, reference-tag
and search repairs while retaining the existing audio and timings. The six historical
trim-record conflicts remain unresolved; the audit has not passed and no audio repair
is claimed. This authorization supersedes the earlier release hold for this prepared
batch, not the normal requirements for future releases. The 33 source questions remain
open. Deployment and served-byte verification are the next steps.

The owner subsequently confirmed that the current live Satpathy recording of
`he-sadaguru-tume-mor-haatku-dhara` is fine as it is. Retain that exact audio and
timing. Its old trim records still disagree, but the current recording is no longer
an open content-repair request. The explicit retention decision is privately bound
to the current reader and audio digests.

## Published result

Commit `04b77d364017994e3064030c9f3012d5a1ed771b` is live. All CI checks passed.
The first run failed only when GitHub Pages could not find the uploaded artifact;
a fresh run, `45308914642`, succeeded. Direct served-byte comparison matched all
779 checked files: 386 reader data files, 386 song entrypoints, the library entrypoint
and six shared runtime/catalogue/search/service-worker resources. The comparison
receipt is preserved privately in `.transcription/library-repair-20261123/live-verification.json`.

All 386 readers retain performance order, timestamps and non-tag metadata from the
previous deployed commit. No audio files were changed. Browser verification was
waived by the owner; neither fresh browser behavior nor acoustic timing is certified.
The 33 source questions and historical trim-record discrepancies remain explicit.


## Owner-reopened whole-library English repair — 25 November 2026

The owner reported obvious defects despite the earlier complete-reading claim.
Every current reader was reopened for an English reading: 386 readers, 9,455 stored
definitions (9,451 referenced by the performance sequences, including non-lyric
entries). Four disjoint groups read the complete songs against source and word maps;
the lead independently read all final changed definitions and challenged altered
images, agency, tense, modifiers, compounds and token links before integration.

Applied 787 English corrections across 221 readers and seven corresponding gloss
repairs. The reported butter passage now says soft throughout; the eyes do not blink.
Other repairs remove calqued sentence order, repair misplaced modifiers and explicit
word-sense errors, and preserve the source's concrete images. Proposed changes that
erased the cooling image, shifted possession, inferred unsupported gifts, or changed
an unresolved boon-bearing phrase were rejected or corrected.

The source script, Roman text, source tokens, language labels, song metadata,
performance sequences, timestamps and audio remain unchanged. The two protected
English readers remain byte-identical. The exact complete coverage and corrections
are in `data/translation-review-2026-11-25.json`; cumulative semantic receipts retain
the original assessment and audio, with 1,220 explicit feature dispositions for the
changed readers. All earlier reductions remain reduced. Integration rejected an
accidentally revived petition feature and a witness taken from a trimmed introduction;
both were corrected against the performed source. The 81 stale subject dismissals
were reinspected in context before rebinding to the corrected text.

Four prior questions were resolved: the two Viṣṇusahasranāma senses from the direct
teaching commentary, Kākaḍ's Muslim-form modifier, and its serpent/matted-locks
compound. The report records exact evidence. Thirty-six source-dependent passages
across 27 readers remain open, including new findings; an awkward phrase is not
permission to invent its missing interpretation. No historical finished flag was
renewed. Current screened marks record this bounded reading and its exact file hash.

The owner requested website publication and explicitly waived browser verification.
No fresh listening or browser/device behavior is claimed. Existing audio is retained;
the six historical trim-record discrepancies remain documented. Local release verification completed: 45 of 46 commands pass. The only failing
command is the historical trim audit with the same six documentary discrepancies.
All 386 reader contracts, subject decisions, shuffle profiles, public assembly,
resource bindings, compilation and whitespace checks pass. The actual reader
consumer passes 30,640 ready/deferred DOM-click seeks for all 15,320 occurrences;
these check stored onsets, not a new acoustic judgment.

Commit `3c247d82fc551ac514b456649526de2f78327282` is live. Pages run
`45668461047` succeeded. All 779 checked served files match the prepared release:
386 reader data files, 386 song entrypoints, the library entrypoint and six shared
runtime/catalogue/search/service-worker resources. The exact comparison receipt is
preserved privately in `.transcription/english-repair-20261125/live-verification.json`.
