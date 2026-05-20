import { Composition, getInputProps } from "remotion";
import { RadioDrama } from "./RadioDrama";

// Python에서 전달받는 props
// v61.1 (#43): 15개 전체 선언
interface InputProps {
  images: Array<{
    path: string;
    startFrame: number;
    durationFrames: number;
    motion?: Record<string, unknown>;
    // v59.4: 이미지별 켄 번스 설정
    kenBurns?: {
      mode: "zoom_in" | "zoom_out" | "pan_left" | "pan_right" | "pan_up" | "pan_down";
      intensity?: number;
    };
  }>;
  audioSegments: Array<{
    path: string;
    startFrame: number;
  }>;
  subtitles: Array<{
    text: string;
    speaker: string;
    speakerColor?: string;  // v57.4: 화자 색상
    startFrame: number;
    durationFrames: number;
    motion?: Record<string, unknown>;
  }>;
  motiontoon?: Record<string, unknown>;
  bgmPath?: string;
  bgmVolume?: number;
  // v59.3.5: SFX 효과음 (Remotion 통합)
  sfxCues?: Array<{
    path: string;
    startFrame: number;
    volume: number;
    durationFrames?: number;
    fadeInFrames?: number;
    fadeOutFrames?: number;
  }>;
  // v57.4: 채널별 자막 크기
  subtitleSize?: number;
  speakerSize?: number;
  // v58.4.0: Hook (오프닝)
  hook?: {
    text: string;
    topLabel?: string;
    durationFrames: number;
    style?: string;
  };
  // v57.6: 전체 TTS 오디오
  fullAudioPath?: string;
  ttsVolume?: number;
  // v59: AI 고지
  showAiDisclosure?: boolean;
  aiDisclosureDuration?: number;
  // v59: 비주얼 이펙트/자막 스타일
  visualEffects?: Record<string, unknown>;
  subtitleStyle?: Record<string, unknown>;
  // 기본
  totalFrames: number;
  fps: number;
  width: number;
  height: number;
}

export const RemotionRoot: React.FC = () => {
  // CLI에서 --props로 전달된 데이터
  const inputProps = getInputProps() as Partial<InputProps>;

  // 기본값 설정
  const totalFrames = inputProps.totalFrames || 900;
  const fps = inputProps.fps || 30;
  const width = inputProps.width || 1920;
  const height = inputProps.height || 1080;

  return (
    <>
      <Composition
        id="RadioDrama"
        component={RadioDrama}
        durationInFrames={totalFrames}
        fps={fps}
        width={width}
        height={height}
        defaultProps={{
          images: inputProps.images || [],
          audioSegments: inputProps.audioSegments || [],
          subtitles: inputProps.subtitles || [],
          motiontoon: inputProps.motiontoon,
          bgmPath: inputProps.bgmPath,
          bgmVolume: inputProps.bgmVolume || 0.15,
          // v59.3.5: SFX 효과음
          sfxCues: inputProps.sfxCues || [],
          // v57.4: 채널별 자막 크기
          subtitleSize: inputProps.subtitleSize || 36,
          speakerSize: inputProps.speakerSize || 28,
          // v61.1 (#43): 누락된 프롭 추가
          hook: inputProps.hook,
          fullAudioPath: inputProps.fullAudioPath,
          ttsVolume: inputProps.ttsVolume || 2.5,
          showAiDisclosure: inputProps.showAiDisclosure ?? true,
          aiDisclosureDuration: inputProps.aiDisclosureDuration || 3.0,
          visualEffects: inputProps.visualEffects,
          subtitleStyle: inputProps.subtitleStyle,
        }}
      />
    </>
  );
};
