# scripts/sanitize_code.py
"""
배포 전 개인정보 제거 및 검증 스크립트

실행 방법:
    python scripts/sanitize_code.py

기능:
1. API 키 하드코딩 검사
2. 비밀번호 하드코딩 검사
3. 개인 경로 하드코딩 검사
4. 이메일/전화번호 검사
5. 자동 수정 제안
"""

import os
import re
from pathlib import Path
from typing import List, Tuple


class CodeSanitizer:
    """코드 위생 검사기"""
    
    # 위험 패턴 정의
    DANGEROUS_PATTERNS = [
        # API 키
        (r'api[_-]?key\s*=\s*["\']([A-Za-z0-9_-]{20,})["\']', "API Key"),
        (r'GEMINI_API_KEY\s*=\s*["\']([^"\']+)["\']', "Gemini API Key"),
        (r'OPENAI_API_KEY\s*=\s*["\']sk-[^"\']+["\']', "OpenAI API Key"),
        (r'ANTHROPIC_API_KEY\s*=\s*["\']sk-ant-[^"\']+["\']', "Anthropic API Key"),
        
        # 비밀번호
        (r'password\s*=\s*["\']([^"\']+)["\']', "Password"),
        (r'passwd\s*=\s*["\']([^"\']+)["\']', "Password"),
        (r'secret\s*=\s*["\']([^"\']+)["\']', "Secret"),
        
        # 개인 경로
        (r'C:/Users/[^/]+/', "Personal Path"),
        (r'C:\\\\Users\\\\[^\\\\]+\\\\', "Personal Path"),
        
        # 이메일
        (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', "Email"),
        
        # 전화번호
        (r'\b\d{2,3}-\d{3,4}-\d{4}\b', "Phone Number"),
        
        # IP 주소 (로컬 제외)
        (r'\b(?!127\.|192\.168\.|10\.|172\.)((?:[0-9]{1,3}\.){3}[0-9]{1,3})\b', "IP Address"),
    ]
    
    # 안전한 예외 패턴 (False Positive 방지)
    SAFE_PATTERNS = [
        r'placeholder_text\s*=',  # GUI placeholder
        r'example\s*=',
        r'default\s*=\s*["\']["\']',  # 빈 문자열
        r'#.*',  # 주석
    ]
    
    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self.issues: List[Tuple[str, int, str, str]] = []
    
    def scan_file(self, filepath: Path) -> List[Tuple[int, str, str]]:
        """단일 파일 스캔"""
        issues = []
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            for line_num, line in enumerate(lines, 1):
                # 안전한 패턴 체크
                is_safe = any(re.search(pattern, line) for pattern in self.SAFE_PATTERNS)
                if is_safe:
                    continue
                
                # 위험 패턴 체크
                for pattern, issue_type in self.DANGEROUS_PATTERNS:
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        issues.append((line_num, issue_type, line.strip()))
        
        except Exception as e:
            print(f"⚠️ 파일 읽기 실패: {filepath} - {e}")
        
        return issues
    
    def scan_directory(self, directory: Path = None) -> None:
        """디렉토리 재귀 스캔"""
        if directory is None:
            directory = self.project_root
        
        # Python 파일만 스캔
        python_files = list(directory.rglob("*.py"))
        
        print(f"📁 스캔 대상: {len(python_files)}개 파일")
        print(f"📂 경로: {directory.absolute()}\n")
        
        for filepath in python_files:
            # 제외 디렉토리
            if any(x in str(filepath) for x in ['venv', '__pycache__', '.git', 'node_modules']):
                continue
            
            file_issues = self.scan_file(filepath)
            
            if file_issues:
                for line_num, issue_type, line in file_issues:
                    self.issues.append((str(filepath), line_num, issue_type, line))
    
    def generate_report(self) -> str:
        """리포트 생성"""
        report = []
        report.append("=" * 80)
        report.append("🔍 코드 위생 검사 리포트")
        report.append("=" * 80)
        report.append("")
        
        if not self.issues:
            report.append("✅ 문제 없음! 모든 코드가 깨끗합니다.")
            report.append("")
            report.append("배포 준비 완료! 🎉")
        else:
            report.append(f"⚠️ {len(self.issues)}개 이슈 발견")
            report.append("")
            
            # 파일별로 그룹화
            issues_by_file = {}
            for filepath, line_num, issue_type, line in self.issues:
                if filepath not in issues_by_file:
                    issues_by_file[filepath] = []
                issues_by_file[filepath].append((line_num, issue_type, line))
            
            for filepath, file_issues in issues_by_file.items():
                report.append(f"\n📄 {filepath}")
                report.append("-" * 80)
                
                for line_num, issue_type, line in file_issues:
                    report.append(f"  Line {line_num}: [{issue_type}]")
                    report.append(f"    → {line}")
                    report.append("")
            
            report.append("=" * 80)
            report.append("🔧 권장 조치:")
            report.append("")
            report.append("1. 하드코딩된 값을 제거하세요")
            report.append("2. 환경 변수 또는 설정 파일 사용")
            report.append("3. GUI에서 사용자 입력 받기 (이미 구현됨!)")
            report.append("")
            report.append("예시:")
            report.append("  ❌ API_KEY = 'AIza...'")
            report.append("  ✅ API_KEY = os.getenv('GEMINI_API_KEY', '')")
            report.append("  ✅ API_KEY = config.get('api_key', '')")
        
        report.append("")
        report.append("=" * 80)
        
        return "\n".join(report)
    
    def save_report(self, output_path: str = "sanitize_report.txt"):
        """리포트 파일 저장"""
        report = self.generate_report()
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report)
        
        print(f"📝 리포트 저장: {output_path}")
        return output_path


# =============================================================================
# CLI 실행
# =============================================================================

if __name__ == "__main__":
    import sys
    
    print("\n" + "=" * 80)
    print("🔍 Reverie Automation - 코드 위생 검사")
    print("=" * 80)
    print("\n개인정보 및 민감정보 하드코딩 검사 중...\n")
    
    # 프로젝트 루트 경로
    if len(sys.argv) > 1:
        project_root = sys.argv[1]
    else:
        # 현재 스크립트 위치에서 상위 디렉토리
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # 스캔 실행
    sanitizer = CodeSanitizer(project_root)
    sanitizer.scan_directory(Path(project_root) / "src")
    
    # 리포트 출력
    print(sanitizer.generate_report())
    
    # 리포트 저장
    report_path = sanitizer.save_report()
    
    # 종료 코드
    if sanitizer.issues:
        print("\n⚠️ 이슈 발견! 수정 후 다시 실행하세요.")
        sys.exit(1)
    else:
        print("\n✅ 배포 준비 완료!")
        sys.exit(0)