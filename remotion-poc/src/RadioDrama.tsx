import { AbsoluteFill, Audio, Img, Sequence, useCurrentFrame, useVideoConfig, interpolate, staticFile } from "remotion";
import React from "react";

// v59: 鍮꾩＜???댄럺??????뺤쓽
type VignetteType = "none" | "light" | "medium" | "heavy" | "horror";
type ColorFilterType = "none" | "sepia" | "cold" | "warm" | "noir" | "vintage" | "horror_green";
type TransitionType = "cut" | "fade" | "dissolve" | "wipe_left" | "wipe_right";

// v59: 鍮꾩＜???댄럺???ㅼ젙 ?명꽣?섏씠??
interface VisualEffectsConfig {
  vignette?: VignetteType;
  colorFilter?: ColorFilterType;
  transition?: TransitionType;
  transitionDuration?: number;  // ?꾨젅??
}

// v59: ?먮쭑 ?ㅽ????명꽣?섏씠??
interface SubtitleStyleConfig {
  fontFamily?: string;
  fontSize?: number;
  speakerFontSize?: number;
  backgroundColor?: string;
  backgroundPadding?: number;
  backgroundRadius?: number;
  marginBottom?: number;
  textColor?: string;
  speakerColors?: Record<string, string>;
  position?: "bottom" | "center" | "top";
  style?: "default" | "horror" | "elegant" | "webtoon";
}

// v59.4: 耳?踰덉뒪 紐⑤뱶 ????뺤쓽
type KenBurnsMode = "zoom_in" | "zoom_out" | "pan_left" | "pan_right" | "pan_up" | "pan_down";

interface MouthCue {
  frame: number;
  mouth?: number;
  energy?: number;
}

interface ImageData {
  path: string;
  backgroundPath?: string;
  foregroundPath?: string;
  headPath?: string;
  bodyPath?: string;
  leftArmPath?: string;
  rightArmPath?: string;
  eyesOpenPath?: string;
  eyesClosedPath?: string;
  mouthClosedPath?: string;
  mouthOpenPath?: string;
  mouthCues?: MouthCue[];
  startFrame: number;
  durationFrames: number;
  motion?: MotionDirective;
  // v59.4: ?대?吏蹂?耳?踰덉뒪 ?ㅼ젙
  kenBurns?: {
    mode: KenBurnsMode;
    intensity?: number;  // 0.05~0.15, 湲곕낯 0.08
  };
}

interface SubtitleData {
  text: string;
  speaker: string;
  speakerColor?: string;  // v57.4: Python?먯꽌 ?꾨떖?섎뒗 ?붿옄 ?됱긽
  startFrame: number;
  durationFrames: number;
  motion?: MotionDirective;
}

interface MotionDirective {
  scene_type?: string;
  dominant_emotion?: string;
  motion_priority?: "low" | "medium" | "high";
  primitives?: string[];
  pose_hint?: string;
  shorts_candidate?: boolean;
  prop_focus?: boolean;
  overlay_theme?: string;
  overlay_kind?: string;
  overlay_label?: string;
  overlay_lines?: string[];
  dialogue_panel?: boolean;
  subtitle_mode?: "default" | "hidden" | "ribbon_only" | "overlay_safe";
  confrontation_style?: "none" | "split" | "ribbon_only";
  character_layer_mode?: string;
  use_layered_cutout?: boolean;
  layered_cutout_strength?: number;
  face_rig?: boolean;
  face_anchor_x?: number;
  face_anchor_y?: number;
  face_scale?: number;
  puppet_bob?: boolean;
  bob_strength?: number;
  cast_slot?: string;
  character_id_hint?: string;
  sprite_center_x?: number;
  sprite_center_y?: number;
  sprite_width_ratio?: number;
  sprite_height_ratio?: number;
  sprite_kind?: string;
  shot_size?: string;
  acting_pose?: string;
  sprite_enter_px?: number;
  sprite_parallax_px?: number;
  sprite_lean_deg?: number;
  sprite_breathe_px?: number;
  sprite_focus_scale?: number;
}

interface MotiontoonConfig {
  enabled?: boolean;
  mode?: string;
  shorts_vertical_ready?: boolean;
}

interface AudioSegment {
  path: string;
  startFrame: number;
}

// v59.3.5: SFX ?④낵???명꽣?섏씠??(FFmpeg 誘뱀떛 ?쒓굅, Remotion ?듯빀)
interface SFXCue {
  path: string;           // SFX ?뚯씪 寃쎈줈 (public ?대뜑 ?곷?)
  startFrame: number;     // ?쎌엯 ?쒖옉 ?꾨젅??
  volume: number;         // 蹂쇰ⅷ (0.0 ~ 1.0)
  durationFrames?: number; // 吏???꾨젅??(?놁쑝硫??뚯씪 ?꾩껜)
  fadeInFrames?: number;  // ?섏씠?????꾨젅??
  fadeOutFrames?: number; // ?섏씠???꾩썐 ?꾨젅??
}

// v58.4.0: Hook ?곗씠???명꽣?섏씠??
interface HookData {
  topLabel: string;      // ?곷떒 ?쇰꺼 (?? "??愿?????)
  topColor: string;      // ?곷떒 ?쇰꺼 ?됱긽
  mainText: string;      // 硫붿씤 二쇱젣 ?띿뒪??
  mainColor: string;     // 硫붿씤 ?띿뒪???됱긽
  bgColor: string;       // 諛곌꼍??(hex)
  durationFrames: number; // hook 湲몄씠 (?꾨젅??
}

interface RadioDramaProps {
  images: ImageData[];
  audioSegments: AudioSegment[];
  subtitles: SubtitleData[];
  motiontoon?: MotiontoonConfig;
  bgmPath?: string;
  bgmVolume?: number;
  // v57.4: 梨꾨꼸蹂??먮쭑 ?ш린 ?ㅼ젙
  subtitleSize?: number;   // ?먮쭑 湲???ш린 (湲곕낯: 36)
  speakerSize?: number;    // ?붿옄紐??ш린 (湲곕낯: 28)
  // v58.1: AI ?쒖옉 ?쒓린 (AI踰?以??
  showAiDisclosure?: boolean;  // AI ?쒖옉 ?쒓린 ?쒖떆 ?щ? (湲곕낯: true)
  aiDisclosureDuration?: number;  // ?쒖떆 ?쒓컙 (珥? 湲곕낯: 3)
  // v58.1: TTS 蹂쇰ⅷ ?ㅼ젙
  ttsVolume?: number;  // TTS 蹂쇰ⅷ 諛곗닔 (湲곕낯: 1.0, 蹂쇰ⅷ 利앺룺? FFmpeg?먯꽌)
  // v58.3.3: ?꾩껜 TTS ?ㅻ뵒???뚯씪 (媛쒕퀎 ?멸렇癒쇳듃 ????ъ슜)
  fullAudioPath?: string;  // full.wav 寃쎈줈 (MoviePy ?쒓굅??
  // v58.4.0: Hook ?곗씠??(?ъ“由??쒓굅, Remotion ?듯빀)
  hook?: HookData;  // hook ?뺣낫 (?놁쑝硫?hook ?놁씠 蹂명렪留?
  // v59: 鍮꾩＜???ㅽ넗由ы뀛留??ㅼ젙
  visualEffects?: VisualEffectsConfig;  // 鍮꾩＜???댄럺???ㅼ젙
  subtitleStyle?: SubtitleStyleConfig;  // ?먮쭑 ?ㅽ????ㅼ젙
  // v59.3.5: SFX ?④낵??(FFmpeg ?쒓굅, Remotion ?듯빀)
  sfxCues?: SFXCue[];  // ?④낵????由ъ뒪??
}

// v59: Vignette 而댄룷?뚰듃 (?ｌ? ?대몼寃?
const Vignette: React.FC<{ type: VignetteType }> = ({ type }: { type: VignetteType }) => {
  if (type === "none") return null;

  const intensityMap: Record<VignetteType, string> = {
    none: "transparent",
    light: "rgba(0,0,0,0.3)",
    medium: "rgba(0,0,0,0.5)",
    heavy: "rgba(0,0,0,0.7)",
    horror: "rgba(0,0,0,0.85)",
  };

  const intensity = intensityMap[type];

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: `radial-gradient(ellipse at center, transparent 40%, ${intensity} 100%)`,
        pointerEvents: "none",
        zIndex: 10,
      }}
    />
  );
};

// v59: ColorFilter 而댄룷?뚰듃 (?됱긽 ?꾪꽣)
const ColorFilter: React.FC<{ type: ColorFilterType }> = ({ type }: { type: ColorFilterType }) => {
  if (type === "none") return null;

  const filterMap: Record<ColorFilterType, React.CSSProperties> = {
    none: {},
    sepia: {
      backgroundColor: "rgba(112, 66, 20, 0.2)",
      mixBlendMode: "multiply" as const,
    },
    cold: {
      backgroundColor: "rgba(100, 149, 237, 0.15)",
      mixBlendMode: "multiply" as const,
    },
    warm: {
      backgroundColor: "rgba(255, 165, 0, 0.1)",
      mixBlendMode: "multiply" as const,
    },
    noir: {
      backgroundColor: "rgba(0, 0, 0, 0.3)",
      mixBlendMode: "saturation" as const,
    },
    vintage: {
      backgroundColor: "rgba(139, 90, 43, 0.25)",
      mixBlendMode: "multiply" as const,
    },
    horror_green: {
      backgroundColor: "rgba(0, 80, 20, 0.2)",
      mixBlendMode: "multiply" as const,
    },
  };

  const style = filterMap[type];

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        ...style,
        pointerEvents: "none",
        zIndex: 9,
      }}
    />
  );
};

// v59.4: ?μ긽???대?吏 而댄룷?뚰듃 (Ken Burns 6紐⑤뱶 + ?몃옖吏??
interface EnhancedImageProps {
  src: string;
  backgroundSrc?: string;
  foregroundSrc?: string;
  headSrc?: string;
  bodySrc?: string;
  leftArmSrc?: string;
  rightArmSrc?: string;
  eyesOpenSrc?: string;
  eyesClosedSrc?: string;
  mouthClosedSrc?: string;
  mouthOpenSrc?: string;
  mouthCues?: MouthCue[];
  durationFrames: number;
  motion?: MotionDirective;
  motiontoonEnabled?: boolean;
  motiontoonMode?: string;
  transition?: TransitionType;
  transitionDuration?: number;
  vignette?: VignetteType;
  colorFilter?: ColorFilterType;
  // v59.4: 耳?踰덉뒪 紐⑤뱶蹂??쒖뼱
  kenBurnsMode?: KenBurnsMode;
  kenBurnsIntensity?: number;  // 0.05~0.15
}

const getMotionTransform = ({
  frame,
  durationFrames,
  motion,
  enabled,
}: {
  frame: number;
  durationFrames: number;
  motion?: MotionDirective;
  enabled?: boolean;
}) => {
  if (!enabled || !motion) {
    return { scaleMultiplier: 1, offsetX: 0, offsetY: 0, rotationDeg: 0 };
  }

  const primitives = motion.primitives || [];
  let scaleMultiplier = 1;
  let offsetX = 0;
  let offsetY = 0;
  let rotationDeg = 0;

  if (primitives.includes("idle_drift")) {
    offsetY += Math.sin(frame / 9) * 16;
    offsetX += Math.cos(frame / 14) * 8;
  }

  if (primitives.includes("walk_drift")) {
    offsetX += interpolate(frame, [0, durationFrames], [-28, 28], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    offsetY += Math.sin(frame / 4.5) * 10;
    rotationDeg += Math.sin(frame / 6) * 0.8;
  }

  if (primitives.includes("slow_push")) {
    scaleMultiplier *= interpolate(frame, [0, durationFrames], [1, 1.14], { extrapolateRight: "clamp" });
  }

  if (primitives.includes("snap_zoom")) {
    scaleMultiplier *= interpolate(frame, [0, 4, 10, 20], [1.28, 1.14, 1.06, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
  }

  if (primitives.includes("impact_shake")) {
    const shakeFrame = Math.min(frame, 18);
    offsetX += (shakeFrame % 2 === 0 ? 1 : -1) * (24 - shakeFrame);
    offsetY += (shakeFrame % 3 === 0 ? -1 : 1) * Math.max(0, 14 - shakeFrame / 2);
    rotationDeg += (shakeFrame % 2 === 0 ? 1 : -1) * Math.max(0, 2.6 - shakeFrame * 0.1);
  }

  return { scaleMultiplier, offsetX, offsetY, rotationDeg };
};

const OverlayHeader: React.FC<{
  label: string;
  theme: string;
}> = ({ label, theme }) => {
  const palette =
    theme === "life_saguk"
      ? { bg: "rgba(68, 35, 18, 0.9)", fg: "#f7e5bd" }
      : { bg: "rgba(14, 18, 28, 0.9)", fg: "#ffe48a" };

  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        padding: "8px 16px",
        borderRadius: 999,
        background: palette.bg,
        color: palette.fg,
        fontSize: 22,
        fontWeight: 800,
        letterSpacing: "0.08em",
        boxShadow: "0 12px 30px rgba(0,0,0,0.28)",
      }}
    >
      {label}
    </div>
  );
};

const MotiontoonPhoneCard: React.FC<{
  motion: MotionDirective;
  slideY: number;
  scale: number;
}> = ({ motion, slideY, scale }) => {
  const lines = motion.overlay_lines || [];
  return (
    <div
      style={{
        position: "absolute",
        right: "9%",
        top: "14%",
        width: 360,
        height: 620,
        borderRadius: 34,
        padding: 18,
        background: "linear-gradient(180deg, rgba(20,23,34,0.96), rgba(8,9,14,0.98))",
        border: "3px solid rgba(255,255,255,0.14)",
        boxShadow: "0 28px 90px rgba(0,0,0,0.42)",
        transform: `translateY(${slideY}px) scale(${scale})`,
        pointerEvents: "none",
        zIndex: 15,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 18,
          color: "#e6edf8",
          fontSize: 18,
          opacity: 0.85,
        }}
      >
        <span>{motion.overlay_label || "긴급 문자"}</span>
        <span>지금</span>
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 12,
          marginTop: 14,
        }}
      >
        {lines.map((line, index) => (
          <div
            key={`${line}-${index}`}
            style={{
              alignSelf: index % 2 === 0 ? "flex-start" : "flex-end",
              maxWidth: "82%",
              padding: "14px 16px",
              borderRadius: 22,
              background: index % 2 === 0 ? "rgba(45,51,67,0.94)" : "rgba(58,118,255,0.94)",
              color: "#ffffff",
              fontSize: 24,
              fontWeight: 700,
              lineHeight: 1.35,
            }}
          >
            {line}
          </div>
        ))}
      </div>
    </div>
  );
};

const MotiontoonDocumentCard: React.FC<{
  motion: MotionDirective;
  slideY: number;
  scale: number;
}> = ({ motion, slideY, scale }) => {
  const lines = motion.overlay_lines || [];
  const isSaguk = motion.overlay_theme === "life_saguk";
  return (
    <div
      style={{
        position: "absolute",
        left: "12%",
        right: "12%",
        top: "18%",
        minHeight: isSaguk ? 410 : 360,
        padding: isSaguk ? "28px 34px" : "24px 28px",
        borderRadius: isSaguk ? 10 : 24,
        background: isSaguk
          ? "linear-gradient(180deg, rgba(235,220,185,0.98), rgba(211,188,145,0.98))"
          : "linear-gradient(180deg, rgba(245,246,250,0.98), rgba(227,232,240,0.96))",
        border: isSaguk ? "4px solid rgba(109,73,40,0.75)" : "3px solid rgba(255,255,255,0.88)",
        boxShadow: "0 28px 90px rgba(0,0,0,0.42)",
        transform: `translateY(${slideY}px) scale(${scale})`,
        pointerEvents: "none",
        zIndex: 15,
      }}
    >
      <div style={{ marginBottom: 18 }}>
        <OverlayHeader
          label={motion.overlay_label || (isSaguk ? "문서 확인" : "증거 서류")}
          theme={motion.overlay_theme || "default"}
        />
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 18,
          color: isSaguk ? "#472d16" : "#1c2430",
          fontSize: isSaguk ? 30 : 28,
          fontWeight: 800,
          lineHeight: 1.45,
          fontFamily: isSaguk ? "'NanumMyeongjo', 'Malgun Gothic', serif" : "'Noto Sans KR', 'Malgun Gothic', sans-serif",
        }}
      >
        {lines.map((line, index) => (
          <div
            key={`${line}-${index}`}
            style={{
              borderBottom: isSaguk ? "2px solid rgba(110,74,42,0.35)" : "2px solid rgba(28,36,48,0.12)",
              paddingBottom: 8,
            }}
          >
            {line}
          </div>
        ))}
      </div>
      {isSaguk ? (
        <div
          style={{
            position: "absolute",
            right: 26,
            bottom: 22,
            width: 86,
            height: 86,
            borderRadius: "50%",
            border: "5px solid rgba(138, 29, 29, 0.66)",
            color: "rgba(138, 29, 29, 0.74)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 20,
            fontWeight: 800,
            transform: "rotate(-12deg)",
          }}
        >
          봉인
        </div>
      ) : null}
    </div>
  );
};

const MotiontoonDialogueRibbon: React.FC<{
  motion: MotionDirective;
}> = ({ motion }) => {
  const line = (motion.overlay_lines || [])[0];
  if (!line) {
    return null;
  }

  return (
    <div
      style={{
        position: "absolute",
        left: "10%",
        right: "10%",
        bottom: "18%",
        padding: "18px 26px",
        borderRadius: 24,
        background: "linear-gradient(90deg, rgba(0,0,0,0.84), rgba(28,32,45,0.78), rgba(0,0,0,0.84))",
        color: "#ffffff",
        fontSize: 30,
        fontWeight: 800,
        letterSpacing: "0.01em",
        lineHeight: 1.35,
        boxShadow: "0 18px 44px rgba(0,0,0,0.32)",
        pointerEvents: "none",
        zIndex: 14,
      }}
    >
      {line}
    </div>
  );
};

const MotiontoonAccent: React.FC<{
  src: string;
  motion?: MotionDirective;
  durationFrames: number;
}> = ({ src, motion, durationFrames }) => {
  const frame = useCurrentFrame();

  if (!motion) {
    return null;
  }

  const sceneType = motion.scene_type || "dialogue";
  const primitives = motion.primitives || [];
  const isImpactScene = sceneType === "shock_entry" || sceneType === "reveal" || primitives.includes("impact_shake");
  const isPropReveal = sceneType === "prop_reveal" || motion.prop_focus;
  const isConfrontation = sceneType === "confrontation" || Boolean(motion.dialogue_panel);
  const isMemory = sceneType === "memory_object";
  const overlayKind = motion.overlay_kind || "";
  const overlayTheme = motion.overlay_theme || "default";
  const confrontationStyle = motion.confrontation_style || (motion.dialogue_panel ? "ribbon_only" : "split");
  const showSplitConfrontation = isConfrontation && confrontationStyle === "split";
  const showDialogueRibbon = isConfrontation && (confrontationStyle === "split" || confrontationStyle === "ribbon_only");

  const flashOpacity = isImpactScene
    ? interpolate(frame, [0, 2, 8, 22], [0.92, 0.28, 0.12, 0], {
        extrapolateRight: "clamp",
      })
    : 0;

  const propSlideY = interpolate(
    frame,
    [0, 10, Math.min(durationFrames, 24)],
    [110, 18, 0],
    { extrapolateRight: "clamp" },
  );
  const propScale = interpolate(
    frame,
    [0, 10, Math.min(durationFrames, 24)],
    [0.82, 1.12, 1],
    { extrapolateRight: "clamp" },
  );

  const splitOffset = interpolate(frame, [0, durationFrames], [0, 26], {
    extrapolateRight: "clamp",
  });

  return (
    <>
      {flashOpacity > 0 ? (
        <>
          <div
            style={{
              position: "absolute",
              inset: 0,
              background: `rgba(255,255,255,${flashOpacity})`,
              mixBlendMode: "screen",
              pointerEvents: "none",
              zIndex: 11,
            }}
          />
          <div
            style={{
              position: "absolute",
              inset: 18,
              border: "3px solid rgba(255,255,255,0.7)",
              boxShadow: "0 0 30px rgba(255,255,255,0.35)",
              pointerEvents: "none",
              zIndex: 12,
            }}
          />
        </>
      ) : null}

      {isPropReveal ? (
        <>
          <div
            style={{
              position: "absolute",
              inset: 0,
              background: "radial-gradient(circle at center, rgba(255,255,255,0.06), rgba(0,0,0,0.35))",
              pointerEvents: "none",
              zIndex: 11,
            }}
          />
          {overlayKind === "message" || overlayKind === "call" ? (
            <MotiontoonPhoneCard motion={motion} slideY={propSlideY} scale={propScale} />
          ) : (
            <MotiontoonDocumentCard motion={motion} slideY={propSlideY} scale={propScale} />
          )}
        </>
      ) : null}

      {showSplitConfrontation ? (
        <>
          <div
            style={{
              position: "absolute",
              inset: 0,
              clipPath: "polygon(0 0, 49% 0, 42% 100%, 0 100%)",
              opacity: 0.42,
              pointerEvents: "none",
              zIndex: 11,
            }}
          >
            <Img
              src={src}
              style={{
                width: "100%",
                height: "100%",
                objectFit: "cover",
                transform: `scale(1.18) translate(${-splitOffset * 1.6}px, -4px)`,
                filter: "contrast(1.24) saturate(1.06)",
              }}
            />
          </div>
          <div
            style={{
              position: "absolute",
              inset: 0,
              clipPath: "polygon(58% 0, 100% 0, 100% 100%, 51% 100%)",
              opacity: 0.42,
              pointerEvents: "none",
              zIndex: 11,
            }}
          >
            <Img
              src={src}
              style={{
                width: "100%",
                height: "100%",
                objectFit: "cover",
                transform: `scale(1.18) translate(${splitOffset * 1.6}px, 4px)`,
                filter: "contrast(1.24) saturate(1.06)",
              }}
            />
          </div>
          <div
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: "50%",
              width: 6,
              transform: "translateX(-50%) skewX(-14deg)",
              background: "linear-gradient(180deg, rgba(255,255,255,0), rgba(255,255,255,0.85), rgba(255,255,255,0))",
              boxShadow: "0 0 24px rgba(255,255,255,0.45)",
              pointerEvents: "none",
              zIndex: 12,
            }}
          />
        </>
      ) : null}

      {showDialogueRibbon ? <MotiontoonDialogueRibbon motion={motion} /> : null}

      {isMemory ? (
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: "linear-gradient(180deg, rgba(255,231,180,0.12), rgba(48,24,8,0.18))",
            mixBlendMode: "screen",
            pointerEvents: "none",
            zIndex: 11,
          }}
        />
      ) : null}

      {overlayTheme === "life_saguk" ? (
        <div
          style={{
            position: "absolute",
            inset: 18,
            border: "2px solid rgba(134, 96, 58, 0.22)",
            boxShadow: "inset 0 0 0 8px rgba(255,241,214,0.03)",
            pointerEvents: "none",
            zIndex: 10,
          }}
        />
      ) : null}
    </>
  );
};

const getMouthCueAmount = (mouthCues: MouthCue[] | undefined, frame: number): number => {
  if (!mouthCues || mouthCues.length === 0) {
    return 0;
  }
  let selected: MouthCue | undefined;
  for (const cue of mouthCues) {
    if (cue.frame <= frame) {
      selected = cue;
    } else {
      break;
    }
  }
  if (!selected) {
    return 0;
  }
  if (typeof selected.mouth === "number") {
    return selected.mouth > 0 ? 1 : 0;
  }
  if (typeof selected.energy === "number") {
    return Math.max(0, Math.min(1, selected.energy * 32));
  }
  return 0;
};

const LayeredCutoutStack: React.FC<{
  src: string;
  backgroundSrc?: string;
  foregroundSrc?: string;
  headSrc?: string;
  bodySrc?: string;
  leftArmSrc?: string;
  rightArmSrc?: string;
  eyesOpenSrc?: string;
  eyesClosedSrc?: string;
  mouthClosedSrc?: string;
  mouthOpenSrc?: string;
  mouthCues?: MouthCue[];
  durationFrames: number;
  scale: number;
  translateX: number;
  translateY: number;
  rotationDeg: number;
  motion?: MotionDirective;
}> = ({
  src,
  backgroundSrc,
  foregroundSrc,
  eyesOpenSrc,
  eyesClosedSrc,
  mouthClosedSrc,
  mouthOpenSrc,
  mouthCues,
  durationFrames,
  scale,
  translateX,
  translateY,
  rotationDeg,
  motion,
}) => {
  const frame = useCurrentFrame();
  const isSimpleSprite =
    (motion?.character_layer_mode || "").trim().toLowerCase() === "simple_sprite" ||
    (motion?.character_layer_mode || "").trim().toLowerCase() === "character_sprite";
  const layeredStrength = Math.max(0.35, Math.min(1.35, motion?.layered_cutout_strength ?? 0.72));
  const hasIdleDrift = Boolean(motion?.primitives?.includes("idle_drift"));
  const sway = hasIdleDrift
    ? Math.sin(frame / (isSimpleSprite ? 18 : 10)) * (isSimpleSprite ? 1.8 : 10) * layeredStrength
    : 0;
  const bobStrength = Math.max(0, Math.min(1.5, motion?.bob_strength ?? (isSimpleSprite ? 0.12 : 1)));
  const legacyPuppetBob = motion?.puppet_bob
    ? Math.sin(frame / (isSimpleSprite ? 9.5 : 5.5)) * (isSimpleSprite ? 2.0 : 16) * layeredStrength * bobStrength
    : 0;
  const spriteSrc = foregroundSrc || "";
  const hasSprite = Boolean(spriteSrc);
  const safeDurationFrames = Math.max(1, durationFrames || 1);
  const progress = Math.max(0, Math.min(1, frame / safeDurationFrames));
  const bgTransform = `scale(1.01) translate(${translateX * 0.08}px, ${translateY * 0.06}px)`;
  const spriteCenterX = Math.max(0.1, Math.min(0.9, motion?.sprite_center_x ?? 0.5));
  const spriteCenterY = Math.max(0.18, Math.min(0.96, motion?.sprite_center_y ?? (isSimpleSprite ? 0.8 : 0.62)));
  const spriteWidthRatio = Math.max(0.16, Math.min(0.62, motion?.sprite_width_ratio ?? (isSimpleSprite ? 0.42 : 0.3)));
  const spriteHeightRatio = Math.max(0.24, Math.min(0.86, motion?.sprite_height_ratio ?? (isSimpleSprite ? 0.76 : 0.54)));
  const spriteBoxWidth = `${spriteWidthRatio * 100}%`;
  const spriteBoxHeight = `${spriteHeightRatio * 100}%`;
  const spriteLeft = `${spriteCenterX * 100}%`;
  const spriteTop = `${spriteCenterY * 100}%`;
  const faceX = `${(motion?.face_anchor_x ?? 0.5) * 100}%`;
  const faceY = `${(motion?.face_anchor_y ?? 0.33) * 100}%`;
  const faceScale = Math.max(0.78, Math.min(1.28, motion?.face_scale ?? 1));
  const blinkCycle = frame % 72;
  const blinkAmount =
    motion?.face_rig && (blinkCycle < 5 || (blinkCycle > 42 && blinkCycle < 47))
      ? interpolate(blinkCycle < 5 ? blinkCycle : blinkCycle - 42, [0, 2, 5], [0.05, 1, 0.08], {
          extrapolateRight: "clamp",
        })
      : 0;
  const mouthCueAmount = getMouthCueAmount(mouthCues, frame);
  const mouthAmount =
    motion?.face_rig && mouthCues && mouthCues.length > 0
      ? mouthCueAmount
      : motion?.face_rig && motion?.primitives?.includes("subtitle_pulse")
      ? interpolate(Math.sin(frame / 1.8), [-1, 1], [0.24, 1], { extrapolateRight: "clamp" })
      : 0;
  const hasEyeSprites = Boolean(motion?.face_rig && hasSprite && eyesOpenSrc && eyesClosedSrc);
  const hasMouthSprites = Boolean(motion?.face_rig && hasSprite && mouthClosedSrc && mouthOpenSrc);
  const hasFaceSprites = hasEyeSprites || hasMouthSprites;
  const actingPose = (motion?.acting_pose || "grounded_talk").trim().toLowerCase();
  const poseLean =
    actingPose.includes("lean") ? -0.8 :
    actingPose.includes("listen") ? 0.7 :
    actingPose.includes("emphasis") ? Math.sin(frame / 20) * 0.45 :
    0;
  const enterPx = Math.max(0, Math.min(80, motion?.sprite_enter_px ?? (isSimpleSprite ? 12 : 0)));
  const enterDirection = spriteCenterX < 0.5 ? -1 : 1;
  const enterMidFrame = Math.max(1, Math.min(10, Math.floor(safeDurationFrames * 0.35)));
  const enterEndFrame = Math.max(enterMidFrame + 1, Math.min(24, Math.floor(safeDurationFrames * 0.7) || 2));
  const enterOffset = enterPx
    ? interpolate(frame, [0, enterMidFrame, enterEndFrame], [enterPx * enterDirection, enterPx * 0.18 * enterDirection, 0], {
        extrapolateRight: "clamp",
      })
    : 0;
  const parallaxPx = Math.max(0, Math.min(18, motion?.sprite_parallax_px ?? (isSimpleSprite ? 4 : 0)));
  const parallax = Math.sin(progress * Math.PI) * parallaxPx * (spriteCenterX < 0.5 ? 1 : -1);
  const breathePx = Math.max(0, Math.min(3, motion?.sprite_breathe_px ?? (isSimpleSprite ? 1.1 : 0)));
  const groundedBreath = isSimpleSprite
    ? Math.sin(frame / 18) * breathePx * layeredStrength
    : legacyPuppetBob;
  const focusScale = Math.max(0.96, Math.min(1.08, motion?.sprite_focus_scale ?? 1));
  const mouthEmphasisScale = hasMouthSprites ? mouthAmount * 0.006 : 0;
  const spriteScale = (isSimpleSprite ? Math.max(0.98, Math.min(1.035, scale)) : Math.max(1, scale * 1.02)) * focusScale + mouthEmphasisScale;
  const spriteRotation = rotationDeg * (isSimpleSprite ? 0.1 : 0.18) + (motion?.sprite_lean_deg ?? 0) + poseLean;
  const spriteTransform = `translate(-50%, -50%) translate(${translateX * 0.22 + sway + enterOffset + parallax}px, ${translateY * 0.1 + groundedBreath}px) scale(${spriteScale}) rotate(${spriteRotation}deg)`;
  const faceMotionY = Math.max(-2, Math.min(2.5, groundedBreath * 0.35 + mouthAmount * 1.2));

  return (
    <>
      <Img
        src={backgroundSrc || src}
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: bgTransform,
          filter: "saturate(0.98) contrast(0.98) brightness(0.96)",
        }}
      />
      {hasSprite ? (
        <div
          style={{
            position: "absolute",
            left: spriteLeft,
            top: spriteTop,
            width: spriteBoxWidth,
            height: spriteBoxHeight,
            transform: spriteTransform,
            transformOrigin: "50% 92%",
            pointerEvents: "none",
            zIndex: 4,
          }}
        >
          <Img
            src={spriteSrc}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "contain",
              filter: "drop-shadow(0 18px 22px rgba(0,0,0,0.34))",
            }}
          />
          {hasFaceSprites ? (
            <div
              style={{
                position: "absolute",
                left: faceX,
                top: faceY,
                width: `${34 * faceScale}%`,
                height: `${24 * faceScale}%`,
                transform: `translate(-50%, -50%) translateY(${faceMotionY}px)`,
                pointerEvents: "none",
              }}
            >
              {hasEyeSprites ? (
                <>
                  <Img
                    src={eyesOpenSrc!}
                    style={{
                      position: "absolute",
                      inset: 0,
                      width: "100%",
                      height: "100%",
                      objectFit: "contain",
                      opacity: 1 - blinkAmount,
                    }}
                  />
                  <Img
                    src={eyesClosedSrc!}
                    style={{
                      position: "absolute",
                      inset: 0,
                      width: "100%",
                      height: "100%",
                      objectFit: "contain",
                      opacity: blinkAmount,
                    }}
                  />
                </>
              ) : null}
              {hasMouthSprites ? (
                <>
                  <Img
                    src={mouthClosedSrc!}
                    style={{
                      position: "absolute",
                      inset: 0,
                      width: "100%",
                      height: "100%",
                      objectFit: "contain",
                      opacity: Math.max(0, 1 - mouthAmount),
                    }}
                  />
                  <Img
                    src={mouthOpenSrc!}
                    style={{
                      position: "absolute",
                      inset: 0,
                      width: "100%",
                      height: "100%",
                      objectFit: "contain",
                      opacity: mouthAmount,
                    }}
                  />
                </>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
};

const EnhancedImage: React.FC<EnhancedImageProps> = ({
  src,
  backgroundSrc,
  foregroundSrc,
  headSrc,
  bodySrc,
  leftArmSrc,
  rightArmSrc,
  eyesOpenSrc,
  eyesClosedSrc,
  mouthClosedSrc,
  mouthOpenSrc,
  mouthCues,
  durationFrames,
  motion,
  motiontoonEnabled = false,
  motiontoonMode = "screen_space",
  transition = "fade",
  transitionDuration = 15,
  vignette = "none",
  colorFilter = "none",
  kenBurnsMode = "zoom_in",
  kenBurnsIntensity = 0.08,
}: EnhancedImageProps) => {
  const frame = useCurrentFrame();
  const isGishiniMode = motiontoonMode === "gishini_motiontoon";
  const isClassicDynamicMode = motiontoonMode === "classic_dynamic";
  const motionActive = motiontoonEnabled || isClassicDynamicMode;
  const motionState = getMotionTransform({ frame, durationFrames, motion, enabled: motionActive });

  // v59.4: 耳?踰덉뒪 6紐⑤뱶 怨꾩궛
  let scale = 1.0;
  let translateX = 0;
  let translateY = 0;
  const intensity = kenBurnsIntensity;

  switch (kenBurnsMode) {
    case "zoom_in":
      // 以뚯씤: 1.0 ??1.0+intensity (?대줈利덉뾽 ?먮굦)
      scale = interpolate(frame, [0, durationFrames], [1.0, 1.0 + intensity], { extrapolateRight: "clamp" });
      break;
    case "zoom_out":
      // 以뚯븘?? 1.0+intensity ??1.0 (?볦뼱吏???먮굦)
      scale = interpolate(frame, [0, durationFrames], [1.0 + intensity, 1.0], { extrapolateRight: "clamp" });
      break;
    case "pan_left":
      // 醫뚯륫 ?? ?ㅻⅨ履쎌뿉???쇱そ?쇰줈 ?대룞
      scale = 1.0 + intensity;  // ?쎄컙 ?뺣??댁꽌 ?대룞 ?щ갚 ?뺣낫
      translateX = interpolate(frame, [0, durationFrames], [intensity * 50, -intensity * 50], { extrapolateRight: "clamp" });
      break;
    case "pan_right":
      // ?곗륫 ?? ?쇱そ?먯꽌 ?ㅻⅨ履쎌쑝濡??대룞
      scale = 1.0 + intensity;
      translateX = interpolate(frame, [0, durationFrames], [-intensity * 50, intensity * 50], { extrapolateRight: "clamp" });
      break;
    case "pan_up":
      // ?곷떒 ?? ?꾨옒?먯꽌 ?꾨줈 ?대룞 (?꾨? ?щ젮?ㅻ낫???먮굦)
      scale = 1.0 + intensity;
      translateY = interpolate(frame, [0, durationFrames], [intensity * 30, -intensity * 30], { extrapolateRight: "clamp" });
      break;
    case "pan_down":
      // ?섎떒 ?? ?꾩뿉???꾨옒濡??대룞 (?대젮?ㅻ낫???먮굦)
      scale = 1.0 + intensity;
      translateY = interpolate(frame, [0, durationFrames], [-intensity * 30, intensity * 30], { extrapolateRight: "clamp" });
      break;
  }

  // ?몃옖吏???④낵 怨꾩궛
  let transitionOpacity = 1;
  let transitionTranslateX = 0;

  switch (transition) {
    case "fade":
    case "dissolve":
      if (frame < transitionDuration) {
        transitionOpacity = interpolate(frame, [0, transitionDuration], [0, 1], { extrapolateRight: "clamp" });
      }
      if (frame > durationFrames - transitionDuration) {
        transitionOpacity = interpolate(frame, [durationFrames - transitionDuration, durationFrames], [1, 0], { extrapolateRight: "clamp" });
      }
      break;
    case "wipe_left":
      if (frame < transitionDuration) {
        transitionTranslateX = interpolate(frame, [0, transitionDuration], [100, 0], { extrapolateRight: "clamp" });
      }
      break;
    case "wipe_right":
      if (frame < transitionDuration) {
        transitionTranslateX = interpolate(frame, [0, transitionDuration], [-100, 0], { extrapolateRight: "clamp" });
      }
      break;
    case "cut":
    default:
      break;
  }

  const imageTransformScale = scale * motionState.scaleMultiplier;
  const imageTranslateX = translateX + motionState.offsetX;
  const imageTranslateY = translateY + motionState.offsetY;
  const canUseLayeredCutout =
    Boolean(foregroundSrc) &&
    (Boolean(backgroundSrc) || Boolean(motion?.use_layered_cutout));

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      <div
        style={{
          width: "100%",
          height: "100%",
          opacity: transitionOpacity,
          transform: `translateX(${transitionTranslateX}%)`,
          overflow: "hidden",
        }}
      >
        {canUseLayeredCutout ? (
          <LayeredCutoutStack
            src={src}
            backgroundSrc={backgroundSrc}
            foregroundSrc={foregroundSrc}
            headSrc={headSrc}
            bodySrc={bodySrc}
            leftArmSrc={leftArmSrc}
            rightArmSrc={rightArmSrc}
            eyesOpenSrc={eyesOpenSrc}
            eyesClosedSrc={eyesClosedSrc}
            mouthClosedSrc={mouthClosedSrc}
            mouthOpenSrc={mouthOpenSrc}
            mouthCues={mouthCues}
            scale={imageTransformScale}
            translateX={imageTranslateX}
            translateY={imageTranslateY}
            rotationDeg={motionState.rotationDeg}
            motion={motion}
            durationFrames={durationFrames}
          />
        ) : (
          <Img
            src={src}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              transform: isGishiniMode
                ? "scale(1.01)"
                : `scale(${imageTransformScale}) translate(${imageTranslateX}px, ${imageTranslateY}px) rotate(${motionState.rotationDeg}deg)`,
              filter: isClassicDynamicMode ? "contrast(1.04) saturate(1.03)" : "none",
            }}
          />
        )}
      </div>
      {isClassicDynamicMode ? (
        <MotiontoonAccent src={src} motion={motion} durationFrames={durationFrames} />
      ) : null}
      <ColorFilter type={colorFilter} />
      <Vignette type={vignette} />
    </AbsoluteFill>
  );
};

// v59.4: Ken Burns ?대?吏 (6紐⑤뱶 吏?? ?섏쐞 ?명솚)
const KenBurnsImage: React.FC<{
  src: string;
  backgroundSrc?: string;
  foregroundSrc?: string;
  headSrc?: string;
  bodySrc?: string;
  leftArmSrc?: string;
  rightArmSrc?: string;
  eyesOpenSrc?: string;
  eyesClosedSrc?: string;
  mouthClosedSrc?: string;
  mouthOpenSrc?: string;
  mouthCues?: MouthCue[];
  durationFrames: number;
  kenBurnsMode?: KenBurnsMode;
  kenBurnsIntensity?: number;
  motion?: MotionDirective;
  motiontoonEnabled?: boolean;
  motiontoonMode?: string;
}> = ({
  src,
  backgroundSrc,
  foregroundSrc,
  headSrc,
  bodySrc,
  leftArmSrc,
  rightArmSrc,
  eyesOpenSrc,
  eyesClosedSrc,
  mouthClosedSrc,
  mouthOpenSrc,
  mouthCues,
  durationFrames,
  kenBurnsMode = "zoom_in",
  kenBurnsIntensity = 0.08,
  motion,
  motiontoonEnabled = false,
  motiontoonMode = "screen_space",
}) => {
  const frame = useCurrentFrame();
  const isGishiniMode = motiontoonMode === "gishini_motiontoon";
  const isClassicDynamicMode = motiontoonMode === "classic_dynamic";
  const motionActive = motiontoonEnabled || isClassicDynamicMode;
  const motionState = getMotionTransform({ frame, durationFrames, motion, enabled: motionActive });

  let scale = 1.0;
  let translateX = 0;
  let translateY = 0;
  const intensity = kenBurnsIntensity;

  switch (kenBurnsMode) {
    case "zoom_in":
      scale = interpolate(frame, [0, durationFrames], [1.0, 1.0 + intensity], { extrapolateRight: "clamp" });
      break;
    case "zoom_out":
      scale = interpolate(frame, [0, durationFrames], [1.0 + intensity, 1.0], { extrapolateRight: "clamp" });
      break;
    case "pan_left":
      scale = 1.0 + intensity;
      translateX = interpolate(frame, [0, durationFrames], [intensity * 50, -intensity * 50], { extrapolateRight: "clamp" });
      break;
    case "pan_right":
      scale = 1.0 + intensity;
      translateX = interpolate(frame, [0, durationFrames], [-intensity * 50, intensity * 50], { extrapolateRight: "clamp" });
      break;
    case "pan_up":
      scale = 1.0 + intensity;
      translateY = interpolate(frame, [0, durationFrames], [intensity * 30, -intensity * 30], { extrapolateRight: "clamp" });
      break;
    case "pan_down":
      scale = 1.0 + intensity;
      translateY = interpolate(frame, [0, durationFrames], [-intensity * 30, intensity * 30], { extrapolateRight: "clamp" });
      break;
  }

  const imageTransformScale = scale * motionState.scaleMultiplier;
  const imageTranslateX = translateX + motionState.offsetX;
  const imageTranslateY = translateY + motionState.offsetY;
  const canUseLayeredCutout =
    Boolean(foregroundSrc) &&
    (Boolean(backgroundSrc) || Boolean(motion?.use_layered_cutout));

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      <div style={{ width: "100%", height: "100%", overflow: "hidden" }}>
        {canUseLayeredCutout ? (
          <LayeredCutoutStack
            src={src}
            backgroundSrc={backgroundSrc}
            foregroundSrc={foregroundSrc}
            headSrc={headSrc}
            bodySrc={bodySrc}
            leftArmSrc={leftArmSrc}
            rightArmSrc={rightArmSrc}
            eyesOpenSrc={eyesOpenSrc}
            eyesClosedSrc={eyesClosedSrc}
            mouthClosedSrc={mouthClosedSrc}
            mouthOpenSrc={mouthOpenSrc}
            mouthCues={mouthCues}
            scale={imageTransformScale}
            translateX={imageTranslateX}
            translateY={imageTranslateY}
            rotationDeg={motionState.rotationDeg}
            motion={motion}
            durationFrames={durationFrames}
          />
        ) : (
          <Img
            src={src}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              transform: isGishiniMode
                ? "scale(1.01)"
                : `scale(${imageTransformScale}) translate(${imageTranslateX}px, ${imageTranslateY}px) rotate(${motionState.rotationDeg}deg)`,
              filter: isClassicDynamicMode ? "contrast(1.04) saturate(1.03)" : "none",
            }}
          />
        )}
      </div>
      {isClassicDynamicMode ? (
        <MotiontoonAccent src={src} motion={motion} durationFrames={durationFrames} />
      ) : null}
    </AbsoluteFill>
  );
};

// v58.4.0: Hook 而댄룷?뚰듃 (寃? 諛곌꼍 + 二쇱젣 ??댄룷洹몃옒??
interface HookProps {
  topLabel: string;
  topColor: string;
  mainText: string;
  mainColor: string;
  bgColor: string;
  durationFrames: number;
}

const Hook: React.FC<HookProps> = ({ topLabel, topColor, mainText, mainColor, bgColor, durationFrames }: HookProps) => {
  const frame = useCurrentFrame();

  // ?섏씠?????꾩썐 (0.8珥?in, 0.5珥?out)
  const fadeInFrames = 24;  // 0.8珥?* 30fps
  const fadeOutFrames = 15; // 0.5珥?* 30fps

  let opacity = 1;
  if (frame < fadeInFrames) {
    opacity = interpolate(frame, [0, fadeInFrames], [0, 1], { extrapolateRight: "clamp" });
  } else if (frame > durationFrames - fadeOutFrames) {
    opacity = interpolate(frame, [durationFrames - fadeOutFrames, durationFrames], [1, 0], { extrapolateRight: "clamp" });
  }

  // v61.1 (#41): 湲?二쇱젣 泥섎━ - 理쒕? 3以? 30??以?(?쒓뎅??怨듬갚 湲곕컲 以꾨컮轅?
  const maxCharsPerLine = 30;
  const maxLines = 3;
  let lines: string[] = [];
  if (mainText.length > maxCharsPerLine) {
    // 怨듬갚???덉쑝硫?怨듬갚 湲곗?, ?놁쑝硫?湲???⑥쐞
    const hasSpaces = mainText.includes(' ');
    if (hasSpaces) {
      const words = mainText.split(' ');
      let currentLine = '';
      for (const word of words) {
        if (currentLine.length + word.length + 1 > maxCharsPerLine && currentLine) {
          lines.push(currentLine.trim());
          currentLine = word;
          if (lines.length >= maxLines) break;
        } else {
          currentLine = currentLine ? `${currentLine} ${word}` : word;
        }
      }
      if (currentLine && lines.length < maxLines) {
        lines.push(currentLine.trim());
      }
    } else {
      // ?쒓뎅?? 怨듬갚 ?놁쑝硫?30???⑥쐞 遺꾨━
      for (let i = 0; i < mainText.length && lines.length < maxLines; i += maxCharsPerLine) {
        lines.push(mainText.slice(i, i + maxCharsPerLine));
      }
    }
  } else {
    lines = [mainText];
  }

  // ?곗샂??異붽?
  const displayLines = lines.map((line, index) => {
    if (lines.length === 1) return `"${line}"`;
    if (index === 0) return `"${line}`;
    if (index === lines.length - 1) return `${line}"`;
    return line;
  });

  return (
    <AbsoluteFill style={{ backgroundColor: bgColor }}>
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          opacity,
        }}
      >
        {/* ?곷떒 ?쇰꺼 */}
        <div
          style={{
            color: topColor,
            fontSize: 36,
            fontWeight: "bold",
            marginBottom: 40,
            textShadow: "2px 2px 4px rgba(0,0,0,0.8)",
            fontFamily: "'Noto Sans KR', 'Malgun Gothic', sans-serif",
          }}
        >
          {topLabel}
        </div>

        {/* 硫붿씤 二쇱젣 */}
        {displayLines.map((line, i) => (
          <div
            key={i}
            style={{
              color: mainColor,
              fontSize: 56,
              fontWeight: "bold",
              textShadow: "4px 4px 8px rgba(0,0,0,0.9)",
              fontFamily: "'Noto Sans KR', 'Malgun Gothic', sans-serif",
              marginBottom: 10,
            }}
          >
            {line}
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};

// v58.1: AI ?쒖옉 ?쒓린 而댄룷?뚰듃 (AI踰?以??
const AiDisclosure: React.FC<{ durationFrames: number }> = ({ durationFrames }: { durationFrames: number }) => {
  const frame = useCurrentFrame();

  // ?섏씠?쒖씤 (0~15?꾨젅?? ???좎? ???섏씠?쒖븘??(留덉?留?15?꾨젅??
  const fadeInEnd = 15;
  const fadeOutStart = durationFrames - 15;

  let opacity = 1;
  if (frame < fadeInEnd) {
    opacity = interpolate(frame, [0, fadeInEnd], [0, 1], { extrapolateRight: "clamp" });
  } else if (frame > fadeOutStart) {
    opacity = interpolate(frame, [fadeOutStart, durationFrames], [1, 0], { extrapolateRight: "clamp" });
  }

  return (
    <div
      style={{
        position: "absolute",
        top: 30,
        left: 30,
        opacity,
        zIndex: 100,
      }}
    >
      <div
        style={{
          color: "rgba(255, 255, 255, 0.85)",
          fontSize: 18,
          fontWeight: "normal",
          padding: "8px 16px",
          backgroundColor: "rgba(0, 0, 0, 0.5)",
          borderRadius: 6,
          fontFamily: "'Noto Sans KR', 'Malgun Gothic', sans-serif",
          letterSpacing: "0.5px",
        }}
      >
        ???곸긽? AI濡??쒖옉?섏뿀?듬땲??
      </div>
    </div>
  );
};

// v59.4: ?ㅽ??쇰맂 ?먮쭑 而댄룷?뚰듃 ???덊띁?곗뒪 梨꾨꼸 ?ㅽ???(?뚮퉬怨듯룷?쇰뵒??誘몄뒪?뚮━?곗껜??李멸퀬)
interface StyledSubtitleProps {
  text: string;
  speaker: string;
  speakerColor?: string;
  style?: SubtitleStyleConfig;
  motion?: MotionDirective;
  motiontoonEnabled?: boolean;
  subtitleMode?: "default" | "overlay_safe";
}

const getSubtitleLayoutMetrics = (
  text: string,
  baseFontSize: number,
  baseSpeakerSize: number,
  subtitleMode: "default" | "overlay_safe" = "default",
) => {
  const compact = text.replace(/\s+/g, " ").trim();
  const length = compact.length;
  const overlaySafe = subtitleMode === "overlay_safe";

  if (length >= 90) {
    return {
      fontSize: Math.max(18, Math.round(baseFontSize * 0.58)),
      speakerFontSize: Math.max(15, Math.round(baseSpeakerSize * 0.72)),
      maxWidth: overlaySafe ? "74%" : "84%",
      padding: "6px 16px",
      lineHeight: 1.14,
      bottom: overlaySafe ? 260 : 88,
    };
  }

  if (length >= 60) {
    return {
      fontSize: Math.max(20, Math.round(baseFontSize * 0.68)),
      speakerFontSize: Math.max(16, Math.round(baseSpeakerSize * 0.78)),
      maxWidth: overlaySafe ? "72%" : "82%",
      padding: "6px 18px",
      lineHeight: 1.2,
      bottom: overlaySafe ? 240 : 96,
    };
  }

  if (length >= 36) {
    return {
      fontSize: Math.max(22, Math.round(baseFontSize * 0.82)),
      speakerFontSize: Math.max(17, Math.round(baseSpeakerSize * 0.9)),
      maxWidth: overlaySafe ? "68%" : "76%",
      padding: "6px 20px",
      lineHeight: 1.26,
      bottom: overlaySafe ? 228 : 104,
    };
  }

  return {
    fontSize: overlaySafe ? Math.max(22, Math.round(baseFontSize * 0.88)) : baseFontSize,
    speakerFontSize: overlaySafe ? Math.max(17, Math.round(baseSpeakerSize * 0.9)) : baseSpeakerSize,
    maxWidth: overlaySafe ? "64%" : "68%",
    padding: overlaySafe ? "6px 20px" : "6px 24px",
    lineHeight: overlaySafe ? 1.28 : 1.36,
    bottom: overlaySafe ? 220 : 108,
  };
};

const StyledSubtitle: React.FC<StyledSubtitleProps> = ({
  text,
  speaker,
  speakerColor,
  style,
  motion,
  motiontoonEnabled = false,
  subtitleMode = "default",
}: StyledSubtitleProps) => {
  const frame = useCurrentFrame();

  // ?섏씠?쒖씤 ?④낵 (遺?쒕읇寃?
  const opacity = interpolate(frame, [0, 8], [0, 1], { extrapolateRight: "clamp" });
  const subtitlePulseScale = motiontoonEnabled && motion?.primitives?.includes("subtitle_pulse")
    ? interpolate(frame, [0, 5, 12], [0.96, 1.04, 1], { extrapolateRight: "clamp" })
    : 1;

  // ?ㅽ????ㅼ젙 湲곕낯媛?
  const config = {
    fontFamily: style?.fontFamily || "'Noto Sans KR', 'Malgun Gothic', sans-serif",
    fontSize: style?.fontSize || 30,  // v62.4: 38??0 (湲???ш린 異뺤냼)
    speakerFontSize: style?.speakerFontSize || 18,  // v62.4: 22??8
    backgroundColor: style?.backgroundColor || "rgba(0,0,0,0.3)",  // v62.4: 0.6??.3
    backgroundPadding: style?.backgroundPadding,
    backgroundRadius: style?.backgroundRadius,
    marginBottom: style?.marginBottom,
    textColor: style?.textColor || "#FFFFFF",
    position: style?.position || "bottom",
    styleType: style?.style || "default",
  };
  const layout = getSubtitleLayoutMetrics(text, config.fontSize, config.speakerFontSize, subtitleMode);
  const effectiveBottom = subtitleMode === "overlay_safe"
    ? layout.bottom
    : (config.marginBottom ?? layout.bottom);
  const effectivePadding = config.backgroundPadding
    ? `${config.backgroundPadding}px ${Math.max(12, config.backgroundPadding * 2)}px`
    : layout.padding;

  // ?붿옄 ?됱긽 寃곗젙
  const getSpeakerColor = (s: string, customColor?: string): string => {
    if (customColor) return customColor;
    if (style?.speakerColors?.[s]) return style.speakerColors[s];
    // v59.4: 湲곕낯 ?붿옄 ?됱긽 留ㅽ븨
    const colorMap: Record<string, string> = {
      "나레이션": "#CCCCCC",
      "내레이터": "#CCCCCC",
    };
    if (colorMap[s]) return colorMap[s];
    return "#FFD700";  // 湲곕낯 怨⑤뱶
  };

  // ?꾩튂蹂??ㅽ???
  const positionStyle: Record<string, React.CSSProperties> = {
    bottom: { bottom: effectiveBottom },
    center: { top: "50%", transform: "translateY(-50%)" },
    top: { top: 100 },
  };

  // v59.4: ?ㅽ?????낅퀎 ?ㅼ젙 ??horror 湲곕낯媛?媛뺥솕
  const styleTypeConfig: Record<string, { bg: string; border: string; shadow: string; speakerBg: string; speakerBorder: string }> = {
    default: {
      bg: config.backgroundColor,
      border: "none",
      shadow: "0 2px 8px rgba(0,0,0,0.95)",
      speakerBg: "rgba(0,0,0,0.7)",
      speakerBorder: "none",
    },
    horror: {
      bg: "rgba(10, 0, 0, 0.3)",  // v62.4: 0.5??.3 (???щ챸?섍쾶)
      border: "1px solid rgba(139, 0, 0, 0.2)",
      shadow: "0 0 15px rgba(139, 0, 0, 0.15), 0 2px 8px rgba(0,0,0,0.5)",
      speakerBg: "rgba(80, 0, 0, 0.35)",  // v62.4: 0.55??.35
      speakerBorder: "1px solid rgba(200, 0, 0, 0.2)",
    },
    elegant: {
      bg: "rgba(25, 25, 50, 0.3)",  // v62.4: 0.5??.3
      border: "1px solid rgba(255, 215, 0, 0.2)",
      shadow: "0 0 15px rgba(255, 215, 0, 0.08), 0 2px 8px rgba(0,0,0,0.5)",
      speakerBg: "rgba(40, 40, 80, 0.35)",  // v62.4: 0.55??.35
      speakerBorder: "1px solid rgba(255, 215, 0, 0.2)",
    },
    webtoon: {
      bg: "rgba(255, 255, 255, 0.95)",
      border: "3px solid #000000",
      shadow: "4px 4px 0px rgba(0,0,0,0.8)",
      speakerBg: "rgba(50, 50, 50, 0.9)",
      speakerBorder: "2px solid #000000",
    },
  };

  const typeStyle = styleTypeConfig[config.styleType] || styleTypeConfig.default;
  const textColorFinal = config.styleType === "webtoon" ? "#000000" : config.textColor;

  // ?섎젅?댄꽣 泥댄겕
  const isNarrator = speaker && (
    speaker.toLowerCase().includes("narrator") ||
    speaker.toLowerCase().includes("narration") ||
    speaker.includes("내레이터") ||
    speaker.includes("나레이션") ||
    speaker.includes("해설")
  );

  // v59.4: ?띿뒪???멸낸??stroke) ??媛?낆꽦 洹밸???(踰덉씤 ?먮쭑 ?ㅽ???
  const textStroke = "-1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000, 0 -2px 0 #000, 0 2px 0 #000, -2px 0 0 #000, 2px 0 0 #000";

  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        textAlign: "center",
        opacity,
        transform: `scale(${subtitlePulseScale})`,
        ...positionStyle[config.position],
      }}
    >
      {/* v59.4: ?붿옄 ?대쫫 ?쒓렇 ??遺꾨━???묒? 諛뺤뒪 (誘몄뒪?뚮━?곗껜???ㅽ??? */}
      {speaker && !isNarrator && (
        <div
          style={{
            display: "inline-block",
            marginBottom: 8,
          }}
        >
          <span
            style={{
              color: getSpeakerColor(speaker, speakerColor),
              fontSize: layout.speakerFontSize,
              fontWeight: "bold",
              padding: "4px 16px",
              backgroundColor: typeStyle.speakerBg,
              borderRadius: 4,
              border: typeStyle.speakerBorder,
              fontFamily: config.fontFamily,
              letterSpacing: "1px",
              textShadow: "1px 1px 3px rgba(0,0,0,0.9)",
            }}
          >
            {speaker}
          </span>
        </div>
      )}
      {/* v59.4: 蹂몃Ц ?먮쭑 ??踰덉씤 ?ㅽ???(?먭볼???멸낸??+ 諛섑닾紐?諛곌꼍) */}
      <div
        style={{
          color: textColorFinal,
          fontSize: layout.fontSize,
          fontWeight: "bold",
          textShadow: `${textStroke}, ${typeStyle.shadow}`,
          padding: effectivePadding,
          backgroundColor: typeStyle.bg,
          display: "inline-block",
          borderRadius: config.styleType === "webtoon" ? 0 : (config.backgroundRadius ?? 6),
          border: typeStyle.border,
          maxWidth: layout.maxWidth,
          lineHeight: layout.lineHeight,
          whiteSpace: "pre-line",
          wordBreak: "keep-all",
          overflowWrap: "break-word",
          fontFamily: config.fontFamily,
          letterSpacing: "0.5px",
        }}
      >
        {text}
      </div>
    </div>
  );
};

// ?먮쭑 而댄룷?뚰듃 (v57.4: 梨꾨꼸蹂??ш린 吏?? v58.1: 媛먯젙 媛뺤“ ?④낵)
interface SubtitleProps {
  text: string;
  speaker: string;
  speakerColor?: string;
  subtitleSize?: number;
  speakerSize?: number;
  motion?: MotionDirective;
  motiontoonEnabled?: boolean;
  subtitleMode?: "default" | "overlay_safe";
}

const Subtitle: React.FC<SubtitleProps> = ({
  text,
  speaker,
  speakerColor,
  subtitleSize = 28,
  speakerSize = 22,
  motion,
  motiontoonEnabled = false,
  subtitleMode = "default",
}: SubtitleProps) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" });
  const isHighlighted = text.includes("‼") || text.includes("!!");
  const displayText = text.replace(/‼/g, "").trim();
  const subtitlePulseScale = motiontoonEnabled && motion?.primitives?.includes("subtitle_pulse")
    ? interpolate(frame, [0, 5, 12], [0.96, 1.04, 1], { extrapolateRight: "clamp" })
    : 1;
  const highlightScale = isHighlighted
    ? interpolate(frame % 30, [0, 15, 30], [1.0, 1.02, 1.0], { extrapolateRight: "clamp" })
    : 1.0;
  const layout = getSubtitleLayoutMetrics(displayText, subtitleSize, speakerSize, subtitleMode);

  const getSpeakerColor = (s: string, customColor?: string) => {
    if (customColor) return customColor;

    const colors: Record<string, string> = {
      "나레이터": "#FFFFFF",
      "내레이션": "#FFFFFF",
      narrator: "#FFFFFF",
      narration: "#FFFFFF",
      여자: "#FFB6C1",
      woman: "#FFB6C1",
      남자: "#87CEEB",
      man: "#87CEEB",
      할머니: "#DDA0DD",
      grandma: "#DDA0DD",
      할아버지: "#F0E68C",
      grandpa: "#F0E68C",
    };

    const lower = s.toLowerCase();
    if (colors[lower]) return colors[lower];
    if (colors[s]) return colors[s];

    if (s.includes("할머니") || s.includes("어머니") || s.includes("엄마")) return "#DDA0DD";
    if (s.includes("할아버지") || s.includes("아버지") || s.includes("아빠")) return "#F0E68C";

    return "#FFD700";
  };

  const isNarrator = speaker && (
    speaker.toLowerCase().includes("narrator") ||
    speaker.toLowerCase().includes("narration") ||
    speaker.includes("나레이터") ||
    speaker.includes("내레이션") ||
    speaker.includes("해설")
  );

  return (
    <div
      style={{
        position: "absolute",
        bottom: layout.bottom,
        left: 0,
        right: 0,
        textAlign: "center",
        opacity,
      }}
    >
      {speaker && !isNarrator && (
        <div
          style={{
            color: getSpeakerColor(speaker, speakerColor),
            fontSize: layout.speakerFontSize,
            fontWeight: "bold",
            marginBottom: 10,
            textShadow: "2px 2px 4px rgba(0,0,0,0.8)",
            fontFamily: "'Noto Sans KR', 'Malgun Gothic', sans-serif",
          }}
        >
          [{speaker}]
        </div>
      )}
      <div
        style={{
          color: isHighlighted ? "#FF4444" : "white",
          fontSize: isHighlighted ? layout.fontSize * 1.05 : layout.fontSize,
          fontWeight: "bold",
          textShadow: isHighlighted
            ? "0 0 10px rgba(255,68,68,0.8), 3px 3px 6px rgba(0,0,0,0.9)"
            : "3px 3px 6px rgba(0,0,0,0.9)",
          padding: layout.padding,
          backgroundColor: isHighlighted ? "rgba(60,0,0,0.35)" : "rgba(0,0,0,0.3)",
          display: "inline-block",
          borderRadius: 8,
          border: isHighlighted ? "2px solid rgba(255,68,68,0.6)" : "none",
          maxWidth: layout.maxWidth,
          lineHeight: layout.lineHeight,
          whiteSpace: "pre-line",
          wordBreak: "keep-all",
          overflowWrap: "break-word",
          fontFamily: "'Noto Sans KR', 'Malgun Gothic', sans-serif",
          transform: `scale(${highlightScale * subtitlePulseScale})`,
          transition: "transform 0.1s ease",
        }}
      >
        {displayText}
      </div>
    </div>
  );
};

// v59: ?꾨젅???ㅻ쾭?덉씠 而댄룷?뚰듃 (湲덉깋 ?뚮몢由??먮（留덈━ ??
interface FrameOverlayProps {
  frameImage?: string;
  frameOpacity?: number;
}

const FrameOverlay: React.FC<FrameOverlayProps> = ({ frameImage, frameOpacity = 1.0 }) => {
  if (!frameImage) return null;

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        pointerEvents: "none",
        zIndex: 20,
        opacity: frameOpacity,
      }}
    >
      <Img
        src={frameImage}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
        }}
      />
    </div>
  );
};

// v59: ?꾨쫫 洹몃젅???④낵 而댄룷?뚰듃
interface FilmGrainProps {
  intensity?: number;
}

const FilmGrain: React.FC<FilmGrainProps> = ({ intensity = 0.1 }) => {
  const frame = useCurrentFrame();

  // 媛꾨떒???몄씠利??④낵 (?꾨젅?꾨퀎濡??쎄컙 蹂??
  const offset = (frame % 60) * 10;

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        pointerEvents: "none",
        zIndex: 15,
        opacity: intensity,
        backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch' seed='${offset}'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E")`,
        mixBlendMode: "overlay" as const,
      }}
    />
  );
};

// v59: ?덊꽣諛뺤뒪 ?④낵 而댄룷?뚰듃 (?쒕꽕留덊떛 鍮꾩쑉)
interface LetterboxProps {
  ratio?: number;  // 2.35:1 ??
}

const Letterbox: React.FC<LetterboxProps> = ({ ratio = 2.35 }) => {
  const { width, height } = useVideoConfig();
  const currentRatio = width / height;

  if (currentRatio >= ratio) return null;

  // ?덊꽣諛뺤뒪 ?믪씠 怨꾩궛
  const targetHeight = width / ratio;
  const barHeight = (height - targetHeight) / 2;

  return (
    <>
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: barHeight,
          backgroundColor: "black",
          zIndex: 25,
        }}
      />
      <div
        style={{
          position: "absolute",
          bottom: 0,
          left: 0,
          right: 0,
          height: barHeight,
          backgroundColor: "black",
          zIndex: 25,
        }}
      />
    </>
  );
};

// v59: ?뚰떚???ㅻ쾭?덉씠 ?④낵 而댄룷?뚰듃
interface ParticleOverlayProps {
  type?: "dust" | "rain" | "snow" | "none";
  opacity?: number;
}

const ParticleOverlay: React.FC<ParticleOverlayProps> = ({ type = "none", opacity = 0.2 }) => {
  const frame = useCurrentFrame();

  if (type === "none") return null;

  // ?좊땲硫붿씠???ㅽ봽??
  const offset = frame * 2;

  const styleMap: Record<string, React.CSSProperties> = {
    dust: {
      backgroundImage: "radial-gradient(circle, rgba(255,255,255,0.1) 1px, transparent 1px)",
      backgroundSize: "20px 20px",
      backgroundPosition: `${offset % 20}px ${offset % 20}px`,
    },
    rain: {
      backgroundImage: "linear-gradient(transparent 90%, rgba(150,150,255,0.3) 100%)",
      backgroundSize: "3px 50px",
      backgroundPosition: `0 ${offset * 5}px`,
    },
    snow: {
      backgroundImage: "radial-gradient(circle, rgba(255,255,255,0.8) 1px, transparent 1px)",
      backgroundSize: "30px 30px",
      backgroundPosition: `${Math.sin(offset / 30) * 10}px ${offset}px`,
    },
  };

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        pointerEvents: "none",
        zIndex: 12,
        opacity,
        ...styleMap[type],
      }}
    />
  );
};

// v59: ?뺤옣??鍮꾩＜???댄럺???ㅼ젙 ?명꽣?섏씠??
interface ExtendedVisualEffectsConfig extends VisualEffectsConfig {
  frameImage?: string;
  frameOpacity?: number;
  filmGrain?: boolean;
  filmGrainIntensity?: number;
  letterbox?: boolean;
  letterboxRatio?: number;
  particleOverlay?: "dust" | "rain" | "snow" | "none";
  particleOpacity?: number;
}

// v59: ?뺤옣??Props ?명꽣?섏씠??(湲곗〈 ?명솚)
interface ExtendedRadioDramaProps extends RadioDramaProps {
  extendedVisualEffects?: ExtendedVisualEffectsConfig;
}

export const RadioDrama: React.FC<RadioDramaProps> = ({
  images,
  audioSegments,
  subtitles,
  motiontoon,
  bgmPath,
  bgmVolume = 0.15,
  subtitleSize = 36,   // v57.4: 梨꾨꼸蹂??먮쭑 ?ш린
  speakerSize = 28,    // v57.4: 梨꾨꼸蹂??붿옄紐??ш린
  showAiDisclosure = true,  // v58.1: AI ?쒖옉 ?쒓린 (湲곕낯 ?쒖꽦??
  aiDisclosureDuration = 3, // v58.1: 3珥덇컙 ?쒖떆
  ttsVolume = 1.0,          // v58.3.4: TTS 蹂쇰ⅷ 1.0 (Remotion ?먮낯, FFmpeg?먯꽌 +10dB)
  fullAudioPath,            // v58.3.3: ?꾩껜 TTS ?ㅻ뵒???뚯씪 寃쎈줈
  hook,                     // v58.4.0: Hook ?곗씠??
  visualEffects,            // v59: 鍮꾩＜???댄럺???ㅼ젙
  subtitleStyle,            // v59: ?먮쭑 ?ㅽ????ㅼ젙
  sfxCues = [],             // v59.3.5: SFX ?④낵??(Remotion ?듯빀)
}) => {
  const { fps, durationInFrames: totalCompositionFrames } = useVideoConfig();
  const aiDisclosureFrames = Math.round(aiDisclosureDuration * fps);

  // v58.4.0: hook 湲몄씠 (?덉쑝硫??대떦 ?꾨젅?? ?놁쑝硫?0)
  const hookDurationFrames = hook?.durationFrames ?? 0;

  // v58.4.0: 蹂명렪 ?쒖옉 ?꾨젅??= hook ?앸궃 ??
  // 湲곗〈: 泥??먮쭑 ?쒖옉 ?쒖젏 ??蹂寃? hook ?앸궃 吏곹썑
  const mainContentStartFrame = hookDurationFrames;

  // v59: 鍮꾩＜???댄럺???쒖꽦???щ?
  const useEnhancedVisuals = !!(visualEffects?.vignette || visualEffects?.colorFilter || visualEffects?.transition);
  const useStyledSubtitles = !!subtitleStyle;

  // staticFile()濡?public ?대뜑 寃쎈줈 留ㅽ븨
  const getAssetPath = (path: string) => {
    if (path.startsWith("http") || path.startsWith("/")) return path;
    return staticFile(path);
  };

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      {/* v58.4.0: Hook ?쒗??(留??욎뿉 ?쒖떆) */}
      {hook && (
        <Sequence from={0} durationInFrames={hook.durationFrames}>
          <Hook
            topLabel={hook.topLabel}
            topColor={hook.topColor}
            mainText={hook.mainText}
            mainColor={hook.mainColor}
            bgColor={hook.bgColor}
            durationFrames={hook.durationFrames}
          />
        </Sequence>
      )}

      {/* ?대?吏 ?쒗??- v59.4: 耳?踰덉뒪 6紐⑤뱶 + 鍮꾩＜???댄럺?? v58.4.0: hook ?ㅽ봽???곸슜 */}
      {images.map((img, index) => {
        // v59.4: ?대?吏蹂?kenBurns ?ㅼ젙 (?놁쑝硫??몃뜳??湲곕컲 ?먮룞 ?좊떦)
        const kbModes: KenBurnsMode[] = ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down"];
        const autoMode = img.kenBurns?.mode || kbModes[index % kbModes.length];
        const autoIntensity = img.kenBurns?.intensity || 0.08;

        return (
          <Sequence
            key={`img-${index}`}
            from={img.startFrame + hookDurationFrames}
            durationInFrames={img.durationFrames}
          >
            {useEnhancedVisuals ? (
              <EnhancedImage
                src={getAssetPath(img.path)}
                backgroundSrc={img.backgroundPath ? getAssetPath(img.backgroundPath) : undefined}
                foregroundSrc={img.foregroundPath ? getAssetPath(img.foregroundPath) : undefined}
                headSrc={img.headPath ? getAssetPath(img.headPath) : undefined}
                bodySrc={img.bodyPath ? getAssetPath(img.bodyPath) : undefined}
                leftArmSrc={img.leftArmPath ? getAssetPath(img.leftArmPath) : undefined}
                rightArmSrc={img.rightArmPath ? getAssetPath(img.rightArmPath) : undefined}
                eyesOpenSrc={img.eyesOpenPath ? getAssetPath(img.eyesOpenPath) : undefined}
                eyesClosedSrc={img.eyesClosedPath ? getAssetPath(img.eyesClosedPath) : undefined}
                mouthClosedSrc={img.mouthClosedPath ? getAssetPath(img.mouthClosedPath) : undefined}
                mouthOpenSrc={img.mouthOpenPath ? getAssetPath(img.mouthOpenPath) : undefined}
                mouthCues={img.mouthCues}
                durationFrames={img.durationFrames}
                motion={img.motion}
                motiontoonEnabled={motiontoon?.enabled}
                motiontoonMode={motiontoon?.mode}
                transition={visualEffects?.transition}
                transitionDuration={visualEffects?.transitionDuration ?? 15}
                vignette={visualEffects?.vignette}
                colorFilter={visualEffects?.colorFilter}
                kenBurnsMode={autoMode}
                kenBurnsIntensity={autoIntensity}
              />
            ) : (
              <KenBurnsImage
                src={getAssetPath(img.path)}
                backgroundSrc={img.backgroundPath ? getAssetPath(img.backgroundPath) : undefined}
                foregroundSrc={img.foregroundPath ? getAssetPath(img.foregroundPath) : undefined}
                headSrc={img.headPath ? getAssetPath(img.headPath) : undefined}
                bodySrc={img.bodyPath ? getAssetPath(img.bodyPath) : undefined}
                leftArmSrc={img.leftArmPath ? getAssetPath(img.leftArmPath) : undefined}
                rightArmSrc={img.rightArmPath ? getAssetPath(img.rightArmPath) : undefined}
                eyesOpenSrc={img.eyesOpenPath ? getAssetPath(img.eyesOpenPath) : undefined}
                eyesClosedSrc={img.eyesClosedPath ? getAssetPath(img.eyesClosedPath) : undefined}
                mouthClosedSrc={img.mouthClosedPath ? getAssetPath(img.mouthClosedPath) : undefined}
                mouthOpenSrc={img.mouthOpenPath ? getAssetPath(img.mouthOpenPath) : undefined}
                mouthCues={img.mouthCues}
                durationFrames={img.durationFrames}
                motion={img.motion}
                motiontoonEnabled={motiontoon?.enabled}
                motiontoonMode={motiontoon?.mode}
                kenBurnsMode={autoMode}
                kenBurnsIntensity={autoIntensity}
              />
            )}
          </Sequence>
        );
      })}

      {/* ?먮쭑 ?쒗??- v59: ?ㅽ????먮쭑 吏?? v57.4: 梨꾨꼸蹂??ш린 ?꾨떖, v58.4.0: hook ?ㅽ봽???곸슜 */}
      {subtitles.map((sub, index) => {
        const subtitleMode = sub.motion?.subtitle_mode || "default";
        if (subtitleMode === "hidden") {
          return null;
        }
        const renderSubtitleMode = subtitleMode === "overlay_safe" ? "overlay_safe" : "default";

        const nextSub = subtitles[index + 1];
        const safeDurationFrames = nextSub
          ? Math.max(1, Math.min(sub.durationFrames, nextSub.startFrame - sub.startFrame))
          : Math.max(1, sub.durationFrames);

        return (
          <Sequence
            key={`sub-${index}`}
            from={sub.startFrame + hookDurationFrames}
            durationInFrames={safeDurationFrames}
          >
            {useStyledSubtitles ? (
              <StyledSubtitle
                text={sub.text}
                speaker={sub.speaker}
                speakerColor={sub.speakerColor}
                style={subtitleStyle}
                motion={sub.motion}
                motiontoonEnabled={motiontoon?.enabled}
                subtitleMode={renderSubtitleMode}
              />
            ) : (
              <Subtitle
                text={sub.text}
                speaker={sub.speaker}
                speakerColor={sub.speakerColor}
                subtitleSize={subtitleSize}
                speakerSize={speakerSize}
                motion={sub.motion}
                motiontoonEnabled={motiontoon?.enabled}
                subtitleMode={renderSubtitleMode}
              />
            )}
          </Sequence>
        );
      })}

      {/* v58.1: AI ?쒖옉 ?쒓린 (蹂명렪 ?쒖옉 ???쇱そ ?곷떒??3珥덇컙 ?쒖떆) */}
      {showAiDisclosure && (
        <Sequence from={mainContentStartFrame} durationInFrames={aiDisclosureFrames}>
          <AiDisclosure durationFrames={aiDisclosureFrames} />
        </Sequence>
      )}

      {/* v58.3.3: ?꾩껜 TTS ?ㅻ뵒??- v58.4.0: hook ?앸궃 ???쒖옉 */}
      {fullAudioPath ? (
        <Sequence from={hookDurationFrames}>
          <Audio src={getAssetPath(fullAudioPath)} volume={ttsVolume} />
        </Sequence>
      ) : (
        audioSegments.map((audio, index) => (
          <Sequence key={`audio-${index}`} from={audio.startFrame + hookDurationFrames}>
            <Audio src={getAssetPath(audio.path)} volume={ttsVolume} />
          </Sequence>
        ))
      )}

      {/* v59.3.5: SFX ?④낵??(FFmpeg 誘뱀떛 ?쒓굅, Remotion ?듯빀) */}
      {sfxCues.map((sfx, index) => (
        <Sequence
          key={`sfx-${index}`}
          from={sfx.startFrame + hookDurationFrames}
          durationInFrames={sfx.durationFrames || 150}
        >
          <Audio
            src={getAssetPath(sfx.path)}
            volume={(f) => {
              const fadeIn = sfx.fadeInFrames || 0;
              const fadeOut = sfx.fadeOutFrames || 0;
              const dur = sfx.durationFrames || 150;
              let vol = sfx.volume;
              // ?섏씠????
              if (fadeIn > 0 && f < fadeIn) {
                vol = interpolate(f, [0, fadeIn], [0, sfx.volume]);
              }
              // ?섏씠???꾩썐
              if (fadeOut > 0 && f > dur - fadeOut) {
                vol = interpolate(f, [dur - fadeOut, dur], [sfx.volume, 0]);
              }
              return vol;
            }}
          />
        </Sequence>
      ))}

      {/* BGM (蹂쇰ⅷ ??땄, ?섏씠?쒖씤/?꾩썐) - 泥섏쓬遺???쒖옉 (hook ?ы븿) */}
      {/* v58.4.1: loop 異붽? - BGM???앸굹??諛섎났 ?ъ깮 */}
      {bgmPath && (
        <Audio
          src={getAssetPath(bgmPath)}
          loop
          volume={(f) => {
            // 泥섏쓬 1珥??섏씠?쒖씤
            if (f < 30) return interpolate(f, [0, 30], [0, bgmVolume]);
            // v61.1 (#40): 留덉?留?3珥??섏씠?쒖븘??(?곸긽 ?앹뿉???뚯븙 ???딄? 諛⑹?)
            const fadeOutStart = totalCompositionFrames - 90;
            if (f > fadeOutStart) return interpolate(f, [fadeOutStart, totalCompositionFrames], [bgmVolume, 0], { extrapolateRight: "clamp" });
            return bgmVolume;
          }}
        />
      )}
    </AbsoluteFill>
  );
};
