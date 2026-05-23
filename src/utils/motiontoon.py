from __future__ import annotations

from dataclasses import asdict, is_dataclass
import re
from typing import Any, Dict, List, Optional


DEFAULT_PROP_KEYWORDS = [
    "문자",
    "계좌",
    "장부",
    "봉투",
    "편지",
    "녹음",
    "사진",
    "통장",
    "계약서",
    "영수증",
    "phone",
    "message",
    "document",
    "bank",
    "envelope",
    "photo",
]

SCAM_ALERT_OVERLAY_KEYWORDS = {
    "message": ["문자", "메시지", "카톡", "톡", "알림", "연락"],
    "call": ["전화", "통화", "ars", "고객센터", "상담원", "보이스피싱"],
    "bank": ["계좌", "송금", "이체", "입금", "출금", "통장", "영수증", "은행", "비밀번호", "주민번호", "금고"],
    "document": ["계약서", "위임장", "서류", "증거", "녹음", "사진", "송장"],
}

LIFE_SAGUK_OVERLAY_KEYWORDS = {
    "letter": ["서찰", "편지", "혼서", "봉투", "연서", "밀지"],
    "ledger": ["장부", "차용증", "약조", "서약", "문서", "서류", "교지", "증표"],
    "seal": ["인장", "도장", "봉인", "낙관"],
    "decree": ["교서", "명", "어명", "관문", "패물"],
}

DEFAULT_OVERLAY_KEYWORDS = {
    "document": ["문서", "서류", "증거", "편지", "사진"],
    "message": ["문자", "메시지", "연락"],
}

SHOCK_KEYWORDS = ["안 돼", "뭐라고", "당장", "거짓말", "들켰", "끝이야", "설마", "!"]
FEAR_KEYWORDS = ["무서", "떨", "숨", "차갑", "소름", "불길", "scared", "fear"]
MEMORY_KEYWORDS = ["그날", "예전", "기억", "처음", "오래전", "다시"]
REVEAL_KEYWORDS = ["진실", "비밀", "들켰", "증거", "알고", "밝혀", "고백", "폭로"]
CONFRONTATION_KEYWORDS = ["왜", "당신", "네가", "거짓말", "그만", "대답", "?"]

NARRATOR_SPEAKER_ALIASES = {
    "narrator",
    "narration",
    "narrator_male",
    "narrator_female",
    "voiceover",
    "나레이터",
    "나레이션",
    "내레이터",
    "내레이션",
    "해설",
    "해설자",
}


def _coerce_dict(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if is_dataclass(raw):
        return asdict(raw)
    data = getattr(raw, "__dict__", None)
    if isinstance(data, dict):
        return dict(data)
    return {}


def normalize_motiontoon_config(raw: Any, *, fallback_enabled: bool = False) -> Dict[str, Any]:
    data = _coerce_dict(raw)

    prop_keywords = data.get("prop_keywords") or data.get("propKeywords") or DEFAULT_PROP_KEYWORDS
    if isinstance(prop_keywords, dict):
        prop_keywords = list(prop_keywords.keys())
    if not isinstance(prop_keywords, list):
        prop_keywords = list(DEFAULT_PROP_KEYWORDS)

    return {
        "enabled": bool(data.get("enabled", fallback_enabled)),
        "mode": str(data.get("mode", "screen_space")),
        "profile": str(data.get("profile", "basic") or "basic"),
        "overlay_theme": str(data.get("overlay_theme", "default") or "default"),
        "character_layer_mode": str(data.get("character_layer_mode", "") or ""),
        "default_scene_type": str(data.get("default_scene_type", "dialogue")),
        "blink_enabled": bool(data.get("blink_enabled", False)),
        "mouth_flap_enabled": bool(data.get("mouth_flap_enabled", False)),
        "layered_cutout_enabled": bool(data.get("layered_cutout_enabled", False)),
        "layered_cutout_strength": float(data.get("layered_cutout_strength", 0.65) or 0.65),
        "prop_overlay_enabled": bool(data.get("prop_overlay_enabled", True)),
        "dialogue_panel_enabled": bool(data.get("dialogue_panel_enabled", True)),
        "idle_drift_enabled": bool(data.get("idle_drift_enabled", True)),
        "impact_shake_enabled": bool(data.get("impact_shake_enabled", True)),
        "snap_zoom_enabled": bool(data.get("snap_zoom_enabled", True)),
        "subtitle_pulse_enabled": bool(data.get("subtitle_pulse_enabled", True)),
        "slow_push_enabled": bool(data.get("slow_push_enabled", True)),
        "shorts_vertical_ready": bool(data.get("shorts_vertical_ready", True)),
        "prop_keywords": [str(keyword) for keyword in prop_keywords if keyword],
        "scene_motion_rules": _coerce_dict(data.get("scene_motion_rules")),
        "cast_slots": _coerce_dict(data.get("cast_slots")),
        "actor_pool": _coerce_dict(data.get("actor_pool")),
        "role_casting_contract": _coerce_dict(data.get("role_casting_contract")),
        "puppet_profiles": _coerce_dict(data.get("puppet_profiles")),
    }


def _contains_any(text: str, keywords: List[str]) -> bool:
    lowered = (text or "").lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _speaker_key(speaker: str) -> str:
    return (speaker or "").strip().lower()


def _is_narrator_speaker(speaker: str) -> bool:
    return _speaker_key(speaker) in NARRATOR_SPEAKER_ALIASES


def infer_scene_type(text: str, speaker: str, config: Optional[Dict[str, Any]] = None) -> str:
    config = config or {}
    prop_keywords = config.get("prop_keywords") or DEFAULT_PROP_KEYWORDS
    stripped = (text or "").strip()

    if _contains_any(stripped, CONFRONTATION_KEYWORDS):
        return "confrontation"
    if _contains_any(stripped, list(prop_keywords)):
        return "prop_reveal"
    if _contains_any(stripped, SHOCK_KEYWORDS):
        return "shock_entry"
    if _contains_any(stripped, REVEAL_KEYWORDS):
        return "reveal"
    if _is_narrator_speaker(speaker) and _contains_any(stripped, MEMORY_KEYWORDS):
        return "memory_object"
    return config.get("default_scene_type", "dialogue")


def infer_dominant_emotion(text: str) -> str:
    stripped = (text or "").strip()
    if _contains_any(stripped, FEAR_KEYWORDS):
        return "fear"
    if _contains_any(stripped, ["울", "후회", "미안", "sad", "눈물"]):
        return "sadness"
    if _contains_any(stripped, ["분노", "화가", "angry", "당장", "그만"]):
        return "anger"
    if _contains_any(stripped, SHOCK_KEYWORDS):
        return "shock"
    if _contains_any(stripped, ["따뜻", "행복", "웃", "다행", "warm"]):
        return "warmth"
    return "tension"


def _get_overlay_keyword_map(theme: str) -> Dict[str, List[str]]:
    normalized = (theme or "default").strip().lower()
    if normalized == "scam_alert":
        return SCAM_ALERT_OVERLAY_KEYWORDS
    if normalized == "life_saguk":
        return LIFE_SAGUK_OVERLAY_KEYWORDS
    return DEFAULT_OVERLAY_KEYWORDS


def infer_overlay_kind(text: str, scene_type: str, config: Optional[Dict[str, Any]] = None) -> str:
    cfg = config or {}
    if not cfg.get("prop_overlay_enabled", True) and scene_type == "prop_reveal":
        return ""

    lowered = (text or "").strip().lower()
    keyword_map = _get_overlay_keyword_map(cfg.get("overlay_theme", "default"))

    for overlay_kind, keywords in keyword_map.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            return overlay_kind

    if scene_type == "prop_reveal":
        return "document"
    if scene_type == "confrontation" and cfg.get("dialogue_panel_enabled", True):
        return "dialogue_panel"
    return ""


def _compact_overlay_text(text: str, limit: int = 42) -> str:
    compact = " ".join((text or "").replace("\n", " ").split())
    return compact[:limit].rstrip()


def _extract_amount_token(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""

    money_match = re.search(
        r"(?:\d[\d,]*\s*(?:조원|억원|천만원|백만원|만원|조|억|천만|백만|만|원))+",
        raw,
    )
    if money_match:
        return re.sub(r"\s+", "", money_match.group(0))

    plain_number = re.search(r"\d[\d,]{3,}", raw)
    if plain_number:
        return f"{plain_number.group(0)}원"

    return ""


def _build_overlay_payload(text: str, overlay_kind: str) -> Dict[str, Any]:
    compact = _compact_overlay_text(text)
    amount = _extract_amount_token(text)

    if not overlay_kind:
        return {
            "lines": [],
            "subtitle_mode": "default",
            "confrontation_style": "none",
        }

    if overlay_kind == "message":
        return {
            "lines": [
                "긴급 알림 도착",
                f"{amount} 관련 안내" if amount else "출처 불명 링크 주의",
            ],
            "subtitle_mode": "overlay_safe",
            "confrontation_style": "none",
        }

    if overlay_kind == "call":
        return {
            "lines": [
                "발신: 확인되지 않음",
                f"즉시 {amount} 송금 요구" if amount else "즉시 송금 요구",
            ],
            "subtitle_mode": "overlay_safe",
            "confrontation_style": "none",
        }

    if overlay_kind == "bank":
        return {
            "lines": [
                f"입금 {amount or '50,000,000원'}",
                "OO은행 → XX은행",
                "방금 전 처리",
            ],
            "subtitle_mode": "overlay_safe",
            "confrontation_style": "none",
        }

    if overlay_kind == "document":
        return {
            "lines": [
                "증거 자료 확인",
                f"금액: {amount}" if amount else "이름/금액/계좌 포함",
                "원본 대조 필요",
            ],
            "subtitle_mode": "overlay_safe",
            "confrontation_style": "none",
        }

    if overlay_kind == "ledger":
        return {
            "lines": [
                "장부 항목 확인",
                f"차용액: {amount}" if amount else "차용 기록 존재",
                "봉인 전 보관",
            ],
            "subtitle_mode": "overlay_safe",
            "confrontation_style": "none",
        }

    if overlay_kind == "decree":
        return {
            "lines": [
                "문서 확인",
                "관인/발급처 대조",
                "즉시 회수 필요",
            ],
            "subtitle_mode": "overlay_safe",
            "confrontation_style": "none",
        }

    if overlay_kind == "letter":
        return {
            "lines": [
                "서찰 일부",
                "급히 오라 하셨소",
                "답장을 기다리오",
            ],
            "subtitle_mode": "overlay_safe",
            "confrontation_style": "none",
        }

    if overlay_kind == "seal":
        return {
            "lines": [
                "봉인 훼손 흔적",
                "밀지 첨부",
                "즉시 회수 필요",
            ],
            "subtitle_mode": "overlay_safe",
            "confrontation_style": "none",
        }

    if overlay_kind == "dialogue_panel":
        first = compact[:22].strip()
        second = compact[22:44].strip()
        lines = [line for line in [first, second] if line]
        return {
            "lines": lines,
            "subtitle_mode": "ribbon_only",
            "confrontation_style": "ribbon_only",
        }

    first = compact[:20].strip()
    second = compact[20:40].strip()
    return {
        "lines": [line for line in [first, second] if line],
        "subtitle_mode": "default",
        "confrontation_style": "none",
    }


def build_overlay_lines(text: str, overlay_kind: str) -> List[str]:
    return [line for line in _build_overlay_payload(text, overlay_kind).get("lines", []) if line]


def build_overlay_label(overlay_kind: str, config: Optional[Dict[str, Any]] = None) -> str:
    theme = (config or {}).get("overlay_theme", "default")
    if theme == "scam_alert":
        labels = {
            "message": "긴급 문자",
            "call": "통화 기록",
            "bank": "거래 내역",
            "document": "증거 서류",
            "dialogue_panel": "대치 장면",
        }
        return labels.get(overlay_kind, "증거 포착")
    if theme == "life_saguk":
        labels = {
            "letter": "서찰 공개",
            "ledger": "장부 확인",
            "seal": "봉인 파기",
            "decree": "문서 확인",
            "dialogue_panel": "정면 대치",
        }
        return labels.get(overlay_kind, "장면 강조")
    labels = {
        "message": "핵심 문자",
        "document": "핵심 증거",
        "dialogue_panel": "대치 장면",
    }
    return labels.get(overlay_kind, "포인트 장면")


def infer_cast_slot(speaker: str, scene_type: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    cfg = config or {}
    slots = cfg.get("cast_slots") or {}
    speaker_lower = (speaker or "").strip().lower()

    for slot_name, slot_data in slots.items():
        if not isinstance(slot_data, dict):
            continue
        aliases = [str(alias).strip().lower() for alias in slot_data.get("aliases", []) if str(alias).strip()]
        character_id = str(slot_data.get("character_id", "") or "")
        if speaker_lower and speaker_lower in aliases:
            return {
                "cast_slot": str(slot_name),
                "character_id_hint": character_id,
            }

    if scene_type == "dialogue" and "protagonist" in slots:
        protagonist = slots.get("protagonist") or {}
        return {
            "cast_slot": "protagonist",
            "character_id_hint": str(protagonist.get("character_id", "") or ""),
        }

    return {
        "cast_slot": "",
        "character_id_hint": "",
    }


def infer_face_rig(scene_type: str, speaker: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = config or {}
    if str(cfg.get("character_layer_mode", "") or "").strip().lower() in {"simple_sprite", "character_sprite"}:
        cast_hint = infer_cast_slot(speaker, scene_type, cfg)
        puppet_profiles = cfg.get("puppet_profiles") or {}
        slot = cast_hint["cast_slot"]
        profile = puppet_profiles.get(slot, {}) if isinstance(puppet_profiles, dict) else {}
        puppet_bob_enabled = bool(cfg.get("puppet_bob_enabled", False))
        return {
            "face_rig": bool(cfg.get("blink_enabled", False) or cfg.get("mouth_flap_enabled", False)),
            "face_anchor_x": float(profile.get("face_anchor_x", 0.5) or 0.5),
            "face_anchor_y": float(profile.get("face_anchor_y", 0.33) or 0.33),
            "face_scale": float(profile.get("face_scale", 1.0) or 1.0),
            "puppet_bob": puppet_bob_enabled,
            "bob_strength": float(profile.get("bob_strength", 0.12) or 0.12),
        }
    cast_hint = infer_cast_slot(speaker, scene_type, cfg)
    puppet_profiles = cfg.get("puppet_profiles") or {}
    if _is_narrator_speaker(speaker):
        return {
            "face_rig": False,
            "face_anchor_x": 0.5,
            "face_anchor_y": 0.33,
            "face_scale": 1.0,
            "puppet_bob": False,
            "bob_strength": 0.0,
        }

    slot = cast_hint["cast_slot"]
    theme = (cfg.get("overlay_theme") or "default").strip().lower()
    anchor_y = 0.33
    anchor_x = 0.5
    scale = 1.0
    bob_strength = 1.0
    if slot in {"elder", "support"}:
        anchor_y = 0.31
        scale = 0.92
        bob_strength = 0.72
    elif slot == "antagonist":
        anchor_y = 0.34
        scale = 1.05
        bob_strength = 0.88
    elif slot == "deuteragonist":
        anchor_y = 0.335
        scale = 0.98
        anchor_x = 0.49

    if theme == "life_saguk":
        anchor_y -= 0.01
        scale *= 0.96

    profile = puppet_profiles.get(slot, {}) if isinstance(puppet_profiles, dict) else {}
    if isinstance(profile, dict):
        anchor_x = float(profile.get("face_anchor_x", anchor_x) or anchor_x)
        anchor_y = float(profile.get("face_anchor_y", anchor_y) or anchor_y)
        scale = float(profile.get("face_scale", scale) or scale)
        bob_strength = float(profile.get("bob_strength", bob_strength) or bob_strength)

    return {
        "face_rig": bool(cfg.get("blink_enabled", False) or cfg.get("mouth_flap_enabled", False)),
        "face_anchor_x": anchor_x,
        "face_anchor_y": anchor_y,
        "face_scale": scale,
        "puppet_bob": True,
        "bob_strength": bob_strength,
    }


def build_scene_motion_directive(
    *,
    text: str,
    speaker: str,
    duration_frames: int,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    cfg = normalize_motiontoon_config(config)
    if not cfg.get("enabled"):
        return {}

    scene_type = infer_scene_type(text, speaker, cfg)
    dominant_emotion = infer_dominant_emotion(text)
    render_mode = str(cfg.get("mode", "classic_dynamic") or "classic_dynamic").strip().lower()
    is_gishini = render_mode == "gishini_motiontoon"
    simple_sprite_mode = str(cfg.get("character_layer_mode", "") or "").strip().lower() in {"simple_sprite", "character_sprite"}
    overlay_kind = "" if is_gishini else infer_overlay_kind(text, scene_type, cfg)
    cast_hint = infer_cast_slot(speaker, scene_type, cfg)
    face_rig = infer_face_rig(scene_type, speaker, cfg)
    overlay_payload = _build_overlay_payload(text, overlay_kind) if not is_gishini else {
        "lines": [],
        "subtitle_mode": "default",
        "confrontation_style": "none",
    }
    if simple_sprite_mode and overlay_kind == "dialogue_panel":
        overlay_payload = {
            **overlay_payload,
            "subtitle_mode": "default",
            "confrontation_style": "none",
        }
    overlay_lines = [line for line in overlay_payload.get("lines", []) if line]
    primitives: List[str] = []

    # v63.1: classic_dynamic에서 모션 효과를 랜덤으로 분배
    # idle_drift만 항상 나오는 것이 아니라, 씬마다 다른 효과가 돌아가면서 적용
    import random as _rand
    _scene_hash = hash((text or "")[:20] + (speaker or ""))  # 결정론적 시드 (같은 씬 = 같은 효과)
    _rng = _rand.Random(_scene_hash)

    if simple_sprite_mode:
        if cfg.get("slow_push_enabled"):
            primitives.append("slow_push")
    elif not is_gishini:
        # v63.1: classic_dynamic — 씬별 랜덤 기본 효과 선택
        _base_effects = []
        if cfg.get("idle_drift_enabled"):
            _base_effects.append("idle_drift")
        if cfg.get("slow_push_enabled"):
            _base_effects.append("slow_push")
        # 기본 효과 중 1개를 랜덤 선택 (매 씬마다 다름)
        if _base_effects:
            primitives.append(_rng.choice(_base_effects))

        # 강조 효과 — 씬 타입/감정 기반 (기존 로직 유지 + 확률 추가)
        if scene_type in {"prop_reveal", "shock_entry", "reveal"} and cfg.get("snap_zoom_enabled"):
            primitives.append("snap_zoom")
        elif scene_type == "confrontation" and cfg.get("snap_zoom_enabled"):
            if _rng.random() < 0.7:  # 70% 확률
                primitives.append("snap_zoom")

        if scene_type in {"shock_entry", "confrontation"} and cfg.get("impact_shake_enabled"):
            primitives.append("impact_shake")

        if dominant_emotion in {"fear", "sadness"} and cfg.get("slow_push_enabled"):
            if "slow_push" not in primitives:  # 중복 방지
                primitives.append("slow_push")
        elif scene_type in {"dialogue", "memory_object"} and cfg.get("slow_push_enabled"):
            if "slow_push" not in primitives and _rng.random() < 0.5:  # 50% 확률
                primitives.append("slow_push")
    else:
        # gishini 모드는 기존 로직 유지
        if cfg.get("idle_drift_enabled"):
            primitives.append("idle_drift")

    if _speaker_key(speaker) and not _is_narrator_speaker(speaker) and cfg.get("subtitle_pulse_enabled"):
        primitives.append("subtitle_pulse")

    motion_priority = "low"
    if scene_type in {"prop_reveal", "shock_entry", "reveal"}:
        motion_priority = "high"
    elif scene_type in {"confrontation", "memory_object"} or dominant_emotion in {"fear", "anger"}:
        motion_priority = "medium"

    shorts_candidate = motion_priority == "high" or (len((text or "").strip()) <= 36 and "subtitle_pulse" in primitives)

    return {
        "scene_type": scene_type,
        "dominant_emotion": dominant_emotion,
        "motion_priority": motion_priority,
        "primitives": primitives,
        "prop_focus": False if is_gishini else scene_type == "prop_reveal",
        "overlay_theme": cfg.get("overlay_theme", "default"),
        "overlay_kind": overlay_kind,
        "overlay_label": build_overlay_label(overlay_kind, cfg) if overlay_kind else "",
        "overlay_lines": overlay_lines,
        "dialogue_panel": False if (is_gishini or simple_sprite_mode) else bool(scene_type == "confrontation" and cfg.get("dialogue_panel_enabled", True)),
        "subtitle_mode": overlay_payload.get("subtitle_mode", "default"),
        "confrontation_style": overlay_payload.get("confrontation_style", "none"),
        "character_layer_mode": cfg.get("character_layer_mode", ""),
        "use_layered_cutout": bool(cfg.get("layered_cutout_enabled", False)),
        "layered_cutout_strength": float(cfg.get("layered_cutout_strength", 0.65) or 0.65),
        "cast_slot": cast_hint["cast_slot"],
        "character_id_hint": cast_hint["character_id_hint"],
        "face_rig": face_rig["face_rig"],
        "face_anchor_x": face_rig["face_anchor_x"],
        "face_anchor_y": face_rig["face_anchor_y"],
        "face_scale": face_rig["face_scale"],
        "puppet_bob": face_rig["puppet_bob"],
        "bob_strength": face_rig["bob_strength"],
        "shorts_candidate": shorts_candidate,
        "duration_frames": max(1, int(duration_frames or 1)),
    }


def build_motiontoon_plan(
    script_list: List[Dict[str, Any]],
    *,
    cold_open: Optional[List[Dict[str, Any]]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    cfg = normalize_motiontoon_config(config)
    if not cfg.get("enabled"):
        return {"enabled": False, "mode": cfg["mode"], "scenes": []}

    scenes: List[Dict[str, Any]] = []
    cold_open_lines = {
        (turn.get("text") or "").strip()
        for turn in (cold_open or [])
        if isinstance(turn, dict)
    }

    for index, turn in enumerate(script_list or []):
        text = (turn.get("text") or "").strip()
        speaker = turn.get("character") or turn.get("role") or turn.get("speaker") or ""
        directive = build_scene_motion_directive(
            text=text,
            speaker=speaker,
            duration_frames=int(turn.get("duration_frames") or 1),
            config=cfg,
        )
        if not directive:
            continue
        directive["index"] = index
        directive["speaker"] = speaker
        directive["preview_text"] = text[:80]
        directive["is_cold_open"] = text in cold_open_lines
        scenes.append(directive)

    return {
        "enabled": True,
        "mode": cfg["mode"],
        "shorts_vertical_ready": cfg["shorts_vertical_ready"],
        "scenes": scenes,
    }
