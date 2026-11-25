#!/usr/bin/env python3
"""Add or revise one song. The person or agent writes song.txt; this does the rest.

  todo                     local bhajans that are not on the site yet
  new SLUG AUDIO           bring in audio, print credit evidence, write song.txt
  draft SLUG               optional local speech-to-text, a hint and never the text
  align SLUG               line starts from the recording, with a score per line
  build SLUG               check song.txt and write songs/SLUG
  assess SLUG              shuffle assessment (about $0.03, capped at $0.25)
  retag SLUG [SLUG ...]     apply reviewed subject tags without paid assessment
  release SLUG [SLUG ...]  publish audio, rebuild catalogue, run all checks
  check                    the release checks alone

docs/ADD_A_SONG.md is the procedure and explains the song.txt format.
Working files live in .transcription/songs/SLUG, which is never published.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
MAIN = Path(subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                           capture_output=True, text=True).stdout.strip() or ROOT / ".git").parent
WORK = MAIN / ".transcription" / "songs"
MUSIC = Path.home() / "Music" / "Music" / "Media.localized"
AUDIO = (".m4a", ".mp3", ".webm", ".opus", ".flac", ".wav", ".aac", ".ogg", ".aif", ".aiff")
CODES = {"Hindi": "hi", "Marathi": "mr", "Punjabi": "pa", "Braj": "bra", "Kannada": "kn", "Sanskrit": "sa",
         "Telugu": "te", "Tamil": "ta", "Odia": "or", "Gujarati": "gu", "Awadhi": "awa", "Bengali": "bn",
         "Rajasthani": "raj", "Urdu": "ur", "Maithili": "mai"}
FIELDS = ("title", "subtitle", "writer", "singer", "composer", "musicDirector", "ensemble", "languages",
          "subjects", "aliases", "source")
SECTIONS = {"invocation", "refrain", "verse", "bridge", "closing", "spoken", "instrumental"}
READER = ('global.window={};eval(require("fs").readFileSync(process.argv[1],"utf8"));'
          'process.stdout.write(JSON.stringify([window.SONG_META,window.SONG_TIMINGS]))')


def fail(message):
    sys.exit("song.py: " + message)


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags", "-of", "json",
                          str(path)], capture_output=True, text=True).stdout
    form = json.loads(out or "{}").get("format", {})
    return float(form.get("duration") or 0), {k.lower(): v for k, v in form.get("tags", {}).items()}


def fold(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    for a, b in (("ee", "i"), ("oo", "u"), ("aa", "a"), ("sh", "s"), ("w", "v"), ("chh", "ch")):
        text = text.replace(a, b)
    return re.sub(r"[^a-z]", "", text)


def library():
    """slug, names, known lengths for every published song."""
    def one(path):
        meta, timings = json.loads(subprocess.run(["node", "-e", READER, str(path)], capture_output=True,
                                                  text=True, check=True).stdout)
        names = [meta["title"], path.parent.name] + list(meta.get("searchAliases") or [])
        lengths = {float(timings[-1]["end"])} if timings else set()
        lengths |= {probe(p)[0] for p in (MAIN / "songs" / path.parent.name).glob("audio.*")}
        return path.parent.name, {fold(n) for n in names} - {""}, lengths
    with ThreadPoolExecutor(8) as pool:
        return list(pool.map(one, sorted((ROOT / "songs").glob("*/data.js"))))


def closest(title, seconds, songs):
    """(slug, 'recording' | 'text' | None): same recording, or the same text in another recording."""
    key = fold(title)
    def alike(name):
        inside = min(len(key), len(name)) > 9 and (key in name or name in key)
        return 1.0 if inside else difflib.SequenceMatcher(None, key, name).ratio()
    score, slug = max(((max(map(alike, names)), s) for s, names, _ in songs), default=(0, ""))
    near = max(((max(map(alike, names)), s) for s, names, lengths in songs
                if min((abs(d - seconds) for d in lengths), default=99) < 5), default=(0, ""))
    if near[0] > 0.7:
        return near[1], "recording"
    return (slug, "text") if score > 0.86 else (slug, None)


def disc(tags):
    return next((v for k, v in tags.items() if "cddb_1" in k), None)


# -- todo ------------------------------------------------------------------------------------

def todo():
    songs = library()
    files = [p for p in MUSIC.rglob("*") if p.suffix.lower() in AUDIO]
    with ThreadPoolExecutor(12) as pool:
        rows = list(zip(files, pool.map(probe, files)))
    groups = {}
    for path, (seconds, tags) in rows:
        if (tags.get("genre") or "") not in ("Bhajan", "Chants") or seconds < 30 or "Orthodox" in str(path):
            continue
        title = tags.get("title") or path.stem
        slug, kind = closest(title, seconds, songs)
        if kind == "recording":
            continue
        note = f"  (text already on site: {slug}; this is another recording)" if kind == "text" else ""
        groups.setdefault(str(path.parent), []).append(f"{title.strip()} [{int(seconds) // 60}:{int(seconds) % 60:02d}]"
                                                       f" {path.name}{note}")
    for folder in sorted(groups):
        print(f"\n{folder}")
        print("\n".join("  " + line for line in sorted(groups[folder])))
    print(f"\n{sum(map(len, groups.values()))} recordings not on the site")


# -- new -------------------------------------------------------------------------------------

def fetch(url):
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        return json.load(urllib.request.urlopen(request, timeout=20))
    except Exception as error:  # evidence only; the song can continue without it
        print("  lookup failed:", str(error)[:80])
        return {}


def evidence(path, title):
    seconds, tags = probe(path)
    print(f"length {seconds:.1f}s")
    print("tags  ", {k: v for k, v in tags.items() if k in ("title", "artist", "album", "composer", "genre", "comment")})
    if disc(tags) and MUSIC.is_dir():
        print("same CD (gives the album):")
        for p in sorted(path.parent.glob("*")) if path.is_relative_to(MUSIC) else []:
            other = probe(p)[1] if p.suffix.lower() in AUDIO else {}
            if disc(other) == disc(tags):
                print("   ", other.get("title"), "|", other.get("artist") or "")
    print("official releases (same length is a lead; align the audio before trusting it):")
    quoted = urllib.parse.quote(title)
    for row in fetch(f"https://itunes.apple.com/search?entity=song&limit=40&country=in&term={quoted}").get("results", []):
        length = row.get("trackTimeMillis", 0) / 1000
        if abs(length - seconds) < 8:
            print(f"    Apple  {length:6.0f}s  {row['trackName']} | {row['artistName']} | {row['collectionName']}")
    saavn = ("https://www.jiosaavn.com/api.php?__call=search.getResults&_format=json&_marker=0&api_version=4"
             f"&ctx=web6dot0&n=30&p=1&q={quoted}")
    for row in fetch(saavn).get("results", []):
        info = row.get("more_info", {})
        length = float(info.get("duration") or 0)
        if abs(length - seconds) < 8:
            people = sorted({f"{a['name']} ({a['role']})" for a in info.get("artistMap", {}).get("artists", [])})
            print(f"    Saavn  {length:6.0f}s  {row['title']} | {', '.join(people)[:150]} | {info.get('album')} | {info.get('label')}")


def new(slug, source):
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
        fail("slug must be lowercase words joined by hyphens")
    if re.match(r"https?://", source):
        fail("give a local file. For a link: python3 scripts/resolve_youtube_music_audio.py URL, then download the "
             "audio-only stream with yt-dlp -f ba, and read its title and caption for the credits")
    path = Path(source).expanduser().resolve()
    if path.suffix.lower() not in AUDIO or not path.is_file():
        fail(f"not an audio file: {path}")
    here, there = WORK / slug, ROOT / "songs" / slug
    if (there / "data.js").exists():
        fail(f"{slug} already exists; edit {here / 'song.txt'} and run build")
    here.mkdir(parents=True, exist_ok=True)
    there.mkdir(parents=True, exist_ok=True)
    seconds, tags = probe(path)
    title = tags.get("title") or path.stem
    target = there / ("audio" + path.suffix.lower())
    shutil.copy2(path, target)
    if target.suffix not in (".m4a", ".mp3"):  # compatibility copy; the original stays first
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(target), "-vn", "-c:a", "aac", "-b:a", "192k",
                        str(there / "audio.m4a")], check=True)
    slug_near, kind = closest(title, seconds, library())
    if kind:
        print(f"!! {'SAME RECORDING' if kind == 'recording' else 'same text, another recording'}: {slug_near}. "
              + ("Stop unless it is wrong." if kind == "recording" else "Reuse its reviewed text and meanings."))
    evidence(path, title)
    text = here / "song.txt"
    if not text.exists():
        head = "\n".join(f"{f}: {title if f == 'title' else ''}" for f in FIELDS)
        text.write_text(head + "\n\n[v1-a verse]\nword | meaning | word in its own script\n"
                        "en: {0:The English, linked word by word.}\nnote: \n\norder: v1-a\n")
    print("write:", text)


# -- song.txt --------------------------------------------------------------------------------

def parse(slug):
    path = WORK / slug / "song.txt"
    if not path.is_file():
        fail(f"missing {path}; run: song.py new {slug} AUDIO")
    meta, lines, order, current, problems = {}, {}, [], None, []
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        row = raw.strip()
        if not row or row.startswith("#"):
            continue
        head = re.fullmatch(r"\[([a-z0-9-]+)(?:\s+([a-z]+))?(?:\s+lang=(\w+))?\]", row)
        if head:
            current = head[1]
            if current in lines:
                problems.append(f"{number}: line id {current} used twice")
            lines[current] = {"section": head[2] or "verse", "lang": head[3], "tokens": [], "en": "", "note": "",
                              "src": "", "rom": "", "row": number}
            if lines[current]["section"] not in SECTIONS:
                problems.append(f"{number}: section must be one of {', '.join(sorted(SECTIONS))}")
            continue
        field = re.match(r"(\w+):\s*(.*)$", row)
        if field and field[1] == "order":
            order += field[2].split()
        elif field and current is None and field[1] in FIELDS:
            meta[field[1]] = field[2].strip()
        elif field and current and field[1] in ("en", "note", "src", "rom"):
            lines[current][field[1]] = field[2].strip() if field[1] != "en" else field[2]
        elif current and row.count("|") == 2:
            lines[current]["tokens"].append([part.strip() for part in row.split("|")])
        else:
            problems.append(f"{number}: not understood: {row[:60]}")
    if problems:
        fail("song.txt\n  " + "\n  ".join(problems))
    return meta, lines, order or list(lines)


def joined(tokens, column):
    """A leading + joins a piece to the one before: compounds and sandhi."""
    out = ""
    for token in tokens:
        piece, glue = token[column], token[0].startswith("+")
        piece = piece.lstrip("+") if column == 0 else piece
        out += piece if glue or not out else " " + piece
    return out


def compile_song(slug):
    import source_word_map
    meta, lines, order = parse(slug)
    languages = [x.strip() for x in meta.get("languages", "").split(",") if x.strip()]
    problems, readers = [], {}
    for need in ("title", "languages", "subjects"):
        if not meta.get(need):
            problems.append(f"{need}: is empty")
    for key, line in lines.items():
        tokens = line["tokens"]
        bad = lambda text: problems.append(f"line {line['row']} [{key}] {text}")
        if not tokens:
            bad("has no words")
            continue
        words = [{"roman": t[0].lstrip("+"), "gloss": t[1], "concept_key": "", "preserve_in_english": False} for t in tokens]
        source, roman = line["src"] or joined(tokens, 2), line["rom"] or joined(tokens, 0)
        mapped = [{"text": t[2], "wordIndices": [i]} for i, t in enumerate(tokens) if t[2]]
        bad_map = source_word_map.validate_source_words(source, words, mapped)
        for text in bad_map:
            bad(text)
        if re.sub(r"\s", "", roman) != "".join(w["roman"] for w in words):
            bad("rom: does not spell the same letters as the words")
        for i, t in enumerate(tokens):
            if not t[1]:
                bad(f"word {i} {t[0]} has no meaning")
        spans = re.findall(r"\{([\d,]+):([^{}]*)\}", line["en"])
        if re.sub(r"\{[\d,]+:[^{}]*\}", "", line["en"]).strip():
            bad("en: has text outside {n:...}")
        used = {int(i) for s, _ in spans for i in s.split(",") if i}
        if used - set(range(len(tokens))):
            bad(f"en: uses word numbers that do not exist: {sorted(used - set(range(len(tokens))))}")
        if set(range(len(tokens))) - used:
            bad("en: leaves out " + ", ".join(f"{i} {words[i]['roman']}" for i in sorted(set(range(len(tokens))) - used)))
        for s, text in spans:
            if len(set(s.split(","))) > 3:
                bad(f"en: one link covers {len(set(s.split(',')))} words ({text.strip()}); link word by word")
        code = line["lang"] or (CODES.get(languages[0]) if languages else None)
        if not code:
            bad("unknown language; add lang=xx to the line head")
        readers[key] = {"source": source, "sourceLanguage": code, "sourceWords": mapped, "roman": roman,
                        "english": line["en"].rstrip(), "words": words, "nameTable": False, "grammarNote": line["note"]}
    sequence = []
    for item in order:
        key, _, times = item.partition("*")
        if key not in lines:
            problems.append(f"order: no line {key}")
            continue
        sequence.append({"ref": key, "section": lines[key]["section"], "repeats": int(times or 1)})
    unused = set(lines) - {r["ref"] for r in sequence}
    if unused:
        problems.append(f"order: never sung: {', '.join(sorted(unused))}")
    if problems:
        fail("song.txt\n  " + "\n  ".join(problems))
    people = [meta.get(k, "") for k in ("writer", "singer", "composer", "musicDirector", "ensemble")]
    if any("traditional" in p.lower() for p in people):
        fail("never credit 'Traditional': name the poet the tradition names, or leave it blank")
    import tag_taxonomy
    subjects = tag_taxonomy.merge_subject_tags(
        [x.strip() for x in meta["subjects"].split(",") if x.strip()], readers.values())
    plain = lambda t: unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    aliases = [x.strip() for x in meta.get("aliases", "").split(",") if x.strip()]
    for extra in [meta["title"], meta.get("writer", "")] + subjects:
        if extra and plain(extra) != extra and plain(extra) not in aliases:
            aliases.append(plain(extra))
    full = {"title": meta["title"], "subtitle": meta.get("subtitle", "") or subjects[0],
            "credit": " · ".join(p for i, p in enumerate(people[:3])
                                  if p and not any(p in q for q in people[:i])) or meta.get("ensemble", ""),
            "pageCredit": meta.get("singer") or meta.get("writer") or meta.get("ensemble", ""),
            "writer": meta.get("writer", ""), "singer": meta.get("singer", ""),
            "composer": meta.get("composer", ""),
            "languages": languages, "subjectTags": subjects, "searchAliases": aliases}
    for key, name in (("musicDirector", "musicDirector"), ("ensemble", "ensemble"), ("source", "sourceUrl")):
        if meta.get(key):
            full[name] = meta[key]
    tag_taxonomy.apply_reviewed_subject_tags(full, slug, readers, sequence, root=ROOT)
    return full, readers, sequence


# -- draft and align ---------------------------------------------------------------------------

def listener(slug):
    found = [p for ext in (".webm", ".opus", ".ogg", ".flac", ".wav", ".mp3", ".m4a")
             for p in [ROOT / "songs" / slug / f"audio{ext}", MAIN / "songs" / slug / f"audio{ext}"] if p.is_file()]
    if found:
        return found[0]
    media = json.loads((ROOT / "data" / "media.json").read_text())["songs"].get(slug)
    if not media:
        fail(f"no audio for {slug}; run song.py new first")
    saved = WORK / slug / ("audio" + Path(media[0]["src"]).suffix)
    if not saved.is_file():
        saved.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(media[0]["src"], saved)
    return saved


def wav(slug):
    path = WORK / slug / "audio.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(listener(slug)), "-ac", "1", "-ar", "16000", str(path)], check=True)
    return path


def isolated(packages, code, *arguments):
    """Run a heavy local model in its own environment; nothing is installed in the project."""
    script = WORK / "_run.py"
    script.write_text(code)
    command = ["uv", "run", "-q", "--no-project", "--python", "3.11"]
    for package in packages:
        command += ["--with", package]
    return subprocess.run(command + ["python", str(script), *map(str, arguments)], text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, check=True).stdout


DRAFT = '''
import sys, mlx_whisper
r = mlx_whisper.transcribe(sys.argv[1], path_or_hf_repo="mlx-community/whisper-large-v3-mlx", language=sys.argv[2],
                           condition_on_previous_text=False)
for s in r["segments"]: print(f"{s['start']:7.1f} {s['text'].strip()}")
'''

ALIGN = '''
import json, sys, wave, numpy as np, torch, torchaudio
b = torchaudio.pipelines.MMS_FA; M = b.get_model(with_star=True).eval(); D = b.get_dict(star="*")
w = wave.open(sys.argv[1]); x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
lines = json.load(open(sys.argv[2])); win, ov, hop, N, pos, chunks = 30*16000, 2*16000, 320, len(x), 0, []
while pos < N:
    s, e = max(0, pos-ov), min(N, pos+win+ov)
    with torch.inference_mode(): em, _ = M(torch.tensor(x[s:e].copy())[None])
    f0 = (pos-s)//hop; chunks.append(em[0][f0:f0+min(win, N-pos)//hop]); pos += win
em = torch.cat(chunks); toks, own = [D["*"]], [None]
for i, line in enumerate(lines):
    for c in line.replace(" ", ""): toks.append(D[c]); own.append(i)
    toks.append(D["*"]); own.append(None)
al, sc = torchaudio.functional.forced_align(em[None], torch.tensor([toks]), blank=0)
sp = torchaudio.functional.merge_tokens(al[0], sc[0].exp()); out = {}
for s, o in zip(sp, own):
    if o is not None: out.setdefault(o, []).append((s.start*.02, s.end*.02, float(s.score)))
print(json.dumps([[round(out[i][0][0], 2), round(out[i][-1][1], 2), round(float(np.mean([z[2] for z in out[i]])), 2)] for i in range(len(lines))]))
'''


def spoken(roman):
    text = unicodedata.normalize("NFC", roman.lower())
    for a, b in (("ṛ", "ri"), ("ṃ", "m"), ("ṁ", "m"), ("m̐", "n"), ("ṅ", "n"), ("ñ", "n"), ("ś", "sh"), ("ṣ", "sh"),
                 ("ḻ", "l"), ("ḥ", "h"), ("c", "ch")):
        text = text.replace(a, b)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", "", text).replace("chh", "ch")


def draft(slug):
    meta, _, _ = parse(slug)
    code = CODES.get(meta.get("languages", "").split(",")[0].strip(), "hi")
    supported = {"hi", "mr", "pa", "kn", "sa", "te", "ta", "gu", "bn", "ur"}
    print("A hint only: sung words are often misheard. Check every line by meaning and by align scores.")
    print(isolated(["mlx-whisper", "numpy"], DRAFT, wav(slug), code if code in supported else "hi"))


def align(slug):
    _, lines, order = compile_song(slug)
    rows = WORK / slug / "lines.json"
    flat = [(row["ref"], spoken(lines[row["ref"]]["roman"])) for row in order for _ in range(row["repeats"])]
    rows.write_text(json.dumps([text for _, text in flat]))
    result = json.loads(isolated(["torch==2.5.1", "torchaudio==2.5.1", "numpy"], ALIGN, wav(slug), rows))
    starts, i = [], 0
    for row in order:
        starts.append(result[i][0])
        i += row["repeats"]
    (WORK / slug / "align.json").write_text(json.dumps({"order": [r["ref"] + f"*{r['repeats']}" for r in order], "starts": starts}))
    for (key, _), (start, end, score) in zip(flat, result):
        print(f"{start:8.2f} {end:8.2f} {score:.2f} {key}{'   << listen: wrong words, wrong order or a missing repeat?' if score < .25 or end - start < .6 else ''}")
    print("To fix a start by ear, edit align.json; keep the order unchanged.")


# -- build, assess, release ----------------------------------------------------------------------

def build(slug):
    import bhakti_pipeline as pipeline
    meta, lines, sequence = compile_song(slug)
    stored = WORK / slug / "align.json"
    if not stored.is_file():
        fail("run align first")
    timing = json.loads(stored.read_text())
    if timing["order"] != [r["ref"] + f"*{r['repeats']}" for r in sequence]:
        fail("the order changed since align; run align again")
    starts = [max(0.0, round(s - 0.02, 2)) for s in timing["starts"]]
    if any(b <= a for a, b in zip(starts, starts[1:])):
        fail("starts are not increasing; fix align.json")
    end = round(probe(listener(slug))[0], 3)
    times = [{"start": a, "end": b} for a, b in zip(starts, starts[1:] + [end])]
    media = json.loads((ROOT / "data" / "media.json").read_text())["songs"].get(slug)
    meta["audioSources"] = [{"src": m["src"], "type": m["type"]} for m in media] if media else [
        {"src": listener(slug).name, "type": "audio/mp4"}]
    meta.update({"timingStatus": "start-only-reviewed", "translationStatus": "gloss-derived literal", "sourceStatus": "reviewed"})
    folder = ROOT / "songs" / slug
    folder.mkdir(parents=True, exist_ok=True)
    show = lambda value: json.dumps(value, ensure_ascii=False, indent=2)
    (folder / "data.js").write_text(f"window.SONG_META = {show(meta)};\n\nwindow.SONG_LINES = {show(lines)};\n\n"
                                    f"window.SONG_SEQUENCE = {show(sequence)};\n\nwindow.SONG_TIMINGS = {show(times)};\n")
    (folder / "index.html").write_text(pipeline.page_html(pipeline.load_song_meta(folder), slug))
    print("\n".join(re.sub(r"\{[\d,]+:([^}]*)\}", r"\1", lines[r["ref"]]["english"]) for r in sequence))
    print("\nRead the English above aloud. Built", folder)


def assess(slug):
    here = WORK / slug
    os.environ.update(BHAKTI_GEMINI_PROVIDER="openrouter", BHAKTI_API_MAX_CONCURRENCY="1",
                      BHAKTI_API_RUN_LEDGER=str(here / f"assess-{int(time.time())}.json"),
                      BHAKTI_API_RUN_BUDGET_USD="0.25", BHAKTI_API_RUN_MAX_CALLS="4")
    import bhakti_shuffle_audio as audio
    import bhakti_shuffle_profiles as profiles
    import bhakti_shuffle_semantics as semantics
    policy, _, taxonomy = profiles._configuration(ROOT)
    reader = profiles.parse_javascript_sources({slug: (ROOT / "songs" / slug / "data.js").read_text()})[slug]
    digest = profiles.recording_sha256(ROOT, slug, reader)
    stored = profiles.read_json(ROOT / profiles.REVIEWS)["profiles"].get(
        hashlib.blake2s(slug.encode(), digest_size=4).hexdigest(), {})
    semantic = stored.get("semantic", {})
    if (semantic.get("inputHash") == profiles.semantic_input_hash(reader, taxonomy)
            or "subjectTagRevision" in semantic or "editorialTextRevision" in semantic):
        try:
            profiles.project_song_profile(hashlib.blake2s(slug.encode(), digest_size=4).hexdigest(),
                slug, reader, taxonomy, digest, stored, required=True, qualification=policy, root=ROOT)
        except ValueError as exc:
            fail(f"stored assessment needs review: {exc}")
        print("assessment is current:", slug)
        return
    here.mkdir(parents=True, exist_ok=True)
    heard = stored.get("audio") or profiles.stamp_qualification(audio.audio_summary(
        audio.analyze_audio(listener(slug), expected_sha256=digest, cache_path=here / "audio.json")), "audio", policy)
    profiles._qualified(heard, "audio", reader, policy)
    ready = semantics.semantic_input_readiness(reader)
    if not ready["eligible"]:
        fail(f"not ready: {ready}")
    raw = semantics.assess_semantics(reader, taxonomy, options=semantics.SemanticOptions(
        allow_paid=True, deadline_at=time.time() + 900), cache_dir=here / "semantic")
    part = profiles.stamp_qualification(semantics.semantic_summary(reader, taxonomy, raw), "semantic", policy)
    profiles._qualified(part, "semantic", reader, policy)
    profiles.store_reviewed_profile(ROOT, slug, reader, digest, {"slug": slug, "semantic": part, "audio": heard})
    print("assessed", slug)


def retag(slugs):
    """Apply source-reviewed public tags as one prepared batch, without intake."""
    import copy
    import tempfile
    import bhakti_pipeline as pipeline
    import bhakti_shuffle_profiles as profiles
    from bhakti_boundary_timebase import boundary_transaction
    from tag_taxonomy import apply_reviewed_subject_tags

    slugs = list(dict.fromkeys(slugs))
    if not slugs or any(not slug or Path(slug).name != slug for slug in slugs):
        fail("retag needs existing song slugs")
    snapshots = {}

    def snapshot(path):
        if path in snapshots:
            return snapshots[path]
        value = path.read_bytes() if path.is_file() else None
        snapshots[path] = value
        return value

    for name in (profiles.POLICY, profiles.TAXONOMY, profiles.REVIEWS,
                 'data/song_tag_overrides.json', 'data/media.json', profiles.TEXT_REPAIRS):
        snapshot(ROOT / name)
    policy, reviews, taxonomy = profiles._configuration(ROOT)
    updated_reviews = copy.deepcopy(reviews)
    prepared = {}
    for slug in slugs:
        folder = ROOT / 'songs' / slug
        source_path, page_path = folder / 'data.js', folder / 'index.html'
        source_bytes, page_bytes = snapshot(source_path), snapshot(page_path)
        if source_bytes is None or page_bytes is None:
            raise ValueError(f'{slug}: retag requires its existing reader and page')
        source, page = source_bytes.decode('utf-8'), page_bytes.decode('utf-8')
        reader = profiles.parse_javascript_sources({slug: source})[slug]
        prior_meta = copy.deepcopy(reader['SONG_META'])
        reviewed_meta = copy.deepcopy(prior_meta)
        apply_reviewed_subject_tags(reviewed_meta, slug, reader['SONG_LINES'], reader['SONG_SEQUENCE'], root=ROOT)
        # This operation changes public tags only, not a reviewed subtitle or text.
        reader['SONG_META']['subjectTags'] = reviewed_meta.get('subjectTags', [])
        queue_id = hashlib.blake2s(slug.encode(), digest_size=4).hexdigest()
        stored = reviews['profiles'].get(queue_id, {})
        record = copy.deepcopy(stored)
        semantic = record.get('semantic', {})
        if (prior_meta.get('subjectTags', []) != reader['SONG_META']['subjectTags']
                or 'subjectTagRevision' in semantic):
            prior_tags = semantic.get('subjectTagRevision', {}).get('priorTags', prior_meta.get('subjectTags', []))
            record['semantic'] = profiles.reviewed_retag_semantic(
                ROOT, slug, reader, stored, prior_tags=prior_tags)
        media_hash = profiles.recording_sha256(ROOT, slug, reader)
        profiles.project_song_profile(queue_id, slug, reader, taxonomy, media_hash, record,
                                      required=True, qualification=policy, root=ROOT)
        updated_reviews['profiles'][queue_id] = record
        matches = list(re.finditer(r'window\.SONG_META\s*=\s*', source))
        if len(matches) != 1:
            raise ValueError(f'{slug}: retag requires one SONG_META assignment')
        start = matches[0].end()
        literal, end = json.JSONDecoder().raw_decode(source[start:])
        if literal != prior_meta:
            raise ValueError(f'{slug}: SONG_META literal differs from its executed reader')
        if reader['SONG_META'] != prior_meta:
            rendered = json.dumps(reader['SONG_META'], ensure_ascii=False, indent=2)
            prepared[source_path] = (source[:start] + rendered + source[start + end:]).encode('utf-8')
        pattern = r'^      <div class="song-meta">.*$'
        old = list(re.finditer(pattern, page, re.M))
        new = re.search(pattern, pipeline.page_html(reader['SONG_META'], slug), re.M)
        if len(old) != 1 or new is None:
            raise ValueError(f'{slug}: retag requires one existing song metadata line')
        changed_page = page[:old[0].start()] + new[0] + page[old[0].end():]
        if changed_page != page:
            prepared[page_path] = changed_page.encode('utf-8')
    if updated_reviews != reviews:
        prepared[ROOT / profiles.REVIEWS] = (json.dumps(updated_reviews, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    outputs = [ROOT / name for name in ('data/songs.js', profiles.PUBLIC, 'data/queue_numbers.json', 'sitemap.xml')]
    for path in outputs:
        snapshot(path)
    population = sorted((ROOT / 'songs').glob('*/data.js'))
    for path in population:
        snapshot(path)
    # Use the real complete-library publisher against a prepared snapshot. Its
    # failure must not leave amended readers paired with yesterday's catalogue.
    with tempfile.TemporaryDirectory(prefix='.retag-', dir=ROOT) as temporary:
        staged = Path(temporary)
        for path, value in snapshots.items():
            if value is None:
                continue
            target = staged / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(prepared.get(path, value))
        # Audio remains immutable input; avoid copying recordings into the
        # scratch publication while preserving the real media identity checks.
        for reader_path in population:
            for audio_path in reader_path.parent.glob('audio.*'):
                if audio_path.is_file():
                    (staged / audio_path.relative_to(ROOT)).symlink_to(audio_path.resolve())
        pipeline_root, queue_path = pipeline.ROOT, pipeline.QUEUE_NUMBERS_PATH
        try:
            pipeline.ROOT = staged
            pipeline.QUEUE_NUMBERS_PATH = staged / 'data/queue_numbers.json'
            pipeline.write_catalogue()
        finally:
            pipeline.ROOT, pipeline.QUEUE_NUMBERS_PATH = pipeline_root, queue_path
        for path in outputs:
            target = staged / path.relative_to(ROOT)
            value = target.read_bytes() if target.is_file() else None
            if value is not None and value != snapshots[path]:
                prepared[path] = value
    with boundary_transaction(ROOT / 'data'):
        if sorted((ROOT / 'songs').glob('*/data.js')) != population:
            raise ValueError('retag song population changed during preparation')
        for path, expected in snapshots.items():
            current = path.read_bytes() if path.is_file() else None
            if current != expected:
                raise ValueError(f'retag inputs changed during preparation: {path}')
        written = []
        try:
            for path, value in prepared.items():
                profiles.atomic_text(path, value.decode('utf-8'))
                written.append(path)
        except Exception:
            for path in reversed(written):
                # Never roll back over a concurrent external writer's bytes.
                if path.read_bytes() != prepared[path]:
                    raise RuntimeError(f'retag rollback blocked by concurrent edit: {path}')
                if snapshots[path] is None:
                    path.unlink()
                else:
                    profiles.atomic_text(path, snapshots[path].decode('utf-8'))
            raise
    if prepared:
        print('\n'.join(str(path.relative_to(ROOT)) for path in sorted(prepared)))
    else:
        print('reviewed tags and public pairing are current:', ', '.join(slugs))


def release(slugs):
    import bhakti_pipeline as pipeline
    known = json.loads((ROOT / "data" / "media.json").read_text())["songs"]
    fresh = [s for s in slugs if s not in known]
    if fresh:
        subprocess.run([sys.executable, "scripts/publish_media_release.py"] + [x for s in fresh for x in ("--song", s)],
                       cwd=ROOT, check=True)
    for slug in slugs:
        if (WORK / slug / "song.txt").is_file():
            build(slug)
        else:  # edited by hand: refresh only the credits and descriptions on its page
            folder = ROOT / "songs" / slug
            page, fresh_page = (folder / "index.html").read_text(), pipeline.page_html(pipeline.load_song_meta(folder), slug)
            for pattern in (r'^      <div class="song-meta">.*$', r'^  <meta name="description".*$',
                            r'^  <meta property="og:description".*$'):
                old, now = (re.search(pattern, text, re.M) for text in (page, fresh_page))
                if old and now:
                    page = page[:old.start()] + now[0] + page[old.end():]
            (folder / "index.html").write_text(page)
        assess(slug)
    pipeline.write_catalogue()
    # Publication mechanics do not establish or renew a translation review.
    # Keep its reviewed hash intact so changed text remains visibly unreviewed.
    check()
    print("\nReady. Commit and push:\n  git add data sitemap.xml " + " ".join(f"songs/{s}" for s in slugs)
          + "\n  git commit && git push origin HEAD:main")


def check_commands(workflow):
    """Read explicit workflow checks as argv, preserving flags and quoted args."""
    import shlex
    commands = [('python3', 'scripts/assemble_public_site.py')]
    for line in workflow.splitlines():
        command = re.sub(r'^\s*(?:-\s*)?run:\s*', '', line).strip()
        if not re.match(r'^(?:node|python3)\s', command):
            continue
        arguments = shlex.split(command, comments=True)
        if (len(arguments) > 1 and re.fullmatch(r'scripts/[\w-]+\.(?:js|py)', arguments[1])):
            commands.append(tuple(arguments))
        elif arguments[:3] == ['python3', '-m', 'py_compile']:
            # subprocess does not invoke a shell: explicitly expand the one
            # compile glob used by this repository's workflow.
            expanded = []
            for argument in arguments[3:]:
                if '*' in argument:
                    expanded.extend(str(path.relative_to(ROOT)) for path in sorted(ROOT.glob(argument)))
                else:
                    expanded.append(argument)
            commands.append(tuple(arguments[:3] + expanded))
    commands.extend([
        ('python3', 'scripts/audit_bhakti_contract.py'),
        ('python3', 'scripts/audit_shuffle_profiles.py'),
        ('python3', 'scripts/search_song_subjects.py', '--check'),
        ('python3', 'scripts/audit_youtube_trims.py'), ('git', 'diff', '--check')])
    return list(dict.fromkeys(commands))


def check():
    import shlex
    if not (ROOT / "node_modules").is_dir():
        subprocess.run(["npm", "ci", "--silent", "--no-audit", "--no-fund"], cwd=ROOT, check=True)
    workflow = (ROOT / ".github/workflows/deploy-pages.yml").read_text()
    commands = check_commands(workflow)
    failed = []
    for arguments in commands:
        command = shlex.join(arguments)
        run = subprocess.run(arguments, cwd=ROOT, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if run.returncode:
            failed.append(command)
            print("FAIL", command, "\n   ", "\n    ".join((run.stdout + run.stderr).strip().splitlines()[-8:]))
    if failed:
        fail(f"{len(failed)} checks failed")
    print(f"{len(commands)} checks passed")


def main(arguments):
    one = {"draft": draft, "align": align, "build": build, "assess": assess}
    if arguments[:1] == ["todo"]:
        todo()
    elif arguments[:1] == ["check"]:
        check()
    elif arguments[:1] == ["new"] and len(arguments) == 3:
        new(*arguments[1:])
    elif arguments[:1] == ["release"] and len(arguments) > 1:
        release(arguments[1:])
    elif arguments[:1] == ["retag"] and len(arguments) > 1:
        retag(arguments[1:])
    elif len(arguments) == 2 and arguments[0] in one:
        one[arguments[0]](arguments[1])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
