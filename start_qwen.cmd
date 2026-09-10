@echo off
setlocal
set "MODELS=E:\LLM's\Qwen3TTS"
set "BIN=D:\Projects\qwentts.cpp\build\Release\tts-server.exe"
if not exist "%BIN%" (
  echo tts-server not found: "%BIN%"
  pause & exit /b 1
)
"%BIN%" --model "%MODELS%\qwen-talker-1.7b-base-Q8_0.gguf" --codec "%MODELS%\qwen-tokenizer-12hz-Q8_0.gguf" --alias qwen3-tts --host 127.0.0.1 --port 8080
