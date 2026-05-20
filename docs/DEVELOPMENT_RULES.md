# Claude-NotebookLM 협업 개발 룰

> 이 문서는 Claude와 NotebookLM AI Agent Team 간의 협업 규칙입니다.
> 모든 개발 과정에서 필수 준수해야 합니다.
> 최종 업데이트: 2026-02-06

---

## 1. 에러/오류 제로 정책

- 코드 작성 후 **반드시 검토**
- 에러 발생 시 **즉시 수정** 후 재검토
- 에러가 **완전히 없어질 때까지** 반복
- 검증 방법:
  ```bash
  python -c "import sys; sys.path.insert(0, 'src'); sys.path.insert(0, 'lib'); from [모듈] import [클래스]"
  ```

---

## 2. 모듈 간 괴리감 제거

### 의존성 규칙
- 모듈 간 의존성 검토
- import 충돌 확인
- 데이터 타입 일관성 유지

### 싱글톤 패턴 (필수)
```python
# 올바른 방법
from utils.instance_manager import get_instance_manager
manager = get_instance_manager()
engine = manager.get_utopia_engine(data_dir, channel_type, channel_id)

# 또는 헬퍼 함수
from utils.feedback_loop import get_feedback_loop
feedback = get_feedback_loop(data_dir, channel_type)
```

### Thread Safety
```python
def _save_state(self):
    with self._lock:
        with open(self.state_path, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)
```

---

## 3. GUI 일관성

- **PySide6** 스타일 통일
- 기존 다이얼로그 패턴 준수
- **한국어 UI** 유지
- 참고 파일: `src/gui/auto_optimizer_dialog.py`

---

## 4. 버전 완료 시 백업

버전이 완성되면:

1. 프로젝트 폴더 전체 복사
2. 최상위 폴더에 버전명으로 저장
3. 명명 규칙: `Reverie_Studio_v{버전}`

예시:
```
C:\
├── ReverieStudio\              # 개발 폴더
├── Reverie_Studio_v56.0.0\    # v56 백업
├── Reverie_Studio_v57.0.0\    # v57 백업
```

---

## 5. 품질 체크리스트

버전 완료 전 반드시 확인:

- [ ] 모든 import 정상 작동
- [ ] 싱글톤 인스턴스 정상
- [ ] GUI 오류 없음
- [ ] 기존 기능 영향 없음
- [ ] Thread Safety 적용 확인
- [ ] 한국어 주석 작성 완료

---

## 6. 협업 워크플로우

```
1. Claude: 개발 계획 수립
      ↓
2. NotebookLM: 분석/검토/피드백
      ↓
3. Claude: 코드 작성
      ↓
4. Claude + NotebookLM: 에러 검토 (반복)
      ↓
5. 에러 제로 확인
      ↓
6. 회장님께 보고
      ↓
7. 승인 후 버전 백업
```

---

## 7. 커밋 규칙

```bash
git commit -m "$(cat <<'EOF'
v57.0.0: 다국어 지원 기능 추가

- src/core/translator.py 신설
- channel_registry.py에 target_language 추가
- media_factory.py 다국어 TTS 지원

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## 8. PDCA 워크플로우 (v58)

> **"설계 없이 구현 금지"**

코드 작성 요청 시:

1. **Plan** - 바로 코드 작성 금지!
   - 목표, 수정 파일, 영향 범위 파악

2. **Design** - 구조 먼저
   - 클래스/함수 시그니처, 데이터 흐름

3. **Review** - 승인 대기
   - "이 설계로 진행해도 될까요?"

4. **Do** - 승인 후 구현

5. **Check** - 검증
   - import 테스트, 기존 코드 호환성

**예외 (PDCA 생략)**
- 단순 오타 수정
- 1~3줄 이하 변경
- 사용자가 "바로 해줘" 요청

---

## 버전 히스토리

| 버전 | 날짜 | 변경 내용 |
|------|------|-----------|
| 1.0 | 2026-01-30 | 초기 룰 문서 작성 |
| 1.1 | 2026-02-06 | PDCA 워크플로우 추가 |
