# Learn With Stories

Learn With Stories is an offline-first AI learning portal for Indian government-exam preparation. It converts uploaded PDF, DOCX, TXT, and JSONL material into approved knowledge, retrieves relevant passages, generates a story-based lesson, verifies the lesson against its sources, and tracks learning progress.

New readers can start with [Product overview and simple flow](docs/PRODUCT_OVERVIEW.md) before following the technical setup below.

## 1. Architecture

| Component | Runs on | Responsibility |
|---|---|---|
| Learn With Stories | Dell laptop | Docker application, portal, document processing, retrieval, learner memory, lesson cache, SQLite database, approvals, and progress |
| Local AI model | RTX 5070 Ti PC | Ollama and the selected model only |
| Production portal | Cloudflare | Authenticated public web portal and private routing to the Dell |

Normal production flow:

```text
Browser → Cloudflare Access → Cloudflare Worker → private tunnel → Dell → RTX Ollama
```

The RTX PC does not need this repository, Docker, the books, or the database. It only runs Ollama. Uploaded books and learner data stay on the Dell.

## 2. Important locations

```text
E:\LearnWithStories\config\settings.json       Active application configuration
E:\LearnWithStories\config\learning_profiles.json  Configurable age and knowledge profiles
E:\LearnWithStories\data\sources\             Uploaded and approved source material
E:\LearnWithStories\data\story_tutor.db        Books, approvals, lessons, memory, and progress
E:\LearnWithStories\secrets\                   Local API-key file used by Docker
E:\LearnWithStories\src\story_tutor\           Python application and agent
E:\LearnWithStories\web\                       Responsive browser portal
E:\LearnWithStories\web\voice\                 Reusable browser voice services and controller
E:\LearnWithStories\docs\PRODUCT_OVERVIEW.md   Plain-language product description and user flow
E:\LearnWithStories\docs\LOCAL_AI_STORY_ARCHITECTURE.md  Adaptive local-LLM design and gap analysis
E:\LearnWithStories\cloudflare\worker.js       Cloudflare gateway
E:\LearnWithStories\compose.yaml               Dell Docker service
```

Do not commit `config\settings.json`, `data`, `secrets`, `.venv`, or `.wrangler`. They are intentionally ignored by Git.

## 3. Cost and security rules

- Ollama and downloaded local models have no API charge. Electricity and normal Internet service still apply.
- OpenAI API usage is billed separately from a ChatGPT subscription.
- To prevent model charges, use `"model_provider": "ollama"` and leave `model_api_key` blank.
- Keep the Cloudflare account on the Free plans and do not enable paid add-ons or accept an upgrade.
- Never expose Dell port `8766` or Ollama port `11434` through router port forwarding.
- Never publish API keys, Cloudflare tunnel tokens, `settings.json`, the SQLite database, or uploaded books.
- Use only API keys that you own. Do not use keys copied from public repositories.

## 4. First-time Dell setup

Complete these steps in order.

### Step 1: Install prerequisites

Install on the Dell:

1. Git.
2. Docker Desktop for Windows.
3. Python 3.11 or newer only if the native Windows fallback or command-line tools will be used.

Enable **Docker Desktop → Settings → General → Start Docker Desktop when you sign in**.

Verify Docker:

```powershell
docker version
docker compose version
```

All commands below must be run from the project directory:

```powershell
Set-Location "E:\LearnWithStories"
```

Running `docker compose` from another directory produces the “no configuration file provided” error.

### Step 2: Create local configuration files

If `config\settings.json` does not exist:

```powershell
Copy-Item ".\config\settings.example.json" ".\config\settings.json"
```

Create the Docker secret file if it does not exist. An empty file is valid when using Ollama:

```powershell
New-Item -ItemType Directory -Path ".\secrets" -Force | Out-Null
if (-not (Test-Path ".\secrets\openai_api_keys.txt")) {
    New-Item -ItemType File -Path ".\secrets\openai_api_keys.txt" | Out-Null
}
```

### Step 3: Select the model provider

Choose exactly one of the following options.

#### Option A: Temporary OpenAI provider

This option requires a user-owned OpenAI Platform API key and can incur API charges.

Run:

```powershell
& ".\configure-openai-keys.cmd"
```

Enter between one and fifty keys that belong to you. Enter `1` when only one key is required. Duplicate keys are removed. Key values are stored outside Git and are never returned to the browser.

Confirm these properties in `config\settings.json` while preserving the remaining properties:

```json
{
  "model_provider": "openai",
  "model_base_url": "https://api.openai.com/v1",
  "model_name": "gpt-5-mini",
  "model_api_key": ""
}
```

The application can move to another configured key after an authentication failure or an explicit insufficient-quota response. It does not rotate keys to evade normal request or token rate limits. A context-window error is retried with a smaller request because changing keys cannot increase a model's context window.

#### Option B: Private RTX Ollama provider

Complete the RTX setup in Section 5, confirm the Dell can reach it, and then switch the Dell configuration as described there. No OpenAI key is required.

### Step 4: Build and start the Dell application

```powershell
Set-Location "E:\LearnWithStories"
docker compose up -d --build
docker compose ps
```

The expected container name is `learn-with-stories`.

Inspect startup errors with:

```powershell
docker compose logs --tail 100 learn-with-stories
```

Do not run the native launcher and Docker simultaneously. Both use port `8766` and the same SQLite database.

### Step 5: Verify the local application

```powershell
Invoke-RestMethod "http://127.0.0.1:8766/api/health"
```

Open the local portal:

```text
http://127.0.0.1:8766
```

Open **Setup & health** and confirm the configured provider and model are online.

On the first start, the portal asks you to create the first administrator account. Use a unique password with at least ten characters, one letter, and one number. The first account receives both `ADMIN` and `STUDENT` roles so the administrator can also use the learning portal. This one-time setup adopts existing local lessons, progress, exams, and learner context without deleting them.

Create this first administrator at `http://127.0.0.1:8766` on the Dell before publishing or opening the production portal. For takeover protection, the first-administrator endpoint rejects requests arriving through the Cloudflare Worker. Additional users are then created by an administrator under **Setup & health → User access**.

### Step 6: Initialize content

The web server initializes the database automatically. The CLI can also initialize it explicitly:

```powershell
& ".\story-tutor.cmd" init
```

Use the Knowledge Library to upload verified and legally authorized editions for exam preparation. The repository no longer includes or automatically ingests sample Polity content.

### Step 7: Upload books

1. Open **Knowledge Library**.
2. Select **Add a document**.
3. Select a PDF, DOCX, TXT, or JSONL file.
4. Enter its subject, book metadata, edition/year, and any useful fallback topic.
5. Confirm that you are authorized to use the document.
6. Select **Convert and add to library**.
7. Wait for the success state before uploading the next book.

Files are stored in:

```text
Original uploads:    data\sources\uploads
Generated JSONL:     data\sources\generated
Indexed information: data\story_tutor.db
```

Searchable PDFs work directly. Image-only PDFs require OCR first. Modern `.docx` files are supported; legacy `.doc` files must be saved as `.docx`. The default upload limit is controlled by `max_upload_bytes` in `settings.json`.

Duplicate titles, authors, topics, and editions are allowed as separate uploads. Knowledge Library supports filtering, topic review, topic deletion, and complete book deletion.

### Step 8: Verify the learning flow

1. Open **Learn**.
2. Select a subject.
3. Optionally search for or manually type a topic/sub-topic.
4. Enter the specific question.
5. Select the level, language, and lesson duration.
6. Generate the lesson.
7. Complete the recall questions.
8. Open **Progress** to review mastery.

The subject is required so retrieval remains grounded. The topic is optional; when supplied, retrieval is restricted to that hierarchy. Manual topic entry and administrator corrections remain available even when the model is offline.

### Step 9: Configure users and roles

One user may have one or both supported roles:

| Capability | Student | Admin |
|---|---:|---:|
| Learn, ask follow-ups, take exams, view own progress | Yes | Yes |
| Add, edit, and delete own manually created learner context | Yes | Yes |
| Delete AI-generated preferences or goals | No | Yes |
| View/upload/reprocess/delete Knowledge Library books | No | Yes |
| View active model configuration and provider checklists | No | Yes |
| Create users and assign multiple roles | No | Yes |

Sign in as an administrator, open **Setup & health**, and use **User access** to create accounts, assign Student/Admin roles, disable access, or reset a password. Authorization is enforced by the Dell APIs as well as by the browser interface. Passwords are stored as salted PBKDF2 hashes; sessions use an HTTP-only cookie plus a request-verification token.

## 5. RTX 5070 Ti model-PC setup

Complete this section once after receiving the RTX PC.

### RTX Step 1: Prepare Windows and the GPU

1. Install current Windows updates.
2. Install the latest NVIDIA driver.
3. Use a wired private network when possible.
4. Set the Windows network profile to **Private**.
5. Prevent automatic sleep while plugged in.

Verify the GPU:

```powershell
nvidia-smi
```

### RTX Step 2: Install Ollama and the model

Install Ollama for Windows from `https://ollama.com/download/windows`.

Open a new PowerShell window:

```powershell
ollama --version
ollama pull gemma3:12b
ollama run gemma3:12b "Reply with only: READY"
```

`gemma3:12b` is the initial local story-generation model. Ollama supplies its supported quantized build; confirm the installed variant and GPU allocation with `ollama show gemma3:12b` and `ollama ps`. Keep larger models out of the initial configuration until their VRAM and latency are measured on the RTX PC.

### RTX Step 3: Allow private Dell access

Run on the RTX PC:

```powershell
setx OLLAMA_HOST "0.0.0.0:11434"
setx OLLAMA_CONTEXT_LENGTH "8192"
setx OLLAMA_NUM_PARALLEL "1"
setx OLLAMA_MAX_LOADED_MODELS "1"
```

Quit Ollama completely from the system tray and start it again. Restart Windows if it continues listening only on localhost.

Verify:

```powershell
reg query HKCU\Environment /v OLLAMA_HOST
netstat -ano | findstr :11434
Invoke-RestMethod "http://127.0.0.1:11434/api/tags"
```

The listener must show `0.0.0.0:11434` or the RTX PC's private address, not only `127.0.0.1:11434`.

### RTX Step 4: Reserve the RTX private IP

```powershell
ipconfig
```

Record the active adapter's IPv4 address, for example `192.168.1.20`, and reserve it in the router's DHCP settings.

Run `ipconfig` on the Dell as well and record the Dell's private IPv4 address.

### RTX Step 5: Restrict the firewall to the Dell

Open PowerShell **as Administrator on the RTX PC**. Replace `<DELL_IP>` with the Dell's private address:

```powershell
New-NetFirewallRule `
  -DisplayName "Ollama from LearnWithStories Dell only" `
  -Direction Inbound `
  -Action Allow `
  -Protocol TCP `
  -LocalPort 11434 `
  -RemoteAddress <DELL_IP> `
  -Profile Private
```

Do not create a router port-forward or a Cloudflare Tunnel to Ollama.

### RTX Step 6: Test from the Dell

Replace `<RTX_PC_IP>` with the reserved RTX address:

```powershell
Test-NetConnection <RTX_PC_IP> -Port 11434
Invoke-RestMethod "http://<RTX_PC_IP>:11434/api/tags"
```

Do not continue until both checks succeed.

### RTX Step 7: Switch the Dell agent from OpenAI to Ollama

This is the only application-side provider switch. Complete RTX Steps 1–6 first.

On the Dell, edit `E:\LearnWithStories\config\settings.json`. Change only the model properties and preserve the remaining configuration:

```json
{
  "model_provider": "ollama",
  "model_base_url": "http://192.168.1.20:11434",
  "model_name": "gemma3:12b",
  "model_api_key": "",
  "request_timeout_seconds": 180
}
```

Replace `192.168.1.20` with the actual RTX address. Do not add `/v1` to the Ollama URL.

`model_provider` is the provider-switch flag. No UI flag or Cloudflare change is required. OpenAI keys can remain configured; they are not used while the provider is `ollama`.

If a local `.env` file contains `LLM_PROVIDER`, `LLM_MODEL`, or `LLM_BASE_URL`, those values take precedence over `settings.json`. Update them to the Ollama values or remove them before restarting Docker.

The same settings can be overridden without changing JSON. Docker reads these optional environment variables from the shell or a local `.env` file:

| Variable | Example |
|---|---|
| `LLM_PROVIDER` | `ollama` |
| `LLM_MODEL` | `gemma3:12b` |
| `LLM_BASE_URL` | `http://192.168.1.20:11434` |
| `LLM_TEMPERATURE` | `0.65` |
| `LLM_TIMEOUT` | `120` |
| `LLM_MAX_RETRIES` | `1` |

Do not use `localhost` for `LLM_BASE_URL` when Ollama runs on the separate RTX PC. Use that PC's private LAN address.

Restart the Dell container so it reloads the file:

```powershell
Set-Location "E:\LearnWithStories"
docker compose restart learn-with-stories
docker compose ps
Invoke-RestMethod "http://127.0.0.1:8766/api/health"
```

The expected response contains:

```json
{
  "status": "online",
  "provider": "ollama",
  "configured_model": "gemma3:12b"
}
```

Also confirm the active configuration without exposing secrets:

```powershell
Invoke-RestMethod "http://127.0.0.1:8766/api/config"
```

If health still reports OpenAI, check for `.env` overrides and recreate the container:

```powershell
Set-Location "E:\LearnWithStories"
docker compose up -d --force-recreate learn-with-stories
Invoke-RestMethod "http://127.0.0.1:8766/api/config"
Invoke-RestMethod "http://127.0.0.1:8766/api/health"
```

If health reports that Ollama is offline, repeat RTX Step 6. The Dell must reach `http://<RTX_PC_IP>:11434/api/tags` before the portal can generate a lesson.

### RTX Step 8: Confirm GPU inference

Generate one lesson from the portal and run on the RTX PC:

```powershell
ollama ps
nvidia-smi
```

`ollama ps` should preferably report `100% GPU` for the model.

After this one-time setup, future Dell restarts do not require another configuration change. Start Ollama on the RTX PC and Docker on the Dell.

## 6. Cloudflare production setup

The production portal is:

```text
https://learn-with-stories.aaankurankur.workers.dev
```

Cloudflare should expose only the portal. The Dell service remains bound to `127.0.0.1:8766` and is reached through the outbound private tunnel and VPC Service.

### Cloudflare Step 1: Keep the Dell private

Keep this mapping in `compose.yaml`:

```yaml
ports:
  - "127.0.0.1:8766:8766"
```

Do not change it to `0.0.0.0:8766` and do not forward router port `8766`.

### Cloudflare Step 2: Install the tunnel service once

1. In Cloudflare, open **Workers VPC → Tunnels**.
2. Use the `learn-with-stories-dell` remotely managed tunnel.
3. Copy the Windows service-install command shown by Cloudflare.
4. Run it once in Administrator PowerShell on the Dell.
5. Keep the tunnel token private.

The tunnel is outbound-only. Do not reinstall it after each reboot.

Verify the Windows service:

```powershell
Get-CimInstance Win32_Service -Filter "Name='cloudflared'" |
  Select-Object Name, State, StartMode
```

Expected values are `Running` and `Auto`. If necessary, run in Administrator PowerShell:

```powershell
Set-Service -Name cloudflared -StartupType Automatic
Start-Service -Name cloudflared
```

### Cloudflare Step 3: Verify the VPC Service and Worker

The VPC Service must target:

```text
Host: 127.0.0.1
Port: 8766
Protocol: HTTP
```

`wrangler.jsonc` binds this service as `DELL_API`. The Worker serves the static `web` directory and forwards only `/api/*` to the Dell.

For a GitHub deployment, keep:

```text
Repository:     Ankur-Verma09/LearnWithStories
Branch:         main
Root directory: repository root
Build command:  empty
Deploy command: npx wrangler deploy
```

#### Publish changes to the production Worker

The Pages address redirects to the production Worker. A successful GitHub/Pages build therefore does **not** update the live Worker by itself. After testing and merging changes into `main`, run this sequence from PowerShell on the Dell:

```powershell
Set-Location "E:\LearnWithStories"

git switch main
git status
git push origin main

npx.cmd wrangler --version
npx.cmd wrangler whoami
npx.cmd wrangler deploy --dry-run
npx.cmd wrangler deploy
```

If `wrangler whoami` says that you are not authenticated, run this once and complete the browser login:

```powershell
npx.cmd wrangler login
```

The final deployment output must show:

- `Uploaded learn-with-stories`
- `Deployed learn-with-stories triggers`
- the production URL and a new `Current Version ID`

Then open the production portal and use `Ctrl+F5` once to bypass any browser-cached assets:

```text
https://learn-with-stories.aaankurankur.workers.dev
```

Run `wrangler deploy` after changes to `web/`, `cloudflare/worker.js`, or `wrangler.jsonc`. It is not required after a normal Dell restart or for backend-only changes under `src/`; rebuild/restart Docker for those backend changes instead.

### Cloudflare Step 4: Require authentication

Protect all Worker traffic with Cloudflare Access and an allow policy restricted to approved email addresses. Do not create an anonymous bypass or `Allow everyone` policy.

### Cloudflare Step 5: Verify production

1. Open the production portal in a private browser window.
2. Confirm Cloudflare requests a login.
3. After login, open `/api/health` on the same production hostname.
4. Confirm subjects and books load.
5. Confirm internal exceptions, tokens, paths, and source code are not shown by error responses.

The Worker remains deployed when either PC is off. When the Dell is offline, the portal should return the controlled `DELL_API_UNAVAILABLE` message.

## 7. Start everything after a restart or shutdown

Use this sequence every time.

### Startup Step 1: Start the RTX PC when using Ollama

1. Power on the RTX PC.
2. Connect it to the same private network as the Dell.
3. Start Ollama if it did not start automatically.
4. Verify:

```powershell
ollama list
Invoke-RestMethod "http://127.0.0.1:11434/api/tags"
```

Skip this step only while intentionally using OpenAI.

### Startup Step 2: Start the Dell application

1. Start the Dell and Docker Desktop.
2. Wait for the Docker engine to report that it is running.
3. Run:

```powershell
Set-Location "E:\LearnWithStories"
docker compose up -d
docker compose ps
```

Use `docker compose up -d --build` only after application code, Python dependencies, the Dockerfile, or the image configuration changes.

### Startup Step 3: Verify the tunnel

```powershell
Get-Service -Name cloudflared
```

If stopped, run Administrator PowerShell:

```powershell
Start-Service -Name cloudflared
```

### Startup Step 4: Verify local and production routes

```powershell
Invoke-RestMethod "http://127.0.0.1:8766/api/health"
```

Then open:

```text
https://learn-with-stories.aaankurankur.workers.dev
```

No Cloudflare redeployment or tunnel-token installation is required after a normal reboot.

## 8. Normal operation

### Ask a question

1. Select a subject.
2. Optionally select or manually enter a topic/sub-topic.
3. Type the specific question, or select the microphone button and speak it.
4. Set the learner's age.
5. Select knowledge level: Beginner, Intermediate, or Advanced.
6. Choose story style, difficulty, language, and duration.
7. Generate the verified lesson.

When the topic is blank, retrieval searches approved content across the selected subject. When supplied, it filters to that topic hierarchy.

Age and knowledge level are deliberately separate. Age controls vocabulary, relatable settings, sentence style, and appropriate humor. Knowledge level controls prerequisites and technical depth. For example, a 28-year-old beginner receives adult examples with foundational physics, while a knowledgeable 16-year-old can receive deeper technical reasoning in age-appropriate language.

### Voice input and story playback

- Select the microphone beside **Your specific question** to request access and begin listening. Select it again to stop. The recognized text remains editable before lesson generation.
- Microphone access is requested only after that user action. If access is denied or blocked, enable it in the browser's site settings and reload instead of repeatedly selecting Retry.
- After a story is generated, use **Play Story**, **Pause**, **Resume**, or **Stop**. Starting another lesson automatically stops the current playback.
- Current Chrome or Edge releases provide the best compatibility. Voice recognition availability and network use are controlled by the browser; browser speech recognition is not guaranteed to work offline.
- Voice input and playback use native browser APIs and add no package, model, or API charge. Normal Internet, electricity, OpenAI, and Cloudflare plan considerations still apply.

### Learning preferences and context memory

Users can add and delete teaching preferences, goals, and misconceptions. The model may recommend a short default teaching preference. Duplicate preferences are normalized case-insensitively and with extra spaces removed.

Only relevant bounded learner context and retrieved evidence are sent to the configured model. Context memory reduces repeated prompt content; it does not train the model.

### Progressive learning and review scheduling

The first release uses one local **Default learner** profile. Every submitted recall check updates that learner's topic progress using deterministic server rules; the model cannot directly change mastery.

The progression states are:

```text
Foundation → Developing → Proficient → Mastered
```

Progress records include mastery, attempt count, success and incorrect streaks, a recommended knowledge level, detected recall gaps, and the next review date. Incorrect recall answers create reviewable misconception signals. Correct later answers can resolve the matching signal. Asking a follow-up question does not lower mastery by itself.

Open **Progress** to see the current stage, mastery percentage, attempts, and scheduled review date for each topic. Existing mastery and recall history are migrated into the default learner profile automatically; books, approvals, lessons, and source references are preserved.

The Progress page also provides a recall-accuracy chart, a deterministic learning-pattern summary, focus topics, and a seven-day study chart. These are derived from the signed-in learner's attempts, difficulty feedback, mastery, misconceptions, and scheduled reviews. They are not guessed directly by the language model.

Progressive behaviour is implemented through stored learner state and bounded prompt context. It does not retrain OpenAI or Ollama after each response, and switching providers does not erase learner progress.

### Ask follow-up questions after a story

After a verified story appears:

1. Scroll to **Ask a follow-up question** below the recall check.
2. Ask for clarification, another example, or a deeper explanation about that lesson.
3. Review the answer and its book/page references.
4. Select a suggested question or type another follow-up.
5. Use **Clear conversation** to remove that lesson's follow-up messages. The lesson, quiz attempts, and mastery remain intact.

Follow-up answers are restricted to the lesson subject/topic and its approved evidence. An unrelated question is redirected to a new lesson instead of mixing source material. The application sends only a compact conversation summary and the latest bounded messages to reduce context usage. Every in-scope answer passes a separate evidence-verification step before display.

The relevant APIs are:

```text
GET    /api/lessons/{lesson_id}/follow-ups
POST   /api/lessons/{lesson_id}/follow-ups
DELETE /api/lessons/{lesson_id}/follow-ups
GET    /api/progress
```

### Knowledge Library review

The hierarchy is:

```text
Subject → Book → Section/Chapter → Topic → Sub-topic → Approved concepts
```

Administrators can search, filter, expand/collapse, rename, merge, move, approve, reject, or delete content. Administrator-locked corrections are retained during reprocessing. Unreliable extracted names are marked **Needs review** with their source pages.

### Examinations

1. Open **Examination**.
2. Select General practice, Bank IBPS PO Prelims, SBI PO Prelims, or SSC CGL Tier-I.
3. Choose Subject, Topic, or Overall practice and select difficulty.
4. A named exam preset applies its stored question count, duration, section guidance, and negative marking. General practice keeps question count and time editable.
5. Generate the grounded examination.
6. Start it only when ready; timers begin at that point.
7. Submit to receive marks and evidence-backed analysis.

The presets are practice aids based on published official patterns and may change. Check the latest official IBPS, SBI, or SSC notification before relying on a preset for a live recruitment cycle.

## 9. Maintenance commands

### View logs

```powershell
Set-Location "E:\LearnWithStories"
docker compose logs --tail 100 learn-with-stories
```

Follow live logs:

```powershell
docker compose logs -f learn-with-stories
```

### Restart after a settings change

```powershell
Set-Location "E:\LearnWithStories"
docker compose restart learn-with-stories
```

### Rebuild after code changes

```powershell
Set-Location "E:\LearnWithStories"
docker compose up -d --build
```

### Deploy web or Worker changes

```powershell
Set-Location "E:\LearnWithStories"
git switch main
git push origin main
npx.cmd wrangler whoami
npx.cmd wrangler deploy --dry-run
npx.cmd wrangler deploy
```

GitHub/Pages deployment alone is not sufficient because the Pages address redirects to the Worker. Deployment is not required after an ordinary PC restart.

### Stop cleanly

```powershell
Set-Location "E:\LearnWithStories"
docker compose stop
```

Start it again with `docker compose up -d`. Do not use `docker compose down -v`.

### Native Windows fallback

Use this only while Docker is stopped:

```powershell
Set-Location "E:\LearnWithStories"
& ".\setup-learn-with-stories.cmd"
& ".\start-learn-with-stories.cmd"
```

Keep the terminal open and stop the native server with `Ctrl+C` before returning to Docker.

### Command-line tools

```powershell
$tutor = "E:\LearnWithStories\story-tutor.cmd"

& $tutor health
& $tutor remember "I understand civic examples best." --kind preference --subject Polity
& $tutor lesson "Article 21" --subject Polity --level 15 --minutes 5
& $tutor history
& $tutor progress
& $tutor content
```

Use `--refresh` with `lesson` to bypass a cached verified lesson.

### Automated checks

```powershell
Set-Location "E:\LearnWithStories"
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -s tests -v
```

## 10. Backup and restoration

The active database is:

```text
E:\LearnWithStories\data\story_tutor.db
```

Before copying it:

```powershell
Set-Location "E:\LearnWithStories"
docker compose stop
```

Back up together:

- `data\story_tutor.db`
- `data\sources`
- `config\settings.json`

Do not back up `secrets` to an unencrypted or shared location. Start the application again with `docker compose up -d`.

## 11. Troubleshooting

| Problem | Resolution |
|---|---|
| `docker compose` reports no configuration file | Run `Set-Location "E:\LearnWithStories"` first. |
| Local portal is unreachable | Start Docker Desktop, run `docker compose up -d`, and inspect the last 100 container log lines. |
| “Older server is still running” or port `8766` is occupied | Stop the native launcher or Docker container. Never run both. |
| Local health works but production reports `DELL_API_UNAVAILABLE` | Check the `cloudflared` Windows service, Cloudflare tunnel health, VPC Service, binding, and deployment. |
| Ollama is offline | Verify both PCs are on the same network, the RTX IP is unchanged, Ollama is listening on the LAN, and the firewall allows the Dell IP. |
| Ollama model is unavailable | Run `ollama list` on the RTX PC and copy the exact name into `settings.json`, then restart the Dell container. |
| OpenAI key is invalid | Run `configure-openai-keys.cmd` with a newly copied user-owned Platform key, then restart. ChatGPT subscriptions do not include API usage. |
| OpenAI quota or billing error | Add valid API billing/credits or switch `model_provider` to `ollama`. |
| PDF upload fails | Check container logs, file size, PDF searchability, and free space under `E:\LearnWithStories\data`. |
| SQLite disk I/O error in Docker | Confirm `E:\LearnWithStories\data` is writable and shared with Docker Desktop; do not run native and Docker instances together. |
| Topic has no approved evidence | Upload or approve relevant content under the matching subject/topic hierarchy. |
| Microphone is blocked or denied | Open the browser's site permissions for the portal, allow Microphone, reload the page, and select the microphone again. |
| Voice input is unavailable | Use a current Chrome or Edge release over HTTPS or localhost, confirm Windows detects the microphone, and ensure Internet access is available. Browser recognition may use an external online service, so type the question if it remains unavailable. Story playback can still work through the browser's speech-synthesis capability. |
| Docker logs show `/.well-known/appspecific/com.chrome.devtools.json` | This is an automatic Chrome DevTools probe, not an application API request. The server returns an empty `204` response and no action is required. |
| Story playback does not start | Select **Play Story** directly, confirm the tab/site is allowed to play audio, check the Windows output device, and retry. |

To identify the process using port `8766` without stopping it:

```powershell
Get-NetTCPConnection -LocalPort 8766 -State Listen |
  Select-Object LocalAddress, LocalPort, OwningProcess
```

Stop it only after confirming that it is an obsolete Learn With Stories process:

```powershell
Stop-Process -Id <PROCESS_ID>
```

## 12. Current boundaries

- English is the verified baseline; Hindi and Hinglish require additional content-quality evaluation.
- Retrieval is lexical in the current MVP.
- One learner and one generation request at a time.
- The books support retrieval-augmented generation; uploading a book does not train or fine-tune the model.
- No router ports should be opened for this application.
- Speech recognition and available synthesis voices vary by browser, operating system, language pack, and device. Native recognition may use a browser-provider service rather than the Dell or RTX model.
- The current RAG retriever is lexical. The provider, prompt, and validation boundaries are ready for a future embedding/vector-store implementation without changing lesson orchestration.
- Live Gemma quality, GPU memory, time-to-first-token, and end-to-end latency require verification on the RTX 5070 Ti PC.
- Browser runtime, model-quality, timer-drift, and load validation remain separate from the automated Python and static contract checks.
