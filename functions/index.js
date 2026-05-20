const functions = require('firebase-functions');
const admin = require('firebase-admin');
admin.initializeApp();

// v62.32: 팩 소유권 매핑 — 모듈 레벨 공유 (checkPackageOwnership + getPackKey 일치 보장)
// Firestore owned_packs의 토큰 값 → 실제 packId 매핑
const PACK_OWNERSHIP_MAP = {
  'horror_v59':      ['horror_pack', 'horror_v59'],
  'senior_touching': ['senior_touching', 'senior_pack', 'senior_touching_pack'],
  'senior_makjang':  ['senior_makjang',  'senior_pack', 'senior_makjang_pack'],
};

// onCall -> onRequest로 변경 (일반 HTTP API 모드)
exports.checkPackageOwnership = functions.https.onRequest(async (req, res) => {
  
  // 1. CORS 허용 (모든 곳에서 접속 가능하게)
  res.set('Access-Control-Allow-Origin', '*');
  
  // 2. Preflight 요청 처리 (브라우저 접근 시 필요)
  if (req.method === 'OPTIONS') {
    res.set('Access-Control-Allow-Methods', 'POST');
    res.set('Access-Control-Allow-Headers', 'Content-Type');
    return res.status(204).send('');
  }

  // 3. POST 방식만 허용
  if (req.method !== 'POST') {
    return res.status(405).send({ valid: false, message: 'POST 요청만 가능합니다.' });
  }

  try {
    // 4. 데이터 받기 (이제 req.body에서 바로 꺼냄)
    // Python에서 {"licenseKey": "..."} 이렇게 보내면 됨. (data로 안 감싸도 됨!)
    const { licenseKey, packId, machineId } = req.body || {};  // v62.33: req.body undefined 방어

    if (!licenseKey || !packId) {
      return res.status(400).send({ valid: false, message: '필수 파라미터 누락 (licenseKey, packId)' });
    }

    const db = admin.firestore();
    const licenseDoc = await db.collection('licenses').doc(licenseKey.toUpperCase()).get();

    if (!licenseDoc.exists) {
      return res.status(200).send({ valid: false, message: '등록되지 않은 라이선스 키입니다.' });
    }

    const licenseData = licenseDoc.data();

    if (!licenseData.is_active) {
      return res.status(200).send({ valid: false, message: '비활성화(정지)된 라이선스입니다.' });
    }

    // 기기 인증 (v62.29: bound_hwid가 있으면 machineId 반드시 필요 — 우회 불가)
    if (licenseData.bound_hwid) {
      if (!machineId || licenseData.bound_hwid !== machineId) {
        return res.status(200).send({
          valid: false,
          message: '기기 인증 실패: HWID 불일치 또는 누락\n라이선스 초기화가 필요합니다.'
        });
      }
    }

    // --- 권한 검사 ---
    
    // Type A: 슈퍼 패스
    if (licenseData.license_type === 'A') {
      return res.status(200).send({ valid: true, message: 'VIP Pass: 승인됨' });
    }

    // 일반 검사 (v62.32: PACK_OWNERSHIP_MAP 통일 — getPackKey와 동일 로직)
    const ownedPacks = licenseData.owned_packs || [];
    const validKeys = PACK_OWNERSHIP_MAP[packId] || [packId];
    const hasAccess = ownedPacks.some(p => validKeys.includes(p));
    if (hasAccess) {
      return res.status(200).send({ valid: true, message: `패키지 승인: ${packId}` });
    }

    // 실패
    return res.status(200).send({
      valid: false,
      message: `구매하지 않은 패키지입니다.\n'${packId}' 패키지 구매가 필요합니다.`
    });

  } catch (error) {
    console.error('Error:', error);
    return res.status(500).send({ valid: false, message: '서버 내부 오류 발생' });
  }
});

// v62.27: 팩 복호화 키 발급 API
// POST { licenseKey, hwid, packId } → { packKey: "..." } or { error: "..." }
// Firestore /pack_keys/{packId}.key 에 서버측 팩 키 저장 필요 (관리자 설정)
exports.getPackKey = functions.https.onRequest(async (req, res) => {
  res.set('Access-Control-Allow-Origin', '*');
  if (req.method === 'OPTIONS') {
    res.set('Access-Control-Allow-Methods', 'POST');
    res.set('Access-Control-Allow-Headers', 'Content-Type');
    return res.status(204).send('');
  }
  if (req.method !== 'POST') {
    return res.status(405).send({ error: 'POST 요청만 가능합니다.' });
  }

  try {
    const { licenseKey, hwid, packId } = req.body || {};  // v62.33: req.body undefined 방어
    if (!licenseKey || !packId) {
      return res.status(400).send({ error: '필수 파라미터 누락 (licenseKey, packId)' });
    }

    const db = admin.firestore();

    // 1. 라이선스 검증
    const licenseDoc = await db.collection('licenses').doc(licenseKey.toUpperCase()).get();
    if (!licenseDoc.exists) {
      return res.status(200).send({ error: '등록되지 않은 라이선스 키입니다.' });
    }
    const licenseData = licenseDoc.data();
    if (!licenseData.is_active) {
      return res.status(200).send({ error: '비활성화된 라이선스입니다.' });
    }

    // HWID 검사 (v62.28: bound_hwid가 있으면 hwid 반드시 필요 — 우회 불가)
    if (licenseData.bound_hwid) {
      if (!hwid || licenseData.bound_hwid !== hwid) {
        return res.status(200).send({ error: '기기 인증 실패: HWID 불일치 또는 누락' });
      }
    }

    // 2. 팩 소유권 확인 (v62.32: 모듈 레벨 PACK_OWNERSHIP_MAP 공유)
    const validKeys = PACK_OWNERSHIP_MAP[packId] || [packId];
    const hasAccess = (
      licenseData.license_type === 'A' ||
      (licenseData.owned_packs || []).some(p => validKeys.includes(p))
    );
    if (!hasAccess) {
      return res.status(200).send({ error: `팩 접근 권한 없음: ${packId}` });
    }

    // 3. 팩 키 조회 (/pack_keys/{packId})
    const packKeyDoc = await db.collection('pack_keys').doc(packId).get();
    if (!packKeyDoc.exists) {
      // pack_keys 미등록 시 Phase A 레거시 모드 허용 응답
      return res.status(200).send({ packKey: null, message: 'pack_keys 미등록 (레거시 모드)' });
    }
    const packKey = packKeyDoc.data().key;
    if (!packKey) {
      return res.status(500).send({ error: '팩 키 데이터 없음' });
    }

    return res.status(200).send({ packKey });

  } catch (error) {
    console.error('getPackKey error:', error);
    return res.status(500).send({ error: '서버 내부 오류' });
  }
});

// 보유 패키지 조회 API (이것도 onRequest로 통일)
exports.getOwnedPacks = functions.https.onRequest(async (req, res) => {
  res.set('Access-Control-Allow-Origin', '*');
  if (req.method === 'OPTIONS') {
    res.set('Access-Control-Allow-Methods', 'POST');
    res.set('Access-Control-Allow-Headers', 'Content-Type');
    return res.status(204).send('');
  }

  // v62.32: try/catch 추가 (req.body undefined 시 TypeError 500 방지)
  try {
    const { licenseKey } = req.body || {};
    if (!licenseKey) {
      return res.status(400).send({ error: '라이선스 키 필요' });
    }

    const db = admin.firestore();
    const licenseDoc = await db.collection('licenses').doc(licenseKey.toUpperCase()).get();

    if (!licenseDoc.exists) {
      return res.status(200).send({ packs: [], licenseType: null });
    }

    const docData = licenseDoc.data();
    return res.status(200).send({
      packs: docData.owned_packs || [],
      licenseType: docData.license_type || null
    });
  } catch (error) {
    console.error('[getOwnedPacks] Error:', error);
    return res.status(500).send({ error: '서버 내부 오류' });
  }
});
