/*
 * Tumhī More Lagan Lagāī Re Fakīrwā — reviewed full-song reader data.
 * Each timing starts at the first audible syllable of this displayed lyric;
 * repeated returns remain individual sequence entries.
 */

window.SONG_META = {
  title: "Tumhī More Lagan Lagāī Re Fakīrwā",
  credit: "Satpathy Baba",
  languages: ["Hindi"],
  subjectTags: ["Śirḍī Sāī"],
  translationStatus: "reviewed",
  sourceStatus: "reviewed"
};

window.SONG_LINES = {
  tu_hi_more_lagan: {
    source: "तू ही मोरे लगन लगाई रे फकीरवा",
    roman: "Tū hī more lagan lagāī re fakīrwā",
    english: "{0,1:You alone} {4:kindled} {3:devotional longing} {2:within me}, {5,6:O fakir}.",
    words: [
      { roman: "Tū", gloss: "you" },
      { roman: "hī", gloss: "alone; emphatic" },
      { roman: "more", gloss: "my; within me" },
      { roman: "lagan", gloss: "devotional longing, attachment" },
      { roman: "lagāī", gloss: "kindled, instilled" },
      { roman: "re", gloss: "O; vocative particle" },
      { roman: "fakīrwā", gloss: "fakir, ascetic mendicant (affectionate form)" }
    ]
  },
  ham_to_sowat: {
    source: "हम तो सोवत रहली ओढ़ के चदरवा",
    roman: "Ham to sowat rahlī oṛh ke chadarwā",
    english: "{0:I} {2,3:was sleeping}, {4,5:wrapped} in a {6:sheet}. ",
    words: [
      { roman: "Ham", gloss: "I" },
      { roman: "to", gloss: "indeed; emphasis" },
      { roman: "sowat", gloss: "sleeping" },
      { roman: "rahlī", gloss: "was, remained" },
      { roman: "oṛh", gloss: "covering oneself, wrapped in" },
      { roman: "ke", gloss: "having; with" },
      { roman: "chadarwā", gloss: "sheet, shawl" }
    ]
  },
  bahiyā_pakaṛ_ke: {
    source: "बहियाँ पकड़ के जगाए रे फकीरवा",
    roman: "Bahiyā̃ pakaṛ ke jagāe re fakīrwā",
    english: "{0,1:Holding my arm}, {3:You awakened me}, {4,5:O fakir}.",
    words: [
      { roman: "Bahiyā̃", gloss: "arm, arms" },
      { roman: "pakaṛ", gloss: "holding, catching" },
      { roman: "ke", gloss: "having done" },
      { roman: "jagāe", gloss: "awakened" },
      { roman: "re", gloss: "O; vocative particle" },
      { roman: "fakīrwā", gloss: "fakir, ascetic mendicant (affectionate form)" }
    ]
  },
  manwā_lāge_na: {
    source: "मनवा लागे न कहीं तोरे बिन सइयाँ",
    roman: "Manwā lāge na kahī̃ tore bin saiyā̃",
    english: "My {0:heart} {1,2:finds no peace} {3:anywhere} {4,5:without You}, {6:my Beloved}.",
    words: [
      { roman: "Manwā", gloss: "heart, mind" },
      { roman: "lāge", gloss: "settles, attaches, finds rest" },
      { roman: "na", gloss: "not" },
      { roman: "kahī̃", gloss: "anywhere" },
      { roman: "tore", gloss: "you (oblique form)" },
      { roman: "bin", gloss: "without" },
      { roman: "saiyā̃", gloss: "beloved, lord" }
    ]
  },
  jahā̃_jāū̃_tohe: {
    source: "जहाँ जाऊँ तोहे पाऊँ बनूँ रे बावरिया",
    roman: "Jahā̃ jāū̃ tohe pāū̃ banū re bāwariyā",
    english: "{0,1:Wherever I go}, {2,3:I find You}; {4:I become} a {6:love-maddened one}.",
    words: [
      { roman: "Jahā̃", gloss: "wherever" },
      { roman: "jāū̃", gloss: "I go" },
      { roman: "tohe", gloss: "You" },
      { roman: "pāū̃", gloss: "I find, attain" },
      { roman: "banū", gloss: "I become" },
      { roman: "re", gloss: "O; emphatic particle" },
      { roman: "bāwariyā", gloss: "one mad with love, ecstatic lover" }
    ]
  },
  more_ghaṭ_mẽ: {
    source: "मोरे घट में है तोरी साँस रे फकीरवा",
    roman: "More ghaṭ mẽ hai torī sā̃s re fakīrwā",
    english: "{4,5:Your breath} {3:is} {2:within} my {1:inner vessel}, {6,7:O fakir}.",
    words: [
      { roman: "More", gloss: "my" },
      { roman: "ghaṭ", gloss: "vessel; body, inner self" },
      { roman: "mẽ", gloss: "in, within" },
      { roman: "hai", gloss: "is" },
      { roman: "torī", gloss: "Your" },
      { roman: "sā̃s", gloss: "breath" },
      { roman: "re", gloss: "O; vocative particle" },
      { roman: "fakīrwā", gloss: "fakir, ascetic mendicant (affectionate form)" }
    ]
  }
};

window.SONG_SEQUENCE = [
  { ref: "tu_hi_more_lagan", section: "refrain", repeats: 4 },
  { ref: "ham_to_sowat", section: "verse", repeats: 2 },
  { ref: "bahiyā_pakaṛ_ke", section: "verse" },
  { ref: "tu_hi_more_lagan", section: "refrain", repeats: 4 },
  { ref: "manwā_lāge_na", section: "verse" },
  { ref: "jahā̃_jāū̃_tohe", section: "verse" },
  { ref: "more_ghaṭ_mẽ", section: "verse", repeats: 2 },
  { ref: "tu_hi_more_lagan", section: "refrain", repeats: 5 },
  { ref: "manwā_lāge_na", section: "verse" },
  { ref: "jahā̃_jāū̃_tohe", section: "verse" },
  { ref: "manwā_lāge_na", section: "verse" },
  { ref: "jahā̃_jāū̃_tohe", section: "verse" },
  { ref: "more_ghaṭ_mẽ", section: "verse", repeats: 2 },
  { ref: "tu_hi_more_lagan", section: "refrain", repeats: 5 },
  { ref: "ham_to_sowat", section: "verse", repeats: 2 },
  { ref: "bahiyā_pakaṛ_ke", section: "verse" },
  { ref: "tu_hi_more_lagan", section: "refrain", repeats: 4 }
];

window.SONG_TIMINGS = [
  { start: 43.5, end: 64.2 },
  { start: 64.2, end: 74.8 },
  { start: 74.8, end: 80.1 },
  { start: 80.1, end: 101.2 },
  { start: 113.8, end: 119.1 },
  { start: 119.1, end: 124.4 },
  { start: 124.4, end: 135.0 },
  { start: 135.0, end: 161.3 },
  { start: 185.0, end: 190.3 },
  { start: 190.3, end: 195.6 },
  { start: 195.6, end: 200.9 },
  { start: 200.9, end: 206.2 },
  { start: 206.2, end: 216.8 },
  { start: 216.8, end: 243.2 },
  { start: 243.2, end: 253.8 },
  { start: 253.8, end: 259.1 },
  { start: 259.1, end: 277.176599 }
];
