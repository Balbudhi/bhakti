/*
 * Tanu Karagadavaralli — Akkamahādevī vachana
 *
 * Roman text follows the sung Kannada wording. The public reader deliberately
 * keeps separate entries for returned lines and for the final address, so a
 * click always seeks to that performance's first vocal onset.
 */

window.SONG_LINES = {
  tanu: {
    roman: "Tanu karagadavaralli majjanavanolleyayyā nīnu",
    english: "Among {2:those whose} {0:body} {1:has not melted}, {5:You} will not accept {3:ritual bathing}.",
    words: [
      { roman: "Tanu", gloss: "body" },
      { roman: "karagada", gloss: "not melted, not softened" },
      { roman: "varalli", gloss: "among those people" },
      { roman: "majjana", gloss: "ritual bathing, ablution" },
      { roman: "vanolleyayyā", gloss: "will not accept it, will not desire it" },
      { roman: "nīnu", gloss: "You" }
    ]
  },
  mana: {
    roman: "Mana karagadavaralli puṣpavanolleyayyā nīnu",
    english: "Among {2:those whose} {0:mind} {1:has not melted}, {5:You} will not accept {3:flowers}.",
    words: [
      { roman: "Mana", gloss: "mind, heart" },
      { roman: "karagada", gloss: "not melted, not softened" },
      { roman: "varalli", gloss: "among those people" },
      { roman: "puṣpa", gloss: "flower" },
      { roman: "vanolleyayyā", gloss: "will not accept it, will not desire it" },
      { roman: "nīnu", gloss: "You" }
    ]
  },
  haduli: {
    roman: "Haḍuligaralladavaralli gandhākṣateyanolleyayyā nīnu",
    english: "Among {1:those who are not} {0:tender-hearted}, {4:You} will not accept {2:sandal paste and consecrated rice}.",
    words: [
      { roman: "Haḍuligar", gloss: "the tender, gentle-hearted people" },
      { roman: "alladavaralli", gloss: "among those who are not" },
      { roman: "gandhākṣate", gloss: "sandalwood paste and akṣata, consecrated unbroken rice" },
      { roman: "yanolleyayyā", gloss: "will not accept it, will not desire it" },
      { roman: "nīnu", gloss: "You" }
    ]
  },
  arivu: {
    roman: "Arivu kaṇtereyadavaralli āratiyanolleyayyā nīnu",
    english: "Among {2:those whose} {0:understanding's} {1:eye has not opened}, {5:You} will not accept {3:lamp-waving}.",
    words: [
      { roman: "Arivu", gloss: "understanding, knowing" },
      { roman: "kaṇtereyada", gloss: "whose eye has not opened" },
      { roman: "varalli", gloss: "among those people" },
      { roman: "ārati", gloss: "lamp-waving offering" },
      { roman: "yanolleyayyā", gloss: "will not accept it, will not desire it" },
      { roman: "nīnu", gloss: "You" }
    ]
  },
  bhava: {
    roman: "Bhāvaśuddhavilladavaralli dhūpavanolleyayyā nīnu",
    english: "Among {2:those} without {0,1:purity of feeling}, {5:You} will not accept {3:incense}.",
    words: [
      { roman: "Bhāva", gloss: "feeling, inward disposition, intention" },
      { roman: "śuddha", gloss: "pure, purity" },
      { roman: "villadavaralli", gloss: "among those who do not have it" },
      { roman: "dhūpa", gloss: "incense" },
      { roman: "vanolleyayyā", gloss: "will not accept it, will not desire it" },
      { roman: "nīnu", gloss: "You" }
    ]
  },
  parinami: {
    roman: "Pariṇāmigalalladavaralli naivēdyavanolleyayyā nīnu",
    english: "Among {1:those who are not} {0:inwardly transformed}, {4:You} will not accept {2:the food offering}.",
    words: [
      { roman: "Pariṇāmigal", gloss: "those who have undergone transformation, the matured" },
      { roman: "alladavaralli", gloss: "among those who are not" },
      { roman: "naivēdya", gloss: "food offering presented to a deity" },
      { roman: "vanolleyayyā", gloss: "will not accept it, will not desire it" },
      { roman: "nīnu", gloss: "You" }
    ]
  },
  trikarana: {
    roman: "Trikaraṇaśuddhavilladavaralli tāmbūlavanolleyayyā nīnu",
    english: "Among {2:those} without {0,1:purity in the three faculties}, {5:You} will not accept {3:the betel-leaf offering}.",
    words: [
      { roman: "Trikaraṇa", gloss: "the three faculties: thought, speech, and action" },
      { roman: "śuddha", gloss: "pure, purity" },
      { roman: "villadavaralli", gloss: "among those who do not have it" },
      { roman: "tāmbūla", gloss: "betel-leaf offering" },
      { roman: "vanolleyayyā", gloss: "will not accept it, will not desire it" },
      { roman: "nīnu", gloss: "You" }
    ]
  },
  hrudaya: {
    roman: "Hṛdayakamala araḷadavaralli iralolleyayyā nīnu",
    english: "In {3:those whose} {0,1:heart-lotus} {2:has not blossomed}, {5:You} will not {4:remain}.",
    words: [
      { roman: "Hṛdaya", gloss: "heart" },
      { roman: "kamala", gloss: "lotus" },
      { roman: "araḷada", gloss: "not blossomed, not opened" },
      { roman: "varalli", gloss: "among those people" },
      { roman: "iralolleyayyā", gloss: "will not stay, will not abide" },
      { roman: "nīnu", gloss: "You" }
    ]
  },
  ennalli: {
    roman: "Ennalli ēnuṇṭendu",
    english: "{0:In me}, {1:what} is {2:there}?…",
    words: [
      { roman: "Ennalli", gloss: "in me" },
      { roman: "ēnu", gloss: "what" },
      { roman: "ṇṭendu", gloss: "there is, saying that" }
    ]
  },
  karasthala: {
    roman: "Karasthalavanimbugoṇḍe",
    english: "{1,2:Having taken delight} in {0:the palm of the hand}…",
    words: [
      { roman: "Karasthala", gloss: "palm of the hand; the hand as the place of worship" },
      { roman: "vanimbu", gloss: "having found sweetness or delight in it" },
      { roman: "goṇḍe", gloss: "having taken, having found" }
    ]
  },
  chennamalli: {
    roman: "Hēḷā Chennamallikārjunayyā",
    english: "{0:Tell me}, {1:O Chennamallikārjuna}.",
    words: [
      { roman: "Hēḷā", gloss: "tell me, speak" },
      { roman: "Chennamallikārjunayyā", gloss: "Chennamallikārjuna, Akkamahādevī's chosen name for Śiva" }
    ]
  }
};

window.SONG_SEQUENCE = [
  { ref: "tanu", repeats: 2 },
  { ref: "mana", repeats: 2 },
  { ref: "tanu" },
  { ref: "haduli", repeats: 2 },
  { ref: "arivu", repeats: 2 },
  { ref: "tanu" },
  { ref: "bhava", repeats: 2 },
  { ref: "parinami", repeats: 2 },
  { ref: "tanu" },
  { ref: "trikarana", repeats: 2 },
  { ref: "hrudaya", repeats: 2 },
  { ref: "ennalli" },
  { ref: "karasthala" },
  { ref: "chennamalli", repeats: 2 }
];

/* First-vocal onsets verified by two independent audio passes and a third
 * reconciliation pass. A segment covers only this displayed lyric and its
 * immediate repeats; musical ālāp and instrumental passages remain unlabelled. */
window.SONG_TIMINGS = [
  { start: 51.8, end: 71.0 },
  { start: 71.0, end: 90.8 },
  { start: 90.8, end: 102.5 },
  { start: 132.7, end: 152.5 },
  { start: 152.5, end: 168.2 },
  { start: 169.75, end: 187.0 },
  { start: 210.1, end: 231.0 },
  { start: 231.0, end: 246.5 },
  { start: 246.5, end: 261.5 },
  { start: 286.6, end: 308.2 },
  { start: 308.2, end: 325.5 },
  { start: 331.4, end: 340.75 },
  { start: 340.75, end: 348.8 },
  { start: 348.8, end: 373.2 }
];
