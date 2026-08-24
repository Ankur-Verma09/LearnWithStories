# Learn With Stories — Product Overview

## Product in one sentence

Learn With Stories turns approved study books into source-verified, story-based lessons and helps a learner remember each topic through questions, follow-up explanations, and progressive review.

## The problem it solves

Competitive-exam books are useful but often large, dense, and difficult to revise. General AI chat tools may provide an easy explanation, but they can also mix unrelated information or make unsupported claims.

Learn With Stories combines both needs:

- the uploaded books remain the source of truth;
- the AI explains the material as an engaging story;
- important claims are checked against approved passages;
- the learner can ask a specific question instead of reading an entire chapter;
- recall results are stored so later lessons and reviews can adapt to the learner.

The product assists learning. It does not replace the original book, an educator, or official exam material.

## Who it is for

### Learner

The learner selects a subject, optionally chooses or types a topic, asks a question, reads the generated story, completes a recall check, and asks follow-up questions.

### Knowledge-library administrator

The administrator uploads authorized books, reviews the extracted hierarchy, corrects topic names, approves useful concepts, and removes incorrect or outdated content.

The learner and administrator can be the same person. A user can hold the Student role, the Admin role, or both.

## Simple product flow

```text
1. Upload an authorized book
              ↓
2. Convert PDF/DOCX/TXT into searchable passages
              ↓
3. Identify subject, book, chapter, topic and pages
              ↓
4. Review and approve the extracted knowledge
              ↓
5. Select a subject and ask a learning question
              ↓
6. Retrieve only relevant approved passages
              ↓
7. Generate a story-based explanation
              ↓
8. Verify the explanation against the source passages
              ↓
9. Show the verified lesson and book/page references
              ↓
10. Record recall answers and schedule the next review
              ↓
11. Answer follow-up questions within the same evidence
```

If the system cannot find sufficient approved evidence or cannot verify an answer, it withholds the answer instead of knowingly presenting uncertain material.

## Main areas of the portal

### Learn

- Subject is required and is populated from uploaded content.
- Topic or sub-topic is optional.
- A learner may select a searchable suggestion or type a new topic name.
- The learner enters the exact question they want answered.
- Age and knowledge level are separate inputs.
- The result contains a story, concept summary, key points, exam facts, memory hook, recall questions, and source references.
- Follow-up questions continue the verified lesson without starting an unrelated conversation.

### Knowledge Library

- Uploads PDF, DOCX, TXT, and JSONL documents.
- Converts supported documents into searchable knowledge automatically.
- Organizes content as Subject → Book → Chapter/Section → Topic → Sub-topic.
- Supports search and subject/book filters.
- Allows administrators to rename, merge, move, approve, reject, or delete topics.
- Preserves page references and labels uncertain topic extraction as `Needs review`.

### Examinations

- Creates topic-based or broader practice examinations from approved content.
- Keeps answer keys hidden while an examination is active.
- Records answers and displays results after completion.

### Progress

- Records recall attempts for the default learner.
- Tracks mastery as Foundation, Developing, Proficient, or Mastered.
- Records success and incorrect streaks.
- Stores possible misconceptions for later review.
- Recommends a knowledge level and schedules the next review.
- Keeps age separate from learning proficiency.

### Setup and health

- Shows whether the Dell application is available.
- Shows which model provider and model are configured.
- Reports whether OpenAI or the private Ollama service is reachable.
- Shows model configuration and provider checklists only to administrators.
- Lets administrators create users and assign one or both roles.

## How progressive learning works

The local model is not retrained after every answer. Learner progress is stored in the Dell database and supplied as bounded context when relevant.

```text
Recall response
      ↓
Deterministic mastery update
      ↓
Misconception and review schedule update
      ↓
Relevant learner context included in a later lesson
      ↓
Explanation depth and revision focus adapt progressively
```

The model cannot directly award mastery. Follow-up questions may create a possible misconception signal, but they do not reduce mastery without a scored recall response.

## Where each part runs

| Machine/service | Responsibility |
|---|---|
| Dell laptop | Portal, APIs, document conversion, retrieval, SQLite database, approvals, learner progress, and Docker |
| RTX 5070 Ti PC | Ollama and the local language model |
| Cloudflare | Public portal address, access protection, and private routing to the Dell |

Normal production request:

```text
Learner browser
   → Cloudflare Access
   → Cloudflare Worker
   → private tunnel
   → Dell application
   → RTX Ollama on the private home network
```

Books and learner records remain on the Dell. The RTX PC only receives the bounded prompt context required for the current generation request.

## Data stored on the Dell

The SQLite database at `E:\LearnWithStories\data\story_tutor.db` stores:

- uploaded-book metadata and extracted chunks;
- topic hierarchy and approval state;
- verified lesson cache and source references;
- recall attempts, mastery, misconceptions, and review dates;
- learner preferences and bounded follow-up conversations;
- examination history and answers.

Docker mounts the `data` directory, so restarting or rebuilding the container does not normally delete this information. Back up the `data` directory before manual database changes or destructive maintenance.

## Model-provider choices

### OpenAI

Useful before the RTX PC is ready, but it requires a user-owned API key and may incur charges.

### Ollama

The preferred private setup. Ollama runs `gemma3:12b` on the RTX PC, while the Dell continues running the application. It has no per-request API charge. Electricity, hardware, and normal Internet/network costs still apply.

Changing the model provider does not remove uploaded books, approvals, lesson history, or learner progress.

## Current boundaries

- Each signed-in user has an isolated learner profile, progress record, exam history, and manually created context.
- It does not continuously train or fine-tune the foundation model.
- Image-only scanned PDFs require OCR before reliable extraction.
- Generated lessons depend on an available configured model provider.
- Manual topic entry and administrative corrections remain available when the model is offline.
- Source verification reduces hallucination risk but does not make the system a substitute for checking official material.

## First successful-use checklist

1. Start Ollama on the RTX PC or configure a valid OpenAI key.
2. Start Docker on the Dell.
3. Confirm `/api/health` reports the model online.
4. Upload an authorized book and wait for processing to finish.
5. Review its extracted topics in Knowledge Library.
6. Open Learn, select the subject, and ask a specific question.
7. Complete the recall check.
8. Ask a follow-up question about the story.
9. Open Progress and confirm the attempt and review date were stored.

For installation, restart, Ollama switching, Cloudflare production, backup, and troubleshooting commands, use the main [README](../README.md).
