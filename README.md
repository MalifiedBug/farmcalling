# 🌾 FarmCalling — Vobiz Voice Automation Platform

> An enterprise-grade automated outbound telephony application built on the **Vobiz Voice API & Applications engine**. Schedule phone calls on specific date/times, intervals, or recurring schedules, play uploaded or microphone-recorded audio prompts, and automatically hang up the call upon completion.

---

## 🌟 Key Features

1. **Flexible Automated Scheduling Engine:**
   - **Specific Date & Time (One-Off):** Schedule targeted calls for a specific date and time (e.g. crop weather warning at 06:30 AM tomorrow).
   - **Repeating Intervals:** Dial automatically every *N* minutes, hours, or days until paused.
   - **Daily / Recurring Cron:** Trigger daily at a specific hour:minute or using custom 5-part cron syntax.
   - **Instant Dial ("Call Now"):** Test dial any number on demand with 1-click.
   - **Bulk Calling Support:** Dial multiple numbers simultaneously using Vobiz `<` delimiter (e.g. `+919876543210<+919876543211`).

2. **Audio Studio (Record, Upload, and Cut Call):**
   - **Microphone Recording:** Record announcements directly in your web browser using HTML5 / Streamlit microphone recording.
   - **Audio File Upload:** Upload standard `.mp3` or `.wav` files with built-in duration analysis and in-browser audio player.
   - **Text-to-Speech (TTS) Synthesizer:** Create virtual voice prompts with customizable voices (`WOMAN`, `MAN`) and multi-language accents (`en-US`, `en-IN`, `hi-IN`).
   - **VobizXML Play & Hangup Flow:** Built-in FastAPI server streams audio with compliant `audio/mpeg` / `audio/wav` headers and generates the exact VobizXML:
     ```xml
     <?xml version="1.0" encoding="UTF-8"?>
     <Response>
         <Play loop="1">https://your-public-url.com/audio/{audio_id}</Play>
         <Hangup/>
     </Response>
     ```
     *The call plays the full audio prompt, and Vobiz immediately cuts the call when playback finishes.*

3. **Complete Telephony Settings Manager:**
   - **Vobiz API Authentication:** Securely configure `X-Auth-ID` and `X-Auth-Token`.
   - **Live Connection Tester:** Validates credentials, fetches real-time account balance, and auto-discovers owned DID numbers.
   - **One-Click Vobiz Application Provisioning:** Calls `POST /api/v1/Account/{auth_id}/Application/` to automatically register your app and webhook URLs (`/webhook/answer` and `/webhook/hangup`) with Vobiz!
   - **Caller ID Management:** Select from account DIDs or specify a custom E.164 caller ID.
   - **Outbound Policy Controls:** Configurable Ring Timeout, Max Call Duration, Answering Machine Detection (AMD: Disabled, Async, or Hangup on Machine), and Timezone.
   - **Built-in Webhook Simulator:** Test answer and hangup flows locally without incurring telephony costs.

4. **Call History & CDR Telemetry Inspector:**
   - Real-time logging of Call UUID, status, duration (seconds), hangup cause (`NORMAL_CLEARING`, `USER_BUSY`, `NO_ANSWER`), and exact VobizXML dispatched.
   - Export all call logs to CSV for record keeping.

---

## 🚀 Deployment to Vercel (Serverless Telephony Engine)

The application is completely configured for **1-click zero-config deployment to Vercel**:

### 1. What's Included for Vercel
- **`vercel.json`**: Configures the `@vercel/python` builder, route rewrites, and periodic **Vercel Cron** (`* * * * *` calling `/api/cron`).
- **`api/index.py`**: ASGI serverless entrypoint routing requests to FastAPI.
- **Serverless Web Dashboard (`static/index.html`)**: Mobile-ready Tailwind CSS dashboard served at `https://your-project.vercel.app/`.
- **Serverless Storage Adapter**: Seamlessly operates with `/tmp/farmcalling.db` and `/tmp/audio/` in Vercel's ephemeral serverless environment.

### 2. Deploying via Vercel CLI or GitHub

#### Option A: Using the Vercel CLI
```bash
npm i -g vercel
vercel
```

#### Option B: Deploying via GitHub
1. Push your repository to GitHub.
2. In the [Vercel Dashboard](https://vercel.com/new), click **Import Project** and select this repository.
3. Under **Environment Variables**, add:
   - `VOBIZ_AUTH_ID`: Your Vobiz Auth ID (e.g. `MA_WTGRSXR3`)
   - `VOBIZ_AUTH_TOKEN`: Your Vobiz Auth Token
   - `VOBIZ_CALLER_ID`: Your outbound phone number (e.g. `+918065354878`)
4. Click **Deploy**.

Vercel will give you an instant global HTTPS URL (e.g. `https://farmcalling.vercel.app`), which will automatically handle:
- Web dashboard at `/`
- Webhook answer endpoint at `/webhook/answer`
- Webhook hangup endpoint at `/webhook/hangup`
- Audio streaming at `/audio/{id}`
- Automated background scheduling via Vercel Cron at `/api/cron`

---

## 🏗️ Architecture & Call Lifecycle Flow

```mermaid
sequenceDiagram
    autonumber
    actor User as User / Scheduler
    participant UI as Streamlit Dashboard (Port 8501)
    participant Sched as APScheduler Daemon
    participant Server as FastAPI Webhook Server (Port 8000)
    participant Vobiz as Vobiz Telephony Cloud
    participant Recipient as Farmer / Recipient Phone

    Note over User,Sched: Trigger Event (Scheduled Date, Interval, or Instant Dial)
    Sched->>Vobiz: POST /api/v1/Account/{auth_id}/Call/<br/>(from, to, answer_url, hangup_url)
    Vobiz-->>Sched: 200 OK (Call fired, Request UUID)
    Vobiz->>Recipient: Outbound PSTN / Mobile Call Ringing

    Recipient->>Vobiz: Answers Call
    Vobiz->>Server: POST /webhook/answer?schedule_id=...&audio_id=...
    Server-->>Vobiz: Returns VobizXML:<br/>&lt;Response&gt;&lt;Play&gt;URL&lt;/Play&gt;&lt;Hangup/&gt;&lt;/Response&gt;
    
    Vobiz->>Server: GET /audio/{audio_id} (Fetch Audio Stream)
    Server-->>Vobiz: Streams Audio (audio/mpeg or audio/wav)
    Vobiz->>Recipient: Plays Recorded Audio Prompt
    
    Note over Recipient,Vobiz: Audio playback finishes
    Vobiz->>Recipient: Cuts Call (Hangup)
    Vobiz->>Server: POST /webhook/hangup (CallUUID, Duration, HangupCause)
    Server->>UI: Updates Call Log in Database (Completed, Duration)
```

---

## 🚀 Quick Start Guide

### 1. Requirements
- Python 3.9+
- A [Vobiz Account](https://console.vobiz.ai) with Auth ID, Auth Token, and an active phone number / DID.

### 2. Installation
The environment and dependencies are pre-configured in `.venv`:
```bash
# If setting up in a new environment:
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 3. Running the Application
Launch both the Webhook & Audio Server and the Streamlit Dashboard with a single command:
```bash
./run.py
# Or:
.venv/bin/python run.py
```

The services will start at:
- **Streamlit Web Dashboard:** [http://localhost:8501](http://localhost:8501)
- **FastAPI Webhook & Audio Server:** [http://localhost:8000](http://localhost:8000)

---

## 🌐 Connecting Vobiz to Your Local Machine (Webhooks)

Because Vobiz runs on the public cloud, it must be able to reach your webhook server (`/webhook/answer` and `/audio/{id}`) over public HTTPS.

### Option A: Using ngrok (Recommended)
```bash
ngrok http 8000
```
1. Copy the forwarded HTTPS URL (e.g. `https://your-domain.ngrok-free.app`).
2. Open **Settings -> Webhook & Tunneling** in FarmCalling.
3. Paste your ngrok URL into **Public Webhook Base URL** and click **Save**.

### Option B: Using localtunnel (No sign-up)
```bash
npx localtunnel --port 8000
```

---

## 📂 Project Structure

```
farmcalling/
├── .streamlit/
│   └── config.toml           # Enterprise theme styling (Dark mode)
├── app.py                    # Main Streamlit application & navigation router
├── server.py                 # FastAPI Webhook & Audio streaming server
├── scheduler.py              # APScheduler background automation engine
├── vobiz_client.py           # Vobiz REST API client & VobizXML builder
├── audio_manager.py          # Microphone recording & audio asset manager
├── database.py               # SQLite database & persistence layer
├── run.py                    # Unified single-command launcher
├── tests/
│   ├── test_farmcalling.py   # Unit & integration tests
│   └── test_streamlit_app.py # Automated Streamlit AppTest
├── data/
│   ├── audio/                # Local storage for recorded & uploaded audio
│   └── farmcalling.db        # SQLite database
├── pages/
│   ├── 1_dashboard.py        # KPIs, quick dialer, recent activity
│   ├── 2_schedules.py        # Date/Time, Interval, Cron scheduling
│   ├── 3_audio_studio.py     # Mic recorder, file uploader, TTS, library
│   ├── 4_call_history.py     # Call logs, CDR telemetry, CSV export
│   └── 5_settings.py         # Credentials, app sync, policies, simulator
└── requirements.txt
```

---

## 🧪 Testing

Run the full automated test suite anytime:
```bash
.venv/bin/python -m unittest discover tests
```
All unit tests and UI rendering integration tests execute in < 1 second.

