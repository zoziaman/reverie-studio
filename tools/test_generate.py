"""테스트 영상 생성 스크립트 - senior_scam_alert 팩"""
import sys, os, json, logging, time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
os.environ['PYTHONIOENCODING'] = 'utf-8'

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger('test_generate')

def main():
    start = time.time()
    logger.info("=== Reverie Test Video Generation ===")

    # 1. 팩 로드
    logger.info("[Step 1] Loading pack: senior_scam_alert")
    from config.pack_config import load_pack_by_id
    success = load_pack_by_id("senior_scam_alert")
    if not success:
        logger.error("Pack load failed!")
        return
    logger.info("  Pack loaded OK")

    # 2. 시나리오 생성
    logger.info("[Step 2] Generating scenario...")
    from modules_pro.scenario_planner import ScenarioPlanner
    planner = ScenarioPlanner()
    plan = planner.generate_full_plan()

    if not plan:
        logger.error("Scenario generation failed!")
        return

    topic = plan.get('topic', 'unknown')
    logger.info(f"  Topic: {topic}")

    # 시나리오 JSON 저장
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'data', 'outputs', 'test_scam_alert',
                              datetime.now().strftime('%Y%m%d_%H%M%S'))
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, 'scenario.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    logger.info(f"  Scenario saved: {json_path}")

    # 3. 영상 생성
    logger.info("[Step 3] Starting video production pipeline...")
    from pipeline.orchestrator import MediaFactory
    factory = MediaFactory()

    def log_cb(msg, level="info"):
        logger.info(f"  [Pipeline] {msg}")

    result = factory.produce_video_with_gui(
        json_path=json_path,
        log_callback=log_cb,
    )

    elapsed = (time.time() - start) / 60
    if result:
        logger.info(f"=== SUCCESS in {elapsed:.1f} min ===")
        logger.info(f"  Video: {result}")
    else:
        logger.error(f"=== FAILED after {elapsed:.1f} min ===")

if __name__ == '__main__':
    main()
