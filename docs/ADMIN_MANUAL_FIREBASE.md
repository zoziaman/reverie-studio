# Firebase 관리자 메뉴얼

> 최종 업데이트: 2026-01-28
> Reverie Studio v54.7.3

이 문서는 Firebase Console을 사용하여 라이선스와 패키지 소유권을 관리하는 방법을 설명합니다.

---

## 목차

1. [Firebase Console 접속](#1-firebase-console-접속)
2. [라이선스 관리](#2-라이선스-관리)
3. [패키지 소유권 관리](#3-패키지-소유권-관리)
4. [Cloud Functions 모니터링](#4-cloud-functions-모니터링)
5. [자주 묻는 질문](#5-자주-묻는-질문)

---

## 1. Firebase Console 접속

### 접속 방법

1. 브라우저에서 [Firebase Console](https://console.firebase.google.com/) 접속
2. Google 계정으로 로그인
3. 프로젝트 선택: **reverie-license**

### 주요 메뉴

| 메뉴 | 용도 |
|------|------|
| **Firestore Database** | 라이선스 데이터 관리 |
| **Functions** | Cloud Functions 모니터링 |
| **Authentication** | (현재 미사용) |
| **Usage and billing** | 사용량 및 비용 확인 |

---

## 2. 라이선스 관리

### 2.1 Firestore 접속

1. 왼쪽 메뉴에서 **Firestore Database** 클릭
2. **licenses** 컬렉션 선택

### 2.2 라이선스 문서 구조

각 라이선스는 라이선스 키를 문서 ID로 사용합니다:

```
/licenses/TEST-1234-5678-ABCD
├── user_id: "user@example.com"       # 사용자 식별
├── hardware_id: "A6BFDA6D2C13AF95"   # 하드웨어 ID (자동 바인딩)
├── license_type: "T"                  # 라이선스 타입
├── is_active: true                    # 활성화 상태
├── expire_date: 2027-01-24 00:00:00  # 만료일
├── created_at: 2026-01-24 10:00:00   # 생성일
├── last_verified: 2026-01-24 15:30:00 # 마지막 검증 시간
├── owned_packs: ["horror_pack", "romance_pack"]  # 보유 패키지
└── memo: "테스트용 라이선스"           # 관리자 메모
```

### 2.3 라이선스 타입

| 타입 | 설명 | owned_packs 처리 |
|------|------|------------------|
| **A** | 전체 이용권 | 무시 (모든 패키지 접근 가능) |
| **H** | 공포 채널 전용 | `["horror_pack"]` |
| **T** | 개별 패키지 구매자 | 구매한 패키지 목록 |
| **M** | 월구독 | 구독 범위 패키지 |

### 2.4 새 라이선스 추가

1. **licenses** 컬렉션에서 **+ 문서 추가** 클릭
2. **문서 ID**: 라이선스 키 입력 (예: `PROD-XXXX-XXXX-XXXX`)
3. 필드 추가:

| 필드명 | 타입 | 값 예시 |
|--------|------|---------|
| `user_id` | string | `user@example.com` |
| `hardware_id` | string | `` (빈 값 - 첫 등록 시 자동 바인딩) |
| `license_type` | string | `T` |
| `is_active` | boolean | `true` |
| `expire_date` | timestamp | 만료일 선택 |
| `created_at` | timestamp | 현재 시간 |
| `owned_packs` | array | `["horror_pack"]` |
| `memo` | string | 관리자 메모 |

4. **저장** 클릭

### 2.5 라이선스 수정

1. 수정할 라이선스 문서 클릭
2. 필드 옆의 **편집** 아이콘 클릭
3. 값 수정 후 **업데이트** 클릭

**자주 수정하는 필드:**
- `is_active`: 라이선스 활성화/비활성화
- `expire_date`: 만료일 연장
- `owned_packs`: 패키지 추가/제거
- `hardware_id`: 다른 PC로 이전 시 빈 값으로 초기화

### 2.6 라이선스 비활성화

1. 해당 라이선스 문서 클릭
2. `is_active` 필드를 `false`로 변경
3. **업데이트** 클릭

> **주의**: 라이선스를 삭제하지 말고 비활성화하세요. 기록 보존을 위해 권장됩니다.

### 2.7 하드웨어 바인딩 해제

사용자가 PC를 교체한 경우:

1. 해당 라이선스 문서 클릭
2. `hardware_id` 필드를 빈 문자열(`""`)로 변경
3. **업데이트** 클릭

> 다음 로그인 시 새 PC의 hardware_id가 자동으로 바인딩됩니다.

---

## 3. 패키지 소유권 관리

### 3.1 패키지 ID 규칙

패키지 ID는 `.revpack` 파일의 `package_id`와 일치해야 합니다:

| 패키지 | ID |
|--------|-----|
| 공포 채널 팩 | `horror_pack` |
| 로맨스 채널 팩 | `romance_pack` |
| 시니어 감동 팩 | `senior_touching_pack` |
| 시니어 막장 팩 | `senior_makjang_pack` |

### 3.2 패키지 추가

사용자가 새 패키지를 구매한 경우:

1. 해당 라이선스 문서 클릭
2. `owned_packs` 배열 편집
3. 새 패키지 ID 추가
4. **업데이트** 클릭

**예시:**
```
기존: ["horror_pack"]
변경: ["horror_pack", "romance_pack"]
```

### 3.3 패키지 제거

환불 또는 구독 해지 시:

1. 해당 라이선스 문서 클릭
2. `owned_packs` 배열에서 해당 패키지 ID 제거
3. **업데이트** 클릭

### 3.4 전체 이용권으로 업그레이드

1. `license_type`을 `A`로 변경
2. `owned_packs`는 그대로 두어도 됨 (A 타입은 무시됨)

---

## 4. Cloud Functions 모니터링

### 4.1 Functions 접속

1. 왼쪽 메뉴에서 **Functions** 클릭
2. 배포된 함수 목록 확인

### 4.2 배포된 함수

| 함수명 | 용도 | 엔드포인트 |
|--------|------|-----------|
| `checkPackageOwnership` | 패키지 소유권 확인 | `https://us-central1-reverie-license.cloudfunctions.net/checkPackageOwnership` |
| `getOwnedPacks` | 보유 패키지 목록 조회 | `https://us-central1-reverie-license.cloudfunctions.net/getOwnedPacks` |

### 4.3 로그 확인

1. 함수 이름 클릭
2. **로그** 탭 선택
3. 최근 호출 기록 확인

**로그 필터링:**
- 에러만: 심각도를 `Error`로 필터
- 특정 사용자: 로그 검색에서 라이선스 키 입력

### 4.4 사용량 확인

1. **Usage and billing** 메뉴 클릭
2. **Functions** 탭에서 호출 수 확인

**무료 한도 (Spark 플랜):**
- 월 200만 회 호출
- 400,000 GB-초 컴퓨팅 시간

---

## 5. 자주 묻는 질문

### Q1: 사용자가 "라이선스가 등록되지 않았습니다"라고 합니다

**원인:**
1. 라이선스 키 오타
2. 라이선스가 Firestore에 없음
3. `is_active`가 `false`

**해결:**
1. Firestore에서 라이선스 키 검색
2. 없으면 새로 생성
3. 있으면 `is_active` 확인

### Q2: "다른 컴퓨터에 등록되어 있습니다"라고 합니다

**원인:** `hardware_id`가 이미 다른 값으로 설정됨

**해결:**
1. 사용자에게 이전 PC 사용 여부 확인
2. 정당한 PC 교체인 경우 `hardware_id`를 빈 값으로 초기화

### Q3: "구매하지 않은 패키지입니다"라고 합니다

**원인:** `owned_packs` 배열에 해당 패키지가 없음

**해결:**
1. 구매 기록 확인
2. `owned_packs`에 패키지 ID 추가

### Q4: 라이선스가 만료되었습니다

**해결:**
1. `expire_date`를 새 만료일로 변경
2. 또는 `is_active`를 `false`로 변경 (갱신 안 함)

### Q5: Cloud Functions가 작동하지 않습니다

**확인 사항:**
1. Functions 콘솔에서 배포 상태 확인 (녹색 체크)
2. 로그에서 에러 메시지 확인
3. 네트워크 문제인지 클라이언트 측 테스트

**재배포 필요 시:**
```bash
cd firebase/functions
firebase deploy --only functions
```

---

## 보안 주의사항

1. **Firebase Console 접근 제한**: 관리자 계정만 접근 가능하게 설정
2. **라이선스 키 유출 주의**: 스크린샷 공유 시 라이선스 키 가리기
3. **정기 백업**: Firestore 데이터 정기 백업 권장
4. **로그 모니터링**: 비정상적인 접근 패턴 주시

---

## 연락처

- 기술 문의: [개발자 이메일]
- 긴급 이슈: [긴급 연락처]

---

*이 문서는 Reverie Studio v54.7.3 기준으로 작성되었습니다.*
*최종 업데이트: 2026-01-28*
# Current Pack Policy (2026-05-01)

Reverie product-facing packs are now:

- `daily_life_toon_pack`: 일상 영상툰
- `mystery_toon_pack`: 미스터리 영상툰

Old examples such as `horror_pack`, `senior_touching_pack`, and `senior_makjang_pack` are historical references only and should not be assigned to new users.

---
