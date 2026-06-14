# X-Ray Transcription Assistant

A local transcription tool for X-ray specialists. It converts medical dictations to text using a local Whisper model, ensuring complete data privacy. Transcribed text can be directly exported to MS Word or LibreOffice Writer.

## Features
- **100% Local Processing**: No cloud data transmission, ensuring patient privacy.
- **Flexible Deployment**: Runs locally or on a dedicated server.
- **Audio Input**: Supports physical microphones or system audio (Windows Loopback).
- **Direct Export**: Copies transcribed text directly to Word or Writer documents.

## Prerequisites
- Python 3.9+
- FFmpeg installed on the system
- *(Optional for Loopback)* VB-Audio Virtual Cable (Windows)

## Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd <project-name>
   ```
2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   *(Includes `openai-whisper`, `pyaudio`, `python-docx`, `odfpy`)*

## Audio Configuration
- **Microphone**: Select the default input device in settings.
- **Windows Loopback**: Route system audio output to a virtual microphone input using virtual cable software.

## Usage

Run the application:
```bash
python main.py
```

1. Select the audio source (Microphone or Loopback).
2. Start real-time recording/transcription.
3. Upon completion, the text is processed and ready to be pasted into a new Word or Writer document.

## Notes
- MS Word or LibreOffice must be installed for document integration.
- The Whisper model downloads automatically on the first run.
