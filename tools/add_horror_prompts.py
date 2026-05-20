#!/usr/bin/env python3
"""
horror_v59.revpack에 v60 프롬프트 16개를 추가하는 스크립트
- 기존 파일은 유지하면서 prompts/ 폴더에 16개 .txt.enc 파일 추가
- Fernet 암호화 적용 (기존 팩과 동일)
"""
import sys
import os
import zipfile
import hashlib
import base64
import tempfile
import shutil

# 암호화 지원
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False
    print("[WARN] cryptography 모듈 없음 — 평문 저장")

PACK_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "packs", "horror_v59.revpack")
PACK_PATH = os.path.normpath(PACK_PATH)

SALT = b"ReveriePack2024Salt!"
PASSWORD = b"ReverieStudio_PackEncryption_v57"  # bytes! pack_config.py와 동일


def get_fernet():
    if not HAS_CRYPTO:
        return None
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=SALT,
        iterations=100000,  # pack_config.py와 동일해야 함!
    )
    key = base64.urlsafe_b64encode(kdf.derive(PASSWORD))
    return Fernet(key)


# ============================================================
# 16개 프롬프트 파일 내용
# ============================================================

PROMPTS = {}

PROMPTS["topic_generation"] = """You are a master horror storytelling topic generator for Korean YouTube psychological horror radio dramas.

Generate ONE unique, compelling horror topic in Korean (1-2 sentences).

RULES:
- Target audience: Korean adults (25-45) who enjoy horror/thriller content
- Focus on psychological horror, NOT gore or violence
- Must include a relatable everyday setting that becomes horrifying
- Include a specific emotional hook (dread, paranoia, unease)
- The topic must be producible as a 3-part radio drama (each part ~3 minutes)
- Output ONLY the topic text in Korean, nothing else

HORROR SUBGENRES TO DRAW FROM:
{pool_context}

QUALITY STANDARD:
- The topic should make the reader feel uneasy just reading it
- Avoid cliche horror tropes (haunted houses, dolls, mirrors) unless given a fresh twist
- Real-world settings (apartments, hospitals, offices, schools) are preferred
- The horror should come from psychological tension, not supernatural elements alone"""

PROMPTS["topic_enhanced"] = """You are an elite horror storytelling architect for Korean YouTube psychological horror radio dramas.

Generate ONE masterfully crafted horror topic in Korean that will maximize viewer retention and engagement.

ENHANCED REQUIREMENTS:
- Must have a "hook within the first sentence" that creates immediate dread
- Include a TWIST element that subverts expectations
- The horror must escalate naturally across 3 parts
- Must tap into universal fears (isolation, betrayal, loss of control, the uncanny)

CREATIVE CONSTRAINTS:
{pool_context}

AVOID:
- Generic ghost stories without psychological depth
- Topics that resolve too easily
- Horror that relies solely on jumpscares or shock value

OUTPUT: One topic in Korean (1-2 sentences). Nothing else."""

PROMPTS["hook_generation"] = """You are a horror radio drama opening hook specialist.

Create a powerful opening hook (2-3 sentences in Korean) for a horror radio drama about:
{topic}

The hook must:
1. Create immediate unease or dread in the first sentence
2. Establish the protagonist's normal world that is about to shatter
3. Plant a subtle hint of the horror to come
4. Use sensory details (sounds, silence, temperature, smell)
5. Be in a calm, unsettling narrative tone

TONE: Quiet dread. The scariest moment is right before something happens.
OUTPUT: 2-3 sentences in Korean. Nothing else."""

PROMPTS["hook_enhanced"] = """You are a master of horror opening sequences for Korean radio dramas.

Create an elite-tier opening hook for:
{topic}

REQUIREMENTS:
1. First sentence must trigger visceral unease (use the "familiar made wrong" technique)
2. Include ONE specific sensory detail that feels personally threatening
3. End with an incomplete thought or question that DEMANDS the listener continue
4. Rhythm: Short sentence → Medium sentence → Trailing sentence...

TECHNIQUE REFERENCE:
- "Something was wrong with the elevator today." (familiar + wrong)
- "The smell hit me first." (sensory + dread)
- "I realized I had been hearing it for hours." (delayed recognition)

OUTPUT: 2-3 sentences in Korean. Nothing else."""

PROMPTS["metadata_generation"] = """You are the chief editor of a 1-million-subscriber Korean horror YouTube channel.
Create click-worthy metadata for a horror radio drama. ALL output must be in Korean.

[Topic] {{topic}}
[Genre] {{genre}}
[Script Sample] {{sample_txt}}

[Requirements]
1) title: May include emoji, spark curiosity AND dread, max 40 Korean characters
   - Use patterns: "[Setting]에서 [Event]한 이야기", "[Situation], 그날 이후..."
   - Include emotion words (소름, 공포, 전율, 오싹)

2) thumbnail_title: ★ CRITICAL — main text on thumbnail ★
   - NO emoji
   - 12-18 Korean characters
   - 2-4 short phrases for visual impact
   - Must capture horror/mystery core
   {{thumb_style_guide}}

3) thumbnail_text: Max 8 Korean characters, genre-tag (e.g., "실화공포", "심리공포")
4) tags: 20 Korean keywords (include: 공포라디오, 무서운이야기, 심리공포, 라디오드라마)
5) description: 3-line Korean summary without spoilers

Output JSON ONLY:
{{"title":"","thumbnail_title":"","description":"","tags":"","thumbnail_text":""}}"""

PROMPTS["thumbnail_style"] = """Generate a thumbnail title text for a Korean horror radio drama.

TOPIC: {topic}

REQUIREMENTS:
- 1-2 lines of large Korean text (max 8 characters per line)
- Must convey horror/dread at a glance
- Use dramatic, concise phrasing
- Style: Dark background with white/red text, high contrast
- The text alone should make someone stop scrolling

EXAMPLES:
- "그날 밤" / "돌아온 것"
- "절대 열지마"
- "뒤에 서있었다"

OUTPUT: Just the title text (1-2 lines), nothing else."""

PROMPTS["story_bible"] = """Create a story bible for a 3-part Korean horror radio drama.

TOPIC: {topic}
HOOK: {hook}

Output JSON:
{{
  "title": "Story title in Korean",
  "logline": "1-sentence premise",
  "protagonist": {{
    "name": "Korean name",
    "age": "age range",
    "occupation": "job",
    "personality": "2-3 traits",
    "fear": "core psychological vulnerability"
  }},
  "antagonist_force": "The source of horror (can be person, entity, or situation)",
  "setting": {{
    "primary": "Main location",
    "time": "Time period/season",
    "atmosphere": "Dominant mood"
  }},
  "horror_mechanism": "How the horror manifests and escalates",
  "theme": "Underlying psychological theme (paranoia, guilt, isolation, etc.)",
  "twist": "The reveal or escalation point",
  "part1_summary": "Setup: Normal world + first sign of wrongness",
  "part2_summary": "Escalation: Horror intensifies, protagonist trapped",
  "part3_summary": "Climax: Full horror revealed + ambiguous/disturbing resolution",
  "characters": [
    {{"name": "name", "role": "role", "voice_type": "narrator/man/woman/young_man/young_woman"}}
  ],
  "rules": [
    "Horror comes from what is NOT shown/said",
    "Silence is scarier than noise",
    "The protagonist must make believable choices"
  ]
}}

IMPORTANT:
- Maximum 4 characters (including narrator)
- Each character must have a distinct voice_type
- The horror must escalate, never plateau
- Part 3 should leave the audience unsettled, not relieved"""

PROMPTS["story_bible_improve"] = """Review and improve this horror story bible for a Korean radio drama.

[Current Story Bible]
{{bible}}

[Feedback]
{{feedback}}

[Genre]
horror

CHECK AND IMPROVE:
1. Is the horror mechanism specific enough? (Not just "something scary happens")
2. Does each part have clear escalation? (tension should go 3 -> 6 -> 9)
3. Are character motivations believable? (Would a real person do this?)
4. Is the twist earned? (Was it foreshadowed?)
5. Is the resolution unsettling? (Avoid neat, happy endings)

IMPROVE:
- Fix the specific issues raised in the feedback
- Strengthen any weak story beats
- Add specific horror moments to each part summary
- Ensure the psychological theme is woven throughout
- Make the antagonist_force more specific and terrifying

OUTPUT: Improved story bible in Korean, numbered list format."""

PROMPTS["story_summarize"] = """Summarize the completed part of a Korean horror radio drama for continuity.

COMPLETED SCRIPT:
{script}

Create a concise summary (3-5 sentences) that captures:
1. What happened (key events)
2. The current horror level (how scared should the audience be?)
3. Unresolved threads (what mysteries remain?)
4. Character emotional states
5. The last moment/image (what the audience is left with)

This summary will be used to write the next part, so include ALL details needed for continuity.
OUTPUT: Summary in Korean."""

PROMPTS["structural_outline"] = """Create a structural outline for a 3-part Korean horror radio drama.

STORY BIBLE:
{story_bible}

For each part, define:
- Opening beat (first 30 seconds)
- Rising tension beats (3-4 per part)
- Peak moment (the scariest/most intense moment)
- Closing beat (cliffhanger for parts 1-2, resolution for part 3)

HORROR PACING RULES:
- Part 1: Slow burn. Normalcy with creeping wrongness. End on first real scare.
- Part 2: Accelerating. Each scene scarier than the last. End on "it's real" moment.
- Part 3: Relentless. Brief false hope, then full horror. End ambiguously disturbing.

TENSION CURVE:
Part 1: 1 → 2 → 3 → 5 (end on spike)
Part 2: 4 → 5 → 7 → 8 (end on spike)
Part 3: 6 → 7 → 9 → 10 → 6 (false calm → maximum → lingering dread)

OUTPUT: Structured outline in Korean with specific scene descriptions."""

PROMPTS["craft_rules"] = """# Horror Radio Drama Writing Rules

You are writing a Korean psychological horror radio drama script.
Target length: {{target_turns}} dialogue turns total for this part.
Minimum dialogue turns (non-narration): {{min_dialogue}}
Maximum narration turns: {{max_narration}}

## CORE PRINCIPLES
1. **Show, don't tell fear**: Never say "무서웠다". Show fear through actions, pauses, breathing.
2. **Sound is everything**: This is audio-only. Every horror beat needs a sound cue.
3. **Silence is your weapon**: The pause before the scare is scarier than the scare itself.
4. **Familiar made wrong**: The horror comes from normal things behaving abnormally.

## HORROR ESCALATION TECHNIQUE
Tension curve per part:
- Part 1: 1 → 2 → 3 → 5 (creeping unease → first real scare)
- Part 2: 4 → 5 → 7 → 8 (mounting dread → "it's real" moment)
- Part 3: 6 → 7 → 9 → 10 → 6 (relentless → peak → lingering dread)

## AUDIO DRAMA TECHNIQUES
- **Breathing**: Use [호흡] or character breathing to convey fear without words
- **Environmental sounds**: footsteps, doors, wind, silence — these ARE the horror
- **Whispers**: The most effective horror tool in audio. Use sparingly.
- **Narrator distance**: Narrator should be clinical/calm — contrast amplifies horror

## DIALOGUE RULES
- Characters speak naturally — no exposition dumps
- Fear makes people say LESS, not more
- Interrupted sentences increase tension: "근데 그게... 아니, 아무것도 아니야"
- Maximum 3 sentences per dialogue turn
- Include at least 2 "silence beats" per part: [잠시 침묵]

## STRUCTURE PER SCENE
1. Establish normalcy (30 seconds)
2. First wrongness (subtle — the audience notices before the character)
3. Character notices (delayed — builds dramatic irony)
4. Escalation (each attempt to resolve makes it worse)
5. Peak/Cliffhanger

## FORBIDDEN
- Jump scares without buildup (NO sudden screams without 30+ seconds of tension)
- Explaining the horror (mystery > explanation)
- Happy resolutions (at best: ambiguous. at worst: the horror won)
- Gore/violence descriptions (psychological > physical)
- Characters acting stupidly for plot convenience"""

PROMPTS["pacing_part1"] = """# Part 1 Pacing Guide — Horror Radio Drama (Setup)

## PURPOSE: Establish normalcy, plant seeds of wrongness, end on first real scare.

## TENSION TARGET: 1 → 2 → 3 → 5

## STRUCTURE (Target: 25-35 dialogue turns, ~3 minutes)

### Opening (turns 1-5): Tension 1
- Narrator sets the scene: ordinary day, ordinary place
- Protagonist is introduced through action, not description
- ONE sensory detail that feels slightly off (but dismissible)

### Early Signs (turns 6-15): Tension 2
- First subtle wrongness — could be nothing
- Protagonist notices but rationalizes it away
- Another character may dismiss or not notice at all
- Environmental sound shifts slightly

### Growing Unease (turns 16-25): Tension 3
- Second wrongness — harder to dismiss
- Protagonist's behavior changes (checking over shoulder, speaking quieter)
- A piece of information doesn't add up
- The audience should be ahead of the character

### First Scare / Cliffhanger (turns 26-35): Tension 5
- Something undeniable happens
- Protagonist's rational world cracks
- End mid-action or mid-realization
- The listener MUST want to hear Part 2

## RULES
- NO rushing to the horror. Slow burn is essential.
- Minimum 5 turns of pure normalcy before first wrongness
- At least 1 moment of dark humor or warmth (contrast makes horror stronger)
- End on a question, not an answer"""

PROMPTS["pacing_part2"] = """# Part 2 Pacing Guide — Horror Radio Drama (Escalation)

## PURPOSE: Horror intensifies. Each scene scarier than the last. Protagonist trapped.

## TENSION TARGET: 4 → 5 → 7 → 8

## STRUCTURE (Target: 30-40 dialogue turns, ~3.5 minutes)

### Aftermath (turns 1-5): Tension 4
- Brief recap through character reaction (NOT narrator exposition)
- Protagonist tries to rationalize or seek help
- But something has fundamentally changed

### Investigation (turns 6-15): Tension 5
- Protagonist actively tries to understand what's happening
- Each discovery makes it WORSE, not better
- A trusted person doesn't believe them OR is part of the problem
- One moment of false hope (immediately crushed)

### Trap (turns 16-28): Tension 7
- Protagonist realizes they can't escape/ignore this
- The horror becomes personal (it knows them, targets them specifically)
- Rules of the horror become clearer but more terrifying
- Environment turns hostile (familiar places become threatening)

### "It's Real" Moment (turns 29-40): Tension 8
- Undeniable confrontation with the horror
- Protagonist's worst fear confirmed
- All escape routes closed
- End on maximum dread — the listener feels trapped too

## RULES
- Part 2 is FASTER than Part 1. Shorter scenes, quicker cuts.
- Each scene must be scarier than the previous
- Include ONE false hope moment (makes the crushing worse)
- The "trap" revelation should feel inevitable in hindsight
- No new major characters (deepen existing ones)"""

PROMPTS["pacing_part3"] = """# Part 3 Pacing Guide — Horror Radio Drama (Climax)

## PURPOSE: Full horror revealed. Brief false hope. Ambiguous, disturbing resolution.

## TENSION TARGET: 6 → 7 → 9 → 10 → 6 (lingering dread)

## STRUCTURE (Target: 30-40 dialogue turns, ~3.5 minutes)

### Desperate Action (turns 1-8): Tension 6-7
- Protagonist takes drastic action to fight/escape the horror
- Brief moment of seeming success
- The audience knows it won't last (dramatic irony)

### False Hope (turns 9-15): Tension 5 (intentional dip)
- Things seem to improve momentarily
- A warm moment with another character
- This calm is the setup for maximum impact
- Plant final twist foreshadowing here

### Full Horror (turns 16-30): Tension 9-10
- The truth is revealed — worse than imagined
- Everything the protagonist believed is wrong
- The horror was closer/more personal than expected
- Peak fear moment — the listener should feel genuinely unsettled

### Resolution (turns 31-40): Tension 6 (lingering dread)
- The immediate crisis may pass, BUT...
- Something is permanently changed/wrong
- Final image/sound that haunts the listener
- Ambiguous ending: Did they escape? Or did the horror win?

## ENDING OPTIONS (choose what fits the story):
A) "It's over... or is it?" (subtle hint horror continues)
B) "They escaped, but lost something essential" (pyrrhic victory)
C) "The horror was inside all along" (psychological reveal)
D) "It was never about them" (cosmic indifference)

## RULES
- The false hope section is ESSENTIAL. Don't skip it.
- Peak horror should last at least 10 turns
- Final narrator line should be poetic and haunting
- DO NOT explain everything. Leave 30% ambiguous.
- The last sound/image should linger in the listener's mind"""

PROMPTS["image_style"] = """dark horror manga illustration style, high contrast black and white with selective red accents, heavy ink shadows, dramatic chiaroscuro lighting, thick expressive linework, psychological horror atmosphere, unsettling composition with tilted angles, deep blacks and stark whites, hatching and cross-hatching for texture, Korean manhwa horror aesthetic, single character focus, detailed emotional expressions showing fear and dread, atmospheric fog and shadow effects, masterpiece quality illustration"""

PROMPTS["image_llm_prompt"] = """You are an SD prompt engineer for Korean horror radio drama illustrations.

## YOUR ROLE
Convert a Korean horror script scene description into an optimized Stable Diffusion prompt.

## ART STYLE (MANDATORY - always include)
dark horror manga illustration, high contrast monochrome with selective red, heavy ink shadows, dramatic chiaroscuro, thick linework, Korean manhwa horror style

## RULES
1. Output ONLY the SD prompt in English. No explanations.
2. Focus on ONE character per image. Never generate multiple people.
3. Describe the CHARACTER'S emotion through body language and facial expression.
4. Include ATMOSPHERE keywords: lighting, shadows, fog, composition.
5. Maximum 75 tokens for the prompt.
6. Use parentheses for emphasis: (keyword:1.3) for important elements.

## HORROR-SPECIFIC TECHNIQUES
- Use "(dark shadows:1.3)" for dread scenes
- Use "(extreme close-up:1.2)" for fear/shock moments
- Use "(dutch angle:1.2)" for disorientation
- Use "(silhouette:1.3)" for mysterious/threatening figures
- Use "(backlit:1.2)" for ominous reveals
- Use "(empty corridor:1.2), (vanishing point:1.1)" for isolation

## SCENE TYPE MAPPINGS
| Scene Mood | Lighting | Composition | Focus |
|---|---|---|---|
| Creepy calm | dim ambient, single light source | centered, negative space | character's subtle unease |
| Building dread | harsh side lighting, long shadows | off-center, tilted | character looking away/behind |
| Peak horror | dramatic backlight, deep shadows | extreme close-up or wide isolation | fear expression, body tension |
| Aftermath | muted, grey, flat lighting | centered, empty space around | exhaustion, thousand-yard stare |

## CHARACTER AGE MAPPING
- 청년/젊은이 → young adult, early 20s
- 회사원/직장인 → office worker, 30s
- 중년 → middle-aged, 40s-50s
- 노인/할머니/할아버지 → elderly, 60s+
- 아이/어린이 → child, young

## EXAMPLE
Input: "주인공이 어두운 복도에서 뒤에서 발자국 소리를 듣고 천천히 뒤돌아보는 장면"
Output: (dark horror manga illustration:1.2), young woman looking over shoulder in fear, (dark empty corridor:1.3), (dramatic backlight:1.2), long shadows on floor, (dutch angle:1.1), expression of dread, single figure, heavy ink shadows, high contrast monochrome, atmospheric fog, masterpiece"""


def main():
    if not os.path.exists(PACK_PATH):
        print(f"[ERROR] 팩 파일 없음: {PACK_PATH}")
        sys.exit(1)

    fernet = get_fernet()

    # 임시 디렉토리에 기존 파일 추출
    tmp_dir = tempfile.mkdtemp(prefix="horror_v59_")
    print(f"[INFO] 임시 디렉토리: {tmp_dir}")

    try:
        # 기존 .revpack 추출
        with zipfile.ZipFile(PACK_PATH, 'r') as zf:
            zf.extractall(tmp_dir)
            existing_files = zf.namelist()
        print(f"[INFO] 기존 파일 {len(existing_files)}개 추출 완료")
        for f in existing_files:
            print(f"  - {f}")

        # 16개 프롬프트 파일 추가
        prompts_dir = os.path.join(tmp_dir, "prompts")
        os.makedirs(prompts_dir, exist_ok=True)

        added = 0
        for name, content in PROMPTS.items():
            content_bytes = content.strip().encode('utf-8')

            if fernet:
                encrypted = fernet.encrypt(content_bytes)
                file_path = os.path.join(prompts_dir, f"{name}.txt.enc")
                with open(file_path, 'wb') as f:
                    f.write(encrypted)
                print(f"  [+] prompts/{name}.txt.enc ({len(encrypted)} bytes, encrypted)")
            else:
                file_path = os.path.join(prompts_dir, f"{name}.txt")
                with open(file_path, 'wb') as f:
                    f.write(content_bytes)
                print(f"  [+] prompts/{name}.txt ({len(content_bytes)} bytes, plaintext)")
            added += 1

        # 새 .revpack 재빌드
        backup_path = PACK_PATH + ".bak"
        shutil.copy2(PACK_PATH, backup_path)
        print(f"[INFO] 백업: {backup_path}")

        with zipfile.ZipFile(PACK_PATH, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(tmp_dir):
                for file in files:
                    full_path = os.path.join(root, file)
                    arc_name = os.path.relpath(full_path, tmp_dir)
                    zf.write(full_path, arc_name)
                    # print(f"  [ZIP] {arc_name}")

        # 최종 확인
        with zipfile.ZipFile(PACK_PATH, 'r') as zf:
            final_files = zf.namelist()
        print(f"\n[SUCCESS] horror_v59.revpack 재빌드 완료!")
        print(f"  기존: {len(existing_files)}개 → 최종: {len(final_files)}개 (+{added} 프롬프트)")
        print(f"\n최종 파일 목록:")
        for f in sorted(final_files):
            print(f"  - {f}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"\n[CLEANUP] 임시 디렉토리 삭제 완료")


if __name__ == "__main__":
    main()
