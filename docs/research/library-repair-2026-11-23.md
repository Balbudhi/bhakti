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

## Release verification

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
