"""VIBE CUT — 여러 클립을 받아 받아쓰기·장면 분석·AI 판단으로 편집 계획(EditPlan)을 만들고
FFmpeg 한 번으로 렌더하는 영상 편집 파이프라인.

    vibecut.settings   환경 변수 → 설정 (모델 이름·경로·AI 모드를 한 곳에서)
    vibecut.models     프론트·AI·렌더가 함께 쓰는 데이터 계약 (EditPlan 등)
    vibecut.media      ffmpeg 실행·탐색·프로브·오디오 추출·프록시
    vibecut.ai         Gemini 통합 클라이언트, 받아쓰기·장면·트리·컷 판단·장면 선택
    vibecut.edit       편집 계획 계산 (남길 구간, 단어 경계, 자막 시각)
    vibecut.render     ASS 자막 생성, EditPlan → FFmpeg 필터 컴파일, 렌더 실행
    vibecut.server     FastAPI 앱, 디스크 저장 작업 큐, 프로젝트 저장소
    vibecut.eval       평가 지표
"""

__version__ = "3.0.0"
