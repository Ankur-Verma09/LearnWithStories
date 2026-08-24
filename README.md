# Learn With Stories

An offline-first AI tutor for Indian government-exam preparation. The application turns approved educational facts into level-adapted teaching stories, verifies the generated lesson, checks recall, and tracks concept mastery.

## System design

| Machine | Runs |
|---|---|
| Dell laptop | This project, local web UI, Python agent, approved sources, retrieval, context memory, lesson cache, SQLite database, recall scoring, and progress tracking |
| RTX 5070 Ti PC | Ollama and the local generation model only |

The machines communicate through the private home network. Internet access is not needed during normal learning, but both machines must be running to generate a new lesson. Previously verified lessons remain available from the Dell.

## Implemented MVP capabilities

- Responsive local learning UI with Learn, Progress, Knowledge Library, and Setup views
- Adjustable understanding level from 10 to 28
- English, Hindi, and Hinglish controls (English is the current acceptance baseline)
- Two-, five-, and ten-minute lessons
- Approved-source ingestion and local lexical retrieval
- Story planning, generation, verification, one repair attempt, and re-verification
- Publication gate that withholds failed or unsupported lessons
- Three-question multiple-choice recall check with deterministic scoring
- Per-concept mastery tracking and progress history
- Learner preferences, goals, and misconception memory with bounded context selection
- Verified-lesson caching to avoid repeated generation
- RTX model health and content-coverage visibility
- Optional Cloudflare Worker gateway for authenticated remote portal access; the Dell database and AI services remain private
- Hierarchical book indexing: Subject → Book → Section/Chapter → Topic → Sub-topic
- Searchable topic suggestions with unrestricted manual topic entry
- Compact, collapsible Knowledge Library with subject/book filters and administrator review
- Grounded online examinations for Subject, Topic, and balanced Overall practice
- Server-authoritative total/question timers, locked submissions, deterministic scoring, analysis, and history

## Project location

```text
E:\LearnWithStories
```

Important locations:

```text
config\settings.json              Active Dell configuration
data\sources\                    Approved JSONL source packs
data\story_tutor.db               Learner data, cache, progress, and content metadata
src\story_tutor\                  Agent and local server
web\                              Browser UI
src\story_tutor\exams.py         Exam validation, generation, factual gate, and allocation service
web\exam.js                      Examination workflow and timers
web\exam.css                     Responsive examination layout
start-learn-with-stories.cmd      UI launcher
story-tutor.cmd                   Command-line launcher
```

## Prerequisites

### Dell laptop

- Windows 10 or 11
- Python 3.11 or newer available as `python.exe`
- Private-network connection to the RTX PC
- No Python packages are required; the application uses the standard library

Check Python:

```powershell
python --version
```

The launchers use Python's `-S` mode, which prevents unrelated or broken global site packages from affecting this application.

### RTX 5070 Ti PC

- Current NVIDIA driver
- Ollama installed
- The selected local model installed
- A stable private IP address or reserved DHCP address

## Step 1: Configure the RTX model PC

Open PowerShell on the **RTX PC**.

### 1.1 Check Ollama and installed models

```powershell
ollama --version
ollama list
```

Install the model you intend to use if it is not listed. Use the exact name shown by `ollama list` later in the Dell configuration.

### 1.2 Allow Ollama to listen on the private LAN

Set the persistent user environment variable:

```powershell
setx OLLAMA_HOST "0.0.0.0:11434"
```

Exit Ollama completely from the system tray, sign out and back in if necessary, and start Ollama again. Confirm the listener:

```powershell
netstat -ano | findstr :11434
```

The listener should include `0.0.0.0:11434` or the RTX PC's private IP, not only `127.0.0.1:11434`.

### 1.3 Find the RTX PC private IP

```powershell
ipconfig
```

Record the active adapter's IPv4 address, for example `192.168.1.20`. Reserve this address in the router if possible.

### 1.4 Restrict the Windows firewall

Open **PowerShell as Administrator** on the RTX PC. Replace `<DELL_IP>` with the Dell's private IPv4 address:

```powershell
New-NetFirewallRule `
  -DisplayName "Ollama from LearnWithStories Dell" `
  -Direction Inbound `
  -Action Allow `
  -Protocol TCP `
  -LocalPort 11434 `
  -RemoteAddress <DELL_IP> `
  -Profile Private
```

Do not create router port forwarding for port 11434. Do not expose Ollama directly to the internet.

## Temporary setup: OpenAI API

Use this while the RTX model PC is being prepared.

1. Create a project API key in the OpenAI Platform. API usage is billed separately from ChatGPT subscriptions.
2. Double-click `E:\LearnWithStories\configure-openai-key.cmd`.
3. Paste the key into the protected Windows prompt. The key is stored as the user-level `OPENAI_API_KEY` environment variable; it is never written to this repository.
4. Confirm `config\settings.json` contains:

```json
{
  "model_provider": "openai",
  "model_base_url": "https://api.openai.com/v1",
  "model_name": "gpt-5-mini",
  "model_api_key": ""
}
```

5. Close any existing Learn With Stories server window and double-click `start-learn-with-stories.cmd`.
6. Open `http://127.0.0.1:8766`, select **Setup & health**, and confirm that OpenAI is online.

Never paste the API key into `settings.json`, source code, browser JavaScript, Git, or support messages. The application sends only the retrieved evidence and relevant learner context needed for the requested lesson; uploaded source files remain on the Dell. OpenAI requests use the Responses API with `store: false`.

### Configure multiple user-owned OpenAI keys

Run:

```powershell
& "E:\LearnWithStories\configure-openai-keys.cmd"
```

Enter between one and ten API keys that belong to you. Duplicate keys are removed. Native Windows runs load the protected user environment variable; Docker runs load the ACL-restricted `secrets\openai_api_keys.txt` file. Neither the UI nor SQLite stores or displays the key values.

The application moves to the next configured key after an authentication failure or an explicit insufficient-quota response. It does not rotate keys to evade ordinary request/token rate limits. A context-window error is retried once with a smaller input and output budget because changing a key cannot increase a model's context window.

## Docker operation

Docker runs the Dell-side web application, document processor, agent, and SQLite access. The future Ollama model continues to run separately on the RTX PC. `data` is mounted from the E: drive, so books, approvals, learning history, and `story_tutor.db` survive container replacement.

One-time preparation:

```powershell
Set-Location "E:\LearnWithStories"
& ".\configure-openai-keys.cmd"
docker compose build
```

Start and inspect the application:

```powershell
docker compose up -d
docker compose ps
docker compose logs -f learn-with-stories
```

Open `http://127.0.0.1:8766`. Stop it with:

```powershell
docker compose down
```

Do not run the native launcher and Docker container simultaneously because both use port `8766` and the same SQLite database. Stop one before starting the other.

## Step 2: Configure the Dell application for the future local model

Open this file on the **Dell**:

```text
E:\LearnWithStories\config\settings.json
```

Example:

```json
{
  "model_provider": "ollama",
  "model_base_url": "http://192.168.1.20:11434",
  "model_name": "qwen3.5:9b",
  "model_api_key": "",
  "request_timeout_seconds": 180,
  "database_path": "data/story_tutor.db",
  "max_evidence_chunks": 5,
  "max_evidence_tokens": 3000,
  "max_memory_tokens": 600,
  "max_session_summary_tokens": 300,
  "default_understanding_level": 18,
  "default_language": "English"
}
```

Settings:

| Setting | Meaning |
|---|---|
| `model_provider` | Use `openai` temporarily or `ollama` for the private RTX model PC. |
| `model_base_url` | RTX PC private URL. Change the example IP to the actual RTX PC address. |
| `model_name` | Exact installed model name returned by `ollama list`. |
| `model_api_key` | Leave blank for direct Ollama. A bearer key requires an authenticated reverse proxy. |
| `request_timeout_seconds` | Maximum time for one model request. |
| `database_path` | Dell-side SQLite location, relative to the project root. |
| `max_evidence_chunks` | Maximum retrieved source chunks per lesson. |
| `max_evidence_tokens` | Evidence portion of the prompt budget. |
| `max_memory_tokens` | Maximum learner-memory portion of the prompt. |
| `max_session_summary_tokens` | Reserved limit for future rolling-session summaries. |
| `default_understanding_level` | Initial level, from 10 to 28. |
| `default_language` | Initial UI language. |

## Step 3: Verify the configured provider

From any PowerShell directory on the Dell:

```powershell
& "E:\LearnWithStories\story-tutor.cmd" health
```

A successful response lists the configured provider model. With Ollama, if the configured model is not in `available_models`, correct `model_name` or install that model on the RTX PC.

You can also test the endpoint directly:

```powershell
Invoke-RestMethod "http://<RTX_PC_IP>:11434/api/tags"
```

## Step 4: Initialize and ingest approved content

Initialize the local database:

```powershell
& "E:\LearnWithStories\story-tutor.cmd" init
```

Ingest the included pipeline sample:

```powershell
& "E:\LearnWithStories\story-tutor.cmd" ingest "examples\sample_polity.jsonl"
```

The sample exists to exercise the pipeline. Before substantive exam preparation, replace or supplement it with text extracted from verified official editions and complete the source metadata.

Each JSONL line must contain:

```text
source_id, title, publisher, authority_tier, license_note, edition,
effective_date, subject, concept, section, text
```

Re-ingesting the same records is safe; duplicates are skipped.

## Step 5: Run the project

On the Dell, run:

```powershell
& "E:\LearnWithStories\start-learn-with-stories.cmd"
```

Keep the terminal open. Then open:

```text
http://127.0.0.1:8766
```

Stop the application with `Ctrl+C` in the launcher terminal.

## Book processing and topic review

Upload PDF or DOCX books from **Knowledge library → Add a document**. Searchable PDFs use their table of contents, chapter page ranges, headings, and surrounding text. Every chunk stores its subject, book, section, chapter, topic, optional sub-topic, and source page range. Unreliable names are shown as **Needs review** rather than being assigned the book title.

Subjects and books are collapsed by default. Expand only the branch you need, or search directly across the complete hierarchy. Use **Review** beside a topic or sub-topic to rename and lock the corrected name, approve it, or reject it. Locked administrator corrections are preserved when the book is processed again. Manual topic entry and administrator corrections work even when OpenAI or the RTX model is offline.

To reprocess an existing book after an extraction improvement, use its reprocess action in the Knowledge Library. The workflow keeps the existing source records and approval status, updates automatically extracted names, and does not overwrite administrator-locked names. Back up `data\story_tutor.db` before bulk reprocessing production content.

## Run the automated checks

From `E:\LearnWithStories`:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -s tests -v
```

The checks cover table-of-contents extraction, misleading running-header rejection, manual-name normalization and deduplication, hierarchy search/filter behavior, legacy-data preservation, administrator locks, and responsive UI contracts.

The application binds to `127.0.0.1` by default, so only the Dell can open it. LAN access from a phone or tablet is intentionally not enabled in this MVP.

## Secure Cloudflare portal and private Dell API setup

The repository includes `wrangler.jsonc` and `cloudflare/worker.js`. Cloudflare Workers VPC lets the Worker call the Dell through an outbound-only private tunnel. The Dell API receives no public hostname, and the browser calls only same-origin `/api/*` URLs on the portal. Workers VPC is currently a beta service and is free on Workers plans during the beta period.

### Zero-charge operating guardrails

This deployment can run without Cloudflare charges when the account remains on **Workers Free** and **Zero Trust Free**:

- Do not upgrade Workers, Pages, or Zero Trust and do not enable paid add-ons.
- Keep Cloudflare Access below the Free plan's 50-user limit.
- Static portal assets are served directly and do not invoke the Worker. Only `/api/*` uses the Workers Free allowance of 100,000 requests per day. When that allowance is exhausted, requests fail until the daily reset; the Free plan does not provide paid overage capacity.
- Workers VPC is free only while it remains in beta. Check Cloudflare's Workers VPC pricing before accepting any future plan or billing change.
- Cloudflare Tunnel is used only as the private outbound connector; no paid network service is required for this design.
- Do not enable Workers AI, R2, D1, KV, Durable Objects, Logpush, Argo, paid image optimization, or another usage-based product for this portal.

Cloudflare being free does **not** make OpenAI API usage free. For a strict zero-charge model path, set `model_provider` to `ollama` and point `model_base_url` to the RTX PC. Until the RTX PC is ready, do not generate lessons or examinations while `model_provider` is `openai`; library browsing, manual topic entry, and administrator correction remain available without model calls. Electricity and Internet service used by the Dell and RTX PC remain ordinary household costs.

### 1. Keep the Dell service private

Start Learn With Stories normally and verify this address on the Dell:

```text
http://127.0.0.1:8766/api/health
```

Docker must continue publishing `127.0.0.1:8766:8766`. Do not change it to `8766:8766` or `0.0.0.0:8766:8766`. Do not create a router port-forwarding rule for port `8766`.

### 2. Create the private Workers VPC tunnel

1. In Cloudflare, open **Workers VPC → Create → Tunnel**.
2. Create a remotely managed tunnel named `learn-with-stories-dell`.
3. Choose Windows and copy the service-install command Cloudflare displays.
4. Run that command once in an Administrator PowerShell window on the Dell. The command contains a private tunnel token; do not store or share it.
5. Wait until Cloudflare shows the connector as healthy.

The tunnel requires outbound QUIC access on UDP port `7844`. It does not require an inbound Windows Firewall rule or a public IP address.

### 3. Register only the Dell API as a VPC Service

1. Open **Workers VPC → Services → Create VPC Service**.
2. Name it `learn-with-stories-api`.
3. Select the `learn-with-stories-dell` tunnel.
4. Choose HTTP and set the target host to `127.0.0.1` and HTTP port to `8766`.
5. Save the service and copy its Service ID.
6. Replace `REPLACE_AFTER_CREATING_VPC_SERVICE` in `wrangler.jsonc` with that Service ID.

Use a VPC Service rather than a broad VPC Network binding. It limits the Worker to this one host and port.

### 4. Deploy the portal Worker from GitHub

1. In **Workers & Pages**, open the existing `learn-with-stories` Worker.
2. Open **Settings → Builds**, connect `Ankur-Verma09/LearnWithStories`, choose branch `main`, and keep the repository root as the root directory.
3. Leave the build command empty and use `npx wrangler deploy` as the deploy command.
4. Confirm that the Worker name remains `learn-with-stories`, matching `wrangler.jsonc`.
5. Push the reviewed gateway changes to GitHub to trigger the deployment.

The Worker uses the `DELL_API` VPC Service binding. No Dell hostname, API key, Access service token, or cross-origin browser permission is needed.

### 5. Require a login for the public portal

Protect the Worker itself so anonymous visitors cannot use the portal or call the Dell:

1. Open the Worker and select the separate **Access** tab. Pages projects do not have this Worker-level tab.
2. Select **Protect this Worker behind Access** and protect **All traffic**.
3. Create an **Allow** policy restricted to your email address or trusted family email addresses.
4. Do not create an `Allow everyone` or public bypass rule.

### 6. Verify the complete path

1. Open the `workers.dev` portal in a private browser window. Cloudflare must request a login.
2. After signing in, open `/api/health` on the same portal hostname. It should return the Dell model-health JSON.
3. Return to the portal and confirm that subjects and books load from the Dell.
4. Stop Learn With Stories on the Dell. The portal should return `DELL_API_UNAVAILABLE`, not expose an internal error.
5. Restart the Dell app and confirm that the portal recovers.

If the portal loads but subjects do not, check in this order: Dell app, Cloudflared Windows service, tunnel health, VPC Service target, `DELL_API` binding, and Worker deployment status.

## Start the complete project after a restart or shutdown

Use **Docker as the normal Dell runtime**. Do not also run `start-learn-with-stories.cmd`, because both methods use port `8766` and the same SQLite database.

### One-time automatic-start settings

1. In Docker Desktop, open **Settings → General**, enable **Start Docker Desktop when you sign in to your computer**, and apply the change.
2. Confirm that Cloudflare Tunnel is installed as a Windows service. In an Administrator PowerShell window, run:

   ```powershell
   Get-CimInstance Win32_Service -Filter "Name='cloudflared'" |
     Select-Object Name, State, StartMode
   ```

   The expected values are `Running` and `Auto`. If the service exists but is not automatic, run once:

   ```powershell
   Set-Service -Name cloudflared -StartupType Automatic
   Start-Service -Name cloudflared
   ```

3. The Docker service already has `restart: unless-stopped` in `compose.yaml`. It normally returns when Docker Desktop starts, provided the container was not manually stopped. The startup command below is still safe to run after every reboot.
4. When using the RTX local model, configure the Ollama Windows application to start when that PC signs in. No Ollama or RTX step is required while the application is deliberately using OpenAI, although OpenAI API calls may incur charges.

Do not paste or reinstall the Cloudflare tunnel token after each restart. The installed Windows service retains the tunnel configuration. If a tunnel token was exposed, rotate it in Cloudflare and reinstall the service using only the replacement command shown in the dashboard.

### Normal power-on sequence

#### 1. Start the RTX model PC when using Ollama

1. Power on the RTX PC and connect it to the same private network as the Dell.
2. Open Ollama from the Windows Start menu if it did not start automatically.
3. On the RTX PC, verify it:

   ```powershell
   ollama list
   Invoke-RestMethod "http://127.0.0.1:11434/api/tags"
   ```

4. Keep the RTX PC awake while generating lessons or examinations. Library browsing and manual administrator corrections do not require the model.

#### 2. Start the Dell application

1. Power on the Dell, connect it to the Internet, and start Docker Desktop. Wait until Docker Desktop reports that the engine is running.
2. Open PowerShell and run:

   ```powershell
   Set-Location "E:\LearnWithStories"
   docker compose up -d
   docker compose ps
   ```

3. `docker compose ps` should show `learn-with-stories` as running or healthy. If this is the first run, or the Docker image must be rebuilt after dependency or Dockerfile changes, use:

   ```powershell
   docker compose up -d --build
   ```

#### 3. Verify the Cloudflare Tunnel service

Run on the Dell:

```powershell
Get-Service -Name cloudflared
```

If it is stopped, open PowerShell as Administrator and run:

```powershell
Start-Service -Name cloudflared
```

The Cloudflare Worker itself is hosted by Cloudflare and does not need to be started or redeployed after a Dell or RTX PC reboot.

#### 4. Verify the complete route

First test the private Dell API locally:

```powershell
Invoke-RestMethod "http://127.0.0.1:8766/api/health"
```

Then open the protected portal:

```text
https://learn-with-stories.aaankurankur.workers.dev
```

Sign in through Cloudflare Access and open **Setup & health**. Confirm that the Dell API is online and, when using Ollama, that the configured model is available.

### Normal shutdown sequence

Before shutting down the Dell, optionally stop the application cleanly:

```powershell
Set-Location "E:\LearnWithStories"
docker compose stop
```

Windows stops the `cloudflared` service during shutdown. The Cloudflare Worker remains deployed but returns the controlled `DELL_API_UNAVAILABLE` response while the Dell is offline. Shut down the RTX PC after active model generation has finished.

At the next startup, always run `docker compose up -d`; it starts a previously stopped container without deleting the database or uploaded books.

### Native Windows fallback without Docker

Use this only when Docker is stopped:

```powershell
Set-Location "E:\LearnWithStories"
& ".\start-learn-with-stories.cmd"
```

Keep that terminal window open. Stop the native server with `Ctrl+C`. Before returning to Docker, close the native server and confirm that port `8766` is free.

### Commands used only after changes

These are not required after an ordinary reboot:

- Run `docker compose up -d --build` after Python dependencies, the Dockerfile, or packaged application code changes.
- Run `npx.cmd wrangler deploy` after `cloudflare/worker.js`, `wrangler.jsonc`, or files in `web` change and a direct Worker deployment is required.
- Run `git pull` only when new repository changes need to be downloaded to the Dell.
- Never run `docker compose down -v`; removing volumes is unnecessary and could delete Docker-managed data. The current project database and uploaded books are bind-mounted under `E:\LearnWithStories\data`.

### Quick recovery checks

| Symptom | Check and recovery |
|---|---|
| `docker compose` says no configuration file was found | Run `Set-Location "E:\LearnWithStories"` first. |
| `http://127.0.0.1:8766` is unreachable | Start Docker Desktop, run `docker compose up -d`, then inspect `docker compose logs --tail 100 learn-with-stories`. |
| Local `/api/health` works but the portal reports `DELL_API_UNAVAILABLE` | Check `Get-Service cloudflared`, the tunnel health in Cloudflare, and the VPC Service binding. |
| Portal opens but the model is offline | Start the RTX PC and Ollama, verify its private IP, and test `/api/tags` from the Dell. |
| Port `8766` is already in use | Stop either the Docker container or the native launcher; never run both. |
| Cloudflare asks for deployment after a reboot | Do not redeploy for a reboot. Verify the Dell container and `cloudflared` service instead. |

## First learning test

1. Open the **Setup & health** page and confirm that the model PC is online.
2. Open **Knowledge library** and confirm that `Article 21` is available.
3. Return to **Learn**.
4. Enter `Article 21`, select `Polity`, level `15`, and five minutes.
5. Generate the story.
6. Complete all three recall questions and submit them.
7. Open **Progress** to see the mastery score.

## Create and take an examination

1. Open **Examination** in the left navigation.
2. Enter an exam name and choose Subject, Topic, or Overall.
3. For Subject, choose one approved subject. For Topic, choose one subject and type or select its topic. For Overall, select at least two subjects.
4. Choose difficulty, question count, and total time, then select **Generate examination**.
5. The AI creates questions from approved evidence and a separate factual gate checks the questions and answer keys. A rejected set is not published.
6. Review the ready summary and select **Start exam**. This is when the total and per-question timers begin.
7. Answer or skip one question at a time. A timed-out question advances automatically and cannot be changed.
8. Finish the test to see marks, percentage, time taken, and question-wise evidence-backed analysis.
9. Reopen a completed result from **Exam history**. Ready and in-progress attempts can also be resumed.

For Overall exams, both the question count and total time are divided as evenly as integer values allow. Any remainder is assigned deterministically to the earliest selected subjects, so totals are never lost.

## Ask a specific question

1. Select a subject. This remains required because every answer must be grounded in an uploaded source.
2. Optionally choose or type a topic/sub-topic. When supplied, retrieval is strictly limited to chunks assigned to that topic hierarchy.
3. Enter the specific question you want answered. When topic is blank, the question searches across all approved content in the selected subject.
4. Generate the verified story lesson.

The specific question is stored with lesson history and participates in the verified-lesson cache key. An unrelated question therefore cannot reuse a lesson cached for another question.

## Learning preferences

Users can add preferences, study goals, and misconceptions from the Learn page. During lesson planning, the model may recommend one short default teaching preference suited to the question; this is saved as a **Model default** without replacing user preferences. Identical recommendations are deduplicated.

Every stored preference has a Delete option in the Learn and Setup views. Deleted preferences are removed from local SQLite immediately and are no longer included in future model context.

## Command-line operation

The UI and CLI use the same agent and database:

```powershell
$tutor = "E:\LearnWithStories\story-tutor.cmd"

& $tutor health
& $tutor ingest "examples\sample_polity.jsonl"
& $tutor remember "I understand household and civic examples best." --kind preference --subject Polity
& $tutor lesson "Article 21" --subject Polity --level 15 --minutes 5
& $tutor history
& $tutor progress
& $tutor content
```

Add `--refresh` to `lesson` to bypass a cached verified lesson.

## Backup and privacy

All learner data is stored on the Dell in:

```text
E:\LearnWithStories\data\story_tutor.db
```

Before copying the database, stop the application so SQLite can close its WAL files. Back up the database and approved source folder together. Encrypt backups that leave the Dell.

Do not store passwords, financial details, health information, or other unnecessary sensitive information as learner memories.

## Troubleshooting

### `No module named story_tutor`

Use the supplied `.cmd` launchers with their full E-drive paths. They set the project root and Python path automatically.

### `_distutils_hack` or `distutils-precedence.pth` error

The supplied launchers use `python -S`, which bypasses the broken global site-package hook. Do not replace the launcher with a bare `python -m story_tutor` command unless your Python installation is repaired and `PYTHONPATH` is set correctly.

### Model PC shows offline

Check, in order:

1. Both machines are connected to the same private network.
2. The RTX PC address in `settings.json` is correct.
3. Ollama is running on the RTX PC.
4. `netstat -ano | findstr :11434` shows a LAN listener.
5. The Windows firewall rule contains the Dell's current private IP.
6. `Invoke-RestMethod "http://<RTX_PC_IP>:11434/api/tags"` works from the Dell.

### Configured model is unavailable

Run `ollama list` on the RTX PC and copy the exact model name into `settings.json`. Restart the Dell application after changing settings.

For OpenAI, run `configure-openai-key.cmd`, confirm that the API project has billing/model access, and restart the application. Do not put the key into `settings.json`.

### OpenAI says the API key is invalid

ChatGPT subscriptions and ChatGPT login/session tokens are not API keys. Create a new project API key at `https://platform.openai.com/api-keys`, then:

1. Close every Learn With Stories server window.
2. Use the dashboard's **Copy** button and paste directly into `configure-openai-key.cmd`. Do not route the key through chat, Word, Google Docs, translated pages, or formatted text. The configurator rejects non-ASCII/look-alike characters, removes accidental quotes or a leading `Bearer` label, and verifies that Windows persisted the exact value.
3. Run `start-learn-with-stories.cmd` again. The launcher deliberately ignores stale keys inherited from old terminals and loads the saved user-level key.
4. Open **Setup & health** and select **Check again**.

If authentication succeeds but generation reports quota or billing errors, add API credits or billing details in the OpenAI Platform; a ChatGPT subscription does not include API usage.

### Topic needs approved evidence

The publication gate is working as intended. Add an approved JSONL source chunk whose `subject` and `concept` match the requested lesson, ingest it, and try again.

### Port 8766 is already in use

Close the older Learn With Stories terminal with `Ctrl+C`. Then start the application again.

## Current boundaries

- English is the verified baseline; Hindi and Hinglish require their own content and quality evaluation.
- Retrieval is lexical in this MVP; embeddings are not required for the first validated learning loop.
- One learner and one generation request at a time.
- No voice conversation, automatic web/current-affairs ingestion, or public hosting. OpenAI is an explicit temporary provider; Ollama remains the intended private local provider.
- The automated suite includes domain and static contracts for the examination module. Runtime browser, model-quality, timer-drift, and load verification remain separate acceptance activities.
# Document upload and automatic conversion

The Knowledge library now accepts PDF, DOCX, TXT, and JSONL files. PDF and Word documents are converted to validated JSONL automatically and then indexed; this is retrieval-based learning material, not model training or fine-tuning.

Before the first run, double-click `setup-learn-with-stories.cmd`. This creates a private Python environment and installs PDF reading support. Then double-click `start-learn-with-stories.cmd` for normal use and open `http://127.0.0.1:8766`.

In the application:

1. Open **Knowledge library**.
2. Choose a document and enter its subject.
3. Optionally enter a default topic when the document has weak or missing headings.
4. Confirm that you are authorized to use the document, then select **Convert and add to library**.
5. Wait for the green success message. The document appears under **Uploaded books**, and its subject/topics immediately appear on the Learn screen. The upload form resets so another book can be selected immediately.

The Uploaded books section can be filtered independently by book title and author/publisher. Expand a book to search its topic list or delete one topic from that book. **Delete book** removes the selected upload and its indexed topics; matching topics from other books remain available.

Duplicate files, titles, authors, and topics are allowed. Every upload is stored as a separate source, so different editions or publication years remain independently manageable. Enter the edition or year while uploading to distinguish them clearly.

Searchable PDFs work directly. Image-only scanned PDFs must first be processed with OCR and saved as a searchable PDF. Modern Word `.docx` files are supported; legacy `.doc` files must be saved as `.docx`. The default upload limit is 150 MB and can be changed with `max_upload_bytes` in `config/settings.json`.

Upload locations:

- Original files: `data/sources/uploads`
- Automatically generated JSONL: `data/sources/generated`
- Indexed application data: `data/story_tutor.db`


To stop a process listening on port 8766, run this in PowerShell:

```powershell
Get-NetTCPConnection -LocalPort 8766 -State Listen |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Stop-Process -Id $_ -Force }
```

Never place API keys in this README or any repository file. Configure only user-owned keys through `configure-openai-keys.cmd`.
