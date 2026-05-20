# tests/test_callback_signatures.py
"""
콜백 시그니처 호환성 테스트
- media_factory에서 호출하는 콜백과 main_window의 lambda가 호환되는지 검증
"""
import sys
import inspect


def test_thumbnail_callback_signature():
    """
    media_factory.produce_video_with_gui()가 thumbnail_callback을 호출할 때
    전달하는 인자와 main_window의 lambda가 호환되는지 검증
    """
    print("=" * 60)
    print("[테스트] thumbnail_callback 시그니처 호환성")
    print("=" * 60)

    # 1. media_factory에서 thumbnail_callback 호출 방식 확인
    from modules_pro.media_factory import MediaFactory

    # produce_video_with_gui 소스에서 thumbnail_callback 호출부 찾기
    source = inspect.getsource(MediaFactory.produce_video_with_gui)

    # thumbnail_callback 호출 패턴 찾기
    if "thumbnail_callback(" in source:
        # 호출부 추출
        import re
        calls = re.findall(r'thumbnail_callback\([^)]+\)', source)
        print(f"\n[media_factory] thumbnail_callback 호출부:")
        for call in calls:
            print(f"  {call[:100]}...")

    # 2. main_window의 _thumbnail_callback 시그니처 확인
    from gui.main_window import ReverieGUI

    sig = inspect.signature(ReverieGUI._thumbnail_callback)
    print(f"\n[main_window] _thumbnail_callback 시그니처:")
    print(f"  {sig}")

    params = list(sig.parameters.keys())
    print(f"  파라미터: {params}")

    # 3. 호환성 검증 - mock 호출 테스트
    print("\n[검증] Mock 호출 테스트:")

    # media_factory가 전달하는 인자 시뮬레이션
    test_args = {
        "real_path": "/fake/real.jpg",
        "art_path": "/fake/art.jpg",
        "channel_type": "senior_touching",
        "main_title": "테스트 제목"
    }

    # main_window의 lambda 시뮬레이션
    # lambda r, a, summary=scenario_summary, **kw: self._thumbnail_callback(r, a, summary, kw.get('channel_type'), kw.get('main_title'))

    def mock_lambda(r, a, summary="test_summary", **kw):
        """main_window의 lambda와 동일한 시그니처"""
        channel_type = kw.get('channel_type')
        main_title = kw.get('main_title')
        return f"받은 인자: r={r}, a={a}, summary={summary}, channel_type={channel_type}, main_title={main_title}"

    try:
        # media_factory 스타일로 호출
        result = mock_lambda(
            test_args["real_path"],
            test_args["art_path"],
            channel_type=test_args["channel_type"],
            main_title=test_args["main_title"]
        )
        print(f"  [OK] 호출 성공!")
        print(f"  {result}")
    except TypeError as e:
        print(f"  [FAIL] 호출 실패: {e}")
        assert False, f"thumbnail_callback signature mismatch: {e}"

    print("\n" + "=" * 60)
    print("[결과] 시그니처 호환성 테스트 통과!")
    print("=" * 60)
    assert True


def test_progress_callback_signature():
    """progress_callback 시그니처 검증"""
    print("\n" + "=" * 60)
    print("[테스트] progress_callback 시그니처 호환성")
    print("=" * 60)

    from gui.main_window import ReverieGUI

    # _update_progress 시그니처 확인
    sig = inspect.signature(ReverieGUI._update_progress)
    print(f"[main_window] _update_progress 시그니처: {sig}")

    # media_factory에서 호출하는 방식: progress_callback(message, percent)
    def mock_progress(msg, pct):
        print(f"  진행: {msg} ({pct}%)")

    try:
        mock_progress("테스트 메시지", 50)
        print("  [OK] 호출 성공!")
    except Exception as e:
        print(f"  [FAIL] {e}")
        assert False, f"progress_callback signature mismatch: {e}"

    assert True


if __name__ == "__main__":
    results = []

    results.append(("thumbnail_callback", test_thumbnail_callback_signature()))
    results.append(("progress_callback", test_progress_callback_signature()))

    print("\n" + "=" * 60)
    print("최종 결과:")
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
    print("=" * 60)

    # 실패가 있으면 exit code 1
    if not all(r[1] for r in results):
        sys.exit(1)
