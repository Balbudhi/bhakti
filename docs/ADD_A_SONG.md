# Add or revise a song

This is the whole procedure. Read it, then work; you do not need the other docs unless a
step below names one. You translate. `scripts/song.py` does everything mechanical.

Goal of the site: someone who does not know the language hears a line, sees it in its own
script and in IAST, taps any word for what that word means here, and reads English that
carries the meaning and feeling of what is being sung.

```sh
git worktree add .claude/worktrees/NAME -b work/NAME origin/main && cd .claude/worktrees/NAME
python3 scripts/song.py todo                       # local bhajans not on the site
python3 scripts/song.py new SLUG /path/audio.m4a   # audio, duplicates, credit evidence, song.txt
#   write .transcription/songs/SLUG/song.txt (in the main checkout; steps 1–3)
python3 scripts/song.py align SLUG                 # line starts and a score per line
python3 scripts/song.py build SLUG                 # names every mistake in song.txt
python3 scripts/song.py release SLUG               # audio, catalogue, every check
git add … && git commit && git push origin HEAD:main   # release prints the paths
```

Do the songs of one album together: they share poets, credits, vocabulary and refrains.
Run `new`, `align` and `build` for several songs at once; run `release` once for all of
them. Pushing main publishes. Confirm the deploy succeeded and stop.

## 1. The words

- Find the text first, by its opening words, then fix it to this recording. A stotra,
  abhaṅga, Gurbāṇī or well-known bhajan has a good text online or in another song here
  (`new` says so): reuse reviewed words and meanings. Two agreeing sources are enough.
- The recording decides what is sung: omitted verses, changed words, repeats, refrains.
  `song.py draft SLUG` gives free local speech-to-text as a hint; it is never the text.
- Write every performed line, in order, in its own script. Give a recurring line one id
  and list it each time in `order:`; write `*2` only for immediate identical repeats.
- A wrong, missing or misplaced line shows in `align` as a low score or a strange length.
  Check those lines only. If a line still cannot be made out after a second source and a
  second listen, use the paid audio model once for that passage (section 5), then leave
  the song unpublished with a note if it is still unclear. Never guess a line.

## 2. The translation

Translate it yourself, well, in one careful pass; then read it as a listener.

1. For each verse settle who speaks to whom, what is asked, the image, and the turn.
2. Give each word its meaning *in this line*, short and plain, with grammar only where it
   helps. Split a compound or sandhi into the parts the English renders.
3. Write English that says all of it and reads beautifully: the image, wordplay, argument,
   tenderness or complaint. Lossless, natural, rhythmic. No word-order calques, no filler
   piety, no added explanations. Say what a name or epithet means in its popup.
4. Read the English alone, top to bottom. If a line is stiff, flat, or could be said about
   anything, rewrite it. Grammatical correctness is not approval.
5. Compare with any published translation or captions you find. Yours must be at least as
   good on every line. Take a better reading; do not copy wording.

Look things up when a word is uncertain, rare, regional or doctrinally loaded, not for
every word: Sanskrit with `cd ~/Dev/prakriya && python3 scripts/lookup/lookup.py kosha WORD
--dict ap90` (standard: `~/Dev/vedanta-timeline/docs/gita_briefs/ENGLISH_CRAFT.md`); others
in a dictionary of that language. A commentary is comparison, not authority.

Keep divine names (Hari, Rāma, Śyāma), not “Lord” for all of them. Roman is IAST: plain e
and o outside Dravidian languages. Never change the owner's English (`koi-hor-nahi`,
`arunachala-akshara-mana-malai`).

Do not narrow a layered term to its most familiar social meaning. In the Datta
address retain **Brahmacārī**: its popup explains life in Brahman (the absolute
reality) as well as the familiar celibate-disciple/ascetic sense. Keep the
Brahman-dwelling explanation distinct from a claim about historical etymology.
For *moh*, preserve the delusion or infatuation where the passage activates it;
“worldly attachment” can explain the binding effect in the popup but must not
silently erase that meaning from the English. Neither is a global substitution:
choose each occurrence from its language and whole passage.

## 3. The credits

Poet, singer, composer: look in this order and stop when one is settled.

1. The song itself: a poet's signature (Tulsī, Mīrā, Kabīr, Nānak…) or a known author.
2. The source's own title and full caption; the file's tags; the rest of its CD.
3. The official release with the same recording: `new` lists candidates of equal length.
4. Other uploads of the same recording and the singer's own channel, with their captions.
5. Shazam (`uvx --from shazamio`, at most one request every 20 seconds, three samples):
   accept only repeated hits whose offsets advance with the song.

“Same recording” means the audio lines up along its length. Equal length or title is a
lead. A record label's artist name is not proof of the voice. Voice similarity is only
support, and only after showing it separates that group of singers.

Credit the poet the tradition names, without caveat. Never write “Traditional”. A poet of
another version of a song did not write this one. If a role is unknown leave it blank and
move on: five minutes of searching per song, no more. Tags are subjects, not albums:
`Śiva`, `Viṣṇu`, `Rāma`, `Kṛṣṇa`, `Śakti`, `Durgā`, `Kālī`, `Lakṣmī`, `Sarasvatī`, `Gaṇeśa`,
`Hanumān`, `Guru`, `Śirḍī Sāī`, `Vaiṣṇo Devī`, `Nirguṇa`, `Gurbāṇī`, and others already used.

### Subject tags are a separate review

Read the whole performed text for names, inflections, compounds, regional spellings,
kinship, attributes and narratives: Murāri/Banvārī, Nanda’s son, the mountain-lifter,
Girijā’s husband with trident and drum. Tags identify the devotion: invoked or praised
names, addressees, and meaningful participants in its narrative or liturgical scene.
Keep specific forms alongside their umbrella tags. Gurbāṇī/Nirguṇa may coexist with
Kṛṣṇa, Viṣṇu or Śiva when those names participate in the devotion; this does not assert
a different theology. The same contextual standard applies across traditions.

A name used only to identify another deity's parent, child or spouse is incidental:
“son of Śiva/Pārvatī” in a Gaṇeśa hymn does not add Śiva or Pārvatī; “Pārvatī's
husband” can identify Śiva without adding Pārvatī. Check the entire song before
removing a tag: an independent invocation or substantial portrayal elsewhere can
justify it. Meaningful joint worship and devotional service relationships are not
excluded merely because they involve relatives. Actual joint divine depictions
(for example, the Goddess on the deity’s lap or the shared half-body form) qualify;
a metaphor about being in a spouse’s heart alone does not. Oṃ qualifies when itself
chanted, praised or meditated upon, not merely prefixed to another deity’s mantra.
Passing comparisons, shared symbols,
generic “Lord”, credits and glossary background do not independently justify tags.
An established central form may be identified by its specific performed narrative
or iconography without a literal name; uncertainty is not proof that its tag is wrong.

The examples and detector aliases are not a closed list. Brahmā or Indra as meaningful
participants (for example, the singing assembly in So Dar) merit tags; merely naming
them is not enough. Narhari as a devotional name needs the specific Nṛsiṃha
reference alongside Viṣṇu. Reuse an established canonical label where available;
otherwise record the evidenced name in IAST. For a group review, record each
song's named references and contextual exclusions, including songs needing no
changes. A clean keyword scan cannot replace that reading.

Search before deciding, using the free local command (no API calls):

```sh
python3 scripts/search_song_subjects.py 'Murari' --context 1
python3 scripts/search_song_subjects.py --candidates --slug SLUG --json
```

It searches source script, IAST, English and word meanings across performed lines.
It is a lead generator, not a rule that every detected name must become a tag.
Read each candidate with its neighbors and the whole poem. Record accepted contextual
changes with an exact performed source witness and reason in
`data/song_tag_overrides.json`; `build` applies the same registry as the older pipeline.
Record rejected candidate groups with their full-text hash and concrete reason in
`data/subject-tag-review.json`. `--check` blocks new or stale unresolved candidates;
a clean scan is coverage of its listed signals, not proof of exhaustive interpretation.
A text edit invalidates a dismissal. Check actual catalogue filters after release.
Keyword matches are suggestions, never automatic assignments. Both writers retain
the explicitly reviewed subjects plus source-bound registry decisions. In particular,
accent folding cannot decide between Ramā and Rāma, or Śyāmā and Śyāma.

For an existing reader, after recording the source-bound decision, run
`python3 scripts/song.py retag SLUG`. This updates reader/page metadata and the
catalogue together, preserving lyrics, timings, audio and the original shuffle
assessment. It records the tag correction separately from that assessment.
Do not rebuild an existing reader from an older intake file just to change tags.

Translation, subject tags, audio/timing and shuffle assessments are distinct reviews.
`release` does not create a translation `finished` mark or move its reviewed hash.
Only a substantive translation review may update that record; metadata-only changes
can retain the prior review after inspecting the diff, without calling it a new review.
The current `screened` status records a bounded contextual reading; it is not a
claim that every source, word analysis and recording has been independently verified.
Keep concrete open passages under `needs_source_review`.

For translation corrections, read the complete passage, compare source and linked
word meanings, and check the resulting English again with its adjacent lines.
Check who does what to whom, negation, imperative versus description, compounds,
proper-name identity, and concrete objects. A dictionary gloss or a clean
structural audit cannot settle these. Record unresolved alternatives explicitly;
do not silently choose a familiar theological reading to make the sentence smooth.
The public search index is generated from the released performed lyrics and word
meanings during assembly; it is loaded only when someone starts searching.

## 4. song.txt

```
title: Devī Aparādha Kṣamāpana Stotram
writer: Ādi Śaṅkarācārya
singer: Ashit Desai & Hema Desai
composer: Ashit Desai
languages: Sanskrit
subjects: Śakti, Durgā
aliases: Devi Aparadha Kshamapana Stotram, Bhavani Stuti
source: https://www.youtube.com/watch?v=LilKBguuRC0

[v2-a verse]
vidher | of the rites: genitive singular | विधे
+ajñānena | through not knowing: instrumental | रज्ञानेन
draviṇa | wealth, means | द्रविण
+viraheṇ | through the lack of | विरहे
+ālasatayā | through sloth | णालसतया
en: {1:Through not knowing }{0:the rites, }{3:through want }{2:of means, }{4:through sloth,}
note: Three causes, each in the instrumental.
src: विधेरज्ञानेन द्रविणविरहेणालसतया

order: v1-a v1-b refrain v2-a*2 refrain
```

- One row per word: `roman | meaning | native piece`. `+` joins it to the row before.
- `en:` every word number appears; each link is one word or one short unit, never four or
  more. The text inside the links, read in order, is the English line with its spaces.
- `src:`/`rom:` only when punctuation or spacing differs from the joined words.
- Sections: invocation, refrain, verse, bridge, closing, spoken. `lang=xx` on a line head
  for a line in another language (`hi sa mr pa bra kn te ta or gu awa bn`).
- Cut spoken introductions and promotions from the audio before `new`.

To revise a published song that has no song.txt, edit its `data.js` directly and run
`release SLUG`; it keeps everything else.

## 5. Effort, money and stopping

- One agent per album, at most four at once. No reviews of reviews, no rerunning passing
  checks, no library-wide audits, no new documents. Fix what `build` names and go on.
- Cost: `assess` about $0.03 a song, nothing else. The older paid pipeline
  (`scripts/bhakti_pipeline.py`, `docs/TRANSLATION_WORKFLOW.md`) transcribes and drafts
  with a model at $0.10–0.50 a song. Use it for a passage or song whose words cannot be
  found any other way, with `--budget-usd`, and still write the translation yourself.
- Keys: only the owner-only key file named by `OPENROUTER_API_KEY_FILE`. Never print,
  copy or commit it. Never use browser cookies to get past a sign-in page; try later.
- Stop and ask only for: a recording that is a different song from its name, a text you
  cannot establish, or anything that deletes published work.
- Tell the owner, per song: poet, singer, what is uncertain. Nothing else.
