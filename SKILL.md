---
name: deadlock-maxing
description: Find the best Deadlock builds for a hero (high-ranked one-tricks, Mobalytics, community), analyse how to play and counter it (role, measured play style, matchups, abilities, power spikes), and produce English and French pages with a TLDR and codes to paste in game via "Paste build"; or translate one build (deadchaps.gg link or id). Use when the user asks for a hero's builds, how to play or counter a hero, to redo / update a hero page, opens the "all heroes" page, gives a build link or id to translate, or pastes a build code copied in game.
---

# Deadlock builds: find, translate, import in game

Deadlock imports a build from the clipboard (**"Coller le build"** / "Paste build" button in the build editor).
Format: `base64(zstd(protobuf CMsgHeroBuild))`, without a trailing newline (the game rejects it otherwise).
This format has been verified in game.

`S` = this skill's folder (`.claude/skills/deadlock-maxing`). Working folders in the project:
`builds/<id>` for a single build, `builds/search-<hero>` for a search.

Pages exist in **English** (default) and **French**: every text is written in French first (`summaries.json`), then
in English with the same structure (`summaries.en.json`, official English item and ability names). Answer the user in
their language.

Philosophy: statistical builds from ".gg" sites are not trusted (a win rate does not say *why* to buy an item).
The goal is builds from strong players, **with early / mid / late explanations**. The win rate is never a ranking
criterion, only displayed information.

## A. "Find me the best <hero> builds": 2 calls

**An analysis is only complete with ALL these fields** (report.py prints what is missing: "To complete for an
up-to-date analysis", and the page and home page show "Ancienne analyse" until nothing is missing): `tr` (when there
are texts to translate), `intro`, one `{resume, points}` per build, `tldr` (pick, why, early, mid, late, keys),
`plan` (lane, early, mid, late, tips, role, abilities 1-4, strengths, weaknesses, vs), `sources`, and `en` (all of these
texts in English, same paths). Never finish with something still missing.

**Writing**: full sentences, every item / ability inside a sentence with a verb ("achète Malédiction de
ralentissement pour…"), never "… pour survivre : Malédiction de ralentissement."; always the **full official name**
(not "Dissipateur", "Redingote"): otherwise there is no link and the EN toggle mixes languages. report.py flags
every "Shortened name".

**Every written text cites its sources** (metadata, not displayed yet): in the same finish.py JSON,
`"sources": {"<path>": ["<ref>", …]}` for EVERY text path (`intro`, `<key>.resume`, `<key>.points[i]`,
`tldr.why/early/mid/late/keys[i]`, `plan.early`, `plan.vs[i]`, `plan.abilities.1`…). Refs: `build:<key>`,
`guide:<n>` ([Gn] from guides.py), `video:<id>@<seconds>`, `stat:<module>` (playstyle, baseline, roles, matchups,
counterplay, counters, kit, items, patch), `roles-guide`, `analyse` (my own deduction, always alongside the sources
it rests on). report.py flags every text without a source and every unknown reference.

**Versioned method** (`data/changelog.json`): ANY change to how information is gathered or what is written (even a
small one) adds an entry `{version, date, title, parts, scripts?, auto?, todo}`; `todo` says exactly what to do on an
existing page, and only that. `ANALYSIS_VERSION` = last version. Older pages show "Méthode changée", the list of
changes and a targeted request to copy. When that request comes in: apply only the `todo` of the pending versions
(read changelog.json), without rewriting the rest; finish.py moves a page to the current version only once nothing
is missing.

1. `python3 -I S/scripts/find.py <hero> builds/search-<hero>` (~30 s; options `--days 60 --otp 2 --community 2`).
   Sources: **OTP** (Phantom+ players who mostly play the hero, build rebuilt from their real purchases:
   items in >= 75% of games sorted into early < 10 min / mid < 22 min / late, then situational 25-75%),
   **Mobalytics** (official accounts only), **Community** (popular, >= 150 characters of notes, Oracle+ authors),
   **Vidéo** (`vid-<id>`: builds recommended in a creator's guide video about the hero, see videos.py `guide`;
   `--videos-only` adds them to an existing search without touching the rest).
   Compact output, read it once (do not reopen the JSON files):
   - shortened OTP notes: `98%@4m rev9m` = bought in 98% of games around 4 min, sold around 9 min;
   - texts to translate are numbered `[n]` in the summary and listed once under "To translate";
   - builds already in French get their `code.txt` right away.
2. One call to finish everything (translations + analysis -> codes + page opened):
   ```
   python3 -I S/scripts/finish.py builds/search-<hero> - <<'EOF'
   {"tr": {"<key>": ["fr of [0]", "fr of [1]", …]},
    "intro": "What the builds agree on, the real differences, my advice",
    "<key>": {"resume": "2 sentences", "points": ["Early : …", "Mid : …", "Late : …", "Particularité : …"]},
    "tldr": {…}, "plan": {…}, "sources": {…},
    "en": {"intro": "…", "<key>": {…}, "tldr": {…}, "plan": {…}},
    "tr_en": {"<key>": ["en of [0]", …]}}
   EOF
   ```
   `tr`: one list per key, **in the exact order** of "To translate" (or a partial `{"n": "fr"}`).
   `en`: the same analysis in English (every path of the French one; sources are shared). Use official English names
   (compare `/v1/assets/items?language=english` with `?language=french`; e.g. Fléau = Affliction, Scopa = Wraith).
   `tr_en`: only for builds listed under "To translate into English" (authors who did not write in English); English
   authors' texts and generated OTP texts are filled in automatically, and finish.py builds the codes in both languages.
   `tldr` (default "L'essentiel" view, readable during a loading screen): `{"pick": "<key of the advised build>",
   "why": "1 sentence", "early": "1-2 sentences", "mid": "…", "late": "…", "keys": ["3 takeaways max"]}`: short and
   concrete, like a good player guide: each phase says first what to DO (where to stand, how to trade in lane, when
   to join fights, which objectives / timers / urns), then the items with their minute.
   `plan` ("Comment le jouer" view): `{"lane": "which lane or map position and why", "early": "…", "mid": "…",
   "late": "…", "tips": ["…"],
   "role": "what the hero must do in fights given its position (initiate, frontline, assassinate, carry…)",
   "abilities": {"1": "how to use ability 1", …, "4": "…"},
   "strengths": ["…"], "weaknesses": ["…"], "vs": ["how to beat it / what to watch out for"],
   "counters": {"<item_id>": "why this counter item"}}` (plan, tldr and sources are merged when sent again).
   The plan **cross-checks** the measured play style (find.py "Measured play style" section: souls/min,
   lane/jungle/fights/objectives share, K/D/A, objective damage vs the Phantom+ average) with the "Community advice"
   [G0]… (guide-like builds and Steam guides newer than the last big patch). Say who says what ("Kiwi",
   "Lowavy's guide", measured numbers), flag contradictions (a pre-patch note vs what players actually do). Check
   every number quoted, and the official French name of every item (e.g. Crippling Headshot = Brise-tête).
   French homonyms: "Fléau" = Pocket's ultimate AND an item (Scourge); "Ténacité" = an item AND an ability.
   Write "l'objet Fléau" for the item (page links give priority to the hero's ability).
   Analysis: only from the data shown; flag inconsistencies. The page computes the "Comparer" view (shared items)
   itself: the intro does not need to list them all.
3. Reply briefly: the candidates, my advice, the page link. No screenshot unless the user reports a display
   issue. Counter items (counters.py) arrive ~2 min later in the background: the page regenerates itself.

## A'. "Redo / update <hero>" (existing page, or "Ancienne analyse" / "Méthode changée" on the home page)

- **Patch released or old data**: rerun `find.py <hero> builds/search-<hero>` in the **same folder** (existing
  translations are kept), then `finish.py` with the full analysis (every field above).
- **Analysis only** (recent data): run `playstyle.py`, `guides.py`, `roles.py`, `matchups.py`, `counterplay.py` on the
  folder (and `counters.py … --report` in the background), read their output, reread `summaries.json`, then
  `finish.py` with the missing fields.
- **"Méthode changée"**: apply only the pending changelog `todo`s (see above).

## B. Translate one build (link or id)

1. `python3 -I S/scripts/fetch.py <url_or_id> builds/<id>`: compact summary + numbered "To translate" list.
2. `python3 -I S/scripts/apply.py builds/<id> --fr - <<'EOF'` + JSON list of translations in order + `EOF`:
   writes `build_fr.json`, `code.txt` and **copies the code**.
3. Tell the user: in game, the hero's builds -> **"Coller le build"**. Summarise in a few lines.
   To copy it again later: `wl-copy -n < builds/<id>/code.txt`.

## C. Details

- **Home page**: `builds/index.html` (`hub.py`, rerun by report.py): every hero, stamps (À jour / À vérifier / Patch
  sorti / Ancienne analyse / Méthode changée), TLDR and "Le contrer" links, a button that copies the request for
  Claude. A new required part = an entry in `data/changelog.json` (+ `NEEDED_*` in `status.py` if needed).
- **Hero page**: `templates/hero.html` (official site look: charcoal, parchment, hero colour) + JSON data injected by
  `report.py`. No item data is hard-coded: names, icons, costs, categories and tooltips come from the API on every
  run (items change with every update). Banner / emblem (`assets/`) are copied to `builds/_assets/`.
  Regenerate a page without refetching: `python3 -I S/scripts/report.py builds/search-<hero>`.
  Hero theme (colour, background, name art, portrait, tags), rank emblems, FR + EN items (FR/EN toggle or `?lang=en`)
  and the patch list are all re-read from the API. The page compares dates with today and with patches itself
  (freshness stamp, ⚠ build older than a big patch, live check for new patches). find.py limits OTP games to the last
  big patch when it is >= 21 days old.
- Code layout: `report.py` (page assembly) uses `tooltips.py` (item / ability tooltips), `textlinks.py` (links in
  texts, shortened-name check) and `status.py` (method version, completeness, sources).
- **Languages**: report.py and hub.py write one page per language: `index.html` (English, default) and
  `index.fr.html`, with an EN | FR switch. Interface strings live in `locales/<lang>.json` (scripts: `i18n.t/table/
  pattern`; templates: `{{ui:key}}` tokens and the `L('key')` helper, keys under `"ui"`); never hard-code interface
  text. Every key must exist in every locale (a test checks it). Written content is tagged: `summaries.json` has
  `"lang": "fr"` (set by finish.py), each video tip has `"lang"`; content missing in a page's language is shown in its
  own language with a notice. Analysis modules store ids (play style tags, metric keys), labelled at render time.
- **playstyle.py** / **guides.py** (run by find.py, can be rerun alone on a search folder): measured style via
  `/v1/analytics/player-performance-curve` (OTPs + authors with >= 10 games on the hero, "small sample" under 20), with
  each phase's lean vs the Phantom+ average (`focus`: lane farm, jungle farm, fights, objectives, >= +15%; shown in
  the TLDR, the build view and the comparison: use it to say how each build is played); advice = in-game builds with
  >= 500 characters of explanation + serious Steam guides updated after the patch.
  Mobalytics (Cloudflare) and Reddit (403) are not reachable: do not try to get around it.
- **roles.py**: game class + meta position (recent Steam "roles / positions" guide, last known guide from the cache
  when Steam answers 429) + hero percentiles (farm, damage taken, damage, assists, kills, deaths, objectives).
- **matchups.py**: matchups (gap to the expected result, often small at high level: say so) and items that beat the
  hero (gain beyond the average gain). Explain *why* from the item description, never guessed.
- **counterplay.py**: late-game counterplay by enemy composition (big healers -> anti-heal, tanks -> % HP /
  resistance shred, heavy spirit / gun damage -> resistances, crowd control -> status resistance). Measured hero
  profiles (cached for a day), items classified by their technical properties in the API, filtered on what the
  hero's players buy. Do not rewrite these lists by hand in the analysis: cite them.
  "against" part ("Le contrer" view): hero profile (heals / tanks / spirit / gun) -> most played late items (tier
  III-IV) of the category; matchups.py adds the counter items measured after 20 min.
- **videos.py**: creator YouTube tips (`fetch <url>` = subtitles via yt-dlp split by chapter; `add <id> -` =
  tips per hero with `"text"` (French) and `"en"`, English hero / item names converted to ids; fields left out keep
  their saved value; `guide <id> <hero> <build_id>@<mm:ss>` = the video is a guide for that hero and recommends that
  build; `list`). A hero guide video is the best source for `plan.lane` and the phase texts (cite
  `video:<id>@<s>`); when the user mentions one, find it and use it. Data in `data/videos.json`, tips shown in
  "Le contrer" ("L'avis des créateurs") with a timestamped link, the date, ⚠ when older than the last big patch, and
  ✓ when a quoted item also stands out in the stats. An opinion is not a statistic: flag disagreements. Adding a
  video = a changelog entry when it changes the method.
  Reference: AndrewChicken, "1 Counter For EVERY Deadlock Hero" (C3yn9SdVHZ8); "Counter Buying…" (Zb82rYYumbY),
  kept for the future live optimisation module (counter-buying during a game).
  Guides: Paz, "The BEST Comprehensive Guide to VIOLET" (kW6zL2_22X4), recommends oses's build 897240.
  Subtitles: only the original track is fetched (`en-orig`); asking for every translated track gets a 429.
- **counters.py** (background, started by find.py, regenerates the page): items the OTPs buy clearly more against
  some heroes (statistical test). Steam pages are cached for a day (`~/.cache/deadlock-maxing`).
- Power spikes and ability cards: computed by report.py (game level thresholds x the OTP's ability order).
- **apply.py** `--lang fr|en` writes `build_<lang>.json` and the code (`code.txt` in French, `code.en.txt` in English);
  `--tr -` fills that language's translations. It recomputes category width / height from the text length (the game cuts text with "..."); constants at
  the top of the file, `--keep-layout` keeps the original. It mirrors an in-game copy, with author account id 0: the game
  requires the field to show "Coller le build" but accepts any value, so codes contain nothing personal.
- **Translation**: official French names of items and abilities (the summary already gives them). Nicknames
  ("Cultist" = Sacrifice rituel, "E-Shift" = Refuge céleste…): compare `api.deadlock-api.com/v1/assets/items?language=<lang>`
  with `?language=french`. Natural French gamer tone (lane, farm, focus… are fine). `#Citadel_HeroBuilds_*` labels are
  not translated. End the description translation with "Traduit du build <id>.".

## Troubleshooting

- Pasting fails: ask the user to copy any build in game ("Copier dans le presse-papier"), then
  `python3 -I S/scripts/codec.py --decode "$(wl-paste -n)"` and compare.
- Reference protobuf: `CMsgHeroBuild` in
  `https://raw.githubusercontent.com/SteamDatabase/GameTracking-Deadlock/master/Protobufs/citadel_gcmessages_common.proto`.
- Game limit: 16,000 raw bytes per build (checked by apply.py).
- `assets.deadlock-api.com` may not answer: use `api.deadlock-api.com/v1/assets/...`.
- Useful endpoints: `/v1/analytics/scoreboards/players` (OTPs), `/v1/analytics/item-stats` and
  `/v1/analytics/ability-order-stats` (filterable by `account_id`), `/v1/builds` (`search_name`, `author_id`,
  `sort_by`), `/v1/players/rank`. Full schema: `https://api.deadlock-api.com/openapi.json`.
- Python 3.14+ required (built-in `compression.zstd`).
