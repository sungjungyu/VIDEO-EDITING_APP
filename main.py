#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 기반 문맥 감지형 자동 영상 편집 플랫폼
Main Pipeline Script
"""

import os
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import List, Dict, Any
import numpy as np
try:
    from moviepy.editor import VideoFileClip, TextClip, ImageClip, CompositeVideoClip, concatenate_videoclips
except ImportError:
    from moviepy import VideoFileClip, TextClip, ImageClip, CompositeVideoClip, concatenate_videoclips
import numpy as np
from PIL import Image, ImageDraw, ImageFont
# MoviePy 1.x still references the Pillow constant removed in Pillow 10.
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS
# from moviepy.config import change_settings  # 더 이상 사용하지 않음
# import openai  # 더 이상 사용하지 않음
# from openai import OpenAI  # 더 이상 사용하지 않음
import whisper

try:
    from google import genai as google_genai
    from google.genai import types as google_types
except Exception:
    google_genai = None
    google_types = None

try:
    import google.generativeai as genai
except Exception:
    genai = None

from config import config

# 한국어 폰트 설정 (macOS 기본 경로)
# Windows: "C:/Windows/Fonts/malgun.ttf"
# Linux: "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"
# KOREAN_FONT_PATH = "/System/Library/Fonts/Supplemental/AppleGothic.ttf"  # 더 이상 사용하지 않음

class VideoEditingPipeline:
    def __init__(self, api_key: str):
        """
        초기화 함수
        
        Args:
            api_key (str): Gemini API 키
        """
        self.gemini_client = None
        self.gemini_model = None
        self.gemini_model_name = "gemini-3.5-flash"
        # 정확도를 우선하는 기본값입니다. 처리 속도가 더 중요하면 환경 변수로
        # WHISPER_MODEL=base 또는 small을 지정할 수 있습니다.
        self.whisper_model_name = os.getenv("WHISPER_MODEL", "medium")
        self.whisper_initial_prompt = os.getenv(
            "WHISPER_INITIAL_PROMPT",
            "다음은 자연스러운 한국어 영상 자막입니다. 고유명사, 제품명, 숫자와 단위를 정확히 표기하세요.",
        )

        # Gemini API 설정
        if google_genai is not None:
            self.gemini_client = google_genai.Client(api_key=api_key)
        elif genai is not None:
            genai.configure(api_key=api_key)
            self.gemini_model = genai.GenerativeModel(self.gemini_model_name)
        else:
            raise ImportError("Google Gemini SDK를 불러올 수 없습니다.")

        self.temp_dir = tempfile.mkdtemp()
        print(f"📁 임시 디렉토리 생성: {self.temp_dir}")
    
    def _create_subtitle_image(self, text: str, fontsize: int, color: str, video_width: int):
        """
        PIL로 자막 이미지를 직접 생성 (ImageMagick 불필요)
        
        Args:
            text (str): 자막 텍스트
            fontsize (int): 폰트 크기
            color (str): 자막 색상
            video_width (int): 영상 너비 (자막 폭 계산용)
            
        Returns:
            np.ndarray: RGBA 이미지 배열
        """
        # 한국어 지원 폰트 로드
        font_candidates = [
            "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
            "/System/Library/Fonts/Supplemental/AppleSDGothicNeo.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
        ]
        font = None
        for font_path in font_candidates:
            if os.path.exists(font_path):
                try:
                    font = ImageFont.truetype(font_path, fontsize)
                    break
                except Exception:
                    continue
        if font is None:
            font = ImageFont.load_default()
        
        # 텍스트 크기 측정
        dummy_img = Image.new("RGBA", (1, 1))
        dummy_draw = ImageDraw.Draw(dummy_img)
        bbox = dummy_draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        
        padding = 20
        img_w = min(int(video_width * 0.9), text_w + padding * 2)
        img_h = text_h + padding * 2
        
        img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 160))
        draw = ImageDraw.Draw(img)
        
        # 텍스트 중앙 정렬 + 검은색 외곽선
        x = (img_w - text_w) // 2 - bbox[0]
        y = (img_h - text_h) // 2 - bbox[1]
        stroke_width = 2
        draw.text((x, y), text, font=font, fill=color, stroke_width=stroke_width, stroke_fill="black")
        
        return np.array(img)
    
    def step1_extract_audio(self, input_video_path: str) -> str:
        """
        Step 1: 영상에서 오디오 추출
        
        Args:
            input_video_path (str): 입력 영상 파일 경로
            
        Returns:
            str: 추출된 오디오 파일 경로
        """
        print("🎬 Step 1: 영상에서 오디오 추출 중...")
        
        video = VideoFileClip(input_video_path)
        # MP3 재압축으로 생길 수 있는 음질 손실을 피하기 위해 Whisper 입력은
        # 16 kHz 모노 PCM WAV로 저장합니다.
        audio_path = os.path.join(self.temp_dir, "audio.wav")
        
        # 오디오 추출 또는 무음 대체 생성
        if video.audio is not None:
            video.audio.write_audiofile(
                audio_path,
                fps=16000,
                nbytes=2,
                codec="pcm_s16le",
                ffmpeg_params=["-ac", "1"],
                logger=None,
            )
            print(f"✅ 오디오 추출 완료: {audio_path}")
        else:
            print("⚠️ 영상에 오디오 트랙이 없어 무음 오디오를 생성합니다.")
            from moviepy.audio.AudioClip import AudioClip
            silent_audio = AudioClip(lambda t: np.zeros(1), duration=video.duration)
            silent_audio.write_audiofile(
                audio_path, fps=16000, nbytes=2, codec="pcm_s16le", logger=None
            )
            silent_audio.close()
            print(f"✅ 무음 오디오 생성 완료: {audio_path}")
        
        video.close()
        return audio_path
    
    def step2_transcribe_audio(self, audio_path: str) -> List[Dict[str, Any]]:
        """
        Step 2: 로컬 Whisper로 음성 인식 및 타임스탬프 추출
        
        Args:
            audio_path (str): 오디오 파일 경로
            
        Returns:
            List[Dict]: 텍스트와 타임스탬프 정보
        """
        print("🎤 Step 2: 로컬 Whisper로 음성 인식 중...")
        
        print(f"📥 Whisper {self.whisper_model_name} 모델 로딩 중...")
        model = whisper.load_model(self.whisper_model_name)
        
        # 오디오 파일 처리
        print("🔊 오디오 처리 중...")
        result = model.transcribe(
            audio_path,
            language="ko",
            task="transcribe",
            initial_prompt=self.whisper_initial_prompt,
            temperature=0,
            beam_size=5,
            best_of=5,
            condition_on_previous_text=True,
            verbose=True,
        )
        
        # 세그먼트 정보 추출
        segments = []
        for segment in result["segments"]:
            segments.append({
                "start": segment["start"],
                "end": segment["end"],
                "text": segment["text"].strip()
            })
        
        print(f"✅ 음성 인식 완료: {len(segments)}개 세그먼트")
        return segments

    def step2_refine_transcript(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Gemini로 자막 표기만 교정하고 Whisper 타임스탬프는 그대로 유지합니다."""
        if not segments:
            return segments

        print("📝 Step 2-보정: 자막 맞춤법·고유명사 교정 중...")
        indexed_segments = [
            {"id": index, "text": segment["text"]}
            for index, segment in enumerate(segments)
        ]
        prompt = f"""
당신은 한국어 영상 자막 교정자입니다. 아래 Whisper 인식 자막의 맞춤법, 띄어쓰기,
숫자·단위, 명백한 고유명사 표기만 교정하세요. 발화에 없는 내용을 추가하거나,
말의 의미·말투를 바꾸거나, 문장을 합치거나 나누지 마세요.

반드시 입력과 같은 id를 하나씩 포함한 순수 JSON 배열만 반환하세요.
형식: [{{"id": 0, "text": "교정된 자막"}}]

입력:
{json.dumps(indexed_segments, ensure_ascii=False)}
"""
        try:
            response_text = str(self._call_gemini(prompt) or "").strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            corrected = json.loads(response_text.strip())
            corrected_texts = {
                item["id"]: item["text"].strip()
                for item in corrected
                if isinstance(item, dict)
                and isinstance(item.get("id"), int)
                and isinstance(item.get("text"), str)
                and item["text"].strip()
            }
            if set(corrected_texts) != set(range(len(segments))):
                raise ValueError("교정 응답의 세그먼트 id가 입력과 일치하지 않습니다.")
        except Exception as error:
            print(f"⚠️ 자막 교정을 건너뜁니다: {error}")
            return segments

        refined_segments = [dict(segment) for segment in segments]
        for index, segment in enumerate(refined_segments):
            segment["text"] = corrected_texts[index]
        print("✅ 자막 표기 교정 완료 (타임스탬프 유지)")
        return refined_segments
    
    def _build_dummy_commands(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Gemini 호출 실패 시 사용할 기본 편집 명령어"""
        dummy_commands = []
        for i, segment in enumerate(segments[:5]):
            dummy_commands.append({
                "start": segment["start"],
                "end": segment["end"],
                "text": segment["text"],
                "cut": i % 2 == 1,
                "subtitle_color": "yellow" if i % 2 == 0 else "red",
                "fontsize": 45
            })
        return dummy_commands

    def _build_local_commands(self, segments: List[Dict[str, Any]], style_preset: str) -> List[Dict[str, Any]]:
        """Gemini 없이도 바로 사용할 수 있는 로컬 편집 명령어 생성"""
        if not segments:
            return [{
                "start": 0.0,
                "end": 3.0,
                "text": "영상 편집 완료",
                "cut": False,
                "subtitle_color": "white",
                "fontsize": 36,
            }]

        style_colors = {
            "매운맛": ("yellow", 44),
            "순한맛": ("white", 34),
            "정석맛": ("cyan", 32),
        }
        color, fontsize = style_colors.get(style_preset, style_colors["정석맛"])

        commands = []
        for i, segment in enumerate(segments):
            text = segment.get("text", "").strip() or f"문장 {i+1}"
            start = float(segment.get("start", i * 2.0))
            end = float(segment.get("end", start + 2.0))
            duration = max(1.0, end - start)
            cut = duration < 1.2 or len(text) < 6
            commands.append({
                "start": start,
                "end": end,
                "text": text,
                "cut": cut,
                "subtitle_color": color,
                "fontsize": fontsize,
            })
        return commands

    def _call_gemini(self, prompt: str) -> str:
        """Gemini에 요청을 보내고 텍스트 응답을 반환합니다."""
        def _run_call() -> str:
            if self.gemini_client is not None:
                response = self.gemini_client.models.generate_content(
                    model=self.gemini_model_name,
                    contents=prompt,
                    config=google_types.GenerateContentConfig(
                        temperature=0.1,
                        max_output_tokens=8192,
                        response_mime_type="application/json",
                    ),
                )
                return getattr(response, "text", "")

            if self.gemini_model is not None:
                response = self.gemini_model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.1,
                        max_output_tokens=8192,
                        response_mime_type="application/json",
                    )
                )
                return getattr(response, "text", "")

            raise RuntimeError("Gemini 클라이언트를 초기화하지 못했습니다.")

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run_call)
            try:
                return future.result(timeout=30)
            except FuturesTimeoutError as exc:
                future.cancel()
                raise TimeoutError("Gemini request timed out") from exc

    def step3_analyze_context(self, segments: List[Dict[str, Any]], style_preset: str) -> List[Dict[str, Any]]:
        """
        Step 3-4: Gemini로 문맥 분석 및 편집 명령어 생성
        
        Args:
            segments (List[Dict]): Whisper 결과 세그먼트
            style_preset (str): AI 스타일 프리셋
            
        Returns:
            List[Dict]: 편집 명령어가 포함된 JSON 데이터
        """
        print(f"🧠 Step 3-4: Gemini 문맥 분석 중 (스타일: {style_preset})...")
        
        # 스타일 프리셋별 시스템 프롬프트
        style_prompts = {
            "매운맛": """
            당신은 예능/숏폼 영상 편집 전문가입니다.
            - 오디오 공백이 1초 이상이면 컷 편집(삭제)을 고려하세요
            - 자막은 크고 화려하게 (폰트 크기 40-50, 밝은 색상)
            - 역동적인 느낌을 주도록 편집하세요
            """,
            "순한맛": """
            당신은 브이로그 편집 전문가입니다.
            - 최소한의 컷 편집으로 자연스러운 호흡을 유지하세요
            - 자막은 차분하고 조화롭게 (폰트 크기 30-35, 부드러운 색상)
            - 감성적이고 따뜻한 분위기를 만드세요
            """,
            "정석맛": """
            당신은 지식/정보 전달 영상 편집 전문가입니다.
            - 말버릇("음", "어" 등)과 불필요한 공백만 제거하세요
            - 자막은 가독성 중심 (폰트 크기 28-32, 배경 박스 포함)
            - 전문적이고 신뢰감 있는 느낌을 주세요
            """
        }
        
        # Gemini 프롬프트 구성
        full_prompt = f"""
        당신은 AI 기반 영상 편집 전문가입니다. 주어진 음성 인식 데이터를 분석하여
        각 문장별로 최적의 편집 명령어를 생성하세요.

        {style_prompts.get(style_preset, style_prompts["정석맛"])}

        출력 형식:
        반드시 순수한 JSON 배열만 반환하세요. 다른 텍스트나 설명을 포함하지 마세요.
        각 객체는 다음 필드를 포함해야 합니다:
        - start: 시작 시간 (초)
        - end: 종료 시간 (초)
        - text: 텍스트 내용
        - cut: 컷 편집 여부 (true/false)
        - subtitle_color: 자막 색상 (예: "red", "blue", "white", "yellow")
        - fontsize: 자막 크기 (숫자)

        text 필드는 이미 맞춤법과 고유명사 표기가 교정된 자막입니다. text의 문구를
        임의로 바꾸지 말고 그대로 사용하세요.

        예시 출력:
        [{{"start": 0.0, "end": 2.5, "text": "안녕하세요", "cut": false, "subtitle_color": "red", "fontsize": 40}}]

        다음 음성 인식 데이터를 분석하여 편집 명령어를 생성해주세요:

        {json.dumps(segments, ensure_ascii=False, indent=2)}

        스타일 프리셋: {style_preset}
        """
        
        # Gemini API 호출은 선택적으로 사용하고, 실패/지연 시에는 로컬 명령으로 대체
        if not segments:
            print("⚠️ 인식된 세그먼트가 없어 기본 편집 명령어를 생성합니다.")
            return self._build_local_commands(segments, style_preset)

        try:
            response_text = self._call_gemini(full_prompt)
        except Exception as e:
            print(f"❌ Gemini API 호출 오류: {e}")
            print("로컬 편집 명령어를 사용합니다...")
            return self._build_local_commands(segments, style_preset)
        
        # JSON 파싱
        try:
            # Gemini 응답에서 텍스트 추출
            response_text = str(response_text or "").strip()
            
            # JSON 형식 정리 (Gemini가 ```json```으로 감쌀 경우 대비)
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            # 강력한 JSON 복구 로직
            lines = response_text.split('\n')
            cleaned_lines = []
            
            for line in lines:
                line = line.strip()
                if line and (line.startswith('[') or line.startswith('{') or line.startswith('"') or 
                           line.startswith('  ') or line == ']' or line == '}' or line == ','):
                    cleaned_lines.append(line)
            
            # 불완전한 마지막 줄 제거
            if cleaned_lines and not cleaned_lines[-1].endswith('}') and not cleaned_lines[-1].endswith(']'):
                cleaned_lines = cleaned_lines[:-1]
            
            # JSON 완성
            response_text = '\n'.join(cleaned_lines)
            if not response_text.endswith(']'):
                if response_text.endswith(','):
                    response_text = response_text[:-1]
                response_text += ']'
            
            result = json.loads(response_text)
            print(f"✅ 문맥 분석 완료: {len(result)}개 편집 명령어")
            if not result:
                return self._build_local_commands(segments, style_preset)
            return result
            
        except json.JSONDecodeError as e:
            print(f"❌ JSON 파싱 오류: {e}")
            print(f"원본 응답: {response_text}")
            print("🔄 로컬 편집 명령어로 대체합니다...")
            
            return self._build_local_commands(segments, style_preset)
    
    def _apply_aspect_ratio(self, clip, aspect_ratio: str):
        """Center-crop a clip to a standard landscape or short-form canvas."""
        target_sizes = {"16:9": (1920, 1080), "9:16": (1080, 1920)}
        if aspect_ratio not in target_sizes:
            raise ValueError("지원하지 않는 영상 비율입니다. 16:9 또는 9:16을 사용하세요.")

        target_width, target_height = target_sizes[aspect_ratio]
        scale = max(target_width / clip.w, target_height / clip.h)
        resized = (
            clip.resized(new_size=(int(clip.w * scale), int(clip.h * scale)))
            if hasattr(clip, "resized")
            else clip.resize(newsize=(int(clip.w * scale), int(clip.h * scale)))
        )
        x1 = max(0, (resized.w - target_width) / 2)
        y1 = max(0, (resized.h - target_height) / 2)
        return (
            resized.cropped(x1=x1, y1=y1, width=target_width, height=target_height)
            if hasattr(resized, "cropped")
            else resized.crop(x1=x1, y1=y1, width=target_width, height=target_height)
        )

    def step5_create_final_video(
        self,
        input_video_path: str,
        edit_commands: List[Dict[str, Any]],
        output_path: str,
        aspect_ratio: str = "16:9",
    ):
        """
        Step 5: 최종 영상 생성 (컷 편집 + 자막 합성)
        
        Args:
            input_video_path (str): 입력 영상 경로
            edit_commands (List[Dict]): 편집 명령어
            output_path (str): 출력 영상 경로
            aspect_ratio (str): 출력 비율 ("16:9" 또는 "9:16")
        """
        print("🎬 Step 5: 최종 영상 생성 중...")
        
        # 원본 영상 로드
        video = VideoFileClip(input_video_path)

        def subclip(source, start, end):
            return (
                source.subclipped(start, end)
                if hasattr(source, "subclipped")
                else source.subclip(start, end)
            )
        
        if not edit_commands:
            print("⚠️ 편집 명령이 비어 있어 기본 편집 명령을 생성합니다.")
            edit_commands = [{
                "start": 0.0,
                "end": video.duration,
                "text": "영상 편집 완료",
                "cut": False,
                "subtitle_color": "white",
                "fontsize": 36,
            }]
        
        # 컷 편집 적용 (cut=false인 세그먼트만 유지)
        keep_segments = []
        for cmd in edit_commands:
            if not cmd.get("cut", False):
                start_time = max(0, float(cmd.get("start", 0) or 0))
                end_time = min(video.duration, float(cmd.get("end", video.duration) or video.duration))
                if end_time > start_time:
                    segment = subclip(video, start_time, end_time)
                    keep_segments.append(segment)
        
        if not keep_segments:
            print("⚠️ 편집 가능한 세그먼트가 없어 전체 영상을 사용합니다.")
            keep_segments = [subclip(video, 0, video.duration)]
            edit_commands = [{
                "start": 0.0,
                "end": video.duration,
                "text": "영상 편집 완료",
                "cut": False,
                "subtitle_color": "white",
                "fontsize": 36,
            }]
        
        # 편집된 영상 생성
        if len(keep_segments) == 1:
            edited_video = keep_segments[0]
        else:
            edited_video = concatenate_videoclips(keep_segments)

        # Short-form output uses a centered 9:16 crop; landscape uses a 16:9 canvas.
        framed_video = self._apply_aspect_ratio(edited_video, aspect_ratio)
        
        # 자막 클립 생성 (PIL 기반, ImageMagick 불필요)
        subtitle_clips = []
        current_time = 0
        
        for i, cmd in enumerate(edit_commands):
            if not cmd.get("cut", False):
                try:
                    subtitle_duration = max(0.1, float(cmd.get("end", 0) or 0) - float(cmd.get("start", 0) or 0))
                    subtitle_img = self._create_subtitle_image(
                        cmd["text"],
                        cmd["fontsize"],
                        cmd["subtitle_color"],
                        framed_video.w
                    )
                    subtitle = ImageClip(subtitle_img)
                    if hasattr(subtitle, "with_position"):
                        subtitle = subtitle.with_position(('center', 'bottom')).with_start(current_time).with_duration(subtitle_duration)
                    else:
                        subtitle = subtitle.set_position(('center', 'bottom')).set_start(current_time).set_duration(subtitle_duration)
                    subtitle_clips.append(subtitle)
                    
                    current_time += subtitle_duration
                    print(f"✅ 자막 생성 성공 ({i+1}번): {cmd['text'][:20]}...")
                    
                except Exception as e:
                    print(f"⚠️ 자막 생성 오류 ({i+1}번): {e}")
                    # 자막 없이 영상만 계속 진행
                    continue
        
        # 최종 영상 합성
        if subtitle_clips:
            final_video = CompositeVideoClip([framed_video] + subtitle_clips)
        else:
            final_video = framed_video
        
        # 영상 렌더링 (속도 개선)
        print("🎥 영상 렌더링 중...")
        final_video.write_videofile(
            output_path,
            codec='libx264',
            audio_codec='aac',
            fps=24,
            threads=4,
            preset='fast',
            temp_audiofile=os.path.join(self.temp_dir, "temp_audio.m4a"),
            remove_temp=True,
            logger=None
        )
        
        # 메모리 정리
        video.close()
        if final_video is not framed_video:
            final_video.close()
        framed_video.close()
        edited_video.close()
        for clip in keep_segments:
            clip.close()
        for clip in subtitle_clips:
            clip.close()
        
        print(f"✅ 최종 영상 생성 완료: {output_path}")
    
    def run_pipeline(self, input_video_path: str, style_preset: str, output_path: str = "output.mp4"):
        """
        전체 파이프라인 실행
        
        Args:
            input_video_path (str): 입력 영상 경로
            style_preset (str): 스타일 프리셋 ("매운맛", "순한맛", "정석맛")
            output_path (str): 출력 영상 경로
        """
        try:
            print("🚀 AI 기반 영상 편집 파이프라인 시작!")
            print(f"📁 입력 파일: {input_video_path}")
            print(f"🎨 스타일 프리셋: {style_preset}")
            print("=" * 50)
            
            # Step 1: 오디오 추출
            audio_path = self.step1_extract_audio(input_video_path)
            
            # Step 2: 음성 인식
            segments = self.step2_transcribe_audio(audio_path)

            # Step 2-보정: 자막 표기만 교정 (Whisper 타임스탬프 유지)
            segments = self.step2_refine_transcript(segments)

            # Step 3-4: 문맥 분석
            edit_commands = self.step3_analyze_context(segments, style_preset)
            
            # Step 5: 최종 영상 생성
            self.step5_create_final_video(input_video_path, edit_commands, output_path)
            
            print("=" * 50)
            print("🎉 파이프라인 완료!")
            print(f"📁 출력 파일: {output_path}")
            
        except Exception as e:
            print(f"❌ 파이프라인 실행 오류: {e}")
            raise
        finally:
            # 임시 파일 정리
            import shutil
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                print(f"🧹 임시 파일 정리 완료")

def main():
    """
    메인 실행 함수
    """
    # API 키 로드
    api_key = config.load_api_key()
    
    if not api_key:
        print("🔑 API 키가 설정되지 않았습니다.")
        api_key = config.setup_api_key()
        
        if not api_key:
            print("❌ API 키 설정이 취소되었습니다.")
            return
    
    # 입력 파일 확인
    input_file = "input.mp4"
    if not os.path.exists(input_file):
        print(f"❌ 입력 파일 '{input_file}'을 찾을 수 없습니다.")
        print("테스트 모드로 샘플 영상을 생성합니다...")
        
        # 테스트용 샘플 영상 생성
        try:
            try:
                from moviepy.editor import ColorClip
            except ImportError:
                from moviepy import ColorClip
            import numpy as np
            
            # 5초짜리 테스트 영상 생성 (텍스트 없이)
            print("🎬 테스트 영상 생성 중...")
            bg = ColorClip(size=(640, 360), color=(64, 128, 255), duration=5)
            
            # 오디오 추가 (무음)
            bg = bg.with_audio(None)
            
            bg.write_videofile(input_file, codec='libx264', audio_codec='aac', fps=24, logger=None)
            bg.close()
            print(f"✅ 테스트 영상 생성 완료: {input_file}")
            
        except Exception as e:
            print(f"❌ 테스트 영상 생성 실패: {e}")
            print("더미 데이터로 테스트를 진행합니다...")
            
            # 더미 데이터로 파이프라인 테스트
            dummy_segments = [
                {"start": 0.0, "end": 2.5, "text": "안녕하세요"},
                {"start": 2.5, "end": 5.0, "text": "AI 영상 편집 테스트입니다"}
            ]
            
            print("🎨 스타일 프리셋을 선택하세요:")
            print("1. 매운맛 (예능/숏폼)")
            print("2. 순한맛 (브이로그)")
            print("3. 정석맛 (지식/정보)")
            
            try:
                choice = input("선택 (1-3): ").strip()
                style_map = {"1": "매운맛", "2": "순한맛", "3": "정석맛"}
                style_preset = style_map.get(choice, "정석맛")
                
                # 파이프라인 테스트 (실제 영상 없이)
                pipeline = VideoEditingPipeline(api_key)
                print("🧠 Gemini 문맥 분석 테스트 중...")
                edit_commands = pipeline.step3_analyze_context(dummy_segments, style_preset)
                print("✅ 테스트 완료!")
                print(f"생성된 편집 명령어: {len(edit_commands)}개")
                return
                
            except KeyboardInterrupt:
                print("\n👋 프로그램 종료")
                return
    
    # 스타일 프리셋 선택
    print("🎨 스타일 프리셋을 선택하세요:")
    print("1. 매운맛 (예능/숏폼)")
    print("2. 순한맛 (브이로그)")
    print("3. 정석맛 (지식/정보)")
    
    try:
        choice = input("선택 (1-3): ").strip()
        style_map = {"1": "매운맛", "2": "순한맛", "3": "정석맛"}
        style_preset = style_map.get(choice, "정석맛")
    except KeyboardInterrupt:
        print("\n👋 프로그램 종료")
        return
    
    # 파이프라인 실행
    pipeline = VideoEditingPipeline(api_key)
    pipeline.run_pipeline(input_file, style_preset, "output.mp4")

if __name__ == "__main__":
    main()
