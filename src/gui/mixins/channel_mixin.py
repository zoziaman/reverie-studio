# src/gui/mixins/channel_mixin.py
"""
v60.1.0: 채널/팩 관리 Mixin — 채널 선택, 팩 로딩, 패키지 설정

ReverieGUI에서 추출된 8개 메서드:
- _load_channel_options: 채널 옵션 목록 로드
- _on_channel_selected: 채널 선택 콜백
- _load_default_pack_for_basic_channel: 기본 팩 로드
- _refresh_channel_list: 채널 목록 새로고침
- _apply_package_settings: 패키지 설정 적용
- _load_package_to_active_pack: ACTIVE_PACK에 패키지 로드
- _load_revpack_to_active: .revpack 파일 로드
- _update_voice_settings_visibility: 음성 설정 UI 표시/숨김

의존하는 self 변수:
- self.channel_options, self.channel_dropdown, self.channel_var
- self.license_info, self.license_validator
- self.voice_settings_frame
"""
from config.settings import config
from utils.logger import get_logger

logger = get_logger("channel_mixin")


class ChannelMixin:
    """채널/팩 관리 횡단 관심사"""

    def _load_channel_options(self):
        """
        채널 옵션 목록 로드

        v63: 라이선스/owned_packs 제거 (개인용).
        기본 채널 + 설치된 모든 패키지를 항상 표시.

        Returns:
            list of (channel_id, display_name, package_data or None)
        """
        options = []

        # VideoToon-only official packs. Legacy horror/senior packs are retired.
        DEFAULT_CHANNELS = [
            ("daily_life_toon", "🎬 일상 영상툰", None),
            ("mystery_toon", "🔎 미스터리 영상툰", None),
        ]

        # 기본 내장 채널 추가
        options.extend(DEFAULT_CHANNELS)

        # 설치된 커스텀 패키지도 모두 추가
        try:
            from utils.package_manager import get_package_manager
            pm = get_package_manager()
            installed = pm.list_installed_packages()

            for pkg_id, pkg_info in installed.items():
                # 기본 채널과 중복 방지
                if pkg_id not in ['daily_life_toon', 'mystery_toon']:
                    pkg_name = pkg_info.get('package_name', pkg_id)
                    display = f"📦 {pkg_name}"
                    options.append((pkg_id, display, pkg_info))

        except Exception as e:
            logger.warning(f"[main_window] 패키지 목록 로드 실패: {e}")

        return options

    def _on_channel_selected(self, selected_display_name: str):
        """채널 선택 시 콜백"""
        # display_name으로 channel_id 찾기
        for ch_id, display, pkg_data in self.channel_options:
            if display == selected_display_name:
                self.channel_var.set(ch_id)

                # 패키지 기반 채널이면 설정 적용
                if pkg_data:
                    self._apply_package_settings(ch_id, pkg_data)
                    self._add_log(f"📦 패키지 채널 선택: {selected_display_name}")
                else:
                    # v57.7.2: 기본 채널 선택 시에도 기본 팩 로드
                    self._load_default_pack_for_basic_channel(ch_id)
                    self._add_log(f"📺 기본 채널 선택: {selected_display_name}")
                break

        # 음성 설정 UI 업데이트
        self._update_voice_settings_visibility()

        # v59.1.0: SD 모델 상태 업데이트 (팩 로드 후)
        self.after(100, self._update_sd_model_status)
        if hasattr(self, "_refresh_pack_feature_statuses"):
            self.after(100, self._refresh_pack_feature_statuses)

    def _load_default_pack_for_basic_channel(self, channel_id: str):
        """
        v57.7.2: 기본 채널 선택 시 기본 팩 로드

        기본 채널(horror, senior 등)도 ACTIVE_PACK을 통해 프롬프트를 사용하도록
        load_default_pack을 호출하여 기본 프롬프트 설정

        Args:
            channel_id: 채널 ID (예: horror, senior_touching, senior_makjang)
        """
        try:
            from config.pack_config import load_default_pack, ACTIVE_PACK

            # v59.1.6: 채널 ID를 그대로 load_default_pack에 전달
            # (senior_touching, senior_makjang 각각의 JSON 팩이 존재)
            genre = channel_id

            # 기본 팩 로드
            if load_default_pack(genre):
                self._add_log(f"  └─ 🎬 팩 로드: {ACTIVE_PACK.pack_name}")
                # v57.7.3: 팩 상세 정보 표시
                bgm_source = ACTIVE_PACK.assets.use_channel_bgm or "기본"
                tts_source = ACTIVE_PACK.assets.use_channel_tts or "기본"
                self._add_log(f"      BGM: {bgm_source} | TTS: {tts_source}")
            else:
                self._add_log(f"  └─ ⚠️ 기본 팩 로드 실패 (장르: {genre})")

        except Exception as e:
            self._add_log(f"  └─ ⚠️ 기본 팩 로드 오류: {e}")

    def _refresh_channel_list(self):
        """채널 목록 새로고침"""
        self.channel_options = self._load_channel_options()
        display_names = [opt[1] for opt in self.channel_options]
        self.channel_dropdown.configure(values=display_names)
        self._add_log("[REFRESH] 채널 목록 새로고침 완료")

    def _apply_package_settings(self, channel_id: str, pkg_data: dict):
        """
        패키지 설정을 현재 세션에 적용

        Args:
            channel_id: 채널 ID
            pkg_data: 패키지 정보 딕셔너리
        """
        try:
            from utils.package_manager import get_package_manager
            pm = get_package_manager()

            # 전체 패키지 데이터 로드
            package = pm.get_channel(channel_id)
            if not package:
                logger.warning(f"[main_window] 패키지 로드 실패: {channel_id}")
                return

            # v57.7.2: ACTIVE_PACK에 패키지 프롬프트 로드
            source_revpack = ""
            if hasattr(package, 'extra_config') and isinstance(package.extra_config, dict):
                source_revpack = package.extra_config.get("source_revpack", "")

            if source_revpack:
                if self._load_revpack_to_active(source_revpack):
                    logger.info(f"[main_window] source_revpack direct load: {source_revpack}")
                else:
                    logger.warning(f"[main_window] source_revpack load failed, fallback to package data: {source_revpack}")
                    self._load_package_to_active_pack(package)
            else:
                self._load_package_to_active_pack(package)

            # 프롬프트 설정 적용 (config에 임시 저장)
            if package.prompts:
                prompts = package.prompts
                if hasattr(prompts, 'sd_positive'):
                    config.PROFILES[channel_id] = {
                        'sd_positive': prompts.sd_positive,
                        'sd_negative': prompts.sd_negative,
                        'pd_prompt': getattr(prompts, 'pd_system_prompt', ''),
                        'writer_prompt': getattr(prompts, 'writer_system_prompt', '')
                    }

            # 캐릭터 설정 적용
            if package.characters:
                # 캐릭터별 자막 색상 등 설정
                for char in package.characters:
                    if hasattr(char, 'role_id'):
                        role_id = char.role_id
                        color = getattr(char, 'subtitle_color', '#FFFFFF')
                        # config에 저장
                        if not hasattr(config, 'CUSTOM_COLORS'):
                            config.CUSTOM_COLORS = {}
                        config.CUSTOM_COLORS[role_id] = color

            logger.info(f"[main_window] 패키지 설정 적용 완료: {channel_id}")

        except Exception as e:
            logger.error(f"[main_window] 패키지 설정 적용 실패: {e}")

    def _load_package_to_active_pack(self, package) -> bool:
        """
        v57.7.2: ChannelPackage를 ACTIVE_PACK에 로드

        채널 선택 시 해당 패키지의 프롬프트가 ACTIVE_PACK에 적용되어
        scenario_planner, script_writers, media_factory에서 사용됨

        Args:
            package: ChannelPackage 객체

        Returns:
            성공 여부
        """
        try:
            from config.pack_config import (
                ACTIVE_PACK, PackPrompts, PackContent, PackAssets
            )

            # 패키지 프롬프트 추출
            prompts = package.prompts if package.prompts else {}

            # prompts가 객체인 경우 딕셔너리로 변환
            if hasattr(prompts, '__dict__'):
                prompts_dict = {
                    'pd_system': getattr(prompts, 'pd_system', '') or getattr(prompts, 'pd_system_prompt', ''),
                    'writer_system': getattr(prompts, 'writer_system', '') or getattr(prompts, 'writer_system_prompt', ''),
                    'sd_positive': getattr(prompts, 'sd_positive', ''),
                    'sd_negative': getattr(prompts, 'sd_negative', ''),
                }
                # sd_prompts가 별도 객체인 경우
                if hasattr(prompts, 'sd_prompts') and prompts.sd_prompts:
                    sd = prompts.sd_prompts
                    if isinstance(sd, dict):
                        prompts_dict['sd_positive'] = sd.get('positive', '')
                        prompts_dict['sd_negative'] = sd.get('negative', '')
                    elif hasattr(sd, 'positive'):
                        prompts_dict['sd_positive'] = sd.positive
                        prompts_dict['sd_negative'] = sd.negative
            elif isinstance(prompts, dict):
                prompts_dict = {
                    'pd_system': prompts.get('pd_system', '') or prompts.get('pd_system_prompt', ''),
                    'writer_system': prompts.get('writer_system', '') or prompts.get('writer_system_prompt', ''),
                    'sd_positive': prompts.get('sd_positive', ''),
                    'sd_negative': prompts.get('sd_negative', ''),
                }
                if 'sd_prompts' in prompts and prompts['sd_prompts']:
                    sd = prompts['sd_prompts']
                    prompts_dict['sd_positive'] = sd.get('positive', '')
                    prompts_dict['sd_negative'] = sd.get('negative', '')
            else:
                prompts_dict = {}

            # ACTIVE_PACK 업데이트
            ACTIVE_PACK.pack_id = package.package_id or ""
            ACTIVE_PACK.pack_name = package.package_name or package.channel_display_name or ""
            ACTIVE_PACK.version = package.version or "1.0.0"
            ACTIVE_PACK.author = package.author or ""
            ACTIVE_PACK.genre = package.channel_type or ""
            ACTIVE_PACK.channel_type = package.channel_type or ""  # v60.1.0: visual_director에서 참조

            # 프롬프트 설정
            ACTIVE_PACK.prompts = PackPrompts(
                pd_system=prompts_dict.get('pd_system', ''),
                writer_system=prompts_dict.get('writer_system', ''),
                sd_positive=prompts_dict.get('sd_positive', ''),
                sd_negative=prompts_dict.get('sd_negative', ''),
            )

            # 토픽 템플릿
            if hasattr(prompts, 'topics') and prompts.topics:
                topics = prompts.topics
                if isinstance(topics, dict):
                    ACTIVE_PACK.topic_templates = topics.get('templates', [])
                    ACTIVE_PACK.tags = topics.get('tags', [])
            elif isinstance(prompts, dict) and 'topics' in prompts:
                topics = prompts['topics']
                if isinstance(topics, dict):
                    ACTIVE_PACK.topic_templates = topics.get('templates', [])
                    ACTIVE_PACK.tags = topics.get('tags', [])

            # 캐릭터 설정 (v57.7.6: 안전하게 접근)
            if hasattr(package, 'character_config') and package.character_config:
                ACTIVE_PACK.character_config = package.character_config

            # v57.7.6: 감정 설정 로드
            # v61: extra_config에 감정 없으면 load_pack_by_id로 재로딩하여
            #       이전 팩 감정이 잔존하는 버그 방지
            emotions_loaded = False
            if hasattr(package, 'extra_config') and package.extra_config:
                extra = package.extra_config
                if 'allowed_emotions' in extra:
                    ACTIVE_PACK.allowed_emotions = extra['allowed_emotions']
                    emotions_loaded = True
                if 'emotion_policy' in extra:
                    ACTIVE_PACK.emotion_policy = extra['emotion_policy']

            if not emotions_loaded:
                # extra_config에 감정이 없으면 .revpack에서 가져옴
                try:
                    from config.pack_config import load_pack_by_id as _reload_pack
                    pack_id = package.package_id or ""
                    if pack_id:
                        _reload_pack(pack_id)
                        logger.info(f"[v61] 감정 미갱신 → load_pack_by_id({pack_id})로 전체 재로딩")
                except Exception as e:
                    logger.warning(f"[v61] 팩 재로딩 실패, 기본 감정 유지: {e}")

            # v57.7.6: 오디오 설정 로드 (BGM/SFX/TTS)
            if hasattr(package, 'audio_config') and package.audio_config:
                audio = package.audio_config
                ACTIVE_PACK.assets.bgm_path = audio.get('bgm_path', '')
                ACTIVE_PACK.assets.sfx_path = audio.get('sfx_path', '')
                ACTIVE_PACK.assets.use_channel_bgm = audio.get('use_channel_bgm', '')
                ACTIVE_PACK.assets.use_channel_sfx = audio.get('use_channel_sfx', '')
                ACTIVE_PACK.assets.use_channel_tts = audio.get('use_channel_tts', '')

            # v59.5.16: Visual Storytelling 설정 로드 — dict이면 dataclass로 변환
            if hasattr(package, 'visual_storytelling') and package.visual_storytelling:
                vs = package.visual_storytelling
                if isinstance(vs, dict):
                    # dict → VisualStorytellingConfig 변환 (_load_visual_storytelling_config 활용)
                    try:
                        from config.pack_config import _load_visual_storytelling_config
                        ACTIVE_PACK.visual_storytelling = _load_visual_storytelling_config({"visual_storytelling": vs})
                        img_gen = vs.get('image_generation', {})
                        logger.info(f"[v59.5.16] visual_storytelling 변환 로드 (dict→dataclass): enabled={vs.get('enabled')}, target_images={img_gen.get('target_images')}")
                    except Exception as e:
                        logger.warning(f"[v59.5.16] visual_storytelling 변환 실패, dict 그대로 저장: {e}")
                        ACTIVE_PACK.visual_storytelling = vs
                else:
                    ACTIVE_PACK.visual_storytelling = vs
                    logger.info(f"[v59.5.16] visual_storytelling 로드됨 (객체): enabled={getattr(vs, 'enabled', False)}")

            if hasattr(package, 'motiontoon') and package.motiontoon:
                motiontoon_data = package.motiontoon
                if isinstance(motiontoon_data, dict):
                    try:
                        from config.pack_config import _load_motiontoon_config
                        fallback_enabled = bool(getattr(ACTIVE_PACK.visual_storytelling, "enabled", False))
                        ACTIVE_PACK.motiontoon = _load_motiontoon_config(
                            {"motiontoon": motiontoon_data},
                            fallback_enabled=fallback_enabled,
                        )
                    except Exception as e:
                        logger.warning(f"[Motiontoon] package fallback load failed: {e}")
                else:
                    ACTIVE_PACK.motiontoon = motiontoon_data

            # v60: SFX/atmosphere/emergency 설정 로드 (팩-클라이언트 아키텍처)
            # NOTE: ChannelPackage에는 raw_settings가 없음. load_pack_by_id()에서 이미 설정됨.
            # 이 블록은 package 객체에 raw_settings가 추가될 경우를 위한 방어 코드.
            try:
                from config.pack_config import PackSFX, PackAtmosphere, PackEmergency

                # SFX 설정
                raw_settings = getattr(package, 'raw_settings', {}) if hasattr(package, 'raw_settings') else {}
                sfx_data = raw_settings.get('sfx', {})
                if sfx_data.get('category_guide') or sfx_data.get('keyword_map'):
                    ACTIVE_PACK.sfx = PackSFX(
                        category_guide=sfx_data.get('category_guide', ''),
                        keyword_map=sfx_data.get('keyword_map', {}),
                    )

                # 분위기 설정
                atmos_data = raw_settings.get('atmosphere', {})
                if atmos_data.get('mood_map') or atmos_data.get('keywords'):
                    ACTIVE_PACK.atmosphere = PackAtmosphere(
                        mood_map=atmos_data.get('mood_map', {}),
                        keywords=atmos_data.get('keywords', {}),
                    )

                # 비상 시퀀스
                emergency_data = raw_settings.get('emergency', {})
                if emergency_data.get('template_sequence'):
                    ACTIVE_PACK.emergency = PackEmergency(
                        template_sequence=emergency_data.get('template_sequence', []),
                    )

                logger.info(f"[v60] SFX/atmosphere/emergency 로드: sfx_guide={bool(sfx_data.get('category_guide'))}, atmos={bool(atmos_data.get('mood_map'))}, emergency={bool(emergency_data.get('template_sequence'))}")
            except ImportError:
                logger.debug("[v60] PackSFX/PackAtmosphere/PackEmergency import 실패, 기본값 유지")

            ACTIVE_PACK.is_loaded = True
            ACTIVE_PACK.source_path = f"package:{package.package_id}"

            logger.info(f"[main_window] ACTIVE_PACK 로드 완료: {ACTIVE_PACK.pack_name} (from package)")
            return True

        except ImportError:
            logger.warning("[main_window] pack_config 모듈 없음")
            return False
        except Exception as e:
            logger.error(f"[main_window] ACTIVE_PACK 로드 실패: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _load_revpack_to_active(self, revpack_path: str) -> bool:
        """
        v57.7.0: .revpack 파일을 ACTIVE_PACK에 로드

        Args:
            revpack_path: .revpack 파일 경로

        Returns:
            성공 여부
        """
        try:
            from config.pack_config import load_pack, ACTIVE_PACK
            success = load_pack(revpack_path)
            if success:
                logger.info(f"[main_window] ACTIVE_PACK 로드 완료: {ACTIVE_PACK.pack_name}")
            return success
        except ImportError:
            logger.warning("[main_window] pack_config 모듈 없음")
            return False
        except Exception as e:
            logger.error(f"[main_window] ACTIVE_PACK 로드 실패: {e}")
            return False

    def _update_voice_settings_visibility(self):
        """채널에 따라 음성 설정 UI 표시/숨김"""
        # UI 초기화 전이면 스킵
        if not hasattr(self, 'voice_settings_frame') or not self.voice_settings_frame:
            return

        channel = self.channel_var.get()

        # 시니어 채널이거나 패키지 채널일 때 음성 설정 표시
        if channel in ['daily_life_toon', 'mystery_toon'] or channel not in ['horror', 'senior_touching', 'senior_makjang']:
            self.voice_settings_frame.pack(fill="x", padx=20, pady=(0, 15))
        else:
            # 공포 채널은 음성 설정 숨김 (나레이터만 사용)
            pass  # 일단 항상 표시
