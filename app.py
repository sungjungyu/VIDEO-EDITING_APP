#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 기반 영상 편집 웹 애플리케이션
FastAPI Web Server
"""

import os
import json
import tempfile
import asyncio
from typing import Optional
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from main import VideoEditingPipeline
from config import config

app = FastAPI(title="AI 영상 편집 플랫폼", version="1.0.0")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 서빙
if not os.path.exists("static"):
    os.makedirs("static")
if not os.path.exists("uploads"):
    os.makedirs("uploads")
if not os.path.exists("outputs"):
    os.makedirs("outputs")

app.mount("/static", StaticFiles(directory="static"), name="static")

# 전역 변수
processing_status = {}

@app.get("/", response_class=HTMLResponse)
async def home():
    """메인 페이지"""
    html_content = """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AI 영상 편집 플랫폼</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            
            .container {
                background: white;
                border-radius: 20px;
                padding: 40px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                max-width: 600px;
                width: 90%;
            }
            
            h1 {
                text-align: center;
                color: #333;
                margin-bottom: 30px;
                font-size: 2.5em;
            }
            
            .upload-area {
                border: 3px dashed #667eea;
                border-radius: 15px;
                padding: 40px;
                text-align: center;
                margin-bottom: 30px;
                transition: all 0.3s ease;
                cursor: pointer;
            }
            
            .upload-area:hover {
                border-color: #764ba2;
                background: #f8f9ff;
            }
            
            .upload-area.dragover {
                border-color: #764ba2;
                background: #f0f2ff;
            }
            
            .file-input {
                display: none;
            }
            
            .upload-icon {
                font-size: 48px;
                color: #667eea;
                margin-bottom: 15px;
            }
            
            .upload-text {
                color: #666;
                font-size: 18px;
                margin-bottom: 10px;
            }
            
            .upload-hint {
                color: #999;
                font-size: 14px;
            }
            
            .style-selection {
                margin-bottom: 30px;
            }
            
            .style-title {
                font-size: 18px;
                color: #333;
                margin-bottom: 15px;
                font-weight: bold;
            }
            
            .style-options {
                display: flex;
                gap: 15px;
                justify-content: center;
            }
            
            .style-option {
                flex: 1;
                padding: 15px;
                border: 2px solid #e0e0e0;
                border-radius: 10px;
                text-align: center;
                cursor: pointer;
                transition: all 0.3s ease;
            }
            
            .style-option:hover {
                border-color: #667eea;
                transform: translateY(-2px);
            }
            
            .style-option.selected {
                border-color: #667eea;
                background: #f8f9ff;
            }
            
            .style-name {
                font-weight: bold;
                color: #333;
                margin-bottom: 5px;
            }
            
            .style-desc {
                font-size: 12px;
                color: #666;
            }
            
            .process-btn {
                width: 100%;
                padding: 15px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 18px;
                font-weight: bold;
                cursor: pointer;
                transition: all 0.3s ease;
            }
            
            .process-btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 10px 20px rgba(102, 126, 234, 0.3);
            }
            
            .process-btn:disabled {
                background: #ccc;
                cursor: not-allowed;
                transform: none;
            }
            
            .progress-container {
                margin-top: 30px;
                display: none;
            }
            
            .progress-bar {
                width: 100%;
                height: 20px;
                background: #f0f0f0;
                border-radius: 10px;
                overflow: hidden;
            }
            
            .progress-fill {
                height: 100%;
                background: linear-gradient(90deg, #667eea, #764ba2);
                width: 0%;
                transition: width 0.3s ease;
            }
            
            .progress-text {
                text-align: center;
                margin-top: 10px;
                color: #666;
            }
            
            .result-container {
                margin-top: 30px;
                display: none;
            }
            
            .download-btn {
                display: inline-block;
                padding: 12px 30px;
                background: #4CAF50;
                color: white;
                text-decoration: none;
                border-radius: 8px;
                font-weight: bold;
                transition: all 0.3s ease;
            }
            
            .download-btn:hover {
                background: #45a049;
                transform: translateY(-2px);
            }
            
            .error-message {
                background: #ffebee;
                color: #c62828;
                padding: 15px;
                border-radius: 8px;
                margin-top: 20px;
                display: none;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎬 AI 영상 편집 플랫폼</h1>
            
            <div class="upload-area" id="uploadArea">
                <div class="upload-icon">📹</div>
                <div class="upload-text">영상 파일을 여기에 드래그하거나 클릭하세요</div>
                <div class="upload-hint">지원 형식: MP4, AVI, MOV (최대 100MB)</div>
                <input type="file" id="fileInput" class="file-input" accept="video/*">
            </div>
            
            <div class="style-selection">
                <div class="style-title">🎨 편집 스타일 선택</div>
                <div class="style-options">
                    <div class="style-option" data-style="매운맛">
                        <div class="style-name">🌶️ 매운맛</div>
                        <div class="style-desc">예능/숏폼</div>
                    </div>
                    <div class="style-option" data-style="순한맛">
                        <div class="style-name">🍲 순한맛</div>
                        <div class="style-desc">브이로그</div>
                    </div>
                    <div class="style-option selected" data-style="정석맛">
                        <div class="style-name">🍚 정석맛</div>
                        <div class="style-desc">지식/정보</div>
                    </div>
                </div>
            </div>
            
            <button class="process-btn" id="processBtn" disabled>영상 편집 시작하기</button>
            
            <div class="progress-container" id="progressContainer">
                <div class="progress-bar">
                    <div class="progress-fill" id="progressFill"></div>
                </div>
                <div class="progress-text" id="progressText">준비 중...</div>
            </div>
            
            <div class="result-container" id="resultContainer">
                <h3>✅ 편집 완료!</h3>
                <a href="#" class="download-btn" id="downloadBtn">편집된 영상 다운로드</a>
            </div>
            
            <div class="error-message" id="errorMessage"></div>
        </div>
        
        <script>
            let selectedFile = null;
            let selectedStyle = '정석맛';
            
            // 파일 업로드
            const uploadArea = document.getElementById('uploadArea');
            const fileInput = document.getElementById('fileInput');
            const processBtn = document.getElementById('processBtn');
            
            uploadArea.addEventListener('click', () => fileInput.click());
            
            uploadArea.addEventListener('dragover', (e) => {
                e.preventDefault();
                uploadArea.classList.add('dragover');
            });
            
            uploadArea.addEventListener('dragleave', () => {
                uploadArea.classList.remove('dragover');
            });
            
            uploadArea.addEventListener('drop', (e) => {
                e.preventDefault();
                uploadArea.classList.remove('dragover');
                handleFile(e.dataTransfer.files[0]);
            });
            
            fileInput.addEventListener('change', (e) => {
                handleFile(e.target.files[0]);
            });
            
            function handleFile(file) {
                if (file && file.type.startsWith('video/')) {
                    if (file.size > 100 * 1024 * 1024) {
                        showError('파일 크기는 100MB를 초과할 수 없습니다.');
                        return;
                    }
                    selectedFile = file;
                    uploadArea.innerHTML = `
                        <div class="upload-icon">✅</div>
                        <div class="upload-text">${file.name}</div>
                        <div class="upload-hint">${(file.size / 1024 / 1024).toFixed(1)}MB</div>
                    `;
                    processBtn.disabled = false;
                } else {
                    showError('영상 파일만 업로드할 수 있습니다.');
                }
            }
            
            // 스타일 선택
            document.querySelectorAll('.style-option').forEach(option => {
                option.addEventListener('click', () => {
                    document.querySelectorAll('.style-option').forEach(opt => opt.classList.remove('selected'));
                    option.classList.add('selected');
                    selectedStyle = option.dataset.style;
                });
            });
            
            // 편집 시작
            processBtn.addEventListener('click', async () => {
                if (!selectedFile) {
                    showError('파일을 선택해주세요.');
                    return;
                }
                
                const formData = new FormData();
                formData.append('file', selectedFile);
                formData.append('style', selectedStyle);
                
                processBtn.disabled = true;
                processBtn.textContent = '처리 중...';
                showProgress();
                
                try {
                    const response = await fetch('/edit', {
                        method: 'POST',
                        body: formData
                    });
                    
                    const result = await response.json();
                    
                    if (response.ok) {
                        updateProgress(100, '편집 완료!');
                        showResult(result.output_file);
                    } else {
                        showError(result.detail || '처리 중 오류가 발생했습니다.');
                    }
                } catch (error) {
                    showError('서버 오류가 발생했습니다.');
                } finally {
                    processBtn.disabled = false;
                    processBtn.textContent = '영상 편집 시작하기';
                }
            });
            
            function showProgress() {
                document.getElementById('progressContainer').style.display = 'block';
                document.getElementById('resultContainer').style.display = 'none';
                document.getElementById('errorMessage').style.display = 'none';
            }
            
            function updateProgress(percent, text) {
                document.getElementById('progressFill').style.width = percent + '%';
                document.getElementById('progressText').textContent = text;
            }
            
            function showResult(filename) {
                document.getElementById('progressContainer').style.display = 'none';
                document.getElementById('resultContainer').style.display = 'block';
                document.getElementById('downloadBtn').href = `/download/${filename}`;
            }
            
            function showError(message) {
                document.getElementById('errorMessage').textContent = message;
                document.getElementById('errorMessage').style.display = 'block';
            }
            
            // 진행 상황 폴링
            let pollingInterval;
            function startPolling() {
                pollingInterval = setInterval(async () => {
                    try {
                        const response = await fetch('/status');
                        const status = await response.json();
                        if (status.progress !== undefined) {
                            updateProgress(status.progress, status.message);
                        }
                    } catch (error) {
                        console.error('Status polling error:', error);
                    }
                }, 1000);
            }
            
            function stopPolling() {
                if (pollingInterval) {
                    clearInterval(pollingInterval);
                }
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.post("/edit")
async def edit_video(file: UploadFile = File(...), style: str = Form("정석맛")):
    """영상 편집 API"""
    try:
        # 파일 저장
        file_path = f"uploads/{file.filename}"
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        # 출력 파일명 생성
        output_filename = f"edited_{file.filename}"
        output_path = f"outputs/{output_filename}"
        
        # 상태 초기화
        global processing_status
        processing_status = {"progress": 0, "message": "준비 중..."}
        
        # 비동기 처리 시작
        asyncio.create_task(process_video_async(file_path, style, output_path, output_filename))
        
        return JSONResponse({
            "message": "영상 편집을 시작했습니다.",
            "output_file": output_filename
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def process_video_async(input_path: str, style: str, output_path: str, output_filename: str):
    """비동기 영상 처리"""
    try:
        # 전역 상태 업데이트
        processing_status["progress"] = 10
        processing_status["message"] = "영상 편집 시작..."
        
        # API 키 로드
        api_key = config.load_api_key()
        if not api_key:
            processing_status["error"] = "API 키가 설정되지 않았습니다."
            return
        
        # 파이프라인 실행
        pipeline = VideoEditingPipeline(api_key)
        
        processing_status["progress"] = 30
        processing_status["message"] = "오디오 추출 중..."
        
        processing_status["progress"] = 50
        processing_status["message"] = "음성 인식 중..."
        
        processing_status["progress"] = 70
        processing_status["message"] = "AI 문맥 분석 중..."
        
        processing_status["progress"] = 90
        processing_status["message"] = "영상 렌더링 중..."
        
        pipeline.run_pipeline(input_path, style, output_path)
        
        processing_status["progress"] = 100
        processing_status["message"] = "완료!"
        processing_status["output_file"] = output_filename
        
    except Exception as e:
        processing_status["error"] = str(e)

@app.get("/status")
async def get_status():
    """처리 상태 확인"""
    return JSONResponse(processing_status)

@app.get("/download/{filename}")
async def download_file(filename: str):
    """파일 다운로드"""
    file_path = f"outputs/{filename}"
    if os.path.exists(file_path):
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="video/mp4"
        )
    else:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

if __name__ == "__main__":
    # API 키 확인
    api_key = config.load_api_key()
    if not api_key:
        print("❌ GEMINI_API_KEY를 설정해주세요.")
        print("1. Google AI Studio에서 API 키 발급: https://aistudio.google.com/app/apikey")
        print("2. gemini_key.txt 파일에 API 키 입력")
        exit(1)
    
    print("🚀 AI 영상 편집 웹 서버 시작!")
    print("🌐 http://localhost:8000 에서 접속하세요")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
