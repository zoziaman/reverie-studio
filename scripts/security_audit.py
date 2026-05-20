#!/usr/bin/env python3
"""
백엔드 보안 자동 점검 스크립트
v62 기준 - 2026-02-23
"""
import os
import re
import subprocess
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent

# 색상 출력
RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
RESET = "\033[0m"

def check_hardcoded_secrets():
    """1. 하드코딩된 API 키/비밀번호 탐지"""
    print(f"\n{'='*60}")
    print("[1] 하드코딩된 Secrets 탐지")
    print(f"{'='*60}")

    patterns = [
        (r'GEMINI_API_KEY\s*=\s*["\']AIza[^"\']+["\']', "Gemini API Key 하드코딩"),
        (r'SECRET_KEY\s*=\s*["\'][^"\']{20,}["\']', "SECRET_KEY 하드코딩"),
        (r'PASSWORD\s*=\s*b["\'][^"\']+["\']', "Password 하드코딩 (bytes)"),
        (r'firebase.*\.(json|key)', "Firebase 인증 파일 경로 노출"),
    ]

    issues = []
    for py_file in ROOT.glob("**/*.py"):
        if "venv" in str(py_file) or ".venv" in str(py_file):
            continue

        try:
            content = py_file.read_text(encoding="utf-8")
            for pattern, desc in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    issues.append(f"{RED}[FAIL]{RESET} {py_file.relative_to(ROOT)}: {desc}")
        except:
            pass

    if issues:
        for issue in issues[:10]:  # 최대 10개만 표시
            print(issue)
        print(f"{RED}총 {len(issues)}개 하드코딩 이슈 발견{RESET}")
    else:
        print(f"{GREEN}[PASS] 하드코딩된 Secrets 없음{RESET}")

def check_gitignore():
    """2. .gitignore 보안 파일 등록 확인"""
    print(f"\n{'='*60}")
    print("[2] .gitignore 보안 점검")
    print(f"{'='*60}")

    gitignore = ROOT / ".gitignore"
    if not gitignore.exists():
        print(f"{RED}[FAIL] .gitignore 파일 없음{RESET}")
        return

    required = [
        (".env", "환경변수 파일"),
        ("firebase_credentials.json", "Firebase 인증"),
        ("**/youtube_token*.pickle", "YouTube 토큰"),
        ("*.key", "비밀 키 파일"),
        ("*.lic", "라이센스 파일"),
    ]

    content = gitignore.read_text(encoding="utf-8")

    for pattern, desc in required:
        if pattern not in content:
            print(f"{YELLOW}[WARN]{RESET} {desc} 누락: {pattern}")
        else:
            print(f"{GREEN}[PASS]{RESET} {desc} 등록됨")

def check_git_history():
    """3. Git 히스토리 민감 파일 확인"""
    print(f"\n{'='*60}")
    print("[3] Git 히스토리 민감 파일 확인")
    print(f"{'='*60}")

    sensitive_patterns = [
        "*.env",
        "*credentials*.json",
        "*token*.pickle",
        "*.key",
    ]

    for pattern in sensitive_patterns:
        result = subprocess.run(
            ["git", "log", "--all", "--full-history", "--", pattern],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )
        if result.stdout and result.stdout.strip():
            print(f"{RED}[FAIL]{RESET} Git 히스토리에 {pattern} 발견 → BFG로 제거 필요")
        else:
            print(f"{GREEN}[PASS]{RESET} {pattern} 히스토리 깨끗")

def check_dependencies():
    """4. 의존성 보안 취약점 (npm audit)"""
    print(f"\n{'='*60}")
    print("[4] 의존성 보안 취약점 점검")
    print(f"{'='*60}")

    # npm audit (remotion-poc)
    remotion_dir = ROOT / "remotion-poc"
    if remotion_dir.exists():
        print("[npm audit] remotion-poc 점검 중...")
        try:
            result = subprocess.run(
                ["npm", "audit", "--json"],
                cwd=remotion_dir,
                capture_output=True,
                text=True,
                timeout=30
            )
            try:
                audit_data = json.loads(result.stdout)
                vulnerabilities = audit_data.get("metadata", {}).get("vulnerabilities", {})
                total = sum(vulnerabilities.values())

                if total > 0:
                    print(f"{RED}[FAIL]{RESET} npm 취약점 {total}개 발견")
                    print(f"   수정: cd remotion-poc && npm audit fix")
                else:
                    print(f"{GREEN}[PASS]{RESET} npm 취약점 없음")
            except:
                print(f"{YELLOW}[WARN]{RESET} npm audit 결과 파싱 실패")
        except FileNotFoundError:
            print(f"{YELLOW}[SKIP]{RESET} npm 미설치 - Node.js 환경 필요")

    # pip-audit (Python)
    print("\n[pip-audit] Python 패키지 점검 중...")
    try:
        result = subprocess.run(
            ["pip-audit", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode != 0:
            print(f"{YELLOW}[WARN]{RESET} pip-audit 미설치 → pip install pip-audit")
        else:
            try:
                audit_data = json.loads(result.stdout)
                if audit_data.get("vulnerabilities"):
                    print(f"{RED}[FAIL]{RESET} Python 패키지 취약점 발견")
                    print(f"   수정: pip-audit --fix")
                else:
                    print(f"{GREEN}[PASS]{RESET} Python 패키지 취약점 없음")
            except:
                print(f"{YELLOW}[WARN]{RESET} pip-audit 결과 파싱 실패")
    except FileNotFoundError:
        print(f"{YELLOW}[SKIP]{RESET} pip-audit 미설치 → pip install pip-audit")

def check_firebase_security():
    """5. Firebase 클라이언트 검증 구조 점검"""
    print(f"\n{'='*60}")
    print("[5] Firebase 인증 구조 점검")
    print(f"{'='*60}")

    license_validator = ROOT / "src" / "utils" / "license_validator.py"
    if license_validator.exists():
        content = license_validator.read_text(encoding="utf-8")

        # .dev 우회 체크
        if 'os.path.exists(dev_marker)' in content:
            print(f"{RED}[FAIL]{RESET} .dev 파일 우회 존재 (L73-75)")
            print(f"   → 프로덕션 배포 시 제거 필수")

        # SECRET_KEY 난독화 체크
        if '_k = [82, 69,' in content:
            print(f"{RED}[FAIL]{RESET} SECRET_KEY 바이트 배열 난독화 취약 (L28-30)")
            print(f"   → Fernet 암호화로 교체 필요")

        # 클라이언트 검증 경고
        if '_validate_offline' in content:
            print(f"{YELLOW}[WARN]{RESET} 클라이언트 측 오프라인 검증 존재")
            print(f"   → Cloud Functions 서버 검증으로 전환 권장")

def main():
    print(f"\n{'#'*60}")
    print("# 레베리 보안 자동 점검 (v62)")
    print(f"{'#'*60}")

    check_hardcoded_secrets()
    check_gitignore()
    check_git_history()
    check_dependencies()
    check_firebase_security()

    print(f"\n{'='*60}")
    print("[OK] 점검 완료")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
