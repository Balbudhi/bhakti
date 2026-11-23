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
python3 scripts/song.py release SLUG               # audio, catalogue, ledger, every check
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
